# Serves the Flask dashboard (app/) against the trimmed deploy_data/ snapshot.
# Built for Hugging Face Spaces' Docker SDK, which expects the app to listen
# on port 7860 -- see SPACE_SETUP.md for how to actually create the Space.
FROM python:3.10-slim

WORKDIR /app

# Install dependencies first so this layer is cached across rebuilds that
# only change app code, not requirements.
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Only what's needed to serve the dashboard -- not the full data pipeline
# (training scripts, notebooks, the full gitignored data/ directory, etc.)
COPY app/ app/
COPY deploy_data/ deploy_data/
COPY run.py .

ENV DATA_DIR=deploy_data
ENV PYTHONUNBUFFERED=1

# Hugging Face Spaces' Docker SDK expects the app on port 7860 and runs the
# container as a non-root user by default -- both handled here.
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:7860", "--timeout", "120"]
