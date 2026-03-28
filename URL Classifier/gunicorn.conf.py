"""
Gunicorn configuration. Override via environment variables on EC2.

Production (behind Nginx): bind only to localhost so port 5000 is not exposed.

    export GUNICORN_BIND=127.0.0.1:5000
    export GUNICORN_WORKERS=4
    gunicorn -c gunicorn.conf.py wsgi:app

Direct exposure (not recommended): GUNICORN_BIND=0.0.0.0:5000

Each worker loads the sklearn model — lower GUNICORN_WORKERS on small instances.
"""

import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:5000")
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
worker_class = "sync"
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
capture_output = True

# Optional: reduce memory if you increase workers (see DEPLOY_EC2.md)
# preload_app = True
