"""
AI Tutor — Evaluator-Optimizer Agent

Teach concept with Mermaid diagrams → Quiz → Evaluate → Re-teach if needed (loop)
"""
import os
import json
from typing import List, Optional
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))


# --- Schemas ---
class QuizQuestion(BaseModel):
    question: str = Field(description="The quiz question")
    options: List[str] = Field(description="4 answer options labeled A, B, C, D")
    correct_answer: str = Field(description="The correct option letter: A, B, C, or D")
    explanation: str = Field(description="Why this answer is correct")


class QuizSet(BaseModel):
    questions: List[QuizQuestion] = Field(description="4 multiple choice questions")


class EvalResult(BaseModel):
    score: int = Field(description="Number of correct answers out of total")
    total: int = Field(description="Total number of questions")
    passed: bool = Field(description="True if score >= 70% of total")
    weak_areas: List[str] = Field(description="Topics the student got wrong or seems confused about")
    feedback: str = Field(description="Specific feedback on what to re-explain and how to make it simpler")


# --- State ---
class TutorState(TypedDict):
    topic: str
    difficulty: int  # 1=beginner, 2=intermediate, 3=advanced (starts at 2, decreases on fail)
    explanation: str  # Current explanation with mermaid diagram
    quiz: dict  # Current quiz questions
    student_answers: list  # Student's selected answers
    evaluation: dict  # Eval results
    history: list  # List of past attempts [{explanation, quiz, answers, eval}]
    attempt: int
    max_attempts: int
    status: str  # "teaching", "quizzing", "passed", "needs_review"
    error: str


# --- Node 1: Teach ---
def teach(state: TutorState) -> dict:
    """Generate explanation with Mermaid diagram"""
    topic = state["topic"]
    difficulty = state.get("difficulty", 2)
    attempt = state.get("attempt", 1)
    history = state.get("history", [])

    difficulty_map = {1: "very simple, like explaining to a 10-year-old", 2: "intermediate, for a college student", 3: "advanced, for a professional"}
    diff_text = difficulty_map.get(difficulty, difficulty_map[2])

    # Build context from past failures
    past_context = ""
    if history:
        last = history[-1]
        past_eval = last.get("evaluation", {})
        past_context = f"""

IMPORTANT: The student failed the previous quiz. Here's what went wrong:
- Weak areas: {', '.join(past_eval.get('weak_areas', []))}
- Feedback: {past_eval.get('feedback', 'Make it simpler')}

You MUST explain differently this time. Use simpler language, more analogies, and a clearer diagram.
Do NOT repeat the same explanation."""

    result = llm.invoke([
        SystemMessage(content=f"""You are an expert tutor. Explain the given topic clearly and engagingly.

Difficulty level: {diff_text}
Attempt: {attempt}

Your response MUST include:
1. A clear, structured explanation using markdown (use ## for headers, bullet points, **bold** for key terms)
2. A Mermaid.js diagram that visually explains the concept. The diagram should be simple and clear.
   - Wrap the diagram in ```mermaid``` code blocks
   - Use graph TD or graph LR format
   - Keep it under 15 lines
   - Use colors with style directives (fill:#3b82f6 for blue, fill:#10b981 for green, fill:#f59e0b for yellow)
   - Make it educational — show the FLOW or STRUCTURE of the concept
3. A real-world analogy that makes the concept click

Keep the explanation under 300 words. Make it engaging, not textbook-boring.{past_context}"""),
        HumanMessage(content=f"Explain this topic: {topic}")
    ])

    return {
        "explanation": result.content,
        "status": "teaching",
        "attempt": attempt
    }


# --- Node 2: Generate Quiz ---
quiz_llm = llm.with_structured_output(QuizSet)

def generate_quiz(state: TutorState) -> dict:
    """Generate MCQ quiz based on the explanation"""
    result = quiz_llm.invoke([
        SystemMessage(content="""Create exactly 4 multiple-choice questions to test understanding of the explanation below.

Rules:
- Each question has exactly 4 options: A, B, C, D
- Only ONE correct answer per question
- Questions should test understanding, not memorization
- Include 1 easy, 2 medium, and 1 tricky question
- correct_answer must be just the letter: A, B, C, or D"""),
        HumanMessage(content=f"Based on this explanation, create a quiz:\n\n{state['explanation']}")
    ])

    return {
        "quiz": {"questions": [q.model_dump() for q in result.questions]},
        "status": "quizzing"
    }


# --- Node 3: Evaluate ---
def evaluate(state: TutorState) -> dict:
    """Evaluate student answers and decide pass/fail"""
    quiz = state.get("quiz", {})
    questions = quiz.get("questions", [])
    answers = state.get("student_answers", [])

    correct = 0
    total = len(questions)
    weak_areas = []

    for i, q in enumerate(questions):
        student_ans = answers[i] if i < len(answers) else ""
        if student_ans.upper() == q.get("correct_answer", "").upper():
            correct += 1
        else:
            weak_areas.append(q.get("question", f"Question {i+1}"))

    passed = correct >= (total * 0.7) if total > 0 else False

    # Get LLM feedback on weak areas
    feedback = ""
    if not passed and weak_areas:
        fb_result = llm.invoke([
            SystemMessage(content="You are a tutor analyzing quiz results. Give brief, specific feedback on what the student doesn't understand and how to explain it better next time. Keep it under 100 words."),
            HumanMessage(content=f"Topic: {state['topic']}\nStudent got these wrong:\n" + "\n".join(weak_areas))
        ])
        feedback = fb_result.content

    evaluation = {
        "score": correct,
        "total": total,
        "passed": passed,
        "percentage": round((correct / total) * 100) if total > 0 else 0,
        "weak_areas": weak_areas,
        "feedback": feedback
    }

    # Save to history
    history = list(state.get("history", []))
    history.append({
        "attempt": state.get("attempt", 1),
        "explanation": state.get("explanation", ""),
        "quiz": state.get("quiz", {}),
        "answers": answers,
        "evaluation": evaluation
    })

    new_status = "passed" if passed else "needs_review"
    new_difficulty = max(1, state.get("difficulty", 2) - 1) if not passed else state.get("difficulty", 2)

    return {
        "evaluation": evaluation,
        "history": history,
        "status": new_status,
        "difficulty": new_difficulty
    }


# --- Route: pass or re-teach ---
def route_evaluation(state: TutorState) -> str:
    evaluation = state.get("evaluation", {})
    attempt = state.get("attempt", 1)
    max_attempts = state.get("max_attempts", 3)

    if evaluation.get("passed", False):
        return END
    if attempt >= max_attempts:
        return END
    return "teach"


# --- Build Workflow ---
# Note: This is a 2-phase workflow.
# Phase 1: teach → generate_quiz (returns to user for answering)
# Phase 2: evaluate → route (pass=END, fail=teach loop)
# We build TWO compiled graphs since the student answers in between.

# Phase 1: Teach + Quiz
teach_workflow = StateGraph(TutorState)
teach_workflow.add_node("teach", teach)
teach_workflow.add_node("generate_quiz", generate_quiz)
teach_workflow.add_edge(START, "teach")
teach_workflow.add_edge("teach", "generate_quiz")
teach_workflow.add_edge("generate_quiz", END)
teach_chain = teach_workflow.compile()

# Phase 2: Evaluate + Route
eval_workflow = StateGraph(TutorState)
eval_workflow.add_node("evaluate", evaluate)
eval_workflow.add_edge(START, "evaluate")
eval_workflow.add_edge("evaluate", END)
eval_chain = eval_workflow.compile()


def start_lesson(topic: str) -> dict:
    """Start a new lesson — returns explanation + quiz"""
    state = {
        "topic": topic,
        "difficulty": 2,
        "explanation": "",
        "quiz": {},
        "student_answers": [],
        "evaluation": {},
        "history": [],
        "attempt": 1,
        "max_attempts": 3,
        "status": "teaching",
        "error": ""
    }
    result = teach_chain.invoke(state)
    return result


def submit_answers(state: dict, answers: list) -> dict:
    """Submit student answers — evaluates and returns result"""
    state["student_answers"] = answers
    result = eval_chain.invoke(state)
    return result


def retry_lesson(state: dict) -> dict:
    """Re-teach after failure — returns new explanation + quiz"""
    state["attempt"] = state.get("attempt", 1) + 1
    state["student_answers"] = []
    state["quiz"] = {}
    state["explanation"] = ""
    result = teach_chain.invoke(state)
    return result
