"""
Market Research Tool — Orchestrator-Worker Agent

Orchestrator plans research sections → Workers search & analyze in parallel → Synthesizer creates final report
"""
import os
import json
from typing import Annotated, List
from typing_extensions import TypedDict
import operator

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Clients ---
llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


# --- Schemas ---
class ResearchSection(BaseModel):
    name: str = Field(description="Section name for the research report")
    search_queries: List[str] = Field(description="2-3 Tavily search queries to research this section")
    description: str = Field(description="What this section should cover")


class ResearchPlan(BaseModel):
    business_idea: str = Field(description="The user's business idea restated clearly")
    target_market: str = Field(description="Identified target market")
    sections: List[ResearchSection] = Field(description="5 research sections to investigate")


# --- State ---
class OrcState(TypedDict):
    idea: str
    plan: dict
    completed_sections: Annotated[list, operator.add]
    final_report: str
    error: str


class WorkerState(TypedDict):
    section: dict
    idea: str
    completed_sections: Annotated[list, operator.add]


# --- Node 1: Orchestrator (Planner) ---
planner_llm = llm.with_structured_output(ResearchPlan)

def orchestrator(state: OrcState):
    """Plan the market research by breaking into 5 parallel research tasks"""
    try:
        plan = planner_llm.invoke([
            SystemMessage(content="""You are a market research strategist. Given a business idea, create a research plan with exactly 5 sections:

1. **Competitor Landscape** — Find direct and indirect competitors, their products, market position
2. **Pricing & Business Model** — How competitors price their products, free vs paid tiers, revenue models
3. **Content & SEO Strategy** — How competitors attract traffic, their blog/content strategy, social media presence
4. **Marketing & Growth** — Ad strategies, messaging, positioning, customer acquisition channels, growth tactics
5. **Market Size & Opportunities** — Market size, trends, gaps, underserved segments, opportunities for differentiation

For each section, generate 2-3 specific search queries that will find real, current data. Make queries specific to the business idea's industry."""),
            HumanMessage(content=f"Business idea: {state['idea']}")
        ])
        return {"plan": plan.model_dump(), "error": ""}
    except Exception as e:
        return {"error": f"Planning failed: {str(e)}"}


# --- Node 2: Worker (Search + Analyze) ---
def worker(state: WorkerState):
    """Search the web and analyze findings for one research section"""
    section = state["section"]
    idea = state["idea"]
    section_name = section.get("name", "Research")
    queries = section.get("search_queries", [])
    description = section.get("description", "")

    # Search with Tavily
    all_results = []
    for query in queries[:3]:
        try:
            response = tavily.search(query=query, max_results=5, include_answer=True)
            if response.get("answer"):
                all_results.append(f"**Summary for '{query}':** {response['answer']}")
            for r in response.get("results", [])[:3]:
                all_results.append(f"- [{r.get('title', 'N/A')}]({r.get('url', '')}) — {r.get('content', '')[:200]}")
        except Exception:
            all_results.append(f"- Search for '{query}' failed")

    search_context = "\n".join(all_results) if all_results else "No search results found."

    # LLM analyzes the search results
    analysis = llm.invoke([
        SystemMessage(content=f"""You are a market research analyst. Write the "{section_name}" section of a competitive research report.

Use the search results below as your primary source. Write in clear, professional markdown with:
- Key findings as bullet points
- Specific competitor names, prices, and strategies when found
- Data-driven insights (numbers, percentages, market sizes)
- Actionable takeaways for the entrepreneur

Section focus: {description}
Business idea context: {idea}

Keep the section focused and under 400 words. Use ## for the section header."""),
        HumanMessage(content=f"Search results:\n{search_context}")
    ])

    return {
        "completed_sections": [{
            "name": section_name,
            "content": analysis.content,
            "sources": [r for r in all_results if r.startswith("- [")]
        }]
    }


# --- Node 3: Synthesizer ---
def synthesizer(state: OrcState):
    """Combine all worker outputs into a final report"""
    sections = state.get("completed_sections", [])
    plan = state.get("plan", {})
    idea = state.get("idea", "")

    # Build report sections
    section_texts = []
    all_sources = []
    for s in sections:
        section_texts.append(s.get("content", ""))
        all_sources.extend(s.get("sources", []))

    combined_sections = "\n\n---\n\n".join(section_texts)

    # LLM creates executive summary + final polish
    final = llm.invoke([
        SystemMessage(content="""You are a senior market research analyst. Create a polished final report by:

1. Write an **Executive Summary** (150 words max) at the top with key findings and recommendations
2. Include all the section content provided below (don't cut anything)
3. Add a **Key Recommendations** section at the end with 5-7 actionable bullet points
4. Add a **Sources** section listing all reference links

Use clean markdown formatting. Start with:
# Market Research Report: [Business Idea]
## Executive Summary"""),
        HumanMessage(content=f"Business idea: {idea}\n\nTarget market: {plan.get('target_market', 'N/A')}\n\nResearch sections:\n{combined_sections}\n\nSources:\n" + "\n".join(all_sources))
    ])

    return {"final_report": final.content}


# --- Assign Workers ---
def assign_workers(state: OrcState):
    """Fan out to parallel workers via Send()"""
    if state.get("error"):
        return []
    plan = state.get("plan", {})
    sections = plan.get("sections", [])
    return [Send("worker", {"section": s if isinstance(s, dict) else s.model_dump(), "idea": state["idea"]}) for s in sections]


# --- Build Workflow ---
workflow = StateGraph(OrcState)
workflow.add_node("orchestrator", orchestrator)
workflow.add_node("worker", worker)
workflow.add_node("synthesizer", synthesizer)

workflow.add_edge(START, "orchestrator")
workflow.add_conditional_edges("orchestrator", assign_workers, ["worker"])
workflow.add_edge("worker", "synthesizer")
workflow.add_edge("synthesizer", END)

research_chain = workflow.compile()


def run_market_research(idea: str) -> dict:
    """Run the full market research pipeline."""
    initial_state = {
        "idea": idea,
        "plan": {},
        "completed_sections": [],
        "final_report": "",
        "error": ""
    }
    return research_chain.invoke(initial_state)
