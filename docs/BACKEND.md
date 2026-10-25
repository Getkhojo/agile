# Backend contract

The frontend already calls these endpoints under `/api` (nginx proxies `/api/` to the backend, see `deploy/nginx-agiletechexpert.conf`).
Until the backend is live, forms fall back to WhatsApp and logins show "service isn't available".

## 1. Leads - `POST /api/leads`

Sent by the contact form and the chat assistant.

```json
{
  "name": "Rahul Sharma",
  "phone": "+91 98xxxxxxx",
  "email": "",
  "company": "",
  "service": "IVR Solutions",
  "mode": "On-premise setup | Managed service | Not sure yet",
  "message": "",
  "source": "contact-form | chat",
  "page": "/services/ivr/"
}
```

Respond `201` with `{"id": "..."}`. Any non-2xx makes the page offer WhatsApp instead.
Suggested: rate limit per IP, store in `leads` table, notify sales on WhatsApp/email.

## 2. Logins - two separate user stores

| Portal   | Endpoint                         | Users                     |
|----------|----------------------------------|---------------------------|
| Employee | `POST /api/auth/employee/login`  | `employees` table / SSO   |
| Client   | `POST /api/auth/client/login`    | `clients` table           |

Request: `{"username": "...", "password": "...", "remember": true}`

- `200` + `{"redirect": "/app/staff/"}` or `{"redirect": "/app/client/"}` and an HttpOnly, Secure, SameSite=Lax session cookie.
- `401` wrong credentials, `429` too many attempts.

Keep employees and clients in separate tables with separate session cookies and separate route guards, so a client session can never open a staff route.

## 3. Chat assistant - `POST /api/assistant`

Today the assistant answers in the browser from site content. To route it to the AI engine, set
`"assistantEndpoint": "/api/assistant"` in the generated `public/assets/js/config.js`
(or in `config_js()` inside `tools/build.py`).

Request: `{"message": "...", "lang": "en-IN | hi-IN", "page": "/"}`
Response: `{"reply": "..."}`

## 4. Voice assistant (next step)

Browser speech recognition is used now. For the real AI voice engine, expose a WebSocket at
`/api/voice` that streams 16 kHz PCM from the mic and returns audio + transcripts; the existing
FreeSWITCH / OpenAI-Gemini realtime bridge can sit behind it.

## Suggested tables

- `leads(id, name, phone, email, company, service, mode, message, source, page, ip, created_at, status, assigned_to)`
- `employees(id, emp_code, email, password_hash, role, active, created_at)`
- `clients(id, client_code, email, password_hash, company, active, created_at)`
- `sessions(id, user_type, user_id, expires_at, ip, user_agent)`
