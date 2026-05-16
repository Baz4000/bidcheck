# Empire OS — Deployment Guide

## Recommended stack
- DigitalOcean / Vultr VPS: Ubuntu 22.04, 1 GB RAM ($6–$12/mo)
- PostgreSQL 15
- Nginx + Gunicorn
- Let's Encrypt SSL (certbot)
- Playwright Chromium (headless)

---

## 1. Provision a VPS

Create a droplet (Ubuntu 22.04 LTS, 1 GB RAM minimum).
Add your SSH key during provisioning.
Point a domain's A record at the droplet IP.

---

## 2. Initial server setup

```bash
# As root
adduser barry
usermod -aG sudo barry
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable

# Install dependencies
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv nginx postgresql \
               certbot python3-certbot-nginx \
               libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
               libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
               libxrandr2 libgbm1 libasound2
```

---

## 3. PostgreSQL setup

```bash
sudo -u postgres psql
CREATE USER empire_os WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE empire_os OWNER empire_os;
\q
```

---

## 4. Deploy the application

```bash
sudo mkdir -p /srv/empire-os
sudo chown barry:barry /srv/empire-os

# As barry
cd /srv/empire-os
git clone https://github.com/YOU/empire-os.git .    # or scp/rsync from local
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# Create .env
cp .env.example .env
nano .env   # fill in real values:
#   SECRET_KEY=<long random string>
#   DEBUG=False
#   ALLOWED_HOSTS=yourdomain.com
#   DATABASE_URL=postgres://empire_os:PASSWORD@localhost:5432/empire_os
#   KALITTA_USERNAME=71837
#   KALITTA_PASSWORD=<your kalitta password>

# Migrate & collect static
DJANGO_SETTINGS_MODULE=empire_os.settings.production python manage.py migrate
DJANGO_SETTINGS_MODULE=empire_os.settings.production python manage.py collectstatic --noinput
DJANGO_SETTINGS_MODULE=empire_os.settings.production python manage.py createsuperuser
```

---

## 5. Systemd service

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn-empire-os.service
# Edit WorkingDirectory and paths if needed
sudo systemctl daemon-reload
sudo systemctl enable gunicorn-empire-os
sudo systemctl start gunicorn-empire-os
```

---

## 6. Nginx

```bash
# Edit deploy/nginx.conf: replace YOUR_DOMAIN_OR_IP
sudo cp deploy/nginx.conf /etc/nginx/sites-available/empire-os
sudo ln -s /etc/nginx/sites-available/empire-os /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# SSL
sudo certbot --nginx -d yourdomain.com
```

---

## 7. Verify

Visit `https://yourdomain.com` → redirected to `/bids/` → login page.
Login with the superuser you created.
Hit **Update** — should scrape Kalitta site and show your dashboard.

---

## Updating the app

```bash
cd /srv/empire-os
source venv/bin/activate
git pull
pip install -r requirements.txt
DJANGO_SETTINGS_MODULE=empire_os.settings.production python manage.py migrate
DJANGO_SETTINGS_MODULE=empire_os.settings.production python manage.py collectstatic --noinput
sudo systemctl restart gunicorn-empire-os
```

---

## Adding future apps (the Empire OS pattern)

1. `python manage.py startapp new_app_name`
2. Add to `INSTALLED_APPS` in `settings/base.py`
3. Register URLs in `empire_os/urls.py`
4. Done — all apps share the same auth, DB, and deployment.

---

## Overview.xlsx

The fleet complement file lives at `bid_checker/data/Overview.xlsx`.
Update it if Kalitta changes the 777 line structure (rare).
No server restart needed — it's read on each refresh.
