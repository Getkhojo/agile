"""Staff/admin and client portal APIs.

Roles
  admin  (employees.role = 'admin')  everything below + users, billing, AI usage, audit log
  staff  (any other employee role)   leads and AI conversations (view, review)
  client (clients table)             own profile and invoices

Conversation log: every website voice call and chat is saved with its transcript so staff can
check what visitors asked (off-topic?) and whether the AI answered well.

Cost estimates use the rates in .env (see .env.example). On the Gemini free tier the real bill is 0;
the portal shows both "billed now" and "estimated if paid".
"""
import json
import os
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

USD_INR = float(os.environ.get("USD_INR", "88"))
VOICE_INR_PER_MIN = float(os.environ.get("VOICE_INR_PER_MIN", "3.5"))
AI_BILLING = os.environ.get("AI_BILLING", "free")          # free | paid
PRICE = {  # USD per 1M tokens: (input, output)
    "gemini": (float(os.environ.get("PRICE_GEMINI_IN", "0.30")), float(os.environ.get("PRICE_GEMINI_OUT", "2.50"))),
    "nvidia": (float(os.environ.get("PRICE_NVIDIA_IN", "0")), float(os.environ.get("PRICE_NVIDIA_OUT", "0"))),
    "openai": (float(os.environ.get("PRICE_OPENAI_IN", "0")), float(os.environ.get("PRICE_OPENAI_OUT", "0"))),
}
GST_PCT = float(os.environ.get("GST_PCT", "18"))
INVOICE_PREFIX = os.environ.get("INVOICE_PREFIX", "AGL")
LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")

# Words that show a visitor is asking about Agile's business. A conversation where none of the
# visitor's lines contain any of these is flagged "possibly off-topic" for a human to check.
TOPIC_WORDS = set("""
ivr whatsapp sms rcs call calls calling caller voice broadcast missed crm hrms webrtc cloud pbx sip
dialer dialler campaign campaigns bot chatbot ai api integration demo price prices pricing cost rate
rates plan plans package setup install installation premise premises managed service services agile
business customer customers lead leads number numbers otp bulk message messages messaging toll free
support trunk channel channels recording reseller panel software platform contact callback team office
company quote quotation trial license licence server agent agents ticket helpdesk
kitna kitne kitni charge charges lagega lagegi chahiye chaiye karwana banwana
""".split())


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec="seconds")


def is_offtopic(user_lines):
    lines = [l for l in user_lines if l and l.strip()]
    if not lines:
        return 0
    words = set(re.findall(r"[a-z]+", " ".join(lines).lower()))
    return 0 if words & TOPIC_WORDS else 1


class _Store:
    db = None


S = _Store()


def init_tables(db):
    S.db = db
    with closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, cid TEXT,
            started_at TEXT NOT NULL, updated_at TEXT, ip TEXT, page TEXT, gender TEXT,
            voice_session_id INTEGER, turns INTEGER DEFAULT 0, offtopic INTEGER DEFAULT 0,
            rating TEXT, note TEXT, reviewed_by TEXT, reviewed_at TEXT);
        CREATE INDEX IF NOT EXISTS ix_conv_cid ON conversations(cid);
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER NOT NULL, at TEXT,
            role TEXT NOT NULL, text TEXT, provider TEXT, in_tok INTEGER DEFAULT 0, out_tok INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS ix_turn_conv ON conversation_turns(conv_id);
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, client_id INTEGER NOT NULL,
            issued_at TEXT, due_at TEXT, period TEXT, description TEXT,
            amount REAL NOT NULL, gst_pct REAL NOT NULL, total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'unpaid', paid_at TEXT, notes TEXT, created_by TEXT);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, actor TEXT, action TEXT, detail TEXT);
        """)
        for table, col, decl in (("clients", "contact_name", "TEXT"), ("clients", "phone", "TEXT"),
                                 ("clients", "email", "TEXT"), ("clients", "notes", "TEXT"),
                                 ("leads", "notes", "TEXT"), ("leads", "updated_by", "TEXT")):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
            if col not in cols:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
        conn.commit()


def audit(actor, action, detail=""):
    with closing(S.db()) as conn:
        conn.execute("INSERT INTO audit_log (at,actor,action,detail) VALUES (?,?,?,?)",
                     (_iso(), actor, action, detail[:500]))
        conn.commit()


# ------------------------------------------------------------------ conversation logging
def save_chat_turn(cid, ip, page, question, reply, provider, in_tok=0, out_tok=0):
    """Called by /api/assistant for every chat message."""
    cid = (cid or "").strip()[:64] or None
    with closing(S.db()) as conn:
        row = None
        if cid:
            row = conn.execute("SELECT id FROM conversations WHERE cid=? AND kind='chat'", (cid,)).fetchone()
        if row:
            conv_id = row[0]
        else:
            conv_id = conn.execute("INSERT INTO conversations (kind,cid,started_at,updated_at,ip,page) VALUES "
                                   "('chat',?,?,?,?,?)", (cid, _iso(), _iso(), ip, page[:300])).lastrowid
        conn.execute("INSERT INTO conversation_turns (conv_id,at,role,text) VALUES (?,?,?,?)",
                     (conv_id, _iso(), "you", question[:2000]))
        conn.execute("INSERT INTO conversation_turns (conv_id,at,role,text,provider,in_tok,out_tok) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (conv_id, _iso(), "agile", reply or "(no AI reply - site's built-in answer was shown)",
                      provider or "built-in", int(in_tok or 0), int(out_tok or 0)))
        users = [r[0] for r in conn.execute("SELECT text FROM conversation_turns WHERE conv_id=? AND role='you'",
                                            (conv_id,))]
        conn.execute("UPDATE conversations SET updated_at=?, turns=(SELECT COUNT(*) FROM conversation_turns "
                     "WHERE conv_id=?), offtopic=? WHERE id=?", (_iso(), conv_id, is_offtopic(users), conv_id))
        conn.commit()


def chat_history(cid, limit=8):
    """Last turns of a chat, oldest first, as [(role, text)] for the AI's context."""
    cid = (cid or "").strip()[:64]
    if not cid:
        return []
    with closing(S.db()) as conn:
        row = conn.execute("SELECT id FROM conversations WHERE cid=? AND kind='chat'", (cid,)).fetchone()
        if not row:
            return []
        rows = conn.execute("SELECT role, text FROM conversation_turns WHERE conv_id=? ORDER BY id DESC LIMIT ?",
                            (row[0], limit)).fetchall()
    out = []
    for r, t in reversed(rows):
        t = (t or "").replace("  [lead saved]", "")
        if t.startswith("(no AI reply"):
            continue
        out.append((r, t))
    return out


def save_voice_conversation(voice_session_id, ip, gender, turns):
    """Called by voice.py when a call ends. turns = [(role, text), ...]"""
    turns = [(r, (t or "").strip()) for r, t in turns if (t or "").strip()]
    with closing(S.db()) as conn:
        conv_id = conn.execute(
            "INSERT INTO conversations (kind,started_at,updated_at,ip,gender,voice_session_id,turns,offtopic) "
            "VALUES ('voice',?,?,?,?,?,?,?)",
            (_iso(), _iso(), ip, gender, voice_session_id, len(turns),
             is_offtopic([t for r, t in turns if r == "you"]))).lastrowid
        conn.executemany("INSERT INTO conversation_turns (conv_id,at,role,text,provider) VALUES (?,?,?,?,?)",
                         [(conv_id, _iso(), r, t[:4000], "gemini-live" if r == "agile" else None) for r, t in turns])
        conn.commit()


# ------------------------------------------------------------------ request models
class EmployeeIn(BaseModel):
    username: str = Field(default="", max_length=60)
    password: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=120)
    role: str = Field(default="staff", max_length=20)


class ClientIn(BaseModel):
    username: str = Field(default="", max_length=60)
    password: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=160)
    contact_name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=25)
    email: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=20)
    company: str | None = Field(default=None, max_length=160)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=25)
    email: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    password: str | None = Field(default=None, max_length=200)


class LeadPatch(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class Review(BaseModel):
    rating: str | None = Field(default=None, max_length=10)   # good | bad | None
    note: str = Field(default="", max_length=1000)


class InvoiceIn(BaseModel):
    client_id: int
    description: str = Field(default="", max_length=500)
    period: str = Field(default="", max_length=60)
    amount: float = Field(gt=0, lt=100000000)
    gst_pct: float | None = Field(default=None, ge=0, le=28)
    due_days: int = Field(default=15, ge=0, le=365)
    notes: str = Field(default="", max_length=1000)


class InvoicePatch(BaseModel):
    status: str | None = Field(default=None, max_length=12)   # unpaid | paid | cancelled
    notes: str | None = Field(default=None, max_length=1000)


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,59}$")


def register(app, db, get_session, hash_pw):
    init_tables(db)

    # ---------------- auth helpers
    def employee(request: Request):
        s = get_session(request.cookies.get("ate_emp"))
        if not s or s["user_type"] != "employee":
            return None
        with closing(db()) as conn:
            r = conn.execute("SELECT id,username,name,role,active FROM employees WHERE id=?",
                             (s["user_id"],)).fetchone()
        return dict(r) if r and r["active"] else None

    def need_staff(request):
        e = employee(request)
        if not e:
            raise HTTPException(status_code=401, detail="Please sign in.")
        return e

    def need_admin(request):
        e = need_staff(request)
        if e["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can do this.")
        return e

    def need_client(request):
        s = get_session(request.cookies.get("ate_cli"))
        if not s or s["user_type"] != "client":
            raise HTTPException(status_code=401, detail="Please sign in.")
        with closing(db()) as conn:
            r = conn.execute("SELECT id,username,company,contact_name,phone,email,active FROM clients WHERE id=?",
                             (s["user_id"],)).fetchone()
        if not r or not r["active"]:
            raise HTTPException(status_code=401, detail="Please sign in.")
        return dict(r)

    def check_password(pw):
        if not pw or len(pw) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    def check_username(u):
        if not USERNAME_RE.match(u):
            raise HTTPException(status_code=422, detail="Username: 3-60 characters, lowercase letters, numbers, . _ -")

    # ---------------- usage maths
    def usage_rows(days):
        start = (_now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        out = {}
        with closing(db()) as conn:
            for r in conn.execute("SELECT substr(started_at,1,10) d, COUNT(*) n, COALESCE(SUM(seconds),0) s "
                                  "FROM voice_sessions WHERE substr(started_at,1,10)>=? GROUP BY d", (start,)):
                out.setdefault(r["d"], {})["voice"] = (r["n"], r["s"])
            for r in conn.execute("SELECT substr(t.at,1,10) d, t.provider p, COUNT(*) n, SUM(t.in_tok) i, "
                                  "SUM(t.out_tok) o FROM conversation_turns t JOIN conversations c ON c.id=t.conv_id "
                                  "WHERE c.kind='chat' AND t.role='agile' AND substr(t.at,1,10)>=? GROUP BY d,p",
                                  (start,)):
                out.setdefault(r["d"], {}).setdefault("chat", []).append((r["p"], r["n"], r["i"] or 0, r["o"] or 0))
        rows = []
        for k in range(days):
            d = (_now() - timedelta(days=days - 1 - k)).strftime("%Y-%m-%d")
            v = out.get(d, {})
            vn, vs = v.get("voice", (0, 0))
            chat_n, chat_inr, by = 0, 0.0, {}
            in_tok = out_tok = 0
            for p, n, i, o in v.get("chat", []):
                chat_n += n
                in_tok += i
                out_tok += o
                by[p] = by.get(p, 0) + n
                pin, pout = PRICE.get((p or "").split("-")[0], (0, 0))
                chat_inr += (i * pin + o * pout) / 1e6 * USD_INR
            vmin = vs / 60.0
            rows.append({"date": d, "voice_calls": vn, "voice_minutes": round(vmin, 1),
                         "voice_inr": round(vmin * VOICE_INR_PER_MIN, 2),
                         "chat_requests": chat_n, "chat_by_provider": by, "chat_in_tokens": in_tok,
                         "chat_out_tokens": out_tok, "chat_inr": round(chat_inr, 2),
                         "total_inr": round(vmin * VOICE_INR_PER_MIN + chat_inr, 2)})
        return rows

    def money_summary(rows):
        tot = round(sum(r["total_inr"] for r in rows), 2)
        return {"estimated_inr": tot, "billed_inr": tot if AI_BILLING == "paid" else 0.0}

    # ---------------- overview
    @app.get("/api/admin/overview")
    def overview(request: Request):
        e = need_staff(request)
        today = _now().strftime("%Y-%m-%d")
        month = _now().strftime("%Y-%m")
        with closing(db()) as conn:
            q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
            data = {
                "me": e,
                "leads_total": q("SELECT COUNT(*) FROM leads"),
                "leads_new": q("SELECT COUNT(*) FROM leads WHERE status='new'"),
                "leads_today": q("SELECT COUNT(*) FROM leads WHERE substr(created_at,1,10)=?", today),
                "conversations_today": q("SELECT COUNT(*) FROM conversations WHERE substr(started_at,1,10)=?", today),
                "offtopic_unreviewed": q("SELECT COUNT(*) FROM conversations WHERE offtopic=1 AND rating IS NULL"),
                "bad_answers": q("SELECT COUNT(*) FROM conversations WHERE rating='bad'"),
                "caller_rating_avg": q("SELECT ROUND(AVG(rating),1) FROM voice_sessions WHERE rating IS NOT NULL "
                                       "AND substr(started_at,1,7)=?", month),
                "caller_ratings": q("SELECT COUNT(rating) FROM voice_sessions WHERE substr(started_at,1,7)=?", month),
            }
            if e["role"] == "admin":
                data.update({
                    "clients": q("SELECT COUNT(*) FROM clients WHERE active=1"),
                    "employees": q("SELECT COUNT(*) FROM employees WHERE active=1"),
                    "invoices_unpaid": q("SELECT COUNT(*) FROM invoices WHERE status='unpaid'"),
                    "invoices_unpaid_inr": round(q("SELECT COALESCE(SUM(total),0) FROM invoices WHERE status='unpaid'"), 2),
                    "paid_this_month_inr": round(q("SELECT COALESCE(SUM(total),0) FROM invoices WHERE status='paid' "
                                                   "AND substr(paid_at,1,7)=?", month), 2),
                })
        if e["role"] == "admin":
            days_in_month = _now().day
            rows = usage_rows(days_in_month)
            data["ai_today"] = rows[-1]
            data["ai_month"] = {"voice_minutes": round(sum(r["voice_minutes"] for r in rows), 1),
                                "voice_calls": sum(r["voice_calls"] for r in rows),
                                "chat_requests": sum(r["chat_requests"] for r in rows), **money_summary(rows)}
            data["ai_billing"] = AI_BILLING
        return data

    # ---------------- leads (staff)
    @app.patch("/api/admin/leads/{lead_id}")
    def update_lead(lead_id: int, body: LeadPatch, request: Request):
        e = need_staff(request)
        sets, args = [], []
        if body.status is not None:
            if body.status not in LEAD_STATUSES:
                raise HTTPException(status_code=422, detail="Unknown status.")
            sets.append("status=?"); args.append(body.status)
        if body.notes is not None:
            sets.append("notes=?"); args.append(body.notes)
        if not sets:
            return {"ok": True}
        sets.append("updated_by=?"); args.append(e["username"])
        with closing(db()) as conn:
            cur = conn.execute("UPDATE leads SET %s WHERE id=?" % ",".join(sets), (*args, lead_id))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Lead not found.")
        audit(e["username"], "lead.update", "lead %d %s" % (lead_id, body.model_dump(exclude_none=True)))
        return {"ok": True}

    # ---------------- conversations (staff)
    @app.get("/api/admin/conversations")
    def list_conversations(request: Request, kind: str = "", flag: str = "", q: str = "",
                           limit: int = 50, offset: int = 0):
        need_staff(request)
        where, args = ["turns>0"], []
        if kind in ("voice", "chat"):
            where.append("kind=?"); args.append(kind)
        if flag == "offtopic":
            where.append("offtopic=1")
        elif flag == "unreviewed":
            where.append("rating IS NULL")
        elif flag in ("good", "bad"):
            where.append("rating=?"); args.append(flag)
        if q.strip():
            where.append("id IN (SELECT conv_id FROM conversation_turns WHERE text LIKE ?)")
            args.append("%" + q.strip()[:80] + "%")
        limit = max(1, min(limit, 200))
        sql_where = " AND ".join(where)
        with closing(db()) as conn:
            total = conn.execute("SELECT COUNT(*) FROM conversations WHERE " + sql_where, args).fetchone()[0]
            rows = conn.execute(
                "SELECT c.*, (SELECT text FROM conversation_turns t WHERE t.conv_id=c.id AND t.role='you' "
                "ORDER BY t.id LIMIT 1) AS first_q, (SELECT seconds FROM voice_sessions v WHERE "
                "v.id=c.voice_session_id) AS seconds, (SELECT rating FROM voice_sessions v WHERE v.id=c.voice_session_id) "
                "AS caller_rating FROM conversations c WHERE " + sql_where +
                " ORDER BY c.id DESC LIMIT ? OFFSET ?", (*args, limit, max(0, offset))).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    @app.get("/api/admin/conversations/{conv_id}")
    def get_conversation(conv_id: int, request: Request):
        need_staff(request)
        with closing(db()) as conn:
            c = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Not found.")
            turns = conn.execute("SELECT role,text,at,provider,in_tok,out_tok FROM conversation_turns "
                                 "WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()
            vs = None
            if c["voice_session_id"]:
                v = conn.execute("SELECT seconds,end_reason,stats,lang,rating,feedback FROM voice_sessions WHERE id=?",
                                 (c["voice_session_id"],)).fetchone()
                vs = dict(v) if v else None
        return {"conversation": dict(c), "turns": [dict(t) for t in turns], "voice": vs}

    @app.post("/api/admin/conversations/{conv_id}/review")
    def review_conversation(conv_id: int, body: Review, request: Request):
        e = need_staff(request)
        if body.rating not in (None, "good", "bad"):
            raise HTTPException(status_code=422, detail="Rating must be good or bad.")
        with closing(db()) as conn:
            cur = conn.execute("UPDATE conversations SET rating=?, note=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                               (body.rating, body.note, e["username"], _iso(), conv_id))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Not found.")
        return {"ok": True}

    # ---------------- AI usage (admin)
    @app.get("/api/admin/usage")
    def usage(request: Request, days: int = 30):
        need_admin(request)
        days = max(1, min(days, 120))
        rows = usage_rows(days)
        return {"days": rows, "summary": {
            "voice_minutes": round(sum(r["voice_minutes"] for r in rows), 1),
            "voice_calls": sum(r["voice_calls"] for r in rows),
            "chat_requests": sum(r["chat_requests"] for r in rows), **money_summary(rows)},
            "rates": {"usd_inr": USD_INR, "voice_inr_per_min": VOICE_INR_PER_MIN,
                      "price_usd_per_million": PRICE, "billing": AI_BILLING}}

    # ---------------- users (admin)
    @app.get("/api/admin/users")
    def list_users(request: Request):
        need_admin(request)
        with closing(db()) as conn:
            emps = conn.execute("SELECT id,username,name,role,active,created_at FROM employees ORDER BY id").fetchall()
            clis = conn.execute("SELECT c.id,c.username,c.company,c.contact_name,c.phone,c.email,c.notes,c.active,"
                                "c.created_at,(SELECT COALESCE(SUM(total),0) FROM invoices i WHERE i.client_id=c.id "
                                "AND i.status='unpaid') AS due FROM clients c ORDER BY c.id").fetchall()
        return {"employees": [dict(r) for r in emps], "clients": [dict(r) for r in clis]}

    @app.post("/api/admin/employees")
    def create_employee(body: EmployeeIn, request: Request):
        e = need_admin(request)
        u = body.username.strip().lower()
        check_username(u); check_password(body.password)
        role = body.role if body.role in ("admin", "staff") else "staff"
        try:
            with closing(db()) as conn:
                conn.execute("INSERT INTO employees (username,password_hash,name,role,active,created_at) "
                             "VALUES (?,?,?,?,1,?)", (u, hash_pw(body.password), body.name.strip(), role, _iso()))
                conn.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="That username is already taken.")
        audit(e["username"], "employee.create", "%s (%s)" % (u, role))
        return {"ok": True}

    @app.post("/api/admin/clients")
    def create_client(body: ClientIn, request: Request):
        e = need_admin(request)
        u = body.username.strip().lower()
        check_username(u); check_password(body.password)
        try:
            with closing(db()) as conn:
                conn.execute("INSERT INTO clients (username,password_hash,company,contact_name,phone,email,notes,"
                             "active,created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                             (u, hash_pw(body.password), body.company.strip(), body.contact_name.strip(),
                              body.phone.strip(), body.email.strip(), body.notes.strip(), _iso()))
                conn.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="That username is already taken.")
        audit(e["username"], "client.create", "%s (%s)" % (u, body.company.strip()))
        return {"ok": True}

    def patch_user(table, user_id, body, actor):
        fields = {"employees": ("name", "role"),
                  "clients": ("company", "contact_name", "phone", "email", "notes")}[table]
        data = body.model_dump(exclude_none=True)
        sets, args = [], []
        for f in fields:
            if f in data:
                v = data[f]
                if f == "role" and v not in ("admin", "staff"):
                    raise HTTPException(status_code=422, detail="Role must be admin or staff.")
                sets.append(f + "=?"); args.append(v.strip() if isinstance(v, str) else v)
        if "active" in data:
            sets.append("active=?"); args.append(1 if data["active"] else 0)
        if "password" in data:
            check_password(data["password"])
            sets.append("password_hash=?"); args.append(hash_pw(data["password"]))
        if not sets:
            return {"ok": True}
        with closing(db()) as conn:
            cur = conn.execute("UPDATE %s SET %s WHERE id=?" % (table, ",".join(sets)), (*args, user_id))
            if "active" in data and not data["active"] or "password" in data:
                kind = "employee" if table == "employees" else "client"
                conn.execute("DELETE FROM sessions WHERE user_type=? AND user_id=?", (kind, user_id))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="User not found.")
        safe = {k: v for k, v in data.items() if k != "password"}
        if "password" in data:
            safe["password"] = "changed"
        audit(actor, table[:-1] + ".update", "id %d %s" % (user_id, safe))
        return {"ok": True}

    @app.patch("/api/admin/employees/{user_id}")
    def update_employee(user_id: int, body: UserPatch, request: Request):
        e = need_admin(request)
        if user_id == e["id"] and (body.active is False or (body.role and body.role != "admin")):
            raise HTTPException(status_code=422, detail="You cannot deactivate or demote your own admin account.")
        return patch_user("employees", user_id, body, e["username"])

    @app.patch("/api/admin/clients/{user_id}")
    def update_client(user_id: int, body: UserPatch, request: Request):
        e = need_admin(request)
        return patch_user("clients", user_id, body, e["username"])

    # ---------------- billing (admin)
    @app.get("/api/admin/invoices")
    def list_invoices(request: Request, status: str = "", client_id: int = 0):
        need_admin(request)
        where, args = ["1=1"], []
        if status in ("unpaid", "paid", "cancelled"):
            where.append("i.status=?"); args.append(status)
        if client_id:
            where.append("i.client_id=?"); args.append(client_id)
        with closing(db()) as conn:
            rows = conn.execute("SELECT i.*, c.company, c.username FROM invoices i LEFT JOIN clients c ON "
                                "c.id=i.client_id WHERE " + " AND ".join(where) + " ORDER BY i.id DESC LIMIT 500",
                                args).fetchall()
        return {"items": [dict(r) for r in rows], "gst_pct_default": GST_PCT}

    @app.post("/api/admin/invoices")
    def create_invoice(body: InvoiceIn, request: Request):
        e = need_admin(request)
        gst = GST_PCT if body.gst_pct is None else body.gst_pct
        total = round(body.amount * (1 + gst / 100.0), 2)
        with closing(db()) as conn:
            if not conn.execute("SELECT 1 FROM clients WHERE id=?", (body.client_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Client not found.")
            year = _now().strftime("%Y")
            n = conn.execute("SELECT COUNT(*) FROM invoices WHERE number LIKE ?",
                             ("%s-%s-%%" % (INVOICE_PREFIX, year),)).fetchone()[0] + 1
            number = "%s-%s-%04d" % (INVOICE_PREFIX, year, n)
            conn.execute("INSERT INTO invoices (number,client_id,issued_at,due_at,period,description,amount,gst_pct,"
                         "total,status,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?,'unpaid',?,?)",
                         (number, body.client_id, _iso(), _iso(_now() + timedelta(days=body.due_days)),
                          body.period.strip(), body.description.strip(), round(body.amount, 2), gst, total,
                          body.notes.strip(), e["username"]))
            conn.commit()
        audit(e["username"], "invoice.create", "%s client %d total %.2f" % (number, body.client_id, total))
        return {"ok": True, "number": number, "total": total}

    @app.patch("/api/admin/invoices/{inv_id}")
    def update_invoice(inv_id: int, body: InvoicePatch, request: Request):
        e = need_admin(request)
        sets, args = [], []
        if body.status is not None:
            if body.status not in ("unpaid", "paid", "cancelled"):
                raise HTTPException(status_code=422, detail="Unknown status.")
            sets += ["status=?", "paid_at=?"]
            args += [body.status, _iso() if body.status == "paid" else None]
        if body.notes is not None:
            sets.append("notes=?"); args.append(body.notes)
        if not sets:
            return {"ok": True}
        with closing(db()) as conn:
            cur = conn.execute("UPDATE invoices SET %s WHERE id=?" % ",".join(sets), (*args, inv_id))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        audit(e["username"], "invoice.update", "id %d %s" % (inv_id, body.model_dump(exclude_none=True)))
        return {"ok": True}

    # ---------------- audit log (admin)
    @app.get("/api/admin/audit")
    def audit_list(request: Request, limit: int = 100):
        need_admin(request)
        with closing(db()) as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                                (max(1, min(limit, 500)),)).fetchall()
        return {"items": [dict(r) for r in rows]}

    # ---------------- client side
    @app.get("/api/client/overview")
    def client_overview(request: Request):
        c = need_client(request)
        with closing(db()) as conn:
            inv = conn.execute("SELECT number,issued_at,due_at,period,description,amount,gst_pct,total,status,paid_at "
                               "FROM invoices WHERE client_id=? AND status!='cancelled' ORDER BY id DESC",
                               (c["id"],)).fetchall()
        items = [dict(r) for r in inv]
        return {"client": c, "invoices": items,
                "due_inr": round(sum(i["total"] for i in items if i["status"] == "unpaid"), 2)}
