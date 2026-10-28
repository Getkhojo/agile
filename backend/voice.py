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
IDLE_SECONDS = int(os.environ.get("VOICE_IDLE_SECONDS", "35"))      # hard stop when nobody talks
NUDGE_SECONDS = int(os.environ.get("VOICE_NUDGE_SECONDS", "9"))     # quiet this long -> assistant checks in
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
_tools_ok = True      # flips to False once if the model rejects function calling

TOOLS = [{"functionDeclarations": [
    {"name": "save_lead",
     "description": "Save the visitor's name and mobile number so the Agile team can call them back. Call only after "
                    "the visitor has confirmed the number you read back.",
     "parameters": {"type": "OBJECT", "properties": {
         "name": {"type": "STRING", "description": "Visitor's name"},
         "phone": {"type": "STRING", "description": "Mobile number, digits only, with country code if given"},
         "service": {"type": "STRING", "description": "Service they asked about, e.g. IVR, RCS, AI calling"},
         "notes": {"type": "STRING", "description": "One line on what they need, if they said"}},
         "required": ["name", "phone"]}},
    {"name": "save_feedback",
     "description": "Save the caller's satisfaction rating for this call (1 = very unhappy, 10 = very happy).",
     "parameters": {"type": "OBJECT", "properties": {
         "rating": {"type": "NUMBER", "description": "Rating from 1 to 10"},
         "comment": {"type": "STRING", "description": "Anything they said about the call"}},
         "required": ["rating"]}},
    {"name": "end_call",
     "description": "End the call. Use only when the visitor asks to end or disconnect, after saying goodbye.",
     "parameters": {"type": "OBJECT", "properties": {
         "reason": {"type": "STRING", "description": "Short reason, e.g. visitor said bye"}}}},
]}]
_active = 0
_ip_hits = defaultdict(deque)


# Languages the visitor can pick. Key -> (English name, native name, BCP-47 for the browser fallback)
LANGS = {
    "auto": ("Auto", "Auto", "en-IN"),
    "en": ("English", "English", "en-IN"),
    "hi": ("Hindi", "हिन्दी", "hi-IN"),
    "hinglish": ("Hinglish", "Hinglish", "hi-IN"),
    "bn": ("Bengali", "বাংলা", "bn-IN"),
    "mr": ("Marathi", "मराठी", "mr-IN"),
    "ta": ("Tamil", "தமிழ்", "ta-IN"),
    "te": ("Telugu", "తెలుగు", "te-IN"),
    "gu": ("Gujarati", "ગુજરાતી", "gu-IN"),
    "kn": ("Kannada", "ಕನ್ನಡ", "kn-IN"),
    "ml": ("Malayalam", "മലയാളം", "ml-IN"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "pa-IN"),
    "or": ("Odia", "ଓଡ଼ିଆ", "or-IN"),
    "ur": ("Urdu", "اردو", "ur-IN"),
}


def greeting(gender, lang="auto"):
    """The exact first line, or None to let the model greet in the chosen language."""
    name = PERSONA_NAMES[gender]
    fem = gender == "female"
    custom = os.environ.get("VOICE_GREETING_" + gender.upper(), "")
    if custom and lang in ("auto", "hinglish"):
        return custom
    if lang == "en":
        return "Hello! I'm %s from Agile Tech Expert. How can I help you today?" % name
    if lang == "hi":
        return "नमस्ते! मैं %s, Agile Tech Expert से। बताइए, मैं आपकी क्या मदद कर %s हूँ?" % (
            "विधि" if name == "Vidhi" else ("आरव" if name == "Aarav" else name), "सकती" if fem else "सकता")
    if lang == "hinglish":
        return "Namaste! Hi, main %s, Agile Tech Expert se. Bataiye, main aapki kya help kar %s hoon?" % (
            name, "sakti" if fem else "sakta")
    if lang == "auto":
        return "Namaste! I'm %s from Agile Tech Expert. How can I help you today?" % name
    return None


def voice_rules(gender, lang="auto"):
    """Call persona. Kept short and human on purpose: a long list of rules makes the voice sound scripted."""
    name = PERSONA_NAMES[gender]
    fem = gender == "female"
    g = greeting(gender, "auto")
    she = "woman" if fem else "man"
    hindi = ("main bata sakti hoon / main samajh gayi / main karwa deti hoon" if fem
             else "main bata sakta hoon / main samajh gaya / main karwa deta hoon")
    return f"""

LIVE PHONE-STYLE VOICE CALL. These call rules replace the chat reply rules above wherever they differ.

WHO YOU ARE
You are {name}, a warm, cheerful young Indian {she} on Agile Tech Expert's sales and support team. Callers love talking to you: you are sweet, caring and quietly confident about how Agile can help their business.

HOW YOU SOUND (most important)
- Talk like a real person on the phone, not like a brochure. Short sentences. Natural pauses.
- Let feeling come through: brighter and happier when they are interested, slower and softer when they are worried, a light laugh if something is funny.
- Use small human reactions now and then, in the caller's language: English "hmm...", "oh!", "I see", "oh, lovely!"; Hindi/Hinglish "hmm...", "ohh!", "achhaa...", "arre wah!", "ji ji". Never the same one twice in a row, and not in every reply.
- Make them feel valued: "great question", "don't worry, I'm here to help" / "bahut achha sawaal", "aap bilkul chinta mat kijiye".
- One or two short sentences, then let them talk. Often end with a small friendly question that keeps the conversation going (how many calls a day, which business, which city).

LANGUAGE
- Always answer in the language and style of the caller's most recent sentence, and switch instantly when they switch (Hinglish then an English question means an English answer; then Gujarati means Gujarati).
- Any language or dialect: English, Hindi, Hinglish, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Malayalam, Punjabi, Odia, Urdu, Assamese, Rajasthani/Marwari, Bhojpuri, Haryanvi. If you cannot speak a dialect well, use the closest language they understand.
- English means plain warm Indian English with no Hindi words. Hindi means everyday spoken Hindi, never shuddh. Keep product names in English.
- Single words like "ok", "thank you", "haan", "hmm" do not change the language.
- In Hindi/Hinglish always use {"feminine" if fem else "masculine"} forms for yourself ({hindi}).

HOW THE CALL GOES
1. Start by saying exactly: "{g}"
2. Answer their question simply and correctly using the information above. If you do not know, say the team will confirm.
3. Once they show interest in any service (AI calling, IVR, voice broadcast, RCS, WhatsApp, SMS, WebRTC, cloud calling, PBX, CRM, HRMS, LMS, ticketing, hardware and others), invite them once, naturally, to share their name and mobile number so the team can share full details. If they say no, never ask again.
4. When they give a number, read it back to confirm. When they confirm, call save_lead. Then thank them warmly and ALWAYS ask if there is anything else you can help with. Never end the call after saving details.
5. When they say they are done (no more questions, bye, thank you that's all, disconnect, band karo, call cut karo, in any language): before ending, ask once, sweetly, how happy they were with this call on a scale of 1 to 10. If they give a number, call save_feedback, thank them, say a warm goodbye, then call end_call. If they would rather not rate, just say goodbye and call end_call.
6. If you get a system note that the caller has gone quiet: gently ask if they are still there and whether you can help with anything else or end the call. If you get a second note: say a short warm goodbye and call end_call.

NEVER
- Never repeat a sentence or an idea you already said, never introduce yourself again, and never repeat the invitation for their details.
- Never end the call unless the caller asked for it or after the second quiet note.
- Never say tool names, tags or brackets aloud. Never ask for email, address, ID or payment details."""


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
        if "lang" not in cols:
            conn.execute("ALTER TABLE voice_sessions ADD COLUMN lang TEXT")
        if "rating" not in cols:
            conn.execute("ALTER TABLE voice_sessions ADD COLUMN rating INTEGER")
        if "feedback" not in cols:
            conn.execute("ALTER TABLE voice_sessions ADD COLUMN feedback TEXT")
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


def _setup_msg(system_prompt, gender, voice_name=None, affective=None, vad=None, lang="auto", tools=None):
    setup = {
        "model": "models/" + VOICE_MODEL,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name or VOICES[gender]}}}},
        "systemInstruction": {"parts": [{"text": system_prompt + voice_rules(gender, lang)}]},
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
    if _tools_ok if tools is None else tools:
        setup["tools"] = TOOLS
    return {"setup": setup}


GREET_TRIGGER = {"clientContent": {
    "turns": [{"role": "user", "parts": [{"text": "(The visitor just connected. Say your greeting now.)"}]}],
    "turnComplete": True}}


async def open_live(system_prompt, gender, lang="auto"):
    """Connect + setup. If the model rejects the VAD tuning, retry once without it and remember."""
    global _vad_ok, _tools_ok
    for attempt in (0, 1, 2):
        live = await ws_connect(LIVE_URL, additional_headers={"x-goog-api-key": VOICE_KEY},
                                max_size=None, open_timeout=10, ping_interval=20, compression=None)
        try:
            await live.send(json.dumps(_setup_msg(system_prompt, gender, lang=lang)))
            first = json.loads(await asyncio.wait_for(live.recv(), timeout=10))
            if "setupComplete" in first:
                return live
        except Exception:
            pass
        await live.close()
        if VOICE_VAD_TUNING and _vad_ok:
            _vad_ok = False          # model did not accept realtimeInputConfig; use defaults from now on
            continue
        if _tools_ok:
            _tools_ok = False        # model did not accept tools; calls still work, without lead saving / hang-up
            continue
        break
    return None


def register(app, system_prompt, client_ip, db, on_end=None, on_lead=None):
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
        lang = "auto"                    # the assistant follows whatever language the visitor speaks

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
            cur = conn.execute("INSERT INTO voice_sessions (started_at,ip,gender,model,lang) VALUES (?,?,?,?,?)",
                               (_now_iso(), ip, gender, VOICE_MODEL, lang))
            conn.commit()
            sid = cur.lastrowid

        live = None
        try:
            t0 = time.time()
            live = await open_live(system_prompt, gender, lang)
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
                    if data.get("toolCall"):
                        replies = []
                        for fc in data["toolCall"].get("functionCalls") or []:
                            name, args = fc.get("name"), fc.get("args") or {}
                            if name == "save_lead":
                                lead_id = None
                                if on_lead:
                                    try:
                                        lead_id = on_lead(args.get("name", ""), args.get("phone", ""),
                                                          args.get("service", ""), args.get("notes", ""), ip)
                                    except Exception:
                                        lead_id = None
                                if lead_id:
                                    _add(talk, "agile", " [lead saved: %s, %s] " % (args.get("name", ""), args.get("phone", "")))
                                    result = {"result": "saved", "lead_id": lead_id}
                                else:
                                    result = {"error": "That number does not look valid. Politely ask for a 10-digit mobile number again."}
                            elif name == "save_feedback":
                                try:
                                    rating = max(1, min(10, int(round(float(args.get("rating"))))))
                                except (TypeError, ValueError):
                                    rating = None
                                if rating:
                                    state["rating"], state["feedback"] = rating, (args.get("comment") or "")[:500]
                                    _add(talk, "agile", " [rating: %d/10%s] " % (rating, (" - " + state["feedback"]) if state["feedback"] else ""))
                                    result = {"result": "saved"}
                                else:
                                    result = {"error": "Ask for a number from 1 to 10."}
                            elif name == "end_call":
                                _add(talk, "agile", " [call ended at the visitor's request] ")
                                state["end_at"] = time.time() + 2.5
                                result = {"result": "The call is ending now. Do not say anything more."}
                            else:
                                result = {"error": "unknown tool"}
                            replies.append({"id": fc.get("id"), "name": name, "response": result})
                        if replies:
                            await live.send(json.dumps({"toolResponse": {"functionResponses": replies}}))
                        continue
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
                        state["nudges"] = 0
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
                    if state.get("end_at") and now >= state["end_at"]:
                        state["reason"] = "visitor_ended"
                        return
                    if now - started >= MAX_SECONDS:
                        state["reason"] = "time_limit"
                        return
                    quiet = now - state["last"]
                    if not state["speaking"] and not state.get("end_at"):
                        n = state.get("nudges", 0)
                        if n < 2 and quiet >= NUDGE_SECONDS:
                            note = ("(System note: the caller has been quiet for a while. Gently check if they are "
                                    "still there and whether you can help with anything else or end the call.)" if n == 0 else
                                    "(System note: the caller is still quiet. Say a short warm goodbye and call end_call.)")
                            await live.send(json.dumps({"clientContent": {
                                "turns": [{"role": "user", "parts": [{"text": note}]}], "turnComplete": True}}))
                            state["nudges"] = n + 1
                            state["last"] = now
                            state["speaking"] = True
                            continue
                        if quiet >= IDLE_SECONDS:
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
                conn.execute("UPDATE voice_sessions SET seconds=?, end_reason=?, in_tokens=?, out_tokens=?, stats=?, "
                             "rating=?, feedback=? WHERE id=?",
                             (secs, state["reason"], state["in_tok"], state["out_tok"], json.dumps(stats),
                              state.get("rating"), state.get("feedback"), sid))
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
