"""Run the Flask UI + API: ``python app.py`` from the ``URL Classifier`` folder."""

import os

from url_classifier.web.app import app
from url_classifier.web.discovery import start_discovery_responder

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    if os.environ.get("CLEANNET_DISCOVERY", "1") != "0":
        start_discovery_responder(port)
    print(
        f"\n  Flask UI: http://127.0.0.1:{port}/\n"
        f"  Same Wi‑Fi: CleanNet auto-discovers this PC (UDP); optional override in app strings.\n"
        f"  Listening: {host}:{port}\n",
        flush=True,
    )
    # Single process so discovery UDP is not bound twice (Werkzeug reloader).
    app.run(debug=True, host=host, port=port, threaded=True, use_reloader=False)
