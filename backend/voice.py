"""Real-time website voice: browser <-> this server <-> Gemini Live (audio-to-audio).

The browser streams 16 kHz PCM16 mic audio over a WebSocket (/api/voice). This module
relays it to the Gemini Live API and streams the 24 kHz PCM16 reply audio back.
The API key never reaches the browser.

Cost guards (all from .env):
  VOICE_MAX_SECONDS      hard cap per session
  VOICE_IDLE_SECONDS     end when the visitor stays silent this long
  VOICE_MAX_CONCURRENT   sessions at the same time
  VOICE_PER_IP_HOUR      sessions per IP per hour
  VOICE_DAILY_MINUTES    total voice minutes per day (UTC); after that the site
                         falls back to the free browser voice
Every session is logged in the voice_sessions table (seconds + tokens) for billing.
"""
import asyncio
import base64
import json
import os
import time
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # websockets < 13
    ws_connect = None

LIVE_URL = os.environ.get(
    "VOICE_LIVE_URL",
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")
VOICE_KEY = os.environ.get("VOICE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
VOICE_MODEL = os.environ.get("VOICE_MODEL", "gemini-3.8-live")
VOICES = {"male": os.environ.get("VOICE_MALE", "Charon"),
          "female": os.environ.get("VOICE_FEMALE", "Kore")}
VOICE_DEFAULT_GENDER = os.environ.get("VOICE_DEFAULT_GENDER", "female")
VOICE_ENABLED = os.environ.get("VOICE_ENABLED", "1") == "1"
MAX_SECONDS = int(os.environ.get("VOICE_MAX_SECONDS", "180"))
IDLE_SECONDS = int(os.environ.get("VOICE_IDLE_SECONDS", "20"))
MAX_CONCURRENT = int(os.environ.get("VOICE_MAX_CONCURRENT", "3"))
PER_IP_HOUR = int(os.environ.get("VOICE_PER_IP_HOUR", "10"))
DAILY_MINUTES = int(os.environ.get("VOICE_DAILY_MINUTES", "60"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "VOICE_ALLOWED_ORIGINS", "https://agiletechexpert.com,https://www.agiletechexpert.com").split(",") if o.strip()]

# Persona (all overridable from .env)
PERSONA_NAMES = {"female": os.environ.get("VOICE_NAME_FEMALE", "Vidhi"),
                 "male": os.environ.get("VOICE_NAME_MALE", "Aarav")}
VOICE_AFFECTIVE = os.environ.get("VOICE_AFFECTIVE", "0") == "1"   # emotion-aware replies, if the model supports it


def greeting(gender):
    custom = os.environ.get("VOICE_GREETING_" + gender.upper(), "")
    if custom:
        return custom
    verb = "sakti" if gender == "female" else "sakta"
    return ("Namaste! Hi, main %s, Agile Tech Expert se. Bataiye, main aapki kya help kar %s hoon?"
            % (PERSONA_NAMES[gender], verb))


def voice_rules(gender):
    name = PERSONA_NAMES[gender]
    fem = gender == "female"
    return (
        "\n\nYou are on a LIVE voice call with a website visitor.\n"
        "Persona: your name is %s, a %s assistant at Agile Tech Expert. You sound like a warm, soft-spoken, "
        "cheerful young Indian customer-care executive who smiles while talking. Gentle, sweet and pleasant to "
        "listen to; never robotic, never stiff, never loud.\n"
        "Emotion: sound genuinely happy to help. Be caring and calm if the visitor has a problem, a little "
        "excited when talking about what Agile can do for them, apologetic and gentle if you cannot help. "
        "Relaxed, natural pace with small natural pauses.\n"
        "Greeting: as soon as the call starts, say exactly this and nothing more: \"%s\"\n"
        "Language - most important:\n"
        "- Understand any mix of Hindi, English and Hinglish, any Indian accent, slang, half sentences and "
        "background noise. If you truly did not catch it, ask once, softly, to repeat.\n"
        "- Reply in the SAME mix the visitor uses. Hinglish in -> casual Hinglish out (Hindi sentence flow with "
        "everyday English words). English in -> simple Indian English. Hindi in -> simple everyday spoken Hindi, "
        "never formal or shuddh Hindi.\n"
        "- Keep product and tech words in English: IVR, WhatsApp, SMS, RCS, AI calling, cloud calling, CRM, "
        "setup, demo, on-premise, managed service.\n"
        "- For yourself always use %s Hindi forms (%s).\n"
        "- Use natural Indian fillers only now and then: ji, haan, achha, bilkul, zaroor.\n"
        "Conversation:\n"
        "- Never repeat a sentence you already said. If asked again, say it differently and shorter.\n"
        "- One idea per reply, then let the visitor talk.\n"
        "- If the visitor says bye, thanks or they are done, give one sweet short goodbye.\n"
        "- If you cannot help, offer that the team will call them back."
        % (name, "female" if fem else "male", greeting(gender),
           "feminine" if fem else "masculine",
           "main bata sakti hoon, main samajh gayi" if fem else "main bata sakta hoon, main samajh gaya"))

_active = 0
_ip_hits = defaultdict(deque)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_table(db):
    with closing(db()) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL, ip TEXT, gender TEXT, model TEXT,
            seconds REAL DEFAULT 0, end_reason TEXT,
            in_tokens INTEGER DEFAULT 0, out_tokens INTEGER DEFAULT 0)""")
        conn.commit()


def _seconds_today(db):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(db()) as conn:
        row = conn.execute("SELECT COALESCE(SUM(seconds),0) FROM voice_sessions WHERE started_at LIKE ?",
                           (day + "%",)).fetchone()
    return float(row[0] or 0)


def _ip_ok(ip):
    now = time.time()
    q = _ip_hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= PER_IP_HOUR:
        return False
    q.append(now)
    return True


def voice_status(db):
    used = _seconds_today(db) / 60.0
    return {"enabled": bool(VOICE_ENABLED and VOICE_KEY and ws_connect),
            "model": VOICE_MODEL, "active": _active, "max_concurrent": MAX_CONCURRENT,
            "minutes_today": round(used, 1), "daily_minutes": DAILY_MINUTES,
            "max_seconds": MAX_SECONDS}


def _setup_msg(system_prompt, gender, voice_name=None, affective=None):
    setup = {
        "model": "models/" + VOICE_MODEL,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name or VOICES[gender]}}}},
        "systemInstruction": {"parts": [{"text": system_prompt + voice_rules(gender)}]},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {}}
    if VOICE_AFFECTIVE if affective is None else affective:
        setup["enableAffectiveDialog"] = True
    return {"setup": setup}


GREET_TRIGGER = {"clientContent": {
    "turns": [{"role": "user", "parts": [{"text": "(The visitor just connected. Say your greeting now.)"}]}],
    "turnComplete": True}}


def register(app, system_prompt, client_ip, db):
    init_table(db)

    @app.get("/api/voice/status")
    def _status():
        return voice_status(db)

    @app.websocket("/api/voice")
    async def voice(ws: WebSocket):
        global _active
        origin = ws.headers.get("origin", "")
        if ALLOWED_ORIGINS and origin not in ALLOWED_ORIGINS:
            await ws.close(code=1008)
            return
        await ws.accept()
        ip = client_ip(ws)
        gender = ws.query_params.get("gender", VOICE_DEFAULT_GENDER)
        gender = gender if gender in VOICES else "female"

        async def refuse(reason):
            await ws.send_text(json.dumps({"type": "end", "reason": reason}))
            await ws.close()

        if not (VOICE_ENABLED and VOICE_KEY and ws_connect):
            return await refuse("unavailable")
        if _active >= MAX_CONCURRENT:
            return await refuse("busy")
        if _seconds_today(db) >= DAILY_MINUTES * 60:
            return await refuse("daily_limit")
        if not _ip_ok(ip):
            return await refuse("ip_limit")

        _active += 1
        started = time.time()
        state = {"reason": "client_closed", "last": time.time(), "speaking": False,
                 "in_tok": 0, "out_tok": 0}
        with closing(db()) as conn:
            cur = conn.execute("INSERT INTO voice_sessions (started_at,ip,gender,model) VALUES (?,?,?,?)",
                               (_now_iso(), ip, gender, VOICE_MODEL))
            conn.commit()
            sid = cur.lastrowid

        try:
            async with ws_connect(LIVE_URL, additional_headers={"x-goog-api-key": VOICE_KEY},
                                  max_size=None, open_timeout=10, ping_interval=20) as live:
                await live.send(json.dumps(_setup_msg(system_prompt, gender)))
                first = json.loads(await asyncio.wait_for(live.recv(), timeout=10))
                if "setupComplete" not in first:
                    state["reason"] = "setup_failed"
                    return await refuse("unavailable")
                await ws.send_text(json.dumps({"type": "ready", "rate": 24000,
                                               "max_seconds": MAX_SECONDS, "gender": gender}))
                # let the assistant greet first
                await live.send(json.dumps(GREET_TRIGGER))
                state["speaking"] = True

                async def up():
                    while True:
                        msg = await ws.receive()
                        if msg.get("type") == "websocket.disconnect":
                            state["reason"] = "client_closed"
                            return
                        if msg.get("bytes"):
                            await live.send(json.dumps({"realtimeInput": {"audio": {
                                "data": base64.b64encode(msg["bytes"]).decode("ascii"),
                                "mimeType": "audio/pcm;rate=16000"}}}))
                        elif msg.get("text"):
                            try:
                                ctl = json.loads(msg["text"])
                            except ValueError:
                                continue
                            if ctl.get("type") == "stop":
                                state["reason"] = "stopped"
                                return

                async def down():
                    async for raw in live:
                        data = json.loads(raw)
                        usage = data.get("usageMetadata")
                        if usage:
                            state["in_tok"] = max(state["in_tok"], int(usage.get("promptTokenCount") or 0))
                            state["out_tok"] = max(state["out_tok"], int(usage.get("responseTokenCount") or 0))
                        if "goAway" in data:
                            state["reason"] = "provider_goaway"
                            return
                        sc = data.get("serverContent")
                        if not sc:
                            continue
                        for part in (sc.get("modelTurn") or {}).get("parts", []):
                            inline = part.get("inlineData")
                            if inline and inline.get("data"):
                                state["speaking"] = True
                                await ws.send_bytes(base64.b64decode(inline["data"]))
                        if (sc.get("inputTranscription") or {}).get("text"):
                            state["last"] = time.time()
                            await ws.send_text(json.dumps({"type": "you", "text": sc["inputTranscription"]["text"]}))
                        if (sc.get("outputTranscription") or {}).get("text"):
                            await ws.send_text(json.dumps({"type": "agile", "text": sc["outputTranscription"]["text"]}))
                        if sc.get("interrupted"):
                            await ws.send_text(json.dumps({"type": "interrupted"}))
                        if sc.get("turnComplete"):
                            state["speaking"] = False
                            state["last"] = time.time()
                            await ws.send_text(json.dumps({"type": "turn_done"}))
                    state["reason"] = "provider_closed"

                async def guard():
                    while True:
                        await asyncio.sleep(1)
                        now = time.time()
                        if now - started >= MAX_SECONDS:
                            state["reason"] = "time_limit"
                            return
                        if not state["speaking"] and now - state["last"] >= IDLE_SECONDS:
                            state["reason"] = "idle"
                            return

                tasks = [asyncio.create_task(t()) for t in (up, down, guard)]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                        state["reason"] = "error"
        except Exception:
            state["reason"] = "error" if state["reason"] == "client_closed" else state["reason"]
        finally:
            _active -= 1
            secs = round(time.time() - started, 1)
            with closing(db()) as conn:
                conn.execute("UPDATE voice_sessions SET seconds=?, end_reason=?, in_tokens=?, out_tokens=? WHERE id=?",
                             (secs, state["reason"], state["in_tok"], state["out_tok"], sid))
                conn.commit()
            try:
                await ws.send_text(json.dumps({"type": "end", "reason": state["reason"]}))
                await ws.close()
            except Exception:
                pass
