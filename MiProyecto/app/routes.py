from flask import Blueprint, jsonify, render_template

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    """Render the project landing page."""
    return render_template("index.html", project_name="MiProyecto")


@main_bp.get("/health")
def health():
    """Simple health-check endpoint for deployment platforms."""
    return jsonify(status="ok"), 200
