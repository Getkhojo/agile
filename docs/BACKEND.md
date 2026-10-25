# Backend

The backend is a small FastAPI + SQLite service (`backend/app.py`) run by systemd
(`agile-api.service`) on `127.0.0.1:8000`, proxied by nginx under `/api/`.

## Endpoints (live now)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/health` | — | Health check → `{"status":"ok"}` |
| POST | `/api/leads` | — | Save an inquiry from the form or chat |
| GET | `/api/leads` | `X-Admin-Token` header | List inquiries (JSON, newest 500) |
| GET | `/api/leads.csv` | `X-Admin-Token` header | Export all inquiries as CSV |

`POST /api/leads` body:
```json
{"name":"...", "phone":"...", "email":"", "company":"", "service":"", "mode":"", "message":"", "source":"contact-form|chat", "page":"/contact/"}
```
- Validates name + phone; returns `201 {"ok":true,"id":N}`, or `422` (bad input), `429` (rate limited).
- Hidden `website` field is a honeypot — if filled, the request is dropped silently.
- A failed POST makes the website offer a WhatsApp fallback, so no lead is lost.

## First-time server setup

Repo already live at `/var/www/agiletechexpert`. After the backend files are in `main`:

```bash
cd /var/www/agiletechexpert
sudo git pull
sudo apt -y install python3-venv
sudo python3 -m venv backend/venv
sudo backend/venv/bin/pip install -r backend/requirements.txt
sudo mkdir -p backend/data

# create .env with a random admin token
sudo cp backend/.env.example backend/.env
TOKEN=$(openssl rand -hex 24)
sudo sed -i "s/^ATE_ADMIN_TOKEN=.*/ATE_ADMIN_TOKEN=$TOKEN/" backend/.env
echo "Your admin token: $TOKEN"     # save this to read leads later
sudo chown -R www-data:www-data backend

# systemd service
sudo cp deploy/agile-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agile-api

# nginx: updated config has the /api/ proxy + full SSL
sudo cp deploy/nginx-agiletechexpert.conf /etc/nginx/sites-available/agiletechexpert.conf
sudo nginx -t && sudo systemctl reload nginx

# test
curl -s https://agiletechexpert.com/api/health
```

## Reading the leads

```bash
# JSON
curl -s https://agiletechexpert.com/api/leads -H "X-Admin-Token: <your token>"
# CSV (save to a file)
curl -s https://agiletechexpert.com/api/leads.csv -H "X-Admin-Token: <your token>" -o leads.csv
```
Or read the SQLite file directly on the server: `sudo sqlite3 /var/www/agiletechexpert/backend/data/leads.db "SELECT * FROM leads;"`

## Email alerts (optional)

To email every new lead, fill the `SMTP_*` and `ATE_NOTIFY_TO` values in `backend/.env`
and `sudo systemctl restart agile-api`. If `SMTP_HOST` is empty, leads are still saved
and appended to `backend/data/leads.log`.

## Updating the backend later

Push changes, then on the server: `sudo bash /var/www/agiletechexpert/deploy/deploy.sh`
(pulls, reinstalls deps, restarts `agile-api`, reloads nginx).

## Still to build

- Portal auth: `POST /api/auth/employee/login` and `POST /api/auth/client/login`
  (separate user tables + session cookies; a client session must never open a staff route).
- Assistant: `POST /api/assistant` (set `assistantEndpoint` in `tools/build.py` → rebuild),
  and the voice WebSocket reusing the FreeSWITCH↔Gemini bridge.
