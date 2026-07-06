"""Minimal Flask server for Red Hat Lifecycle Graph."""

from flask import Flask, send_from_directory
from pathlib import Path

BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / "docs"
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    return send_from_directory(DOCS_DIR, "index.html")


@app.route("/<path:filename>")
def docs_files(filename):
    filepath = DOCS_DIR / filename
    if filepath.is_file():
        return send_from_directory(DOCS_DIR, filename)
    return "Not found", 404


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
