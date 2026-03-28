# Production setup on EC2 (Linux)

**Do not run Flask’s built-in server in production** (`python app.py`). Use **Gunicorn** as the app server and **Nginx** as the reverse proxy on port **80** so clients use `http://<your-ec2-ip>/` with **no port in the URL**.

---

## 1. App directory and virtualenv

```bash
cd /opt/url-classifier   # or your clone path
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` already includes **gunicorn**.

---

## 2. Environment (behind Nginx)

```bash
export CLEANNET_DISCOVERY=0
export TRUST_PROXY=1
export GUNICORN_BIND=127.0.0.1:5000
export GUNICORN_WORKERS=4
```

- **`TRUST_PROXY=1`** — Required so Flask sees real client IPs and `X-Forwarded-*` from Nginx.
- **`GUNICORN_BIND=127.0.0.1:5000`** — Gunicorn listens **only on localhost**. The public internet talks to **Nginx on port 80**, not to Gunicorn directly.
- **`GUNICORN_WORKERS`** — `4` matches a common setup; each worker loads the ML model — on small instances use **`2`** to avoid OOM.

---

## 3. Run with Gunicorn (WSGI entry for this repo)

This project exposes the app as **`wsgi:app`** (see `wsgi.py`), not `app:app`.

```bash
cd /opt/url-classifier
source venv/bin/activate
gunicorn -c gunicorn.conf.py wsgi:app
```

Equivalent one-liner (without `gunicorn.conf.py`):

```bash
gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app
```

---

## 4. Install Nginx

```bash
sudo apt update
sudo apt install nginx -y
```

---

## 5. Configure Nginx (HTTP on port 80)

Copy the example from the repo:

```bash
sudo cp deploy/ec2/nginx-flaskapp-http80.conf /etc/nginx/sites-available/flaskapp
```

Or create `/etc/nginx/sites-available/flaskapp` with the same contents (proxy to `http://127.0.0.1:5000`).

Enable the site:

```bash
sudo ln -sf /etc/nginx/sites-available/flaskapp /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## 6. Security group (AWS)

- Allow inbound **TCP 22** (SSH) and **TCP 80** (HTTP).
- **Do not** open **TCP 5000** to `0.0.0.0/0` when using this layout — Gunicorn is bound to **127.0.0.1** only.

---

## 7. Verify

- Browser or curl: `http://<your-ec2-public-ip>/health` → `{"status":"ok",...}`
- API: `POST http://<your-ec2-public-ip>/v1/classify`

---

## 8. Android app (`classifier_api_endpoint`)

Use the **public URL without `:5000`**:

`http://<your-ec2-public-ip>/v1/classify`

The repo default in `strings.xml` follows this pattern (edit the IP if yours differs).

---

## 9. HTTPS (recommended later)

Use Let’s Encrypt (`certbot`) or terminate TLS on an ALB. See `deploy/ec2/nginx-url-classifier.conf.example` for an HTTPS server block pattern.

---

## 10. systemd

See `deploy/ec2/cleannet-classifier.service` — set `WorkingDirectory`, `User`, and ensure `Environment` includes `TRUST_PROXY=1` and `GUNICORN_BIND=127.0.0.1:5000`.

---

## Details to confirm (optional)

1. **Domain vs raw IP** — For HTTPS, a domain is usually required.
2. **Worker count** — `4` vs `2` depending on instance RAM.
3. **Final Android URL** — `http://` vs `https://` after you add TLS.
