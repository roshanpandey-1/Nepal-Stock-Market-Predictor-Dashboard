"""Gunicorn settings, read automatically when gunicorn starts in this folder (Render runs
`gunicorn run:app --bind 0.0.0.0:$PORT --timeout 120`; command-line flags still win).

Threads let one worker serve several requests at once. Without them a single slow request,
for example a live NEPSE call waiting up to ~30 s on a server outside Nepal, blocked every
other request, including Render's health checks, and Render restarted the app.
Threads share one process, so memory stays the same as a single worker.
"""
worker_class = "gthread"
workers = 1
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
