"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver...) about every URL in the sitemap.
Run on the server after a deploy:  python3 /var/www/agiletechexpert/deploy/indexnow.py
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
site = json.loads((ROOT / "content" / "site.json").read_text())
key = site.get("indexnow_key")
if not key:
    sys.exit("No indexnow_key in content/site.json")
base = site["base_url"].rstrip("/")
urls = re.findall(r"<loc>([^<]+)</loc>", (ROOT / "public" / "sitemap.xml").read_text())
body = json.dumps({"host": base.split("//", 1)[1], "key": key, "keyLocation": "%s/%s.txt" % (base, key), "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print("IndexNow: submitted %d URLs, HTTP %s" % (len(urls), r.status))
except Exception as e:
    print("IndexNow: not submitted (%s)" % e)
