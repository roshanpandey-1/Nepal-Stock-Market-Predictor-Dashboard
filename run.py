"""
NEPSE Intelligence Platform - Entry Point
Run: python run.py
"""
import os

# The dashboard reads the same trimmed snapshot the live site uses (deploy_data),
# so what you see locally matches Render. Set DATA_DIR yourself to override, e.g.
# DATA_DIR=data to browse the full local dataset. This must run before the app
# is imported, because the app reads DATA_DIR at import time.
os.environ.setdefault("DATA_DIR", "deploy_data")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
