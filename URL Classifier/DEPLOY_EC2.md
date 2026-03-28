# Deploying the URL Classifier on AWS EC2 (Linux)

The Flask app is served in production with **Gunicorn**. Local Wi‑Fi **UDP discovery does not apply** on EC2; point the CleanNet Android app at your **public HTTPS (or HTTP) URL** for `POST /v1/classify`.

## Quick run (manual)

```bash
cd /opt/url-classifier   # or your clone path
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export CLEANNET_DISCOVERY=0
export TRUST_PROXY=1          # if behind nginx/ALB
export GUNICORN_BIND=0.0.0.0:5000
gunicorn -c gunicorn.conf.py wsgi:app
```

Open the EC2 **security group** inbound: **TCP 5000** (if exposing Gunicorn directly) or **443** / **80** if using nginx.

Health check: `GET http://<host>:5000/health` → `{"status":"ok",...}`

API: `POST http://<host>:5000/v1/classify` (use **HTTPS** in production).

## Android app

Set `classifier_api_endpoint` to your full API URL, for example:

`https://your-domain.com/v1/classify`

Leave **UDP discovery disabled** for cloud; the app uses this string (or cached value). Clear app data if you change the server URL.

## Environment variables (reference)

| Variable | Purpose |
|----------|---------|
| `CLEANNET_DISCOVERY` | Set `0` on EC2 (no LAN UDP). |
| `TRUST_PROXY` | Set `1` behind nginx/ALB so client IP / HTTPS scheme are correct. |
| `GUNICORN_BIND` | Default `0.0.0.0:5000`. |
| `GUNICORN_WORKERS` | Default `2` (each worker loads the ML model — watch RAM). |
| `GUNICORN_TIMEOUT` | Default `120` seconds (URL classification can be slow). |
| `MAX_IMAGE_UPLOAD_BYTES` | Max upload size for `/classify-image` (default 8 MB). |

## systemd

See `deploy/ec2/cleannet-classifier.service`. Adjust `User`, `WorkingDirectory`, and paths to match your server.

## nginx + TLS

See `deploy/ec2/nginx-url-classifier.conf.example`. Use Let’s Encrypt (`certbot`) or AWS ACM (with ALB).

---

## Details to confirm (so deployment matches your setup)

1. **Access pattern** — Will clients use a **domain name** (e.g. `classifier.example.com`) or **raw public IP**? (HTTPS almost always needs a domain.)
2. **TLS** — Terminate TLS on **nginx on the instance**, **Application Load Balancer**, or **CloudFront**? (Sets whether `TRUST_PROXY=1` and how many hops to configure.)
3. **Instance** — Type and RAM (e.g. `t3.small`)? Each Gunicorn worker loads scikit-learn + model; start with **`GUNICORN_WORKERS=2`** or **`1`** on small instances.
4. **Ports** — Direct Gunicorn on **5000**, or only **443** behind nginx/ALB?
5. **Firewall** — Security group + OS firewall (`firewalld`/`ufw`) rules you can apply.
6. **Android** — Final base URL you will put in `classifier_api_endpoint` (must match scheme: `https://` if you use HTTPS).

If you share these, the service file and nginx snippet can be tailored (domain, paths, worker count).
