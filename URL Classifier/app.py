"""Run the Flask UI + API: ``python app.py`` from the ``URL Classifier`` folder.

Production on Linux/EC2: use Gunicorn instead — see ``wsgi.py`` and ``DEPLOY_EC2.md``.
"""

import os

from url_classifier.web.app import app
from url_classifier.web.discovery import start_discovery_responder


def _env_truthy(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    # Cloud / EC2: set CLEANNET_DISCOVERY=0 (UDP is only for same LAN).
    if _env_truthy("CLEANNET_DISCOVERY", "1"):
        start_discovery_responder(port)
    flask_debug = _env_truthy("FLASK_DEBUG", "1")
    print(
        f"\n  Flask UI: http://127.0.0.1:{port}/\n"
        f"  Dev: FLASK_DEBUG=1 (default). EC2: use gunicorn + CLEANNET_DISCOVERY=0 — see DEPLOY_EC2.md\n"
        f"  Listening: {host}:{port}  debug={flask_debug}\n",
        flush=True,
    )
    app.run(
        debug=flask_debug,
        host=host,
        port=port,
        threaded=True,
        use_reloader=False,
    )
