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
2. Put it in `backend/.env` as `GEMINI_API_KEY=...` (optionally set `GEMINI_MODEL`, default `gemini-flash-latest`).
3. `sudo systemctl restart agile-api`. Check: `curl -s https://agiletechexpert.com/api/health` shows `"assistant": true`.

The key stays on the server (never in the browser). A short system prompt + a fact sheet built
from `content/*.json` keep it on Agile topics only, in Hindi/English/Hinglish, with no prices.
Cost is capped by a per-IP rate limit (`ATE_ASSIST_MAX`/`ATE_ASSIST_WINDOW`) and a short reply length.

## Real-time voice (Gemini Live)

`WS /api/voice?gender=female|male` streams the visitor's mic (16 kHz PCM16) to Gemini Live and plays the
reply audio (24 kHz PCM16) in the browser. This is audio-to-audio, like the FreeSWITCH bridge, so the voice
is natural and the visitor can interrupt. The Female/Male toggle on the home page picks `VOICE_FEMALE` /
`VOICE_MALE`; the voice comes from the server, so every device hears the same voice.

Barge-in: while Agile speaks, the browser sends no mic audio unless the mic level stays above the barge
threshold for ~120 ms; then playback stops and the visitor's audio goes through. Echo cannot interrupt Agile.

Cost guards (`.env`): `VOICE_MAX_SECONDS` per call, `VOICE_IDLE_SECONDS` silence cut-off,
`VOICE_MAX_CONCURRENT`, `VOICE_PER_IP_HOUR`, `VOICE_DAILY_MINUTES`. When a limit is hit (or the voice
server is down) the site falls back to the free browser voice automatically.

Usage for billing: `GET /api/voice/status` (minutes today), or
`sudo sqlite3 backend/data/leads.db "SELECT date(started_at), COUNT(*), ROUND(SUM(seconds)/60,1) AS minutes, SUM(in_tokens), SUM(out_tokens) FROM voice_sessions GROUP BY 1;"`

nginx needs the `location = /api/voice` block from `deploy/nginx-agiletechexpert.conf` (WebSocket upgrade).

## Updating the backend later

Push changes, then on the server: `sudo bash /var/www/agiletechexpert/deploy/deploy.sh`
(pulls, reinstalls deps, restarts `agile-api`, reloads nginx).

## Portals & users

Separate logins for staff and clients, with session cookies (HttpOnly, Secure, SameSite=Lax):

| Endpoint | Who |
|----------|-----|
| `POST /api/auth/employee/login` | staff → redirects to `/portal/leads/` |
| `POST /api/auth/client/login` | clients → redirects to `/portal/client/home/` |
| `POST /api/auth/logout` | clears the session |
| `GET /api/me` | `{employee}` and/or `{client}` from cookies |

Employee and client sessions are isolated: a client session can never open `/api/leads`.
The leads page uses the employee session (no token needed once signed in); the admin token still works as a fallback.

**Create users** with `manage.py` on the server (run as the service user):
```bash
cd /var/www/agiletechexpert/backend
sudo -u www-data venv/bin/python manage.py add-employee <username> <password> "Full Name" admin
sudo -u www-data venv/bin/python manage.py add-client   <username> <password> "Company"
sudo -u www-data venv/bin/python manage.py list
```
Usernames are lowercase; re-running updates the user. Passwords are stored as salted PBKDF2 hashes.

## Still to build

- Voice WebSocket for real-time audio (reuse the FreeSWITCH↔Gemini bridge) — the current voice uses
  browser speech-to-text/text-to-speech plus the text `/api/assistant`.
- Client dashboard content (campaigns, reports) — ships with the reseller platform on the demo server.
