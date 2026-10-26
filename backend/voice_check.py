"""Check that the server can open a Gemini Live session with the configured key, model and voice.

Run on the server from the backend folder:
  sudo -u www-data bash -c 'set -a; . ./.env; set +a; venv/bin/python voice_check.py'
"""
import asyncio
import json

import voice


async def main():
    if not voice.VOICE_KEY:
        print("FAIL: no GEMINI_API_KEY / VOICE_API_KEY in .env")
        return
    print("model:", voice.VOICE_MODEL, "| voices:", voice.VOICES)
    try:
        async with voice.ws_connect(voice.LIVE_URL, additional_headers={"x-goog-api-key": voice.VOICE_KEY},
                                    max_size=None, open_timeout=10) as live:
            await live.send(json.dumps(voice._setup_msg("You are a test assistant.", "female")))
            first = json.loads(await asyncio.wait_for(live.recv(), timeout=10))
            print("OK: Gemini Live session opened" if "setupComplete" in first else "UNEXPECTED: %s" % first)
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:400])


asyncio.run(main())
