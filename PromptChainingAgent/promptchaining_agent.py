"""
Invoice Processing Pipeline using LangGraph prompt chaining.
5-node workflow: extract -> duplicate_check -> validate -> match_po -> generate_payment_entry
"""
import os
import time
import json
from typing import Optional, List
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from llama_cloud import LlamaCloud
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))
llama_client = LlamaCloud(api_key=os.getenv("LAMAINDEX_API_KEY"))


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total: float


class InvoiceData(BaseModel):
    vendor_name: str
    invoice_number: str
    invoice_date: str
    due_date: Optional[str] = None
    po_number: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: float
    currency: str = "USD"
    line_items: List[LineItem]


# ---------------------------------------------------------------------------
# Mock Data
# ---------------------------------------------------------------------------

MOCK_PO_DATABASE: dict = {
    "PO-2024-001": {"vendor": "Acme Corp", "amount": 1500.00, "items": "Office Supplies", "status": "open"},
    "PO-2024-002": {"vendor": "TechParts Inc", "amount": 8750.00, "items": "Server Components", "status": "open"},
    "PO-2024-003": {"vendor": "CloudHost Ltd", "amount": 3200.00, "items": "Cloud Hosting - Q1", "status": "open"},
    "PO-2024-004": {"vendor": "Office Depot", "amount": 420.50, "items": "Printer Cartridges", "status": "open"},
    "PO-2024-005": {"vendor": "DataFlow Systems", "amount": 15000.00, "items": "Annual Software License", "status": "open"},
}

PROCESSED_INVOICES: List[dict] = []


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class InvoiceState(TypedDict):
    file_path: str
    raw_extract: dict
    invoice_data: dict
    duplicate_check: dict
    validation: dict
    po_match: dict
    payment_entry: dict
    error: str
    current_step: str


# ---------------------------------------------------------------------------
# Node 1: extract_invoice
# ---------------------------------------------------------------------------

def extract_invoice(state: InvoiceState) -> dict:
    """Upload PDF to LlamaCloud and extract invoice data."""
    file_path = state["file_path"]
    try:
        with open(file_path, "rb") as f:
            file_obj = llama_client.files.create(file=f, purpose="extract")

        job = llama_client.extract.create(
            file_input=file_obj.id,
            configuration={
                "data_schema": InvoiceData.model_json_schema(),
                "extraction_target": "per_doc",
                "tier": "agentic",
            },
        )

        while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
            time.sleep(2)
            job = llama_client.extract.get(job.id)

        if job.status != "COMPLETED":
            return {
                "error": f"Extraction job ended with status: {job.status}",
                "current_step": "extract_invoice",
            }

        raw_result = job.extract_result
        extracted = raw_result[0] if isinstance(raw_result, list) else raw_result
        if hasattr(extracted, "dict"):
            extracted = extracted.dict()
        elif hasattr(extracted, "model_dump"):
            extracted = extracted.model_dump()
        elif not isinstance(extracted, dict):
            extracted = dict(extracted) if extracted else {}

        return {
            "raw_extract": extracted,
            "invoice_data": extracted,
            "current_step": "extract_invoice",
        }

    except Exception as exc:
        return {
            "error": f"extract_invoice failed: {exc}",
            "current_step": "extract_invoice",
        }


# ---------------------------------------------------------------------------
# Node 2: check_duplicate
# ---------------------------------------------------------------------------

def check_duplicate(state: InvoiceState) -> dict:
    """Check if this invoice has already been processed."""
    if state.get("error"):
        return {"duplicate_check": {"is_duplicate": False, "message": "Skipped due to upstream error"}, "current_step": "check_duplicate"}

    invoice = state.get("invoice_data", {})
    invoice_number = invoice.get("invoice_number", "")
    vendor_name = invoice.get("vendor_name", "")
    total_amount = invoice.get("total_amount", 0)

    # Exact match
    for processed in PROCESSED_INVOICES:
        if processed.get("invoice_number") == invoice_number and processed.get("vendor_name") == vendor_name:
            return {
                "duplicate_check": {
                    "is_duplicate": True,
                    "message": f"Exact duplicate: invoice {invoice_number} from {vendor_name} already processed.",
                    "match": processed,
                },
                "current_step": "check_duplicate",
            }

    # Fuzzy: same vendor + same total amount
    for processed in PROCESSED_INVOICES:
        if processed.get("vendor_name") == vendor_name and processed.get("total_amount") == total_amount:
            return {
                "duplicate_check": {
                    "is_duplicate": True,
                    "message": f"Fuzzy duplicate: same vendor ({vendor_name}) and same total amount ({total_amount}).",
                    "match": processed,
                },
                "current_step": "check_duplicate",
            }

    return {
        "duplicate_check": {
            "is_duplicate": False,
            "message": "No duplicate found.",
        },
        "current_step": "check_duplicate",
    }


def duplicate_gate(state: InvoiceState) -> str:
    if state.get("error") or state.get("duplicate_check", {}).get("is_duplicate", False):
        return END
    return "validate_fields"


# ---------------------------------------------------------------------------
# Node 3: validate_fields
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    is_valid: bool
    issues: List[str]
    confidence: float


def validate_fields(state: InvoiceState) -> dict:
    """Use LLM to validate invoice fields."""
    invoice = state.get("invoice_data", {})

    structured_llm = llm.with_structured_output(ValidationResult)
    prompt = f"""You are an invoice validation expert. Check this invoice data and return a structured result.

Invoice data:
{json.dumps(invoice, indent=2, default=str)}

Checks to perform:
1. Required fields present and non-empty: vendor_name, invoice_number, invoice_date, total_amount
2. Dates are parseable (any reasonable format is fine — YYYY-MM-DD, "March 28, 2026", etc.)
3. total_amount is a positive number
4. If line_items exist, quantities and unit_prices should be positive
5. Currency is a valid ISO code (USD, EUR, GBP, PKR, etc.)

IMPORTANT RULES:
- Set is_valid=true if ALL checks pass. Set is_valid=false ONLY if there are actual problems.
- The "issues" list must contain ONLY actual problems found. Do NOT list passing checks.
- If everything looks good, return is_valid=true with an empty issues list.
- Set confidence between 0.0 and 1.0 based on data quality."""

    result: ValidationResult = structured_llm.invoke(prompt)

    return {
        "validation": result.dict(),
        "current_step": "validate_fields",
    }


def validation_gate(state: InvoiceState) -> str:
    if not state.get("validation", {}).get("is_valid", False):
        return END
    return "match_po"


# ---------------------------------------------------------------------------
# Node 4: match_po
# ---------------------------------------------------------------------------

class POMatchResult(BaseModel):
    matched: bool
    po_number: Optional[str] = None
    match_confidence: float
    discrepancies: List[str]
    reasoning: str


def match_po(state: InvoiceState) -> dict:
    """Use LLM to match invoice against PO database."""
    invoice = state.get("invoice_data", {})

    structured_llm = llm.with_structured_output(POMatchResult)
    prompt = f"""You are a procurement matching specialist. Match the following invoice against the PO database.

Invoice data:
{json.dumps(invoice, indent=2, default=str)}

PO Database:
{json.dumps(MOCK_PO_DATABASE, indent=2, default=str)}

Matching rules (try ALL of these, not just the first):
1. **Exact PO number match**: Check if the invoice's po_number matches any PO key in the database
2. **Vendor name match**: Match invoice vendor_name against PO "vendor" field (case-insensitive, partial match OK — "TechSolutions Pvt Ltd" matches "TechSolutions Pvt Ltd")
3. **Amount match**: Check if invoice total_amount is within 10% of any PO's amount

IMPORTANT: If the PO number on the invoice does NOT match any key in the database, DO NOT stop there. Continue checking vendor name and amount. A match by vendor + amount is still a valid match even if PO numbers differ. The invoice may reference an external PO number that differs from our internal PO key.

Set matched=true if vendor name AND amount match (within 10% tolerance), even if PO numbers differ. Use the matching PO's key as po_number in your response. Note any PO number discrepancy in the discrepancies list.

Set match_confidence between 0.0 and 1.0."""

    result: POMatchResult = structured_llm.invoke(prompt)

    return {
        "po_match": result.dict(),
        "current_step": "match_po",
    }


# ---------------------------------------------------------------------------
# Node 5: generate_payment_entry
# ---------------------------------------------------------------------------

class PaymentEntry(BaseModel):
    entry_id: str
    vendor_name: str
    invoice_number: str
    po_number: Optional[str] = None
    amount: float
    currency: str
    due_date: Optional[str] = None
    payment_method: str
    gl_account: str
    department: str
    notes: str
    status: str


def generate_payment_entry(state: InvoiceState) -> dict:
    """Generate a payment entry for the validated invoice."""
    invoice = state.get("invoice_data", {})
    po_match = state.get("po_match", {})

    structured_llm = llm.with_structured_output(PaymentEntry)
    prompt = f"""You are a financial accounting specialist. Generate a payment entry for the following invoice.

Invoice data:
{json.dumps(invoice, indent=2)}

PO Match result:
{json.dumps(po_match, indent=2)}

Payment entry rules:
1. payment_method: Use "ACH" if amount > $1000, use "Check" if $1000 or less
2. gl_account: Assign based on item type:
   - Office supplies / printer items → "6100-Office Supplies"
   - Technology / server / software items → "6200-Technology"
   - Cloud / hosting services → "6300-Cloud Services"
   - Other → "6900-General Expenses"
3. department: Infer from item type (IT, Finance, Operations, etc.)
4. status: "pending_approval" if amount > $5000, otherwise "approved"
5. entry_id: Generate a unique ID like "PAY-YYYY-NNNN" using current year
6. notes: Include any relevant notes about the payment, PO match status, discrepancies

Generate a complete and accurate payment entry."""

    result: PaymentEntry = structured_llm.invoke(prompt)
    entry_dict = result.dict()

    # Record in processed invoices
    PROCESSED_INVOICES.append({
        "invoice_number": invoice.get("invoice_number", ""),
        "vendor_name": invoice.get("vendor_name", ""),
        "total_amount": invoice.get("total_amount", 0),
        "entry_id": entry_dict.get("entry_id", ""),
    })

    return {
        "payment_entry": entry_dict,
        "current_step": "generate_payment_entry",
    }


# ---------------------------------------------------------------------------
# Wire the workflow
# ---------------------------------------------------------------------------

workflow = StateGraph(InvoiceState)
workflow.add_node("extract_invoice", extract_invoice)
workflow.add_node("check_duplicate", check_duplicate)
workflow.add_node("validate_fields", validate_fields)
workflow.add_node("match_po", match_po)
workflow.add_node("generate_payment_entry", generate_payment_entry)

workflow.add_edge(START, "extract_invoice")
workflow.add_edge("extract_invoice", "check_duplicate")
workflow.add_conditional_edges("check_duplicate", duplicate_gate, {"validate_fields": "validate_fields", END: END})
workflow.add_conditional_edges("validate_fields", validation_gate, {"match_po": "match_po", END: END})
workflow.add_edge("match_po", "generate_payment_entry")
workflow.add_edge("generate_payment_entry", END)

invoice_chain = workflow.compile()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def run_invoice_pipeline(file_path: str) -> dict:
    """Run the full invoice processing pipeline for a given PDF file path."""
    initial_state: InvoiceState = {
        "file_path": file_path,
        "raw_extract": {},
        "invoice_data": {},
        "duplicate_check": {},
        "validation": {},
        "po_match": {},
        "payment_entry": {},
        "error": "",
        "current_step": "",
    }
    return invoice_chain.invoke(initial_state)
