"""Agile Tech Expert - backend API (FastAPI + SQLite).

Endpoints:
  GET  /api/health
  POST /api/leads               save an inquiry (form or chat)
  GET  /api/leads               list inquiries (employee session OR X-Admin-Token)
  GET  /api/leads.csv           export inquiries (employee session OR X-Admin-Token)
  POST /api/assistant           AI reply (Gemini, server-side key) with rule-based fallback
  POST /api/auth/employee/login staff sign in  -> session cookie
  POST /api/auth/client/login   client sign in -> session cookie
  POST /api/auth/logout
  GET  /api/me                  who am I (from cookies)

Create users with manage.py (see docs/BACKEND.md). Config: see .env.example.
"""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
CONTENT_DIR = BASE.parent / "content"
DB_PATH = os.environ.get("ATE_DB", str(BASE / "data" / "leads.db"))
ADMIN_TOKEN = os.environ.get("ATE_ADMIN_TOKEN", "")
RATE_MAX = int(os.environ.get("ATE_RATE_MAX", "5"))
RATE_WINDOW = int(os.environ.get("ATE_RATE_WINDOW", "600"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ASSIST_MAX = int(os.environ.get("ATE_ASSIST_MAX", "20"))
ASSIST_WINDOW = int(os.environ.get("ATE_ASSIST_WINDOW", "600"))
# Cookies are Secure by default; set ATE_COOKIE_SECURE=0 only for local http testing.
COOKIE_SECURE = os.environ.get("ATE_COOKIE_SECURE", "1") != "0"

PHONE_RE = re.compile(r"^[+0-9][0-9\s-]{7,15}$")

app = FastAPI(title="Agile Tech Expert API", docs_url=None, redoc_url=None, openapi_url=None)

_lead_hits = defaultdict(deque)
_assist_hits = defaultdict(deque)
_login_hits = defaultdict(deque)


# ------------------------------------------------------------------ database
def db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
                email TEXT, company TEXT, service TEXT, mode TEXT, message TEXT,
                source TEXT, page TEXT, ip TEXT, user_agent TEXT,
                status TEXT NOT NULL DEFAULT 'new')""")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, name TEXT, role TEXT DEFAULT 'staff',
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT)""")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, company TEXT,
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT)""")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_type TEXT NOT NULL, user_id INTEGER NOT NULL,
                created_at TEXT, expires_at TEXT NOT NULL)""")
        conn.commit()


init_db()


# ------------------------------------------------------------------ passwords & sessions
def hash_pw(pw):
    salt = secrets.token_hex(16)
    h = pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200000).hex()
    return salt + "$" + h


def verify_pw(pw, stored):
    try:
        salt, h = stored.split("$", 1)
        calc = pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200000).hex()
        return secrets.compare_digest(calc, h)
    except Exception:
        return False


def create_session(user_type, user_id, days):
    tok = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with closing(db()) as conn:
        conn.execute("INSERT INTO sessions (token,user_type,user_id,created_at,expires_at) VALUES (?,?,?,?,?)",
                     (tok, user_type, user_id, now.isoformat(), (now + timedelta(days=days)).isoformat()))
        conn.commit()
    return tok


def get_session(token):
    if not token:
        return None
    with closing(db()) as conn:
        r = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not r:
        return None
    try:
        if datetime.fromisoformat(r["expires_at"]) < datetime.now(timezone.utc):
            return None
    except Exception:
        return None
    return r


def delete_session(token):
    if not token:
        return
    with closing(db()) as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


def is_employee(request):
    s = get_session(request.cookies.get("ate_emp"))
    return bool(s and s["user_type"] == "employee")


# ------------------------------------------------------------------ fact sheet / Gemini
def build_facts():
    try:
        site = json.loads((CONTENT_DIR / "site.json").read_text())
        svc = json.loads((CONTENT_DIR / "services.json").read_text())
    except Exception:
        return "Agile Tech Expert provides AI calling, IVR, voice broadcast and business messaging.", "Agile Tech Expert"
    lines = [f"Brand: {site.get('brand','')} ({site.get('legal_name','')})",
             f"Tagline: {site.get('tagline','')}", f"Email: {site.get('email','')}",
             "Phones: " + ", ".join(site.get("phones", [])),
             "Office: " + site.get("address", {}).get("display", ""),
             "Hours: " + site.get("hours", ""),
             "Every service is available two ways: On-Premise (installed on the client's own servers) or Managed (hosted and run by Agile).",
             "Services:"]
    for s in svc.get("services", []):
        lines.append(f"- {s['name']}: {s['short']}")
    return "\n".join(lines), site.get("brand", "Agile Tech Expert")


FACTS, BRAND = build_facts()
SYSTEM_PROMPT = (
    "You are the friendly virtual assistant for " + BRAND + ". Rules:\n"
    "1. Only talk about " + BRAND + "'s services, how they are delivered (on-premise or managed), "
    "and how to get a demo or contact the team. If asked anything unrelated, warmly say you can only help "
    "with " + BRAND + "'s services.\n"
    "2. Reply in the user's language - Hindi, English or Hinglish - matching how they spoke.\n"
    "3. Keep replies short, warm and natural: 2 to 3 sentences, because they may be read aloud.\n"
    "4. Never quote prices or invent numbers. If asked about price, say it depends on their needs and offer a callback.\n"
    "5. Never invent services, phone numbers or facts not in the information below.\n\n"
    "Information about " + BRAND + ":\n" + FACTS)


def gemini_reply(message, lang):
    if not GEMINI_API_KEY:
        return None
    url = ("https://generativelanguage.googleapis.com/v1beta/models/" + GEMINI_MODEL
           + ":generateContent?key=" + GEMINI_API_KEY)
    hint = " (Reply in Hindi/Hinglish.)" if lang and lang.startswith("hi") else ""
    payload = {"system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
               "contents": [{"role": "user", "parts": [{"text": message + hint}]}],
               "generationConfig": {"maxOutputTokens": 240, "temperature": 0.6, "topP": 0.9}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read().decode("utf-8"))
        parts = res.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return ("".join(p.get("text", "") for p in parts).strip()) or None
    except Exception:
        return None


# ------------------------------------------------------------------ helpers
def client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")


def rate_ok(bucket, ip, limit, window):
    now = time.time()
    q = bucket[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


# ------------------------------------------------------------------ models
class Lead(BaseModel):
    name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=25)
    email: str = Field(default="", max_length=160)
    company: str = Field(default="", max_length=160)
    service: str = Field(default="", max_length=120)
    mode: str = Field(default="", max_length=60)
    message: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=40)
    page: str = Field(default="", max_length=300)
    website: str = Field(default="", max_length=200)  # honeypot


class Ask(BaseModel):
    message: str = Field(default="", max_length=500)
    lang: str = Field(default="", max_length=10)
    page: str = Field(default="", max_length=300)


class Login(BaseModel):
    username: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=200)
    remember: bool = False


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    return {"status": "ok", "assistant": bool(GEMINI_API_KEY)}


@app.post("/api/leads")
async def create_lead(lead: Lead, request: Request):
    if lead.website.strip():
        return JSONResponse({"ok": True}, status_code=201)
    name, phone = lead.name.strip(), lead.phone.strip()
    if not name or not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Name and a valid phone number are required.")
    ip = client_ip(request)
    if not rate_ok(_lead_hits, ip, RATE_MAX, RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    row = (datetime.now(timezone.utc).isoformat(timespec="seconds"), name, phone, lead.email.strip(),
           lead.company.strip(), lead.service.strip(), lead.mode.strip(), lead.message.strip(),
           lead.source.strip() or "web", lead.page.strip(), ip, request.headers.get("user-agent", "")[:300])
    with closing(db()) as conn:
        cur = conn.execute(
            "INSERT INTO leads (created_at,name,phone,email,company,service,mode,message,source,page,ip,user_agent)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
        conn.commit()
        lead_id = cur.lastrowid
    notify(lead_id, name, phone, lead)
    return JSONResponse({"ok": True, "id": lead_id}, status_code=201)


def leads_authorized(request, token):
    return (ADMIN_TOKEN and token == ADMIN_TOKEN) or is_employee(request)


@app.get("/api/leads")
def list_leads(request: Request, x_admin_token: str = Header(default="")):
    if not leads_authorized(request, x_admin_token):
        raise HTTPException(status_code=403, detail="Forbidden")
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
    return {"count": len(rows), "leads": [dict(r) for r in rows]}


@app.get("/api/leads.csv")
def leads_csv(request: Request, x_admin_token: str = Header(default="")):
    if not leads_authorized(request, x_admin_token):
        raise HTTPException(status_code=403, detail="Forbidden")
    cols = ["id", "created_at", "name", "phone", "email", "company",
            "service", "mode", "message", "source", "page", "ip", "status"]
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@app.post("/api/assistant")
def assistant(ask: Ask, request: Request):
    msg = ask.message.strip()
    if not msg or not rate_ok(_assist_hits, client_ip(request), ASSIST_MAX, ASSIST_WINDOW):
        return {"reply": None}
    return {"reply": gemini_reply(msg, ask.lang)}


# ------------------------------------------------------------------ auth
def do_login(kind, body, request, response):
    if not rate_ok(_login_hits, client_ip(request), 10, 600):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a few minutes.")
    table = "employees" if kind == "employee" else "clients"
    u = body.username.strip().lower()
    if not u or not body.password:
        raise HTTPException(status_code=422, detail="Enter your ID and password.")
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM %s WHERE username=? AND active=1" % table, (u,)).fetchone()
    if not row or not verify_pw(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="That ID and password don't match.")
    days = 30 if body.remember else 1
    tok = create_session(kind, row["id"], days)
    cookie = "ate_emp" if kind == "employee" else "ate_cli"
    response.set_cookie(cookie, tok, max_age=days * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="lax", path="/")
    return {"ok": True, "redirect": "/portal/leads/" if kind == "employee" else "/portal/client/home/"}


@app.post("/api/auth/employee/login")
def employee_login(body: Login, request: Request, response: Response):
    return do_login("employee", body, request, response)


@app.post("/api/auth/client/login")
def client_login(body: Login, request: Request, response: Response):
    return do_login("client", body, request, response)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    for c in ("ate_emp", "ate_cli"):
        delete_session(request.cookies.get(c))
        response.delete_cookie(c, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    out = {}
    emp = get_session(request.cookies.get("ate_emp"))
    if emp and emp["user_type"] == "employee":
        with closing(db()) as conn:
            r = conn.execute("SELECT id,username,name,role FROM employees WHERE id=?", (emp["user_id"],)).fetchone()
        if r:
            out["employee"] = dict(r)
    cli = get_session(request.cookies.get("ate_cli"))
    if cli and cli["user_type"] == "client":
        with closing(db()) as conn:
            r = conn.execute("SELECT id,username,company FROM clients WHERE id=?", (cli["user_id"],)).fetchone()
        if r:
            out["client"] = dict(r)
    return out


# ------------------------------------------------------------------ notifications
def notify(lead_id, name, phone, lead):
    summary = (f"New inquiry #{lead_id}\nName: {name}\nPhone: {phone}\nService: {lead.service}\n"
               f"Setup: {lead.mode}\nEmail: {lead.email}\nCompany: {lead.company}\n"
               f"Message: {lead.message}\nSource: {lead.source}  Page: {lead.page}")
    try:
        with open(Path(DB_PATH).parent / "leads.log", "a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).isoformat(timespec="seconds")
                    + f" #{lead_id} {name} {phone} {lead.service} {lead.mode}\n")
    except Exception:
        pass
    _telegram(summary)
    _email(lead_id, name, summary)


def _telegram(text):
    token, chat = os.environ.get("TG_BOT_TOKEN", ""), os.environ.get("TG_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage",
                                     data=json.dumps({"chat_id": chat, "text": text}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        pass


def _email(lead_id, name, body):
    host, to = os.environ.get("SMTP_HOST", ""), os.environ.get("ATE_NOTIFY_TO", "")
    if not host or not to:
        return
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = f"New inquiry #{lead_id}: {name}"
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=10) as s:
            s.starttls()
            user = os.environ.get("SMTP_USER", "")
            if user:
                s.login(user, os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    except Exception:
        pass
