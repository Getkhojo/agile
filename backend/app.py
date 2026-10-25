"""Agile Tech Expert - leads API (FastAPI + SQLite).

Endpoints:
  GET  /api/health      health check
  POST /api/leads       save an inquiry (from the website form or chat)
  GET  /api/leads       list inquiries as JSON  (needs X-Admin-Token header)
  GET  /api/leads.csv   export inquiries as CSV (needs X-Admin-Token header)

Config via environment (see .env.example):
  ATE_DB            path to the SQLite file (default: ./data/leads.db)
  ATE_ADMIN_TOKEN   token required to read leads (empty = reading disabled)
  ATE_RATE_MAX      max POSTs per IP per window (default 5)
  ATE_RATE_WINDOW   window in seconds (default 600)
  SMTP_*            optional email notification for each new lead
  ATE_NOTIFY_TO     where lead emails go
"""
import csv
import io
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DB_PATH = os.environ.get("ATE_DB", str(BASE / "data" / "leads.db"))
ADMIN_TOKEN = os.environ.get("ATE_ADMIN_TOKEN", "")
RATE_MAX = int(os.environ.get("ATE_RATE_MAX", "5"))
RATE_WINDOW = int(os.environ.get("ATE_RATE_WINDOW", "600"))

PHONE_RE = re.compile(r"^[+0-9][0-9\s-]{7,15}$")

app = FastAPI(title="Agile Tech Expert API", docs_url=None, redoc_url=None, openapi_url=None)

_hits = defaultdict(deque)


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
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                company TEXT,
                service TEXT,
                mode TEXT,
                message TEXT,
                source TEXT,
                page TEXT,
                ip TEXT,
                user_agent TEXT,
                status TEXT NOT NULL DEFAULT 'new'
            )"""
        )
        conn.commit()


init_db()


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
    website: str = Field(default="", max_length=200)  # honeypot, must stay empty


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def rate_ok(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_MAX:
        return False
    q.append(now)
    return True


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/leads")
async def create_lead(lead: Lead, request: Request):
    # Honeypot: bots fill the hidden "website" field. Pretend success, save nothing.
    if lead.website.strip():
        return JSONResponse({"ok": True}, status_code=201)

    name = lead.name.strip()
    phone = lead.phone.strip()
    if not name or not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Name and a valid phone number are required.")

    ip = client_ip(request)
    if not rate_ok(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    row = (
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        name, phone, lead.email.strip(), lead.company.strip(),
        lead.service.strip(), lead.mode.strip(), lead.message.strip(),
        lead.source.strip() or "web", lead.page.strip(),
        ip, request.headers.get("user-agent", "")[:300],
    )
    with closing(db()) as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (created_at,name,phone,email,company,service,mode,message,source,page,ip,user_agent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        conn.commit()
        lead_id = cur.lastrowid

    notify(lead_id, name, phone, lead)
    return JSONResponse({"ok": True, "id": lead_id}, status_code=201)


def require_admin(token: str):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/leads")
def list_leads(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
    return {"count": len(rows), "leads": [dict(r) for r in rows]}


@app.get("/api/leads.csv")
def leads_csv(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
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


def notify(lead_id: int, name: str, phone: str, lead: Lead):
    """Append to a local log always; send email only if SMTP is configured.
    Never raises - a notification failure must not fail the request."""
    try:
        logp = Path(DB_PATH).parent / "leads.log"
        with open(logp, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                    f"#{lead_id} {name} {phone} {lead.service} {lead.mode}\n")
    except Exception:
        pass

    host = os.environ.get("SMTP_HOST", "")
    to = os.environ.get("ATE_NOTIFY_TO", "")
    if not host or not to:
        return
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = f"New inquiry #{lead_id}: {name}"
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
        msg["To"] = to
        msg.set_content(
            f"Name: {name}\nPhone: {phone}\nEmail: {lead.email}\nCompany: {lead.company}\n"
            f"Service: {lead.service}\nSetup: {lead.mode}\nMessage: {lead.message}\n"
            f"Source: {lead.source}\nPage: {lead.page}\n"
        )
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            user = os.environ.get("SMTP_USER", "")
            if user:
                s.login(user, os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    except Exception:
        pass
