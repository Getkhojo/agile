"""Check Gemini Live on the server, and make voice samples to pick the nicest voice by ear.

Run on the server from the backend folder:
  sudo -u www-data bash -c 'set -a; . ./.env; set +a; venv/bin/python voice_check.py'
  sudo -u www-data bash -c 'set -a; . ./.env; set +a; venv/bin/python voice_check.py --samples'

--samples writes one greeting per voice to public/voice-samples/ and a page to listen at
https://agiletechexpert.com/voice-samples/ . Delete the folder after choosing:
  sudo rm -rf /var/www/agiletechexpert/public/voice-samples
"""
import asyncio
import base64
import json
import sys
import wave
from pathlib import Path

import voice

# Google's descriptions of each prebuilt voice
CANDIDATES = {
    "female": [("Achernar", "Soft"), ("Sulafat", "Warm"), ("Vindemiatrix", "Gentle"), ("Leda", "Youthful"),
               ("Aoede", "Breezy"), ("Despina", "Smooth"), ("Kore", "Firm (current default)")],
    "male": [("Achird", "Friendly"), ("Algieba", "Smooth"), ("Umbriel", "Easy-going"), ("Puck", "Upbeat"),
             ("Charon", "Informative (current default)")],
}
OUT = Path(__file__).resolve().parent.parent / "public" / "voice-samples"


async def speak_once(gender, voice_name, affective=None, timeout=15):
    """Open a session, ask for the greeting, return (pcm_bytes, transcript) or raise."""
    async with voice.ws_connect(voice.LIVE_URL, additional_headers={"x-goog-api-key": voice.VOICE_KEY},
                                max_size=None, open_timeout=10) as live:
        await live.send(json.dumps(voice._setup_msg("You are a test assistant for Agile Tech Expert.",
                                                    gender, voice_name, affective)))
        first = json.loads(await asyncio.wait_for(live.recv(), timeout=10))
        if "setupComplete" not in first:
            raise RuntimeError("setup: %s" % str(first)[:300])
        await live.send(json.dumps(voice.GREET_TRIGGER))
        pcm, text = bytearray(), ""

        async def collect():
            nonlocal text
            async for raw in live:
                sc = json.loads(raw).get("serverContent") or {}
                for part in (sc.get("modelTurn") or {}).get("parts", []):
                    if (part.get("inlineData") or {}).get("data"):
                        pcm.extend(base64.b64decode(part["inlineData"]["data"]))
                text += (sc.get("outputTranscription") or {}).get("text", "")
                if sc.get("turnComplete"):
                    return
        await asyncio.wait_for(collect(), timeout=timeout)
        if not pcm:
            raise RuntimeError("no audio returned")
        return bytes(pcm), text.strip()


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)


async def main():
    if not voice.VOICE_KEY:
        print("FAIL: no GEMINI_API_KEY / VOICE_API_KEY in .env")
        return
    print("model:", voice.VOICE_MODEL, "| voices:", voice.VOICES, "| names:", voice.PERSONA_NAMES)
    for g in ("female", "male"):
        try:
            pcm, text = await speak_once(g, None)
            print("OK  %-6s %-10s %.1fs  \"%s\"" % (g, voice.VOICES[g], len(pcm) / 48000, text))
        except Exception as e:
            print("FAIL %-6s %-10s %s" % (g, voice.VOICES[g], str(e)[:300]))
    try:
        await speak_once("female", None, affective=True)
        print("affective dialog: SUPPORTED (you can set VOICE_AFFECTIVE=1)")
    except Exception as e:
        print("affective dialog: not supported on this model (%s)" % str(e)[:160])

    if "--samples" not in sys.argv:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for g, items in CANDIDATES.items():
        for name, mood in items:
            try:
                pcm, text = await speak_once(g, name)
                write_wav(OUT / ("%s.wav" % name), pcm)
                rows.append((g, name, mood, text))
                print("sample OK   %-6s %-12s %s" % (g, name, mood))
            except Exception as e:
                print("sample FAIL %-6s %-12s %s" % (g, name, str(e)[:200]))
    items_html = "\n".join(
        '<div class="v"><b>%s</b> <span>%s &middot; %s</span><audio controls preload="none" src="%s.wav"></audio>'
        '<code>VOICE_%s=%s</code></div>' % (n, g, m, n, g.upper(), n) for g, n, m, _ in rows)
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta name=robots content=noindex><title>Voice samples</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:24px auto;padding:0 16px;"
        "background:#f4fbfa;color:#063a3a}.v{background:#fff;border-radius:12px;padding:14px;margin:10px 0;"
        "box-shadow:0 1px 4px rgba(0,0,0,.08)}.v span{color:#5a7a7a;font-size:13px}audio{width:100%;margin:8px 0}"
        "code{font-size:12px;background:#e8f6f4;padding:3px 6px;border-radius:6px}</style>"
        "<h1>Agile voice samples</h1><p>Listen, pick one per gender, and put its line in backend/.env.</p>"
        + items_html, encoding="utf-8")
    print("\nListen at: https://agiletechexpert.com/voice-samples/")


asyncio.run(main())
