"""Blueprint for Market Research Tool — Orchestrator-Worker Agent"""
import os
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, send_file
from fpdf import FPDF
from Orchestrator_workerAgent.orc import run_market_research

research_bp = Blueprint("research", __name__, url_prefix="/research")


@research_bp.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "orc.html")


@research_bp.route("/api/research", methods=["POST"])
def research():
    data = request.get_json()
    if not data or not data.get("idea", "").strip():
        return jsonify({"error": "Please provide a business idea"}), 400

    idea = data["idea"].strip()

    try:
        result = run_market_research(idea)
        return jsonify({
            "success": not bool(result.get("error")),
            "plan": result.get("plan", {}),
            "sections": result.get("completed_sections", []),
            "final_report": result.get("final_report", ""),
            "error": result.get("error", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@research_bp.route("/api/download-report", methods=["POST"])
def download_report():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    report_md = data.get("report", "")
    idea = data.get("idea", "Market Research")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pw = pdf.w - 40

    DARK = (15, 23, 42)
    ACCENT = (59, 130, 246)
    GRAY = (100, 116, 139)
    WHITE = (255, 255, 255)

    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, pdf.w, 40, "F")
    pdf.set_y(8)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "MARKET RESEARCH REPORT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(200, 220, 255)
    pdf.cell(0, 8, f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(48)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, "BUSINESS IDEA", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(pw, 6, idea[:500])
    pdf.ln(4)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
    pdf.ln(4)

    lines = report_md.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue
        if stripped.startswith("# "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(pw, 8, stripped[2:])
            pdf.ln(2)
        elif stripped.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*ACCENT)
            pdf.multi_cell(pw, 7, stripped[3:])
            pdf.ln(1)
        elif stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(pw, 6, stripped[4:])
            pdf.ln(1)
        elif stripped.startswith("---"):
            pdf.set_draw_color(226, 232, 240)
            pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
            pdf.ln(4)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            bullet_text = stripped[2:].replace("**", "")
            pdf.cell(8, 5, "-", new_x="RIGHT")
            pdf.multi_cell(pw - 8, 5, bullet_text)
        elif stripped.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(pw, 5, stripped)
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(pw, 5, stripped.replace("**", ""))

    pdf.ln(8)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "Market Research Report | Orchestrator-Worker Agent", align="C")

    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in idea[:30]).strip().replace(" ", "_")
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"market_research_{safe_name}.pdf")
