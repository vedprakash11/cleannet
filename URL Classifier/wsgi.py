"""
WSGI entry for production servers (Gunicorn on EC2, etc.).

    cd "URL Classifier"
    pip install -r requirements.txt
    gunicorn -c gunicorn.conf.py wsgi:app

See DEPLOY_EC2.md for security groups, HTTPS, and systemd.
"""

from url_classifier.web.app import app
