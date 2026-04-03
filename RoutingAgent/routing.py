"""
Smart Customer Support — Routing Agent

Router classifies customer intent → Routes to specialized handler → Returns tailored response
"""
import os
from typing_extensions import TypedDict, Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))


# --- Schemas ---
class RouteDecision(BaseModel):
    category: Literal["billing", "technical", "refund", "account", "general"] = Field(
        description="The category that best matches the customer's intent"
    )
    confidence: float = Field(description="Confidence score 0-1")
    reasoning: str = Field(description="Brief reasoning for this classification")


# --- State ---
class SupportState(TypedDict):
    query: str
    category: str
    confidence: float
    reasoning: str
    response: str
    specialist: str
    error: str


# --- Node 1: Router ---
router_llm = llm.with_structured_output(RouteDecision)

def classify_intent(state: SupportState):
    """Classify the customer query into a support category"""
    try:
        decision = router_llm.invoke([
            SystemMessage(content="""You are a customer support intent classifier. Classify the customer's query into exactly ONE category:

- **billing**: Payment issues, charges, invoices, subscription costs, payment methods, billing cycles
- **technical**: Bugs, errors, how-to questions, feature usage, API issues, integrations, performance
- **refund**: Refund requests, cancellation with money back, dispute charges, overcharged
- **account**: Login issues, password reset, account settings, profile changes, deletion, security
- **general**: Product info, feature requests, feedback, general inquiries, anything else

Be precise. "I was charged twice" = billing, not refund (unless they explicitly ask for money back)."""),
            HumanMessage(content=f"Customer query: {state['query']}")
        ])
        return {
            "category": decision.category,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "error": ""
        }
    except Exception as e:
        return {"error": f"Classification failed: {str(e)}", "category": "general"}


# --- Specialist Handlers ---
SPECIALIST_PROMPTS = {
    "billing": {
        "name": "Billing Specialist",
        "prompt": """You are a billing support specialist. You handle:
- Payment issues and failed transactions
- Subscription and plan changes
- Invoice questions and billing cycles
- Payment method updates

Be empathetic, clear about next steps, and offer specific solutions. If the issue requires escalation (like a double charge), acknowledge it and explain the process. Always end with a clear action item."""
    },
    "technical": {
        "name": "Technical Support Engineer",
        "prompt": """You are a technical support engineer. You handle:
- Bug reports and error troubleshooting
- How-to guides and feature walkthroughs
- API and integration issues
- Performance problems

Be technical but clear. Provide step-by-step solutions when possible. If you need more info, ask specific diagnostic questions. Use numbered steps for instructions."""
    },
    "refund": {
        "name": "Refund & Retention Specialist",
        "prompt": """You are a refund and retention specialist. You handle:
- Refund requests and processing
- Cancellation requests (try to retain first)
- Charge disputes
- Overcharge corrections

Be understanding and empathetic. For refund requests: acknowledge the issue, explain the refund policy (14-day no-questions refund, after that case-by-case), and offer alternatives before processing. Always confirm the expected timeline."""
    },
    "account": {
        "name": "Account Security Specialist",
        "prompt": """You are an account security specialist. You handle:
- Login and authentication issues
- Password resets and 2FA
- Account settings and profile changes
- Account deletion and data requests
- Security concerns

Prioritize security. Never share sensitive info. Guide users through self-service options first. For security issues, be thorough and cautious."""
    },
    "general": {
        "name": "Customer Success Agent",
        "prompt": """You are a friendly customer success agent. You handle:
- General product questions
- Feature requests and feedback
- Onboarding help
- Any query that doesn't fit other categories

Be warm, helpful, and proactive. Point users to relevant features and resources. For feature requests, acknowledge and log them."""
    }
}

def make_specialist(category):
    """Factory to create specialist handler nodes"""
    spec = SPECIALIST_PROMPTS[category]
    def handler(state: SupportState):
        response = llm.invoke([
            SystemMessage(content=spec["prompt"]),
            HumanMessage(content=f"Customer query: {state['query']}\n\nProvide a helpful, professional response.")
        ])
        return {
            "response": response.content,
            "specialist": spec["name"]
        }
    handler.__name__ = f"handle_{category}"
    return handler


# --- Route function ---
def route_to_specialist(state: SupportState):
    """Route to the appropriate specialist based on classification"""
    category = state.get("category", "general")
    return f"handle_{category}"


# --- Build Workflow ---
workflow = StateGraph(SupportState)

# Add router node
workflow.add_node("classify_intent", classify_intent)

# Add specialist nodes
for cat in SPECIALIST_PROMPTS:
    workflow.add_node(f"handle_{cat}", make_specialist(cat))

# Edges
workflow.add_edge(START, "classify_intent")
workflow.add_conditional_edges(
    "classify_intent",
    route_to_specialist,
    {f"handle_{cat}": f"handle_{cat}" for cat in SPECIALIST_PROMPTS}
)
for cat in SPECIALIST_PROMPTS:
    workflow.add_edge(f"handle_{cat}", END)

support_chain = workflow.compile()


def handle_support_query(query: str) -> dict:
    """Run a customer query through the support routing pipeline."""
    initial_state = {
        "query": query,
        "category": "",
        "confidence": 0.0,
        "reasoning": "",
        "response": "",
        "specialist": "",
        "error": ""
    }
    return support_chain.invoke(initial_state)
