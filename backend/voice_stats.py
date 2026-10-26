"""Show the last voice calls with timing stats, to see where delay or stutter comes from.

  cd /var/www/agiletechexpert/backend && sudo -u www-data venv/bin/python voice_stats.py [count]
"""
import json
import sqlite3
import sys

from app import DB_PATH

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT id, started_at, gender, seconds, end_reason, in_tokens, out_tokens, stats "
                    "FROM voice_sessions ORDER BY id DESC LIMIT ?", (n,)).fetchall()
for r in rows:
    s = json.loads(r[7] or "{}")
    sv, br = s.get("server", {}), s.get("browser", {})
    rs = br.get("reply_start_ms") or []
    print("#%s %s %s %.0fs end=%s tokens=%s/%s" % (r[0], r[1], r[2], r[3] or 0, r[4], r[5], r[6]))
    print("   reply starts after you stop (browser): avg %s ms, max %s ms   | server saw: avg %s, max %s" % (
        int(sum(rs) / len(rs)) if rs else "-", max(rs) if rs else "-",
        sv.get("reply_start_ms_avg", "-"), sv.get("reply_start_ms_max", "-")))
    print("   audio gaps: Gemini->server max %s ms | server->browser max %s ms | stalls (underruns) %s | "
          "jitter buffer %s ms" % (sv.get("gemini_max_gap_ms", "-"), br.get("max_gap_ms", "-"),
                                   br.get("underruns", "-"), br.get("jitter_buffer_ms", "-")))
    print("   barge-ins %s, real interrupts %s, connect %s ms, VAD tuning %s" % (
        br.get("barges", "-"), br.get("interrupts", "-"), sv.get("connect_ms", "-"), sv.get("vad_tuning", "-")))
