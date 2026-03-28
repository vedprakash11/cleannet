"""WSGI entry for production servers (e.g. ``waitress-serve --call wsgi:app``)."""

from url_classifier.web.app import app
