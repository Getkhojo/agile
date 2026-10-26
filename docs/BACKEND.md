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

## Lead alerts (optional)

Leads are always saved and appended to `backend/data/leads.log`. To be notified instantly:

- **Telegram (easiest, free):** create a bot with `@BotFather`, copy the token; message the bot
  once, then get your numeric chat id from `@userinfobot`. Put both in `backend/.env`
  (`TG_BOT_TOKEN`, `TG_CHAT_ID`) and `sudo systemctl restart agile-api`.
- **Email:** fill the `SMTP_*` and `ATE_NOTIFY_TO` values and restart.
- **WhatsApp:** no official free server API; the website already offers a WhatsApp fallback link
  on the form when the server is unreachable. Proper WhatsApp alerts need the WhatsApp Business API.

## AI assistant (Gemini)

`POST /api/assistant` powers the chat + voice assistant.
Request `{message, lang, page}` → `{reply: "..."}`, or `{reply: null}` when no key is set
(the website then falls back to its built-in answers, so it always works).

To turn on the real AI:
1. Get a key at https://aistudio.google.com/apikey
2. Put it in `backend/.env` as `GEMINI_API_KEY=...` (optionally set `GEMINI_MODEL`, default `gemini-2.5-flash`).
3. `sudo systemctl restart agile-api`. Check: `curl -s https://agiletechexpert.com/api/health` shows `"assistant": true`.

The key stays on the server (never in the browser). A short system prompt + a fact sheet built
from `content/*.json` keep it on Agile topics only, in Hindi/English/Hinglish, with no prices.
Cost is capped by a per-IP rate limit (`ATE_ASSIST_MAX`/`ATE_ASSIST_WINDOW`) and a short reply length.

## Updating the backend later

Push changes, then on the server: `sudo bash /var/www/agiletechexpert/deploy/deploy.sh`
(pulls, reinstalls deps, restarts `agile-api`, reloads nginx).

## Still to build

- Portal auth: `POST /api/auth/employee/login` and `POST /api/auth/client/login`
  (separate user tables + session cookies; a client session must never open a staff route).
- Assistant: `POST /api/assistant` (set `assistantEndpoint` in `tools/build.py` → rebuild),
  and the voice WebSocket reusing the FreeSWITCH↔Gemini bridge.
