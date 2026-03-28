"""
WSGI entry for production (Gunicorn + Nginx). Do not use Flask’s dev server in prod.

    cd "URL Classifier"
    source venv/bin/activate
    pip install -r requirements.txt
    export TRUST_PROXY=1
    export GUNICORN_BIND=127.0.0.1:5000
    gunicorn -c gunicorn.conf.py wsgi:app

One-liner (same app, 4 workers):

    gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app

Put Nginx on port 80 → proxy_pass http://127.0.0.1:5000 — see DEPLOY_EC2.md.
"""

import os
import sys

# Gunicorn/systemd must resolve `url_classifier`; cwd is not always the repo root.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from url_classifier.web.app import app  # noqa: E402
