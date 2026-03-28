"""
Gunicorn configuration. Override via environment variables on EC2.

    GUNICORN_BIND=0.0.0.0:5000
    GUNICORN_WORKERS=2
    GUNICORN_TIMEOUT=120

Each worker loads the sklearn model — use a small worker count on small instances.
"""

import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5000")
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
worker_class = "sync"
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
capture_output = True

# Optional: reduce memory if you increase workers (see DEPLOY_EC2.md)
# preload_app = True
