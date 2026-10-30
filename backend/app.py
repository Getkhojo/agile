"""Agile Tech Expert - backend API (FastAPI + SQLite).

Endpoints:
  GET  /api/health
  POST /api/leads               save an inquiry (form or chat)
  GET  /api/leads               list inquiries (employee session OR X-Admin-Token)
  GET  /api/leads.csv           export inquiries (employee session OR X-Admin-Token)
  POST /api/assistant           AI text reply (NVIDIA -> Gemini chain) with rule-based fallback
  WS   /api/voice               real-time voice (Gemini Live audio-to-audio), see voice.py
  GET  /api/voice/status        voice usage today and limits
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
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
# Provider order for the assistant, first that answers wins. Any of: nvidia, openai, gemini
AI_PROVIDERS = [p.strip() for p in os.environ.get("AI_PROVIDERS", "nvidia,gemini").split(",") if p.strip()]
# OpenAI-compatible providers: everything comes from .env, nothing hardcoded in the call path
OAI_COMPAT = {
    "nvidia": {
        "base_url": os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "model": os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"),
        # thinking off: faster replies, fewer tokens
        "extra": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "openai": {
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "model": os.environ.get("OPENAI_MODEL", ""),
        "extra": {},
    },
}
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
    """Employees who may read leads (admin and staff; not the accounts role)."""
    s = get_session(request.cookies.get("ate_emp"))
    if not (s and s["user_type"] == "employee"):
        return False
    with closing(db()) as conn:
        r = conn.execute("SELECT role, active FROM employees WHERE id=?", (s["user_id"],)).fetchone()
    return bool(r and r["active"] and r["role"] != "accounts")


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
    for fname, label in (("hardware.json", "Hardware supplied, installed and supported"),
                         ("software.json", "Software licensing and support")):
        try:
            data = json.loads((CONTENT_DIR / fname).read_text())
        except Exception:
            continue
        lines.append(label + ":")
        for x in data.get("items", []):
            lines.append(f"- {x['name']}: {x['short']}")
        if data.get("rentals"):
            lines.append("Hardware rentals (daily, weekly or monthly):")
            for r in data["rentals"]:
                lines.append(f"- {r['name']}: " + ", ".join(r.get("points", [])))
        if data.get("promises"):
            lines.append("  " + "; ".join(data["promises"]))
    return "\n".join(lines), site.get("brand", "Agile Tech Expert")


FACTS, BRAND = build_facts()
SYSTEM_PROMPT = (
    "You are the friendly virtual assistant for " + BRAND + ". Rules:\n"
    "1. Only talk about " + BRAND + "'s services, how they are delivered (on-premise or managed), "
    "and how to get a demo or contact the team. If asked anything unrelated, warmly say you can only help "
    "with " + BRAND + "'s services.\n"
    "2. Reply in the same language the user used: English, Hindi, Hinglish or any Indian language. "
    "If they write in English, answer in plain English with no Hindi words.\n"
    "3. Your reply is spoken aloud on a call. Use at most 2 short sentences and under 35 words. "
    "No lists, no markdown, no emojis.\n"
    "4. After you answer a question about any service, add one short, friendly line inviting them to share "
    "their name and mobile number so the team can connect with more details. Do this once; do not repeat it "
    "after they share their details or say no.\n"
    "4b. When the user has given their name and mobile number, thank them, say the team will call soon, and "
    "end your reply with one extra line exactly in this form: [[LEAD|name|mobile number|service they asked about]]. "
    "Never write that line in any other situation.\n"
    "5. Never quote prices or invent numbers. If asked about price, say it depends on their needs and offer a callback.\n"
    "6. Never invent services, phone numbers or facts not in the information below.\n\n"
    "Information about " + BRAND + ":\n" + FACTS)

ASSIST_MAX_WORDS = int(os.environ.get("ATE_ASSIST_MAX_WORDS", "60"))


def trim_reply(text, max_sentences=2, max_words=ASSIST_MAX_WORDS):
    """Hard cap on reply length, whatever the model returns."""
    text = re.sub(r"[*_#`>]+", "", text or "").replace("\n", " ").strip()
    parts = re.split(r"(?<=[.!?।])\s+", text)
    out = " ".join(parts[:max_sentences]).strip()
    words = out.split()
    if len(words) > max_words:
        out = " ".join(words[:max_words]).rstrip(",;:") + "."
    return out


def oai_compat_reply(name, message, lang, history=None):
    """Chat completion against any OpenAI-compatible endpoint (NVIDIA, OpenAI, ...)."""
    cfg = OAI_COMPAT.get(name) or {}
    if not cfg.get("api_key") or not cfg.get("model"):
        return None
    hint = " (Reply in Hindi/Hinglish.)" if lang and lang.startswith("hi") else ""
    payload = {"model": cfg["model"],
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}]
                           + [{"role": "user" if r == "you" else "assistant", "content": t} for r, t in (history or [])]
                           + [{"role": "user", "content": message + hint}],
               "max_tokens": 200, "temperature": 0.4, "top_p": 0.9, "stream": False}
    payload.update(cfg.get("extra") or {})
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + cfg["api_key"]})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read().decode("utf-8"))
        text = (res.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        # some models leak <think> blocks even with thinking off
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        u = res.get("usage") or {}
        return (text, u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0) if text else None
    except Exception:
        return None


LEAD_TAG = re.compile(r"\[\[\s*LEAD\s*\|([^|\]]*)\|([^|\]]*)(?:\|([^\]]*))?\]\]", re.I)


def ai_reply(message, lang, history=None):
    """Try each configured provider in order.
    Returns (reply, provider, in_tokens, out_tokens, lead); reply None means use the site's built-in answers.
    lead is (name, phone, service) when the model tagged one."""
    for name in AI_PROVIDERS:
        got = (gemini_reply(message, lang, history) if name == "gemini"
               else oai_compat_reply(name, message, lang, history))
        if got:
            raw, lead = got[0], None
            m = LEAD_TAG.search(raw)
            if m:
                lead = tuple((g or "").strip() for g in m.groups())
                raw = LEAD_TAG.sub("", raw)
            reply = trim_reply(raw, max_sentences=3)
            if reply:
                return (reply, name, got[1], got[2], lead)
    return (None, None, 0, 0, None)


def ai_ready():
    return any((p == "gemini" and GEMINI_API_KEY) or (OAI_COMPAT.get(p, {}).get("api_key"))
               for p in AI_PROVIDERS)


def gemini_reply(message, lang, history=None):
    if not GEMINI_API_KEY:
        return None
    url = ("https://generativelanguage.googleapis.com/v1beta/models/" + GEMINI_MODEL
           + ":generateContent")
    hint = " (Reply in Hindi/Hinglish.)" if lang and lang.startswith("hi") else ""
    payload = {"system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
               "contents": [{"role": "user" if r == "you" else "model", "parts": [{"text": t}]}
                            for r, t in (history or [])]
                           + [{"role": "user", "parts": [{"text": message + hint}]}],
               "generationConfig": {"maxOutputTokens": 200, "temperature": 0.4, "topP": 0.9}}
    # Pass the key via header (works for both new "AQ." keys and classic "AIza" keys)
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "X-goog-api-key": GEMINI_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read().decode("utf-8"))
        parts = res.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        u = res.get("usageMetadata") or {}
        return (text, u.get("promptTokenCount") or 0, u.get("candidatesTokenCount") or 0) if text else None
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
    cid: str = Field(default="", max_length=64)       # browser conversation id, groups a chat


class Login(BaseModel):
    username: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=200)
    remember: bool = False


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    return {"status": "ok", "assistant": bool(ai_ready()),
            "providers": [p for p in AI_PROVIDERS
                          if (p == "gemini" and GEMINI_API_KEY) or OAI_COMPAT.get(p, {}).get("api_key")]}


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
    try:
        history = portal.chat_history(ask.cid, limit=8)
    except Exception:
        history = []
    reply, provider, tin, tout, lead = ai_reply(msg, ask.lang, history)
    saved = None
    if lead:
        try:
            saved = save_lead_record(lead[0], lead[1], lead[2], "Shared in website chat: " + msg,
                                     source="chat", page=ask.page, ip=client_ip(request))
        except Exception:
            saved = None
    try:
        portal.save_chat_turn(ask.cid, client_ip(request), ask.page, msg,
                              (reply or "") + ("  [lead saved]" if saved else ""), provider, tin, tout)
    except Exception:
        pass                                            # logging must never break the chat
    return {"reply": reply, "lead_saved": bool(saved)}


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
    return {"ok": True, "redirect": "/portal/admin/" if kind == "employee" else "/portal/client/home/"}


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
def normalize_phone(phone):
    """Indian mobile/landline -> +91XXXXXXXXXX style; None if it does not look like a phone number."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 10:
        return "+91" + d
    if len(d) == 12 and d.startswith("91"):
        return "+" + d
    if len(d) == 11 and d.startswith("0"):
        return "+91" + d[1:]
    return ("+" + d) if 10 <= len(d) <= 13 else None


def save_lead_record(name, phone, service="", message="", source="voice", page="", ip=""):
    """Save a lead collected by the AI (voice or chat). Returns the lead id, or None if the number is not valid.
    The same number from the same source within 24 hours is not saved twice."""
    name = (name or "").strip()[:120]
    phone = normalize_phone(phone)
    if not name or not phone:
        return None
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with closing(db()) as conn:
        dup = conn.execute("SELECT id FROM leads WHERE phone=? AND source=? AND created_at>=?",
                           (phone, source, since)).fetchone()
        if dup:
            return dup[0]
        cur = conn.execute(
            "INSERT INTO leads (created_at,name,phone,service,message,source,page,ip) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), name, phone, (service or "")[:120],
             (message or "")[:2000], source, (page or "")[:300], ip))
        conn.commit()
        lead_id = cur.lastrowid
    notify(lead_id, name, phone, Lead(name=name, phone=phone, service=(service or "")[:120],
                                      message=(message or "")[:2000], source=source, page=(page or "")[:300]))
    return lead_id


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


# ------------------------------------------------------------------ real-time voice
import portal  # noqa: E402
import voice  # noqa: E402  (needs SYSTEM_PROMPT, client_ip and db defined above)
import billing  # noqa: E402

portal.register(app, db, get_session, hash_pw)
billing.register(app, db, get_session, portal.audit)
import docs  # noqa: E402
docs.register(app, db, get_session, portal.audit)
voice.register(app, SYSTEM_PROMPT, client_ip, db, on_end=portal.save_voice_conversation,
               on_lead=lambda name, phone, service, notes, ip: save_lead_record(
                   name, phone, service, "Shared on the website voice call. " + (notes or ""),
                   source="voice", page="/ (voice call)", ip=ip))
