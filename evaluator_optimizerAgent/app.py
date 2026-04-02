"""Blueprint for AI Tutor — Evaluator-Optimizer Agent"""
import os
from flask import Blueprint, request, jsonify, send_from_directory
from evaluator_optimizerAgent.eo import start_lesson, submit_answers, retry_lesson

tutor_bp = Blueprint("tutor", __name__, url_prefix="/tutor")


@tutor_bp.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "eo.html")


@tutor_bp.route("/api/start-lesson", methods=["POST"])
def api_start_lesson():
    data = request.get_json()
    if not data or not data.get("topic", "").strip():
        return jsonify({"error": "Please provide a topic"}), 400

    topic = data["topic"].strip()
    try:
        result = start_lesson(topic)
        return jsonify({
            "success": True,
            "explanation": result.get("explanation", ""),
            "quiz": result.get("quiz", {}),
            "attempt": result.get("attempt", 1),
            "difficulty": result.get("difficulty", 2),
            "status": result.get("status", ""),
            "state": {
                "topic": result.get("topic", ""),
                "difficulty": result.get("difficulty", 2),
                "explanation": result.get("explanation", ""),
                "quiz": result.get("quiz", {}),
                "history": result.get("history", []),
                "attempt": result.get("attempt", 1),
                "max_attempts": result.get("max_attempts", 3),
                "status": result.get("status", ""),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tutor_bp.route("/api/submit-answers", methods=["POST"])
def api_submit_answers():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    state = data.get("state", {})
    answers = data.get("answers", [])

    if not state or not answers:
        return jsonify({"error": "State and answers are required"}), 400

    try:
        # Fill in required state fields with defaults
        state.setdefault("student_answers", [])
        state.setdefault("evaluation", {})
        state.setdefault("error", "")

        result = submit_answers(state, answers)
        evaluation = result.get("evaluation", {})

        return jsonify({
            "success": True,
            "evaluation": evaluation,
            "passed": evaluation.get("passed", False),
            "status": result.get("status", ""),
            "state": {
                "topic": result.get("topic", ""),
                "difficulty": result.get("difficulty", 2),
                "explanation": result.get("explanation", ""),
                "quiz": result.get("quiz", {}),
                "student_answers": answers,
                "evaluation": evaluation,
                "history": result.get("history", []),
                "attempt": result.get("attempt", 1),
                "max_attempts": result.get("max_attempts", 3),
                "status": result.get("status", ""),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tutor_bp.route("/api/retry-lesson", methods=["POST"])
def api_retry_lesson():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    state = data.get("state", {})
    if not state:
        return jsonify({"error": "State is required"}), 400

    try:
        state.setdefault("student_answers", [])
        state.setdefault("evaluation", {})
        state.setdefault("error", "")

        result = retry_lesson(state)
        return jsonify({
            "success": True,
            "explanation": result.get("explanation", ""),
            "quiz": result.get("quiz", {}),
            "attempt": result.get("attempt", 1),
            "difficulty": result.get("difficulty", 2),
            "status": result.get("status", ""),
            "state": {
                "topic": result.get("topic", ""),
                "difficulty": result.get("difficulty", 2),
                "explanation": result.get("explanation", ""),
                "quiz": result.get("quiz", {}),
                "history": result.get("history", []),
                "attempt": result.get("attempt", 1),
                "max_attempts": result.get("max_attempts", 3),
                "status": result.get("status", ""),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
