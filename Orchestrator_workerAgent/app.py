"""Blueprint for Market Research Tool — Orchestrator-Worker Agent"""
import os
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, send_file
from fpdf import FPDF
import zipfile
from Orchestrator_workerAgent.orc import run_market_research, generate_research_images

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


@research_bp.route("/api/generate-images", methods=["POST"])
def generate_images():
    """Generate research visuals using Gemini and return as a zip file."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    idea = data.get("idea", "")
    report_summary = data.get("report", "")[:500]

    try:
        images = generate_research_images(idea, report_summary)
        if not images:
            return jsonify({"error": "No images were generated. Gemini may be rate-limited."}), 500

        # Package into a zip file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for img in images:
                zf.writestr(img["filename"], img["data"])
        zip_buffer.seek(0)

        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in idea[:30]).strip().replace(" ", "_")
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"research_visuals_{safe_name}.zip"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@research_bp.route("/api/download-report", methods=["POST"])
def download_report():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    report_md = data.get("report", "")
    idea = data.get("idea", "Market Research")

    def sanitize_text(text):
        """Replace unicode chars that Helvetica can't handle."""
        replacements = {
            "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u2022": "-",
            "\u2192": "->", "\u2190": "<-", "\u2715": "x", "\u2713": "v",
            "\u2714": "v", "\u2716": "x", "\u00a0": " ", "\u200b": "",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        # Strip any remaining non-latin-1 chars
        return text.encode("latin-1", errors="replace").decode("latin-1")

    report_md = sanitize_text(report_md)
    idea = sanitize_text(idea)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pw = pdf.w - 40
    ml = 20  # margin left

    DARK = (15, 23, 42)
    ACCENT = (59, 130, 246)
    GRAY = (100, 116, 139)
    LIGHT_BG = (245, 247, 250)
    WHITE = (255, 255, 255)

    # --- Header ---
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
    pdf.ln(6)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(ml, pdf.get_y(), pdf.w - ml, pdf.get_y())
    pdf.ln(6)

    # --- Table renderer ---
    def render_table(rows):
        """Render a markdown table. rows = list of lists of cell strings."""
        if len(rows) < 2:
            return
        headers = rows[0]
        data_rows = [r for r in rows[1:] if not all(c.strip().replace("-", "") == "" for c in r)]
        num_cols = len(headers)
        if num_cols == 0:
            return
        col_w = pw / num_cols

        # Header row
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(*DARK)
        pdf.set_text_color(*WHITE)
        pdf.set_x(ml)
        for i, h in enumerate(headers):
            if i < num_cols - 1:
                pdf.cell(col_w, 7, h.strip(), fill=True, align="C", new_x="RIGHT")
            else:
                pdf.cell(col_w, 7, h.strip(), fill=True, align="C", new_x="LMARGIN", new_y="NEXT")

        # Data rows
        pdf.set_font("Helvetica", "", 7.5)
        for ri, row in enumerate(data_rows):
            bg = LIGHT_BG if ri % 2 == 0 else WHITE
            pdf.set_fill_color(*bg)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml)
            # Calculate row height based on longest cell
            max_lines = 1
            for cell in row:
                cell_text = cell.strip().replace("**", "")
                lines_needed = max(1, len(cell_text) // int(col_w / 1.8))
                max_lines = max(max_lines, lines_needed)
            rh = max(6, max_lines * 4.5)
            for i, cell in enumerate(row):
                cell_text = cell.strip().replace("**", "")
                if i < num_cols - 1:
                    pdf.cell(col_w, rh, cell_text[:50], fill=True, align="C", new_x="RIGHT")
                else:
                    pdf.cell(col_w, rh, cell_text[:50], fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # --- Parse and render markdown ---
    lines = report_md.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Skip empty lines with spacing
        if not stripped:
            pdf.ln(3)
            i += 1
            continue

        clean = stripped.replace("**", "")

        # Detect table (line starts with |)
        if stripped.startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(row)
                i += 1
            render_table(table_rows)
            continue

        # Headings
        if stripped.startswith("# "):
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 15)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml)
            pdf.multi_cell(pw, 7, clean[2:])
            pdf.ln(3)
        elif stripped.startswith("## "):
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*ACCENT)
            pdf.set_x(ml)
            pdf.multi_cell(pw, 7, clean[3:])
            pdf.ln(2)
        elif stripped.startswith("### "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml)
            pdf.multi_cell(pw, 6, clean[4:])
            pdf.ln(2)
        # Horizontal rule
        elif stripped.startswith("---"):
            pdf.ln(2)
            pdf.set_draw_color(226, 232, 240)
            pdf.line(ml, pdf.get_y(), pdf.w - ml, pdf.get_y())
            pdf.ln(4)
        # Bullets
        elif stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml + 4)
            pdf.multi_cell(pw - 4, 5, "  -  " + clean[2:])
            pdf.ln(1)
        # Numbered list
        elif stripped.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml + 4)
            pdf.multi_cell(pw - 4, 5, clean)
            pdf.ln(1)
        # Normal text
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.set_x(ml)
            pdf.multi_cell(pw, 5, clean)
            pdf.ln(1)

        i += 1

    # --- Footer ---
    pdf.ln(8)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(ml, pdf.get_y(), pdf.w - ml, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "Market Research Report | Orchestrator-Worker Agent", align="C")

    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in idea[:30]).strip().replace(" ", "_")
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"market_research_{safe_name}.pdf")
