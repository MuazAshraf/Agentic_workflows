"""
Main Flask app — registers all agent Blueprints on a single port.

Routes:
  /                     → Landing page
  /invoice/             → Prompt Chaining Agent (Invoice Pipeline)
  /research/            → Orchestrator-Worker Agent (Market Research)
"""
from flask import Flask, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- Register Blueprints ---
from PromptChainingAgent.app import invoice_bp
from Orchestrator_workerAgent.app import research_bp
from evaluator_optimizerAgent.app import tutor_bp
from RoutingAgent.app import support_bp
from ParallelizationAgent.app import content_bp

app.register_blueprint(invoice_bp)
app.register_blueprint(research_bp)
app.register_blueprint(tutor_bp)
app.register_blueprint(support_bp)
app.register_blueprint(content_bp)


# --- Landing page ---
@app.route("/")
def landing():
    return send_from_directory(".", "agents_landingpage.html")


if __name__ == "__main__":
    print("\n=== Agent Workflows Server ===")
    print("  http://localhost:5000/              → Landing Page")
    print("  http://localhost:5000/invoice/       → Invoice Pipeline")
    print("  http://localhost:5000/research/      → Market Research")
    print("  http://localhost:5000/tutor/         → AI Tutor")
    print("  http://localhost:5000/support/       → Customer Support")
    print("  http://localhost:5000/content/       → Content Generator")
    print()
    app.run(debug=True, port=5000)
