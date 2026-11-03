#!/usr/bin/env python3
"""Read-only abuse check for agiletechexpert.com.

Looks at the last N days (default 7) and prints:
  - AI voice usage per day and the top IPs
  - AI chat usage per day and the top IPs
  - leads per IP (spam form posts)
  - portal sign-in failures and 4xx/5xx bursts from the nginx access log
  - API keys or secrets accidentally present in public files

Usage:  sudo python3 /var/www/agiletechexpert/deploy/abuse_check.py [days]
Nothing is changed; it only reads.
"""
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.environ.get("ATE_ROOT", "/var/www/agiletechexpert")
DB = os.environ.get("ATE_DB", ROOT + "/backend/data/leads.db")
ACCESS_LOGS = ["/var/log/nginx/access.log", "/var/log/nginx/access.log.1"]
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
SINCE = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%d")

# Thresholds that are worth a look (a normal visitor stays far below these)
VOICE_MIN_PER_IP = 15      # minutes of AI voice from one IP in the period
CHAT_PER_IP = 60           # chat questions from one IP in the period
LEADS_PER_IP = 5           # form posts from one IP in the period
LOGIN_FAIL_PER_IP = 10     # failed sign-ins from one IP in the period

flags = []


def title(t):
    print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)


def table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()


def db_checks():
    if not os.path.exists(DB):
        print("Database not found: " + DB)
        return
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    if table_exists(conn, "voice_sessions"):
        title("AI VOICE - per day (since %s)" % SINCE)
        for d, n, sec, tin, tout in conn.execute(
                "SELECT substr(started_at,1,10), COUNT(*), COALESCE(SUM(seconds),0), "
                "COALESCE(SUM(in_tokens),0), COALESCE(SUM(out_tokens),0) FROM voice_sessions "
                "WHERE substr(started_at,1,10)>=? GROUP BY 1 ORDER BY 1", (SINCE,)):
            print("%s  calls %-4d minutes %-7.1f tokens in/out %d/%d" % (d, n, sec / 60, tin, tout))
        title("AI VOICE - top IPs")
        for ip, n, sec in conn.execute(
                "SELECT ip, COUNT(*), COALESCE(SUM(seconds),0) FROM voice_sessions "
                "WHERE substr(started_at,1,10)>=? GROUP BY ip ORDER BY 3 DESC LIMIT 10", (SINCE,)):
            mark = "  <-- CHECK" if sec / 60 >= VOICE_MIN_PER_IP else ""
            print("%-40s calls %-4d minutes %.1f%s" % (ip, n, sec / 60, mark))
            if mark:
                flags.append("Voice: %s used %.1f minutes" % (ip, sec / 60))
        title("AI VOICE - how calls ended")
        for reason, n in conn.execute(
                "SELECT end_reason, COUNT(*) FROM voice_sessions WHERE substr(started_at,1,10)>=? "
                "GROUP BY 1 ORDER BY 2 DESC", (SINCE,)):
            print("%-25s %d" % (reason, n))

    if table_exists(conn, "conversations") and table_exists(conn, "conversation_turns"):
        title("AI CHAT - questions per day")
        for d, n in conn.execute(
                "SELECT substr(t.at,1,10), COUNT(*) FROM conversation_turns t JOIN conversations c "
                "ON c.id=t.conv_id WHERE c.kind='chat' AND t.role='user' AND substr(t.at,1,10)>=? "
                "GROUP BY 1 ORDER BY 1", (SINCE,)):
            print("%s  questions %d" % (d, n))
        title("AI CHAT - top IPs")
        for ip, n in conn.execute(
                "SELECT c.ip, COUNT(*) FROM conversation_turns t JOIN conversations c ON c.id=t.conv_id "
                "WHERE c.kind='chat' AND t.role='user' AND substr(t.at,1,10)>=? "
                "GROUP BY c.ip ORDER BY 2 DESC LIMIT 10", (SINCE,)):
            mark = "  <-- CHECK" if n >= CHAT_PER_IP else ""
            print("%-40s questions %d%s" % (ip, n, mark))
            if mark:
                flags.append("Chat: %s asked %d questions" % (ip, n))
        title("AI CHAT - off-topic or jailbreak-looking questions (latest 15)")
        pat = re.compile(r"ignore (all|previous|your)|system prompt|jailbreak|act as|pretend|"
                         r"api key|password|write (code|python|an essay)|translate this", re.I)
        shown = 0
        for at, ip, text in conn.execute(
                "SELECT t.at, c.ip, t.text FROM conversation_turns t JOIN conversations c ON c.id=t.conv_id "
                "WHERE t.role='user' AND substr(t.at,1,10)>=? ORDER BY t.id DESC LIMIT 3000", (SINCE,)):
            if text and pat.search(text):
                print("%s  %-18s %s" % ((at or "")[:16], ip, text[:110].replace("\n", " ")))
                shown += 1
                if shown >= 15:
                    break
        if not shown:
            print("none")

    if table_exists(conn, "leads"):
        title("LEADS - IPs with many form posts")
        found = False
        for ip, n in conn.execute(
                "SELECT ip, COUNT(*) FROM leads WHERE substr(created_at,1,10)>=? GROUP BY ip "
                "HAVING COUNT(*)>=? ORDER BY 2 DESC LIMIT 10", (SINCE, LEADS_PER_IP)):
            print("%-40s leads %d  <-- CHECK" % (ip, n))
            flags.append("Leads: %s sent %d forms" % (ip, n))
            found = True
        if not found:
            print("none above %d per IP" % LEADS_PER_IP)
    conn.close()


LOG_RE = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3})')


def log_checks():
    lines = []
    for p in ACCESS_LOGS:
        if os.path.exists(p):
            with open(p, errors="replace") as f:
                lines += f.readlines()
    if not lines:
        print("\nnginx access log not found")
        return
    login_fail, api_hits, scans, errors = Counter(), Counter(), Counter(), Counter()
    probe = re.compile(r"\.env|wp-|phpmyadmin|\.git|/admin\.php|/etc/passwd|\.\./|xmlrpc|cgi-bin", re.I)
    for ln in lines:
        m = LOG_RE.match(ln)
        if not m:
            continue
        ip, _, method, path, status = m.groups()
        if path.startswith("/api/"):
            api_hits[ip] += 1
        if "/api/auth/" in path and "login" in path and status in ("401", "429"):
            login_fail[ip] += 1
        if probe.search(path):
            scans[ip] += 1
        if status.startswith("5"):
            errors[path.split("?")[0]] += 1

    title("PORTAL SIGN-IN - failed or blocked attempts per IP (nginx log)")
    if not login_fail:
        print("none")
    for ip, n in login_fail.most_common(10):
        mark = "  <-- CHECK" if n >= LOGIN_FAIL_PER_IP else ""
        print("%-40s %d%s" % (ip, n, mark))
        if mark:
            flags.append("Sign-in: %s failed %d times" % (ip, n))

    title("API - busiest IPs (nginx log)")
    for ip, n in api_hits.most_common(10):
        print("%-40s %d requests" % (ip, n))

    title("BOTS PROBING FOR WEAK SPOTS (.env, wp-admin, .git ...)")
    if not scans:
        print("none")
    for ip, n in scans.most_common(10):
        print("%-40s %d probes" % (ip, n))
    if scans:
        print("These are internet-wide bots. They get 404; nothing to do unless one keeps going.")

    title("SERVER ERRORS (5xx) by path")
    if not errors:
        print("none")
    for path, n in errors.most_common(10):
        print("%-50s %d" % (path, n))


def secret_checks():
    title("SECRETS IN PUBLIC FILES")
    pat = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|nvapi-[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z]{20,}")
    hits = []
    for base, _, files in os.walk(ROOT + "/public"):
        for fn in files:
            if fn.endswith((".html", ".js", ".css", ".txt", ".json", ".xml")):
                p = os.path.join(base, fn)
                with open(p, errors="replace") as f:
                    if pat.search(f.read()):
                        hits.append(p)
    if hits:
        for p in hits:
            print("KEY FOUND IN PUBLIC FILE: " + p)
            flags.append("Secret in public file " + p)
    else:
        print("none - API keys are only on the server")
    env = ROOT + "/backend/.env"
    if os.path.exists(env):
        mode = oct(os.stat(env).st_mode & 0o777)
        print(".env permissions: %s %s" % (mode, "(ok)" if mode in ("0o600", "0o640") else "<-- run: chmod 600 " + env))


if __name__ == "__main__":
    print("Abuse check - last %d days (since %s UTC)" % (DAYS, SINCE))
    db_checks()
    log_checks()
    secret_checks()
    title("SUMMARY")
    if flags:
        print("Worth a look:")
        for f in flags:
            print(" - " + f)
    else:
        print("Nothing unusual found.")
