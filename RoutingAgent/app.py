"""Blueprint for Smart Customer Support — Routing Agent"""
import os
from flask import Blueprint, request, jsonify, send_from_directory
from RoutingAgent.routing import handle_support_query

support_bp = Blueprint("support", __name__, url_prefix="/support")


@support_bp.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "routing.html")


@support_bp.route("/api/query", methods=["POST"])
def query():
    data = request.get_json()
    if not data or not data.get("query", "").strip():
        return jsonify({"error": "Please provide a customer query"}), 400

    query_text = data["query"].strip()

    try:
        result = handle_support_query(query_text)
        return jsonify({
            "success": not bool(result.get("error")),
            "category": result.get("category", ""),
            "confidence": result.get("confidence", 0),
            "reasoning": result.get("reasoning", ""),
            "response": result.get("response", ""),
            "specialist": result.get("specialist", ""),
            "error": result.get("error", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
