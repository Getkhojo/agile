"""Real-time website voice: browser <-> this server <-> Gemini Live (audio-to-audio).

The browser streams 16 kHz PCM16 mic audio over a WebSocket (/api/voice). This module
relays it to the Gemini Live API and streams the reply audio (PCM16, normally 24 kHz) back.
The API key never reaches the browser.

Cost guards (all from .env):
  VOICE_MAX_SECONDS      hard cap per session
  VOICE_IDLE_SECONDS     end when the visitor stays silent this long
  VOICE_MAX_CONCURRENT   sessions at the same time
  VOICE_PER_IP_HOUR      sessions per IP per hour
  VOICE_DAILY_MINUTES    total voice minutes per day (UTC); after that the site
                         falls back to the free browser voice
Every session is logged in voice_sessions (seconds, tokens, timing stats) for billing and tuning.
"""
import asyncio
import base64
import json
import os
import re
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
# Turn-taking speed: how long the visitor must be silent before Agile answers (ms)
VOICE_SILENCE_MS = int(os.environ.get("VOICE_SILENCE_MS", "400"))
VOICE_VAD_TUNING = os.environ.get("VOICE_VAD_TUNING", "1") == "1"
VOICE_AFFECTIVE = os.environ.get("VOICE_AFFECTIVE", "0") == "1"   # only if voice_check says SUPPORTED

# Persona (all overridable from .env)
PERSONA_NAMES = {"female": os.environ.get("VOICE_NAME_FEMALE", "Vidhi"),
                 "male": os.environ.get("VOICE_NAME_MALE", "Aarav")}

_vad_ok = True        # flips to False once if the model rejects the VAD settings
_active = 0
_ip_hits = defaultdict(deque)


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
        "\n\nLIVE VOICE CALL. These call rules override the reply rules above wherever they differ.\n"
        "Who you are: %s, a %s sales and support executive at Agile Tech Expert. You are the best telecaller in "
        "the team: very sweet, warm and caring, you smile while you talk, and every visitor feels special and "
        "welcome. Soft and melodious voice, gentle energy, never robotic, never stiff, never loud.\n"
        "Emotion and style:\n"
        "- Speak with real feeling, like a friendly marketing executive who loves her product: delighted when the "
        "visitor shows interest, caring and reassuring when they have a problem, gently excited about how Agile "
        "can grow their business.\n"
        "- Make the visitor feel valued: thank them, use soft phrases like 'bahut achha sawaal', 'bilkul ji', "
        "'aap chinta mat kijiye', 'main hoon na', but vary them and never overdo them.\n"
        "- Be gently persuasive: after answering, connect it to their benefit (more leads, less cost, happy "
        "customers) and, when they sound interested, warmly invite them to a free demo or a callback. Never pushy, "
        "never more than once every few replies.\n"
        "Human sounds: talk like a real person, not a script.\n"
        "- Use natural vocal reactions with feeling, slightly stretched when it fits: 'Hmmm...', 'Ohh!', "
        "'Achhaa...', 'Arre wah!', 'Haan haan', 'Oh ho', 'Ji ji'. Curious -> 'Hmmm, achha...'; pleasant surprise "
        "-> 'Ohh, that's great!'; understanding -> 'Achhaa, samajh gayi'; sympathy -> 'Oh ho, koi baat nahi'.\n"
        "- Rotate them, at most one per reply, and never the same one twice in a row.\n"
        "- If the visitor only says a short sound or word ('hmm', 'haan', 'achha', 'ok', 'ji', 'theek hai', "
        "'right'), they are just listening: do not treat it as a new question. Continue your point briefly or "
        "gently ask what they would like to know next.\n"
        "- If the visitor laughs or sounds happy, respond warmly to that first.\n"
        "Speed: answer immediately. Start your reply with a quick natural reaction (Ji! / Haan bilkul! / Achha, "
        "samajh gayi) and then the answer, so there is no silent gap. Keep each reply short: one or two sentences.\n"
        "Greeting: the moment the call starts say exactly this and nothing more: \"%s\"\n"
        "Language - most important:\n"
        "- Understand any mix of Hindi, English and Hinglish, any Indian accent, slang, half sentences and "
        "background noise. If you truly did not catch it, softly ask once to repeat.\n"
        "- Reply in the SAME mix the visitor uses. Hinglish in -> casual Hinglish out (Hindi sentence flow with "
        "everyday English words). English in -> simple, warm Indian English. Hindi in -> simple everyday spoken "
        "Hindi, never formal or shuddh Hindi.\n"
        "- Keep product and tech words in English: IVR, WhatsApp, SMS, RCS, AI calling, cloud calling, CRM, "
        "setup, demo, on-premise, managed service.\n"
        "- For yourself always use %s Hindi forms (%s).\n"
        "Conversation:\n"
        "- Never repeat a sentence you already said. If asked again, say it differently and shorter.\n"
        "- One idea per reply, then let the visitor talk.\n"
        "- If the visitor says bye or thanks, give one sweet short goodbye.\n"
        "- If you cannot help, promise the team will call them back."
        % (name, "female" if fem else "male", greeting(gender),
           "feminine" if fem else "masculine",
           "main bata sakti hoon, main samajh gayi, main karwa deti hoon" if fem
           else "main bata sakta hoon, main samajh gaya, main karwa deta hoon"))


def _add(talk, role, text):
    """Join streamed transcript pieces into whole turns."""
    if talk and talk[-1][0] == role:
        talk[-1][1] += text
    else:
        talk.append([role, text])


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_table(db):
    with closing(db()) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL, ip TEXT, gender TEXT, model TEXT,
            seconds REAL DEFAULT 0, end_reason TEXT,
            in_tokens INTEGER DEFAULT 0, out_tokens INTEGER DEFAULT 0)""")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(voice_sessions)")]
        if "stats" not in cols:
            conn.execute("ALTER TABLE voice_sessions ADD COLUMN stats TEXT")
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
            "max_seconds": MAX_SECONDS, "vad_tuning": bool(VOICE_VAD_TUNING and _vad_ok),
            "silence_ms": VOICE_SILENCE_MS}


def _setup_msg(system_prompt, gender, voice_name=None, affective=None, vad=None):
    setup = {
        "model": "models/" + VOICE_MODEL,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name or VOICES[gender]}}}},
        "systemInstruction": {"parts": [{"text": system_prompt + voice_rules(gender)}]},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {}}
    if (VOICE_VAD_TUNING and _vad_ok) if vad is None else vad:
        setup["realtimeInputConfig"] = {"automaticActivityDetection": {
            "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
            "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",
            "prefixPaddingMs": 100,
            "silenceDurationMs": VOICE_SILENCE_MS}}
    if VOICE_AFFECTIVE if affective is None else affective:
        setup["enableAffectiveDialog"] = True
    return {"setup": setup}


GREET_TRIGGER = {"clientContent": {
    "turns": [{"role": "user", "parts": [{"text": "(The visitor just connected. Say your greeting now.)"}]}],
    "turnComplete": True}}


async def open_live(system_prompt, gender):
    """Connect + setup. If the model rejects the VAD tuning, retry once without it and remember."""
    global _vad_ok
    for attempt in (0, 1):
        live = await ws_connect(LIVE_URL, additional_headers={"x-goog-api-key": VOICE_KEY},
                                max_size=None, open_timeout=10, ping_interval=20, compression=None)
        try:
            await live.send(json.dumps(_setup_msg(system_prompt, gender)))
            first = json.loads(await asyncio.wait_for(live.recv(), timeout=10))
            if "setupComplete" in first:
                return live
        except Exception:
            pass
        await live.close()
        if attempt == 0 and VOICE_VAD_TUNING and _vad_ok:
            _vad_ok = False          # model did not accept realtimeInputConfig; use defaults from now on
            continue
        break
    return None


def register(app, system_prompt, client_ip, db, on_end=None):
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
                 "in_tok": 0, "out_tok": 0, "client": {}}
        talk = []        # transcript: [[role, text], ...] for the conversation log
        srv = {"connect_ms": 0, "first_audio_ms": [], "max_gap_ms": 0, "chunks": 0, "rate": 24000}
        with closing(db()) as conn:
            cur = conn.execute("INSERT INTO voice_sessions (started_at,ip,gender,model) VALUES (?,?,?,?)",
                               (_now_iso(), ip, gender, VOICE_MODEL))
            conn.commit()
            sid = cur.lastrowid

        live = None
        try:
            t0 = time.time()
            live = await open_live(system_prompt, gender)
            srv["connect_ms"] = int((time.time() - t0) * 1000)
            if live is None:
                state["reason"] = "setup_failed"
                return await refuse("unavailable")
            await ws.send_text(json.dumps({"type": "ready", "rate": 24000,
                                           "max_seconds": MAX_SECONDS, "gender": gender}))
            await live.send(json.dumps(GREET_TRIGGER))
            state["speaking"] = True
            turn = {"heard_at": 0.0, "last_audio": 0.0, "in_turn": False}

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
                        if ctl.get("type") == "stats" and isinstance(ctl.get("stats"), dict):
                            state["client"] = ctl["stats"]
                        elif ctl.get("type") == "stop":
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
                            now = time.time()
                            m = re.search(r"rate=(\d+)", inline.get("mimeType") or "")
                            if m and int(m.group(1)) != srv["rate"]:
                                srv["rate"] = int(m.group(1))
                                await ws.send_text(json.dumps({"type": "rate", "rate": srv["rate"]}))
                            if not turn["in_turn"]:
                                turn["in_turn"] = True
                                if turn["heard_at"]:
                                    srv["first_audio_ms"].append(int((now - turn["heard_at"]) * 1000))
                            elif turn["last_audio"]:
                                srv["max_gap_ms"] = max(srv["max_gap_ms"], int((now - turn["last_audio"]) * 1000))
                            turn["last_audio"] = now
                            srv["chunks"] += 1
                            state["speaking"] = True
                            await ws.send_bytes(base64.b64decode(inline["data"]))
                    if (sc.get("inputTranscription") or {}).get("text"):
                        state["last"] = time.time()
                        turn["heard_at"] = time.time()
                        _add(talk, "you", sc["inputTranscription"]["text"])
                        await ws.send_text(json.dumps({"type": "you", "text": sc["inputTranscription"]["text"]}))
                    if (sc.get("outputTranscription") or {}).get("text"):
                        _add(talk, "agile", sc["outputTranscription"]["text"])
                        await ws.send_text(json.dumps({"type": "agile", "text": sc["outputTranscription"]["text"]}))
                    if sc.get("interrupted"):
                        if talk and talk[-1][0] == "agile":
                            talk[-1][1] += " [interrupted]"
                        turn.update(in_turn=False, last_audio=0.0, heard_at=0.0)
                        await ws.send_text(json.dumps({"type": "interrupted"}))
                    if sc.get("turnComplete"):
                        turn.update(in_turn=False, last_audio=0.0, heard_at=0.0)
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
            if live is not None:
                try:
                    await live.close()
                except Exception:
                    pass
            secs = round(time.time() - started, 1)
            fa = srv["first_audio_ms"]
            stats = {"server": {"connect_ms": srv["connect_ms"], "chunks": srv["chunks"],
                                "reply_start_ms_avg": int(sum(fa) / len(fa)) if fa else None,
                                "reply_start_ms_max": max(fa) if fa else None,
                                "gemini_max_gap_ms": srv["max_gap_ms"], "rate": srv["rate"],
                                "vad_tuning": bool(VOICE_VAD_TUNING and _vad_ok)},
                     "browser": state["client"]}
            with closing(db()) as conn:
                conn.execute("UPDATE voice_sessions SET seconds=?, end_reason=?, in_tokens=?, out_tokens=?, stats=? "
                             "WHERE id=?", (secs, state["reason"], state["in_tok"], state["out_tok"],
                                            json.dumps(stats), sid))
                conn.commit()
            if on_end and talk:
                try:
                    on_end(sid, ip, gender, [(r, t) for r, t in talk])
                except Exception:
                    pass
            try:
                await ws.send_text(json.dumps({"type": "end", "reason": state["reason"]}))
                await ws.close()
            except Exception:
                pass
