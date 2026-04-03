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
from google import genai
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Clients ---
llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


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

CRITICAL FORMATTING RULES:
1. Keep it SHORT — max 200 words of prose. Humans won't read walls of text.
2. Use MARKDOWN TABLES for any comparison data. Example:
   | Competitor | Price | Key Feature | Weakness |
   |-----------|-------|-------------|----------|
   | Drata | $500/mo | SOC 2 automation | No HIPAA |
3. Use bullet points for findings — max 4-5 bullets, each under 20 words
4. End with exactly 2-3 "Actionable Takeaways" as bullets
5. NO long paragraphs. If you can say it in a table, use a table.
6. Use ## for the section header, ### for subsections

Section focus: {description}
Business idea context: {idea}"""),
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
        SystemMessage(content="""You are a senior market research analyst. Create a CONCISE, SCANNABLE final report.

A busy founder will spend MAX 5 minutes reading this. Make every word count.

STRUCTURE (follow exactly):

# Market Research Report: [Business Idea]

## Executive Summary
- 3-4 bullet points ONLY, each one sentence. Key numbers highlighted.

## Competitive Overview
- A markdown TABLE comparing top 3-5 competitors: | Competitor | Pricing | Strengths | Weaknesses | Your Advantage |

## Market Opportunity
- Market size as a single bold number
- 3 bullet points on trends/gaps

## Pricing Strategy
- A markdown TABLE: | Tier | Price | Target | Features |
- 1-2 sentences on positioning

## Go-To-Market Playbook
- 5 numbered action items, each ONE sentence

## Bottom Line
- 2-3 sentences: what to build, who to target, and why you'll win

RULES:
- Total report under 600 words
- Use tables wherever possible instead of bullets
- No filler words, no "In conclusion", no "It's worth noting"
- Every sentence must be actionable or contain a data point
- Preserve competitor names, prices, and numbers from the research"""),
        HumanMessage(content=f"Business idea: {idea}\n\nTarget market: {plan.get('target_market', 'N/A')}\n\nResearch data:\n{combined_sections}\n\nSources:\n" + "\n".join(all_sources))
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


# --- Image Generation via Gemini ---
IMAGE_PROMPTS = [
    "A clean, modern infographic showing a competitive landscape map with company logos positioned by market share and innovation. Professional business style, white background, minimal design.",
    "A visually appealing market positioning chart showing different pricing tiers (Free, Pro, Enterprise) with features comparison. Clean corporate infographic style.",
    "A professional target audience persona infographic showing demographics, pain points, and needs. Modern flat design with icons and data visualization.",
    "A growth strategy roadmap infographic showing phases of market entry, customer acquisition channels, and scaling milestones. Professional timeline style.",
]

def generate_research_images(idea: str, report_summary: str) -> list:
    """Generate research visuals using Gemini image generation. Returns list of image bytes."""
    images = []

    # Create contextual prompts based on the business idea
    prompts = [
        f"Create a professional business infographic: Competitive landscape overview for '{idea}'. Show a clean market map with placeholder competitor positions. Modern minimal style, light background, corporate colors.",
        f"Create a professional pricing comparison infographic for the '{idea}' market. Show 3 pricing tiers (Basic, Pro, Enterprise) with feature checkmarks. Clean modern design, light background.",
        f"Create a professional target customer persona infographic for '{idea}'. Show demographics, key pain points, and needs. Modern flat design with icons.",
        f"Create a professional growth strategy timeline infographic for '{idea}'. Show 4 phases: Launch, Growth, Scale, Dominate. Modern minimal design with milestones.",
    ]

    for i, prompt in enumerate(prompts):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=[prompt],
            )
            for part in response.parts:
                if part.inline_data is not None:
                    # Use raw bytes directly from inline_data
                    img_bytes = part.inline_data.data
                    mime = part.inline_data.mime_type or "image/png"
                    ext = "png" if "png" in mime else "jpeg"
                    images.append({
                        "data": img_bytes,
                        "filename": f"research_visual_{i+1}.{ext}",
                    })
                    break
        except Exception as e:
            print(f"Image generation {i+1} failed: {e}")
            continue

    return images
