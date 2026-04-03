"""Blueprint for Multi-Platform Content Generator — Parallelization Agent"""
import os
from flask import Blueprint, request, jsonify, send_from_directory
from ParallelizationAgent.parallel import generate_content

content_bp = Blueprint("content", __name__, url_prefix="/content")


@content_bp.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "parallel.html")


@content_bp.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    if not data or not data.get("topic", "").strip():
        return jsonify({"error": "Please provide a topic"}), 400

    topic = data["topic"].strip()
    context = data.get("context", "").strip()
    tone = data.get("tone", "professional")

    try:
        result = generate_content(topic, context, tone)
        return jsonify({
            "success": not bool(result.get("error")),
            "twitter": result.get("twitter", ""),
            "linkedin": result.get("linkedin", ""),
            "blog": result.get("blog", ""),
            "email": result.get("email", ""),
            "error": result.get("error", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
