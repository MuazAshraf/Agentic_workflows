"""Blueprint for Invoice Processing Pipeline — Prompt Chaining Agent"""
import os
import io
import tempfile
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, send_file
from fpdf import FPDF
from PromptChainingAgent.promptchaining_agent import run_invoice_pipeline, MOCK_PO_DATABASE

invoice_bp = Blueprint("invoice", __name__, url_prefix="/invoice")

UPLOAD_DIR = tempfile.mkdtemp(prefix="invoice_uploads_")


@invoice_bp.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "promptchaining.html")


@invoice_bp.route("/api/process-invoice", methods=["POST"])
def process_invoice():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    file.save(file_path)

    try:
        result = run_invoice_pipeline(file_path)
        response = {
            "success": not bool(result.get("error")),
            "steps": {
                "extract": result.get("invoice_data", {}),
                "duplicate_check": result.get("duplicate_check", {}),
                "validation": result.get("validation", {}),
                "po_match": result.get("po_match", {}),
                "payment_entry": result.get("payment_entry", {})
            },
            "error": result.get("error", "")
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@invoice_bp.route("/api/po-database", methods=["GET"])
def get_po_database():
    return jsonify(MOCK_PO_DATABASE)


@invoice_bp.route("/api/generate-slip", methods=["POST"])
def generate_slip():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    payment = data.get("payment_entry", {})
    invoice = data.get("extract", {})
    po_match = data.get("po_match", {})
    validation = data.get("validation", {})

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pw = pdf.w - 40

    DARK = (15, 23, 42)
    ACCENT = (59, 130, 246)
    GREEN = (16, 185, 129)
    GRAY = (100, 116, 139)
    LIGHT_BG = (248, 250, 252)
    WHITE = (255, 255, 255)

    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, pdf.w, 40, "F")
    pdf.set_y(8)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "PAYMENT SLIP", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(200, 220, 255)
    pdf.cell(0, 8, f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(48)

    entry_id = payment.get("entry_id", "N/A")
    status = payment.get("status", "N/A")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*DARK)
    pdf.cell(pw / 2, 8, f"Entry ID: {entry_id}", new_x="RIGHT")
    if "approved" in status.lower() and "pending" not in status.lower():
        pdf.set_text_color(*GREEN)
        status_label = "APPROVED"
    elif "pending" in status.lower():
        pdf.set_text_color(245, 158, 11)
        status_label = "PENDING APPROVAL"
    else:
        pdf.set_text_color(*GRAY)
        status_label = status.upper()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(pw / 2, 8, f"Status: {status_label}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def draw_divider():
        pdf.set_draw_color(226, 232, 240)
        pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
        pdf.ln(4)

    def info_row(label, value, bold_value=False):
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRAY)
        pdf.cell(45, 7, label, new_x="RIGHT")
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "B" if bold_value else "", 9)
        pdf.cell(pw / 2 - 45, 7, str(value) if value else "N/A", new_x="LMARGIN", new_y="NEXT")

    draw_divider()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, "PAYMENT DETAILS", new_x="LMARGIN", new_y="NEXT")
    info_row("Vendor:", payment.get("vendor_name", "N/A"), True)
    info_row("Invoice #:", payment.get("invoice_number", "N/A"))
    info_row("PO Number:", payment.get("po_number", "N/A"))
    info_row("Due Date:", payment.get("due_date", "N/A"))
    info_row("Method:", payment.get("payment_method", "N/A"))
    info_row("Currency:", payment.get("currency", "USD"))
    info_row("GL Account:", payment.get("gl_account", "N/A"))
    info_row("Department:", payment.get("department", "N/A"))
    pdf.ln(4)
    draw_divider()

    pdf.set_fill_color(*LIGHT_BG)
    box_y = pdf.get_y()
    pdf.rect(20, box_y, pw, 24, "F")
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(20, box_y, pw, 24, "D")
    pdf.set_y(box_y + 4)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(pw / 2, 8, "  Total Amount Due", new_x="RIGHT")
    amount = payment.get("amount", 0)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*DARK)
    pdf.cell(pw / 2, 8, f"${amount:,.2f} {payment.get('currency', 'USD')}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(box_y + 28)

    line_items = invoice.get("line_items", [])
    if line_items:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*ACCENT)
        pdf.cell(0, 8, "LINE ITEMS", new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(*DARK)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 8)
        col_w = [pw * 0.45, pw * 0.12, pw * 0.2, pw * 0.23]
        headers = ["Description", "Qty", "Unit Price", "Total"]
        for i, h in enumerate(headers):
            if i < 3:
                pdf.cell(col_w[i], 8, h, fill=True, align="C" if i > 0 else "L", new_x="RIGHT")
            else:
                pdf.cell(col_w[i], 8, h, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        for idx, item in enumerate(line_items):
            bg = LIGHT_BG if idx % 2 == 0 else WHITE
            pdf.set_fill_color(*bg)
            pdf.set_text_color(*DARK)
            desc = str(item.get("description", ""))[:50]
            qty = item.get("quantity", 0)
            price = item.get("unit_price", 0)
            total = item.get("total", 0)
            pdf.cell(col_w[0], 7, desc, fill=True, new_x="RIGHT")
            pdf.cell(col_w[1], 7, str(int(qty) if qty == int(qty) else qty), fill=True, align="C", new_x="RIGHT")
            pdf.cell(col_w[2], 7, f"${price:,.2f}", fill=True, align="R", new_x="RIGHT")
            pdf.cell(col_w[3], 7, f"${total:,.2f}", fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        sub = invoice.get("subtotal")
        tax = invoice.get("tax_amount")
        if sub is not None:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(pw - 50, 6, "Subtotal:", align="R", new_x="RIGHT")
            pdf.set_text_color(*DARK)
            pdf.cell(50, 6, f"${sub:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")
        if tax is not None:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*GRAY)
            pdf.cell(pw - 50, 6, "Tax:", align="R", new_x="RIGHT")
            pdf.set_text_color(*DARK)
            pdf.cell(50, 6, f"${tax:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    draw_divider()

    if po_match.get("matched"):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*GREEN)
        pdf.cell(0, 8, f"PO MATCHED: {po_match.get('po_number', 'N/A')} (Confidence: {int(po_match.get('match_confidence', 0) * 100)}%)", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(245, 158, 11)
        pdf.cell(0, 8, "PO: No match found in database", new_x="LMARGIN", new_y="NEXT")
    if po_match.get("reasoning"):
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(pw, 5, po_match["reasoning"])
    pdf.ln(2)

    notes = payment.get("notes", "")
    if notes:
        draw_divider()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*ACCENT)
        pdf.cell(0, 8, "NOTES", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(pw, 5, notes)

    pdf.ln(8)
    draw_divider()
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "This is a system-generated payment slip from the Invoice Processing Pipeline.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Validation Confidence: {int(validation.get('confidence', 0) * 100)}% | Prompt Chaining Agent", align="C")

    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"payment_slip_{entry_id}.pdf")


@invoice_bp.route("/api/create-po", methods=["POST"])
def create_po():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    vendor_name = data.get("vendor_name")
    items = data.get("items")
    amount = data.get("amount")
    deadline = data.get("deadline")
    department = data.get("department")

    if not all([vendor_name, items, amount is not None]):
        return jsonify({"error": "vendor_name, items, and amount are required"}), 400

    current_year = datetime.now().year
    year_prefix = f"PO-{current_year}-"
    max_seq = 0
    for key in MOCK_PO_DATABASE:
        if key.startswith(year_prefix):
            try:
                seq = int(key[len(year_prefix):])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    po_number = f"{year_prefix}{max_seq + 1:05d}"

    po_entry = {
        "vendor": vendor_name,
        "amount": amount,
        "items": items,
        "status": "open",
        "deadline": deadline or "",
        "department": department or "",
        "created_at": datetime.now().isoformat(),
    }
    MOCK_PO_DATABASE[po_number] = po_entry
    return jsonify({"po_number": po_number, **po_entry}), 201


@invoice_bp.route("/api/generate-po-pdf", methods=["POST"])
def generate_po_pdf():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    po_number = data.get("po_number", "N/A")
    vendor_name = data.get("vendor_name") or data.get("vendor", "N/A")
    items = data.get("items", "N/A")
    amount = data.get("amount", 0)
    deadline = data.get("deadline", "N/A")
    department = data.get("department", "N/A")
    status = data.get("status", "open")
    created_at = data.get("created_at", datetime.now().isoformat())

    DARK = (15, 23, 42)
    ACCENT = (59, 130, 246)
    GREEN = (16, 185, 129)
    GRAY = (100, 116, 139)
    LIGHT_BG = (248, 250, 252)
    WHITE = (255, 255, 255)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pw = pdf.w - 40

    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, pdf.w, 40, "F")
    pdf.set_y(8)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "PURCHASE ORDER", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(200, 220, 255)
    pdf.cell(0, 8, f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(48)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*DARK)
    pdf.cell(pw / 2, 8, f"PO Number: {po_number}", new_x="RIGHT")
    pdf.set_text_color(*GREEN)
    pdf.cell(pw / 2, 8, f"Status: {status.upper()}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def draw_divider():
        pdf.set_draw_color(226, 232, 240)
        pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
        pdf.ln(4)

    def info_row(label, value, bold_value=False):
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRAY)
        pdf.cell(45, 7, label, new_x="RIGHT")
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "B" if bold_value else "", 9)
        pdf.cell(pw / 2 - 45, 7, str(value) if value else "N/A", new_x="LMARGIN", new_y="NEXT")

    draw_divider()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, "PURCHASE ORDER DETAILS", new_x="LMARGIN", new_y="NEXT")
    info_row("Vendor:", vendor_name, True)
    info_row("Department:", department)
    info_row("Deadline:", deadline)
    info_row("Created:", created_at[:10] if created_at and len(created_at) >= 10 else created_at)
    pdf.ln(4)
    draw_divider()

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, "DESCRIPTION / ITEMS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(pw, 6, str(items))
    pdf.ln(4)
    draw_divider()

    pdf.set_fill_color(*LIGHT_BG)
    box_y = pdf.get_y()
    pdf.rect(20, box_y, pw, 24, "F")
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(20, box_y, pw, 24, "D")
    pdf.set_y(box_y + 4)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(pw / 2, 8, "  Total PO Amount", new_x="RIGHT")
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*DARK)
    pdf.cell(pw / 2, 8, f"${float(amount):,.2f} USD", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(box_y + 28)
    pdf.ln(8)
    draw_divider()

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "System-generated Purchase Order | Prompt Chaining Agent", align="C")

    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"purchase_order_{po_number}.pdf")
