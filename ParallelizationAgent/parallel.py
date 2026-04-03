"""
Multi-Platform Content Generator — Parallelization Agent

4 parallel workers generate content for different platforms simultaneously, then aggregate.
"""
import os
from typing import Annotated
from typing_extensions import TypedDict
import operator
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))


# --- State ---
class ContentState(TypedDict):
    topic: str
    context: str  # Additional context/details from user
    tone: str  # professional, casual, excited, informative
    twitter: str
    linkedin: str
    blog: str
    email: str
    error: str


# --- Worker 1: Twitter/X Thread ---
def generate_twitter(state: ContentState):
    """Generate a Twitter/X thread"""
    result = llm.invoke([
        SystemMessage(content=f"""You are a viral Twitter/X content creator. Write a thread about the given topic.

Rules:
- Write exactly 5 tweets in a thread
- First tweet is the hook (attention-grabbing, makes people want to read more)
- Each tweet max 280 characters
- Use line breaks between tweets
- Format: "1/ [tweet]" then "2/ [tweet]" etc.
- Include 1-2 relevant emojis per tweet (not excessive)
- Last tweet = CTA (call to action)
- Tone: {state.get('tone', 'professional')}

Do NOT use hashtags in every tweet. Max 2-3 hashtags in the last tweet only."""),
        HumanMessage(content=f"Topic: {state['topic']}\nContext: {state.get('context', 'N/A')}")
    ])
    return {"twitter": result.content}


# --- Worker 2: LinkedIn Post ---
def generate_linkedin(state: ContentState):
    """Generate a LinkedIn post"""
    result = llm.invoke([
        SystemMessage(content=f"""You are a LinkedIn content strategist. Write a single LinkedIn post.

Rules:
- Start with a strong hook (first line people see before "...see more")
- 150-200 words max
- Use short paragraphs (1-2 sentences each)
- Include a personal angle or insight
- End with a question to drive engagement
- Add 3-5 relevant hashtags at the end
- Tone: {state.get('tone', 'professional')}
- Use line breaks for readability (LinkedIn rewards whitespace)

Do NOT be generic. Be specific and opinionated."""),
        HumanMessage(content=f"Topic: {state['topic']}\nContext: {state.get('context', 'N/A')}")
    ])
    return {"linkedin": result.content}


# --- Worker 3: Blog Post ---
def generate_blog(state: ContentState):
    """Generate a blog post outline + intro"""
    result = llm.invoke([
        SystemMessage(content=f"""You are a blog content writer. Write a blog post outline with an introduction.

Rules:
- Write a compelling title (SEO-friendly)
- Write an intro paragraph (3-4 sentences, hook the reader)
- Then an outline with 5-6 sections (## heading + 1-sentence description each)
- End with a conclusion section description
- Use markdown formatting
- Tone: {state.get('tone', 'informative')}
- Total output: ~200 words

The outline should be practical and actionable, not generic."""),
        HumanMessage(content=f"Topic: {state['topic']}\nContext: {state.get('context', 'N/A')}")
    ])
    return {"blog": result.content}


# --- Worker 4: Email Newsletter ---
def generate_email(state: ContentState):
    """Generate an email newsletter draft"""
    result = llm.invoke([
        SystemMessage(content=f"""You are an email marketing specialist. Write a newsletter email draft.

Rules:
- Subject line (compelling, under 60 chars)
- Preview text (under 90 chars)
- Email body: 150-200 words max
- Structure: Hook → Value → CTA
- One clear call-to-action button text
- Tone: {state.get('tone', 'professional')} but conversational
- Use short paragraphs
- Format with markdown (## for subject, **bold** for emphasis)

Write like you're emailing a friend who happens to be a professional."""),
        HumanMessage(content=f"Topic: {state['topic']}\nContext: {state.get('context', 'N/A')}")
    ])
    return {"email": result.content}


# --- Aggregator ---
def aggregate(state: ContentState):
    """All content is already in state from parallel workers. Just validate."""
    return {"error": ""}


# --- Build Workflow ---
workflow = StateGraph(ContentState)

# Add nodes
workflow.add_node("twitter", generate_twitter)
workflow.add_node("linkedin", generate_linkedin)
workflow.add_node("blog", generate_blog)
workflow.add_node("email", generate_email)
workflow.add_node("aggregate", aggregate)

# Fan out from START to all 4 workers in parallel
workflow.add_edge(START, "twitter")
workflow.add_edge(START, "linkedin")
workflow.add_edge(START, "blog")
workflow.add_edge(START, "email")

# All workers feed into aggregator
workflow.add_edge("twitter", "aggregate")
workflow.add_edge("linkedin", "aggregate")
workflow.add_edge("blog", "aggregate")
workflow.add_edge("email", "aggregate")

workflow.add_edge("aggregate", END)

content_chain = workflow.compile()


def generate_content(topic: str, context: str = "", tone: str = "professional") -> dict:
    """Generate content for all 4 platforms."""
    initial_state = {
        "topic": topic,
        "context": context,
        "tone": tone,
        "twitter": "",
        "linkedin": "",
        "blog": "",
        "email": "",
        "error": ""
    }
    return content_chain.invoke(initial_state)
