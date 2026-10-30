#!/usr/bin/env python3
"""Build the static site for agiletechexpert.com.

Reads content/*.json and src/assets, writes the finished site to public/.

    python3 tools/build.py              # production build -> public/ (pretty URLs)
    python3 tools/build.py --preview    # relative links, opens from disk -> preview/

Edit text in content/*.json, then run the build and commit public/.
"""
import json
import shutil
import sys
from datetime import date
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
SRC = ROOT / "src"
PREVIEW = "--preview" in sys.argv
OUT = ROOT / ("preview" if PREVIEW else "public")
TODAY = date.today().isoformat()

SITE = json.loads((CONTENT / "site.json").read_text())
SVC = json.loads((CONTENT / "services.json").read_text())
TEAM = json.loads((CONTENT / "team.json").read_text())
GALLERY = json.loads((CONTENT / "gallery.json").read_text())
HARDWARE = json.loads((CONTENT / "hardware.json").read_text())
SOFTWARE = json.loads((CONTENT / "software.json").read_text())
CATS = {c["id"]: c for c in SVC["categories"]}
SERVICES = SVC["services"]


def _load_legal():
    """content/legal/*.md: a small front-matter block (title, path, description) then simple markdown."""
    order = ["terms", "acceptable-use", "telecom-compliance", "privacy", "data-processing", "refund", "grievance", "disclaimer"]
    pages = []
    for name in order:
        raw = (CONTENT / "legal" / (name + ".md")).read_text()
        _, fm, body = raw.split("---", 2)
        meta = dict(line.split(": ", 1) for line in fm.strip().splitlines())
        pages.append({**meta, "body": body.strip(), "key": name})
    return pages


LEGAL_PAGES = _load_legal()
BASE = SITE["base_url"].rstrip("/")

# Cache-busting version: short hash of the CSS/JS so browsers refetch when they change
import hashlib as _hashlib
_assets_blob = b""
for _f in ["css/site.css", "js/site.js", "js/chat.js", "css/admin.css", "js/admin.js", "js/billing.js", "js/docs.js"]:
    try:
        _assets_blob += (SRC / "assets" / _f).read_bytes()
    except OSError:
        pass
ASSET_VER = _hashlib.sha1(_assets_blob).hexdigest()[:8]


def e(s):
    return escape(str(s), quote=True)


# ---------------------------------------------------------------- icons
def svg(body, sw="2"):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % (sw, body))


ICONS = {
    "ai": svg('<rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9.5 15.5h5M2 12v2M22 12v2"/>'),
    "ivr": svg('<path d="M4 5h6v6H4zM14 5h6v6h-6zM4 15h6v4H4z"/><path d="M17 14v6M14 17h6"/>'),
    "broadcast": svg('<path d="M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M16 8.5a5 5 0 0 1 0 7M19 5.5a9 9 0 0 1 0 13"/>'),
    "cloud": svg('<path d="M17.5 19a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.6 1.5A3.8 3.8 0 0 0 6.5 19z"/><path d="M10 14.5c1.2 1 2.8 1 4 0"/>'),
    "webrtc": svg('<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M10 9l2 2 3-3"/>'),
    "phone": svg('<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>'),
    "whatsapp": svg('<path d="M3 21l1.6-4.6A8.5 8.5 0 1 1 7.6 19.4z"/><path d="M9 9.5c.5 2.5 2.5 4.5 5 5l1.2-1.2-2-1-1 .8c-.8-.4-1.4-1-1.8-1.8l.8-1-1-2z"/>'),
    "sms": svg('<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>'),
    "rcs": svg('<rect x="3" y="4" width="18" height="16" rx="3"/><rect x="6" y="7" width="7" height="5" rx="1"/><path d="M15 8h3M15 11h3M6 15h12"/>'),
    "missed": svg('<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8"/><path d="M15 3l6 6M21 3l-6 6"/>'),
    "crm": svg('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M17 4l1.5 1.5L21 3M16 11h5M16 15h5"/>'),
    "hrms": svg('<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><circle cx="9" cy="14.5" r="1.6"/><path d="M13 14h5M13 17h3"/>'),
    "arrow": svg('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    "chev": svg('<path d="M6 9l6 6 6-6"/>'),
    "mic": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    "download": svg('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>'),
    "palette": svg('<path d="M12 22a10 10 0 1 1 10-10c0 2.8-2.2 4-4 4h-2a2 2 0 0 0-1.5 3.3A2 2 0 0 1 12 22z"/><circle cx="7.5" cy="10.5" r="1.3" fill="currentColor"/><circle cx="12" cy="7" r="1.3" fill="currentColor"/><circle cx="16.5" cy="10.5" r="1.3" fill="currentColor"/>'),
    "shield": svg('<path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>'),
    "lock": svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
    "server": svg('<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6"/>'),
    "managed": svg('<path d="M17.5 19a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.6 1.5A3.8 3.8 0 0 0 6.5 19z"/><path d="M9 14l2 2 4-4"/>'),
    "clock": svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    "lang": svg('<path d="M4 5h9M8.5 3v2M6 5c1 4 3.5 7 7 8M11 5c-1 4-3.5 7-7 9M13 21l4-9 4 9M14.5 18h5"/>'),
    "tools": svg('<path d="M14.7 6.3a4 4 0 0 0-5 5L3 18l3 3 6.7-6.7a4 4 0 0 0 5-5l-2.5 2.5-2.5-.5-.5-2.5z"/>'),
    "check": svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    "mail": svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>'),
    "pin": svg('<path d="M12 22s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>'),
    "photo": svg('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/>', "1.6"),
    "user": svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
    "building": svg('<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/>'),
    "chat": svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>'),
    "linkedin": svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 10v7M8 7v.01M12 17v-4a2 2 0 0 1 4 0v4M12 10v7"/>'),
    "facebook": svg('<path d="M15 3h-2.5A3.5 3.5 0 0 0 9 6.5V10H6v4h3v7h4v-7h3l1-4h-4V7a1 1 0 0 1 1-1h2z"/>'),
    "instagram": svg('<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.5 6.5h.01"/>'),
    "youtube": svg('<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="M10 9l5 3-5 3z" fill="currentColor"/>'),
    "x": svg('<path d="M4 4l16 16M20 4L4 20"/>'),
}
SOCIAL_NAMES = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube", "x": "X"}
ICONS.update({
    "lms": svg('<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5M22 9v6"/>'),
    "ticket": svg('<path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/><path d="M9 9h6M9 12h6M9 15h4"/>'),
    "workstation": svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'),
    "nas": svg('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h6"/><circle cx="12" cy="18.5" r=".6"/>'),
    "ups": svg('<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M13 7l-3 5h4l-3 5"/>'),
    "laptop": svg('<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>'),
    "network": svg('<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="16" width="6" height="5" rx="1"/><rect x="16" y="16" width="6" height="5" rx="1"/><path d="M12 7v4M5 16v-2h14v2M12 11v3"/>'),
    "switch": svg('<rect x="2" y="8" width="20" height="8" rx="2"/><path d="M6 12h.01M9 12h.01M12 12h.01M15 12h.01M18 12h.01"/>'),
    "ont": svg('<rect x="4" y="10" width="16" height="9" rx="2"/><path d="M8 10V6M16 10V6M8 15h.01M12 15h.01"/>'),
    "peripherals": svg('<rect x="2" y="12" width="14" height="8" rx="1.5"/><path d="M5 15h.01M8 15h.01M11 15h.01M5 17.5h6"/><rect x="18" y="10" width="4" height="7" rx="2"/><path d="M20 10V6"/>'),
    "gsm": svg('<rect x="5" y="7" width="14" height="13" rx="2"/><path d="M9 7V3M15 7V4M9 12h6M9 16h3"/>'),
    "pri": svg('<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 17v3M17 17v3M7 12h.01M10 12h.01M13 12h4"/>'),
    "headset": svg('<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="2" y="14" width="4" height="6" rx="1.5"/><rect x="18" y="14" width="4" height="6" rx="1.5"/><path d="M20 20c0 1-2 2-6 2"/>'),
    "dialer": svg('<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3"/><path d="M14 2h.01M18 2h.01M22 2h.01M14 6h.01M18 6h.01M22 6h.01M14 10h.01M18 10h.01M22 10h.01"/>'),
    "web": svg('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 9h20M6 6.5h.01M9 6.5h.01M7 13h6M7 16h10"/>'),
    "megaphone": svg('<path d="M3 11v3a1 1 0 0 0 1 1h2l1 5h2l-1-5h1l9 5V5l-9 5H4a1 1 0 0 0-1 1z"/>'),
    "microsoft": svg('<rect x="3" y="3" width="8" height="8"/><rect x="13" y="3" width="8" height="8"/><rect x="3" y="13" width="8" height="8"/><rect x="13" y="13" width="8" height="8"/>'),
    "database": svg('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
    "ledger": svg('<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5M16 16h.01"/>'),
    "ipphone": svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M6 8h7v4H6zM16 8h2M16 11h2M6 15h.01M9 15h.01M12 15h.01M15 15h.01M18 15h.01"/>'),
    "led": svg('<rect x="2" y="4" width="20" height="13" rx="1.5"/><path d="M5 7h3v3H5zM10 7h3v3h-3zM15 7h4v3h-4zM5 12h14M8 21h8M12 17v4"/>'),
})

RINGS7 = '<div class="spin">' + '<div class="ring"></div>' * 7 + '</div>'
RINGS6 = '<div class="spin">' + '<div class="ring"></div>' * 6 + '</div>'


# ---------------------------------------------------------------- paths
def route(path):
    """path like '' (home), 'services/', 'services/ivr/'. Returns site-relative route."""
    return path


class Ctx:
    def __init__(self, path):
        self.path = path                    # '' or 'about/' etc.
        self.depth = path.count("/")
        self.prefix = "../" * self.depth if PREVIEW else "/"

    def link(self, path):
        if PREVIEW:
            return self.prefix + path + ("index.html" if path == "" or path.endswith("/") else "")
        return "/" + path

    def asset(self, path):
        return self.prefix + "assets/" + path

    def canonical(self):
        return BASE + "/" + self.path


def svc_path(s):
    return "services/%s/" % s["slug"]


PAGES = {
    "home": "", "services": "services/", "about": "about/", "team": "team/", "gallery": "gallery/",
    "contact": "contact/", "privacy": "privacy/", "portal": "portal/",
    "employee": "portal/employee/", "client": "portal/client/", "admin": "portal/admin/", "hardware": "hardware/", "software": "software/", "legal": "legal/",
}


# ---------------------------------------------------------------- shared chrome
def header(c, active):
    def li(key, label):
        cur = ' aria-current="page"' if active == key else ""
        return '<li><a href="%s"%s>%s</a></li>' % (c.link(PAGES[key]), cur, label)

    mega_cols = []
    for cat in SVC["categories"]:
        items = "".join(
            '<li><a href="%s"><span class="ico ic">%s</span>%s</a></li>' % (c.link(svc_path(s)), ICONS[s["icon"]], e(s["name"]))
            for s in SERVICES if s["category"] == cat["id"])
        mega_cols.append("<div><h4>%s</h4><ul>%s</ul></div>" % (e(cat["name"]), items))
    drawer_svc = "".join(
        '<h4>%s</h4>%s' % (e(cat["name"]), "".join('<a href="%s">%s</a>' % (c.link(svc_path(s)), e(s["name"]))
                                                  for s in SERVICES if s["category"] == cat["id"]))
        for cat in SVC["categories"])
    svc_on = " on" if active == "services" else ""
    return f'''<header class="site-header rise">
  <nav class="nav" aria-label="Main">
    <a class="logo" href="{c.link('')}" aria-label="{e(SITE['brand'])} home"><img class="logo-mark" src="{c.asset('img/logo-mark.png')}" width="44" height="40" alt=""><span class="logo-txt"><b>AGILE</b><small>TECH EXPERT</small></span></a>
    <ul class="menu">
      {li('home', 'Home')}
      <li><button type="button" class="dd{svc_on}" aria-expanded="false" aria-controls="mega">Services {ICONS['chev']}</button>
        <div class="mega glass" id="mega" hidden>{''.join(mega_cols)}</div></li>
      {li('hardware', 'Hardware')}
      {li('software', 'Software')}
      {li('about', 'About')}
      {li('team', 'Team')}
      {li('gallery', 'Gallery')}
      {li('contact', 'Contact')}
    </ul>
    <div class="nav-cta">
      <a class="btn btn-g btn-sm" href="{c.link(PAGES['portal'])}">{ICONS['lock']} Login</a>
      <a class="btn btn-p btn-sm" href="{c.link(PAGES['contact'])}" data-chat="lead">Talk to us</a>
      <button class="burger" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="drawer"><span></span></button>
    </div>
  </nav>
  <div class="drawer glass" id="drawer" hidden>
    <a href="{c.link('')}">Home</a><a href="{c.link(PAGES['services'])}">All services</a>{drawer_svc}
    <h4>IT solutions</h4><a href="{c.link(PAGES['hardware'])}">Hardware &amp; rentals</a><a href="{c.link(PAGES['software'])}">Software &amp; licensing</a>
    <h4>Company</h4><a href="{c.link(PAGES['about'])}">About</a><a href="{c.link(PAGES['team'])}">Team</a>
    <a href="{c.link(PAGES['gallery'])}">Gallery</a><a href="{c.link(PAGES['contact'])}">Contact</a>
    <a href="{c.link(PAGES['portal'])}">Login</a>
  </div>
</header>'''


def social_links():
    out = []
    for k, label in SOCIAL_NAMES.items():
        u = SITE["social"].get(k)
        if u:
            out.append('<a href="%s" target="_blank" rel="noopener" aria-label="%s">%s</a>' % (e(u), label, ICONS[k]))
    out.append('<a href="https://wa.me/%s" target="_blank" rel="noopener" aria-label="WhatsApp">%s</a>' % (SITE["whatsapp"], ICONS["whatsapp"]))
    return '<div class="social">%s</div>' % "".join(out)


def footer(c):
    svc_li = "".join('<li><a href="%s">%s</a></li>' % (c.link(svc_path(s)), e(s["name"])) for s in SERVICES[:8])
    phones = "".join('<li><a href="tel:%s">%s</a></li>' % (p.replace(" ", ""), e(p)) for p in SITE["phones"])
    return f'''<footer class="site-footer">
  <div class="f-grid">
    <div>
      <a class="logo" href="{c.link('')}" aria-label="{e(SITE['brand'])} home"><img class="logo-mark" src="{c.asset('img/logo-mark.png')}" width="44" height="40" alt=""><span class="logo-txt"><b>AGILE</b><small>TECH EXPERT</small></span></a>
      <p>{e(SITE['tagline'])}</p>
      {social_links()}
    </div>
    <div><h3>Company</h3><ul>
      <li><a href="{c.link(PAGES['about'])}">About us</a></li>
      <li><a href="{c.link(PAGES['team'])}">Our team</a></li>
      <li><a href="{c.link(PAGES['gallery'])}">Gallery</a></li>
      <li><a href="{c.link(PAGES['hardware'])}">Hardware &amp; rentals</a></li>
      <li><a href="{c.link(PAGES['software'])}">Software &amp; licensing</a></li>
      <li><a href="{c.link(PAGES['services'])}#delivery">On-premise &amp; managed</a></li>
      <li><a href="{c.link(PAGES['contact'])}">Contact</a></li>
      <li><a href="{c.link(PAGES['legal'])}">Legal &amp; compliance</a></li>
      <li><a href="{c.link(PAGES['portal'])}">Employee &amp; client login</a></li>
    </ul></div>
    <div><h3>Services</h3><ul>{svc_li}<li><a href="{c.link(PAGES['services'])}">All services</a></li></ul></div>
    <div><h3>Contact</h3><ul>
      <li><a href="mailto:{e(SITE['email'])}">{e(SITE['email'])}</a></li>
      {phones}
      <li>{e(SITE['address']['display'])}</li>
    </ul></div>
  </div>
  <div class="f-bottom">
    <span>© <span id="year">{date.today().year}</span> {e(SITE['legal_name'].rstrip('.'))}. All rights reserved.{(' · GSTIN ' + e(SITE['gstin'])) if SITE.get('gstin') else ''}</span>
    <span class="f-legal"><a href="{c.link('terms/')}">Terms</a> · <a href="{c.link(PAGES['privacy'])}">Privacy</a> · <a href="{c.link('acceptable-use-policy/')}">Acceptable use</a> · <a href="{c.link('telecom-compliance/')}">Telecom compliance</a> · <a href="{c.link('refund-policy/')}">Refunds</a> · <a href="{c.link('grievance-redressal/')}">Grievance</a> · <a href="{c.link('') if PREVIEW else '/sitemap.xml'}">Sitemap</a></span>
  </div>
</footer>'''


BASE_KEYWORDS = ["Agile Tech Expert", "Agile", "Agile Tech Experts Private Limited", "AI voice calling", "IVR solutions",
                 "voice broadcast", "cloud telephony", "business communication India", "Greater Noida", "Noida"]
PAGE_KEYWORDS = {
    "": ["AI calling company India", "AI voice agent", "voice bot", "IVR service provider", "bulk voice call", "WhatsApp Business API",
         "bulk SMS", "RCS messaging", "on-premise call center software", "WebRTC calling"],
    "services/": ["AI calling", "IVR", "cloud calling", "PBX", "WhatsApp API", "SMS", "RCS", "missed call service", "CRM", "HRMS"],
    "hardware/": ["server", "workstation", "NAS", "online UPS", "IP phone", "GSM gateway", "PRI gateway", "headset", "network switch",
                  "laptop rental", "hardware rental Noida"],
    "software/": ["Microsoft 365", "Windows Server licence", "Oracle", "SQL Server", "Adobe Creative Cloud", "Tally Prime", "Busy accounting"],
    "contact/": ["contact Agile Tech Expert", "IVR company Noida", "AI calling company Greater Noida"],
    "about/": ["about Agile Tech Expert", "telecom technology company", "IT infrastructure company"],
}


def page_keywords(path):
    extra = PAGE_KEYWORDS.get(path)
    if extra is None and path.startswith("services/"):
        slug = path.split("/")[1]
        svc = next((x for x in SERVICES if x["slug"] == slug), None)
        extra = [svc["name"], svc["name"] + " India", svc["name"] + " Noida"] if svc else []
    return ", ".join((extra or []) + BASE_KEYWORDS)


def org_schema():
    same = [u for u in SITE["social"].values() if u]
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": BASE + "/#org",
        "name": SITE["legal_name"],
        "legalName": SITE["legal_name"],
        "alternateName": [SITE["brand"], "Agile", "Agile Tech Experts", "AgileTechExpert", "Agile Tech Experts Private Limited"],
        "url": BASE + "/",
        "logo": {"@type": "ImageObject", "url": BASE + "/assets/img/logo.png", "width": 512, "height": 512},
        "image": BASE + "/assets/img/logo-full.jpg",
        "slogan": "Fast, Reliable, Secure",
        "description": "Agile Tech Expert (Agile) is an Indian IT and telecom-technology company providing AI voice calling, IVR, voice broadcast, cloud and WebRTC calling, business PBX, WhatsApp Business API, SMS, RCS, CRM, HRMS, IT hardware and software licensing, on-premise or fully managed.",
        "areaServed": {"@type": "Country", "name": "India"},
        "knowsAbout": ["AI voice calling", "Voice AI agents", "IVR", "Voice broadcast", "Cloud telephony", "WebRTC calling",
                       "IP PBX", "FreeSWITCH", "Asterisk", "WhatsApp Business API", "Bulk SMS", "RCS messaging",
                       "Missed call service", "CRM", "HRMS", "IT hardware", "Software licensing"],
        "email": SITE["email"],
        "telephone": SITE["phones"][0],
        **({"taxID": SITE["gstin"]} if SITE.get("gstin") else {}),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": SITE["address"]["street"],
            "addressLocality": SITE["address"]["locality"],
            "addressRegion": SITE["address"]["region"],
            "addressCountry": SITE["address"]["country"],
        },
        "contactPoint": [{"@type": "ContactPoint", "telephone": p, "contactType": "sales", "areaServed": "IN",
                          "availableLanguage": ["en", "hi"]} for p in SITE["phones"][:1]],
        **({"sameAs": same} if same else {}),
    }


def layout(c, *, title, description, body, active="", schema=None, noindex=False, inner=True, home=False):
    full_title = title if home else "%s | %s" % (title, SITE["brand"])
    schemas = [org_schema()] if home or not schema else []
    if home:
        schemas.append({"@context": "https://schema.org", "@type": "WebSite", "name": SITE["brand"], "url": BASE + "/",
                        "publisher": {"@id": BASE + "/#org"}})
    schemas += schema or []
    ld = "\n".join('<script type="application/ld+json">%s</script>' % json.dumps(s, ensure_ascii=False) for s in schemas)
    robots = "noindex, nofollow" if noindex else "index, follow, max-image-preview:large"
    verify = ('<meta name="google-site-verification" content="%s">' % e(SITE["google_site_verification"])) if SITE.get("google_site_verification") else ""
    ga = ""
    if SITE.get("ga4_id") and not PREVIEW:
        gid = e(SITE["ga4_id"])
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag('js',new Date());gtag('config','{gid}');</script>")
    preload = ('<link rel="preload" as="image" href="%s" media="(min-width:701px)">'
               '<link rel="preload" as="image" href="%s" media="(max-width:700px)">') % (c.asset("img/bg.webp"), c.asset("img/bg-mobile.webp"))
    return f'''<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{c.canonical()}">
<meta name="theme-color" content="#0b7d76">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(SITE['brand'])}">
<meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{c.canonical()}">
<meta property="og:image" content="{BASE}/assets/img/og.jpg">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Agile Tech Expert logo — Fast, Reliable, Secure">
<meta property="og:locale" content="en_IN">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(full_title)}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{BASE}/assets/img/og.jpg">
{verify}
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="{c.asset('img/favicon-32.png')}" type="image/png" sizes="32x32">
<link rel="icon" href="{c.asset('img/icon-192.png')}" type="image/png" sizes="192x192">
<link rel="apple-touch-icon" href="{c.asset('img/apple-touch-icon.png')}">
<meta name="keywords" content="{e(page_keywords(c.path))}">
<meta name="author" content="{e(SITE['legal_name'])}">
<link rel="manifest" href="{c.prefix}site.webmanifest">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Michroma&family=Outfit:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap">
{preload}
<link rel="stylesheet" href="{c.asset('css/site.css')}?v={ASSET_VER}">
{ld}
{ga}
</head>
<body class="{'inner' if inner else 'home'}">
<a class="skip" href="#main">Skip to content</a>
<div class="scene" aria-hidden="true">
  <div class="bg" style="--d:18"></div>
  <div class="sun" data-depth style="--d:6"></div>
  <div class="dust"></div>
  <div class="comet"></div>
</div>
<div class="page"><div class="wrap">
{header(c, active)}
<main id="main">
{body}
</main>
{footer(c)}
</div></div>
<script>window.ATE_ROOT={json.dumps(c.prefix)};</script>
<script src="{c.asset('js/config.js')}?v={ASSET_VER}"></script>
<script src="{c.asset('js/site.js')}?v={ASSET_VER}" defer></script>
<script src="{c.asset('js/chat.js')}?v={ASSET_VER}" defer></script>
</body>
</html>
'''


def crumbs(c, items):
    lis = []
    for i, (label, path) in enumerate(items):
        if i == len(items) - 1:
            lis.append('<li aria-current="page">%s</li>' % e(label))
        else:
            lis.append('<li><a href="%s">%s</a></li>' % (c.link(path), e(label)))
    return '<nav aria-label="Breadcrumb"><ol class="crumbs">%s</ol></nav>' % "".join(lis)


def crumb_schema(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": label, "item": BASE + "/" + path} for i, (label, path) in enumerate(items)]}


def service_card(c, s, tilt=True):
    return f'''<a class="card{' tcard' if tilt else ''}" href="{c.link(svc_path(s))}">
  <span class="ico">{ICONS[s['icon']]}</span>
  <h3 class="h3">{e(s['name'])}</h3>
  <p>{e(s['short'])}</p>
  <span class="more">Learn more {ICONS['arrow']}</span>
</a>'''


def models_html(c, detailed=False):
    onprem_extra = ('<li>Hardware supply: servers, GSM/PRI gateways, IP phones and headsets</li>'
                    '<li>Two-key licensing: an install key and a go-live key bound to your machine</li>') if detailed else ""
    managed_extra = ('<li>Monitoring, backups and upgrades handled by our engineers</li>'
                     '<li>Start in days; scale channels and users up or down monthly</li>') if detailed else ""
    return f'''<div class="models">
  <article class="model glass tcard">
    <span class="chip tag">{ICONS['server']} On-Premise Setup</span>
    <h3 class="h2" style="font-size:clamp(22px,2.2vw,28px)">Install it in your office or data center</h3>
    <p class="muted" style="margin:0">We set up the platform on your servers, inside your network. Your data and recordings never leave your premises, and you can run it under your own brand.</p>
    <ul class="list">
      <li>Installed and configured by our engineers on site or remotely</li>
      <li>Works with your SIP trunks, PRI lines and GSM gateways</li>
      <li>White-label branding for resellers</li>
      {onprem_extra}
      <li>Training for your team and annual support</li>
    </ul>
  </article>
  <article class="model dark tcard">
    <span class="chip tag">{ICONS['managed']} Managed Service</span>
    <h3 class="h2" style="font-size:clamp(22px,2.2vw,28px)">We host it and run it for you</h3>
    <p style="margin:0">Use the service directly from us. No servers to buy, nothing to install. Your team logs in and starts working.</p>
    <ul class="list">
      <li>Hosted on our cloud with telecom connectivity included</li>
      <li>24/7 monitoring and support</li>
      <li>Client panel with reports, recordings and billing</li>
      {managed_extra}
      <li>Move to on-premise later without changing platforms</li>
    </ul>
  </article>
</div>'''


def cta_band(c, heading="Tell us what you need", text="No price lists or plans to wade through. Ask the assistant, speak to it, or send an inquiry, and an engineer will come back with a setup that fits."):
    return f'''<section class="band glass rise" aria-labelledby="cta-h" style="text-align:center;display:flex;flex-direction:column;align-items:center;gap:16px">
  <span class="eyebrow">Get started</span>
  <h2 class="h2" id="cta-h">{e(heading)}</h2>
  <p class="lead">{e(text)}</p>
  <div class="ctas" style="justify-content:center">
    <button class="btn btn-p" type="button" data-chat="open">{ICONS['chat']} Chat with us</button>
    <button class="btn btn-d" type="button" data-voice>{ICONS['mic']} Talk to the voice assistant</button>
    <a class="btn btn-g" href="{c.link(PAGES['contact'])}">Send an inquiry</a>
  </div>
</section>'''


# ---------------------------------------------------------------- pages
def page_home():
    c = Ctx("")
    cats = []
    for cat in SVC["categories"]:
        cards = "".join(service_card(c, s) for s in SERVICES if s["category"] == cat["id"])
        n = sum(1 for s in SERVICES if s["category"] == cat["id"])
        cols = "g3" if n % 3 == 0 else ("g4" if n % 4 == 0 else "g2")
        cats.append(f'''<div class="cat"><div class="cat-head"><h3 class="h3" style="font-size:20px">{e(cat['name'])}</h3><p>{e(cat['blurb'])}</p></div>
<div class="grid {cols}">{cards}</div></div>''')
    feats = [
        ("phone", "High-CPS Dialer", "Auto dial, higher connect rates, with trunk failover and DID rotation.", svc_path(SERVICES[2])),
        ("palette", "White-Label Branding", "Your brand, your identity, our platform.", PAGES["services"] + "#delivery"),
        ("shield", "Two-Key Licensing", "Install key + go-live key, bound to one machine.", PAGES["services"] + "#delivery"),
        ("download", "4-Step Deployment", "Download, install, activate, brand & bill.", PAGES["services"] + "#how"),
    ]
    feat_html = "".join(f'''<a class="feat tcard" href="{c.link(p)}"><span class="ico">{ICONS[i]}</span><h3 class="h3">{e(t)}</h3><p>{e(d)}</p><span class="go">{ICONS['arrow']}</span></a>''' for i, t, d, p in feats)
    why = [
        ("clock", "24/7 support", "Engineers on call around the clock for production voice and messaging systems."),
        ("tools", "Hardware and software together", "We supply and install servers, gateways and IP phones, so one team owns the whole setup."),
        ("lang", "Multilingual AI", "Voice agents and IVRs in English, Hindi and regional Indian languages."),
        ("shield", "Built for Indian telecom rules", "DLT registration help, DND scrubbing and TRAI calling windows set up from day one."),
    ]
    why_html = "".join(f'<div class="card tcard"><span class="ico">{ICONS[i]}</span><h3 class="h3">{e(t)}</h3><p>{e(d)}</p></div>' for i, t, d in why)
    body = f'''
<section class="hero" aria-labelledby="h1">
  <div class="hero-card tilt rise" style="--dl:.12s">
    <div class="demo">
      <div class="talk">
        <div class="talk-row"><h2>Talk to Agile</h2>
          <button class="mic" type="button" data-voice="hero" aria-label="Talk to the Agile voice assistant">{ICONS['mic']}</button></div>
        <p>Real-time AI voice &bull; talk in any language</p>
        <div class="vrow"><div class="vg" role="group" aria-label="Assistant voice"><button type="button" data-g="female" aria-pressed="true">Female</button><button type="button" data-g="male" aria-pressed="false">Male</button></div></div>
      </div>
      <div class="orb3d" aria-hidden="true"><div class="core"></div>{RINGS7}</div>
      <div class="wave" data-wave="78" aria-hidden="true"></div>
    </div>
    <div class="divider" aria-hidden="true"></div>
    <div class="copy">
      <h1 class="h1" id="h1">Your Own <span class="grad">AI Calling</span>, IVR &amp; Messaging Platform</h1>
      <p>Set it up on your premises or let us run it for you. Voice, WhatsApp, SMS and RCS from one team.</p>
      <div class="ctas">
        <button class="btn btn-p" type="button" data-voice="hero">Try Live Demo {ICONS['arrow']}</button>
        <a class="btn btn-g" href="{c.link(PAGES['services'])}">{ICONS['download']} Explore Services</a>
      </div>
    </div>
  </div>
  <div class="phone" aria-hidden="true"><div class="screen">
    <div class="pl">AGILE<small>TECH EXPERT</small></div>
    <div class="mini-orb">{RINGS6}</div>
    <div class="mini-wave" data-wave="22"></div>
    <div class="ph-rest">
      <h3>Talk to Agile</h3><div class="tag">Real-time AI voice &middot; Indian languages</div>
    </div>
    <div class="ph-live" hidden>
      <p class="ph-msg ph-you"><span class="ph-tag">You</span><b class="ph-txt" id="phoneQ"></b></p>
      <p class="ph-msg ph-ai"><span class="ph-tag">Agile</span><b class="ph-txt" id="phoneA"></b></p>
    </div>
    <button class="mic" type="button" data-voice="hero">{ICONS['mic']}</button>
    <button class="ph-stop" id="phoneStop" type="button" hidden>Stop</button>
    <div class="state" id="phoneState">Tap to talk</div>
  </div></div>
</section>
<section class="features rise" style="--dl:.3s;margin-top:clamp(22px,3.2vw,40px)" aria-label="Platform highlights">{feat_html}</section>

<div class="stack" style="margin-top:clamp(28px,4vw,48px)">
<section class="band glass" aria-labelledby="svc-h">
  <div class="sec-head"><span class="eyebrow">What we do</span><h2 class="h2" id="svc-h">Twelve services, one team behind all of them</h2>
  <p class="lead">From the phone line to the AI agent on it, and the WhatsApp message that follows. Pick what you need today and add the rest when you're ready.</p></div>
  {''.join(cats)}
</section>

<section class="band glass" id="delivery" aria-labelledby="dl-h">
  <div class="sec-head"><span class="eyebrow">Two ways to work with us</span><h2 class="h2" id="dl-h">On your premises, or fully managed by us</h2>
  <p class="lead">Every service is available both ways. Choose by where you want your data to live and how much you want to run yourself.</p></div>
  {models_html(c)}
</section>

<section class="band glass" aria-labelledby="how-h">
  <div class="sec-head"><span class="eyebrow">How it works</span><h2 class="h2" id="how-h">From first call to go-live</h2></div>
  <ol class="steps">
    <li><h3 class="h3">Tell us your need</h3><p>Chat, speak to our assistant or send an inquiry. We ask about volumes, channels and where it should run.</p></li>
    <li><h3 class="h3">Get a setup plan</h3><p>An engineer proposes the setup, hardware if any, and a quote for on-premise or managed.</p></li>
    <li><h3 class="h3">Install and go live</h3><p>We deploy, connect your lines and numbers, brand the panel and train your team.</p></li>
    <li><h3 class="h3">Run and grow</h3><p>24/7 support, reports in your panel, and new channels added as you grow.</p></li>
  </ol>
</section>

<section class="band glass" aria-labelledby="why-h">
  <div class="sec-head"><span class="eyebrow">Why Agile</span><h2 class="h2" id="why-h">An IT team that already knows telecom</h2></div>
  <div class="grid g4">{why_html}</div>
</section>

{cta_band(c)}
</div>'''
    return c, layout(c, title="Agile Tech Expert — AI Calling, IVR, Voice Broadcast & Business Messaging",
                     description="AI voice calling, IVR, voice broadcast, cloud calling, WhatsApp Business API, SMS, RCS, CRM and HRMS. Set up on your premises or fully managed. Greater Noida, India.",
                     body=body, active="home", inner=False, home=True)



def page_hardware():
    c = Ctx(PAGES["hardware"])
    hw = HARDWARE
    cards = "".join(f'''<div class="card"><span class="ico">{ICONS[h['icon']]}</span><h3 class="h3">{e(h['name'])}</h3><p>{e(h['short'])}</p></div>''' for h in hw["items"])
    rentals = "".join(f'''<div class="card"><span class="ico">{ICONS[r['icon']]}</span><h3 class="h3">{e(r['name'])}</h3>
<ul class="list">{"".join("<li>%s</li>" % e(p) for p in r['points'])}</ul></div>''' for r in hw["rentals"])
    promises = "".join("<li>%s</li>" % e(p) for p in hw["promises"])
    items = [("Home", ""), ("Hardware", PAGES["hardware"])]
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Hardware</span><h1 class="h1" id="h1">{e(hw['title'])}</h1>
  <p class="lead">{e(hw['intro'])}</p></div>
  <div class="grid g3" id="products">{cards}</div>
  <ul class="list" style="margin-top:22px">{promises}</ul>
</section>
<section class="band glass" id="rentals" aria-labelledby="rent-h">
  <div class="sec-head"><span class="eyebrow">Rentals</span><h2 class="h2" id="rent-h">Flexible hardware rentals</h2>
  <p class="lead">{e(hw['rentals_intro'])}</p></div>
  <div class="grid g4">{rentals}</div>
</section>
{cta_band(c, "Need hardware for your office or call centre?", "Tell us what you need and how many. We'll share options, pricing and delivery time, including setup by our engineers.")}
</div>'''
    schema = [crumb_schema(items), {
        "@context": "https://schema.org", "@type": "ItemList", "name": "Hardware",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": h["name"]} for i, h in enumerate(hw["items"])]}]
    return c, layout(c, title="Hardware & Rentals — Servers, IP Phones, GSM & PRI Gateways, Headsets",
                     description="Servers, workstations, NAS, online UPS, laptops, networking, switches, ONT, GSM and PRI gateways, headsets and IP phones. Supply, installation, support and rentals from Agile Tech Expert.",
                     body=body, active="hardware", schema=schema)


def page_software():
    c = Ctx(PAGES["software"])
    sw = SOFTWARE
    cards = "".join(f'''<div class="card"><span class="ico">{ICONS[x['icon']]}</span><h3 class="h3">{e(x['name'])}</h3><p>{e(x['short'])}</p></div>''' for x in sw["items"])
    own = "".join(service_card(c, s, tilt=False) for s in SERVICES if s["slug"] in ("agile-dialer", "crm", "hrms", "lms", "ticket-solution", "ai-calling"))
    promises = "".join("<li>%s</li>" % e(p) for p in sw["promises"])
    items = [("Home", ""), ("Software", PAGES["software"])]
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Software</span><h1 class="h1" id="h1">{e(sw['title'])}</h1>
  <p class="lead">{e(sw['intro'])}</p></div>
  <div class="grid g4">{cards}</div>
  <ul class="list" style="margin-top:22px">{promises}</ul>
</section>
<section class="band glass" id="own" aria-labelledby="own-h">
  <div class="sec-head"><span class="eyebrow">Built by Agile</span><h2 class="h2" id="own-h">Our own software platforms</h2>
  <p class="lead">{e(sw['own'])}</p></div>
  <div class="grid g3">{own}</div>
</section>
{cta_band(c, "Need licences or a software setup?", "Tell us which software and how many users. We'll share pricing and handle installation and support.")}
</div>'''
    schema = [crumb_schema(items)]
    return c, layout(c, title="Software & Licensing — Microsoft 365, Oracle & SQL, Adobe, Tally & Busy",
                     description="Genuine software licences with setup and support: Microsoft 365, Azure, Windows Server, Oracle and SQL Server, Adobe Creative Cloud, Tally and Busy, plus Agile's own dialer and business software.",
                     body=body, active="software", schema=schema)


def page_services():
    c = Ctx(PAGES["services"])
    cats = []
    for cat in SVC["categories"]:
        cards = "".join(service_card(c, s) for s in SERVICES if s["category"] == cat["id"])
        n = sum(1 for s in SERVICES if s["category"] == cat["id"])
        cols = "g3" if n % 3 == 0 else ("g4" if n % 4 == 0 else "g2")
        cats.append(f'''<div class="cat" id="{cat['id']}"><div class="cat-head"><h2 class="h3" style="font-size:20px">{e(cat['name'])}</h2><p>{e(cat['blurb'])}</p></div>
<div class="grid {cols}">{cards}</div></div>''')
    items = [("Home", ""), ("Services", PAGES["services"])]
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Services</span><h1 class="h1" id="h1">Voice, AI, messaging and business software</h1>
  <p class="lead">Every service below can be installed on your own servers or used as a managed service from us. Open any service to see what's included.</p></div>
  {''.join(cats)}
</section>
<section class="band glass" id="delivery" aria-labelledby="dl-h">
  <div class="sec-head"><span class="eyebrow">Delivery models</span><h2 class="h2" id="dl-h">On-premise setup or managed service</h2>
  <p class="lead">If you want the system in your office, under your control and brand, we install it there. If you'd rather not run servers, we host and operate it for you.</p></div>
  {models_html(c, detailed=True)}
</section>
<section class="band glass" id="how" aria-labelledby="how-h">
  <div class="sec-head"><span class="eyebrow">On-premise in four steps</span><h2 class="h2" id="how-h">Download, install, activate, brand &amp; bill</h2></div>
  <ol class="steps">
    <li><h3 class="h3">Download</h3><p>We share the installer for your server, or our engineer brings it on site.</p></li>
    <li><h3 class="h3">Install</h3><p>The install key sets up the platform and connects your trunks and gateways.</p></li>
    <li><h3 class="h3">Activate</h3><p>The go-live key binds the licence to your machine and switches on live traffic.</p></li>
    <li><h3 class="h3">Brand &amp; bill</h3><p>Add your logo and domain, create client accounts and bill them monthly.</p></li>
  </ol>
</section>
{cta_band(c, "Not sure which service fits?", "Describe what you want to achieve and we'll suggest the right mix of voice, messaging and software.")}
</div>'''
    schema = [crumb_schema(items), {
        "@context": "https://schema.org", "@type": "ItemList", "name": "Services",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": BASE + "/" + svc_path(s), "name": s["name"]} for i, s in enumerate(SERVICES)]}]
    return c, layout(c, title="Services — AI Calling, IVR, Cloud Calling, WhatsApp, SMS, RCS, CRM, HRMS",
                     description="All Agile Tech Expert services: AI voice calling, IVR, voice broadcast, cloud and WebRTC calling, PBX, WhatsApp Business API, SMS, RCS, missed call, CRM and HRMS.",
                     body=body, active="services", schema=schema)


def page_service(s):
    c = Ctx(svc_path(s))
    cat = CATS[s["category"]]
    items = [("Home", ""), ("Services", PAGES["services"]), (s["name"], svc_path(s))]
    feats = "".join(f'<div class="card tcard"><span class="ico">{ICONS["check"]}</span><h3 class="h3">{e(t)}</h3><p>{e(d)}</p></div>' for t, d in s["features"])
    uses = "".join("<li>%s</li>" % e(u) for u in s["use_cases"])
    faqs = "".join(f'<details><summary>{e(q)}</summary><p>{e(a)}</p></details>' for q, a in s["faqs"])
    related = [x for x in SERVICES if x["category"] == s["category"] and x["slug"] != s["slug"]][:3]
    rel = "".join(service_card(c, x) for x in related)
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="svc-hero">
    <div style="display:flex;flex-direction:column;gap:16px;min-width:0">
      <span class="ico">{ICONS[s['icon']]}</span>
      <span class="eyebrow">{e(cat['name'])}</span>
      <h1 class="h1" id="h1">{e(s['title'])}</h1>
      <p class="lead">{e(s['intro'])}</p>
      <div class="ctas">
        <button class="btn btn-p" type="button" data-chat="lead" data-service="{e(s['name'])}">Book a demo {ICONS['arrow']}</button>
        <button class="btn btn-g" type="button" data-voice>{ICONS['mic']} Ask the voice assistant</button>
      </div>
    </div>
    <aside class="aside" aria-label="At a glance">
      <h2>Available as</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><span class="chip">{ICONS['server']} On-premise</span><span class="chip">{ICONS['managed']} Managed</span></div>
      <h2>Used for</h2>
      <ul class="list">{uses}</ul>
    </aside>
  </div>
</section>
<section class="band glass" aria-labelledby="f-h">
  <div class="sec-head"><span class="eyebrow">What's included</span><h2 class="h2" id="f-h">{e(s['name'])} features</h2></div>
  <div class="grid g3">{feats}</div>
</section>
<section class="band glass" aria-labelledby="dl-h">
  <div class="sec-head"><span class="eyebrow">Your choice</span><h2 class="h2" id="dl-h">Run {e(s['name'])} on your premises or ours</h2></div>
  {models_html(c)}
</section>
<section class="band glass" aria-labelledby="faq-h">
  <div class="sec-head"><span class="eyebrow">FAQ</span><h2 class="h2" id="faq-h">Common questions</h2></div>
  <div class="faq">{faqs}</div>
</section>
{'<section class="band glass" aria-labelledby="rel-h"><div class="sec-head"><span class="eyebrow">Related</span><h2 class="h2" id="rel-h">Works well with</h2></div><div class="grid g3">' + rel + '</div></section>' if rel else ''}
{cta_band(c, "See " + s['name'] + " in action", "Tell us about your volumes and setup, and we'll arrange a live demo on your numbers.")}
</div>'''
    schema = [crumb_schema(items), {
        "@context": "https://schema.org", "@type": "Service", "name": s["name"], "serviceType": s["name"],
        "description": s["description"], "url": BASE + "/" + svc_path(s), "areaServed": {"@type": "Country", "name": "India"},
        "provider": {"@type": "Organization", "name": SITE["legal_name"], "url": BASE + "/"}},
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in s["faqs"]]}]
    return c, layout(c, title=s["title"], description=s["description"], body=body, active="services", schema=schema)


def page_about():
    c = Ctx(PAGES["about"])
    items = [("Home", ""), ("About", PAGES["about"])]
    profile = [
        ("Company", SITE["legal_name"]),
        ("Brand", SITE["brand"]),
        *([("GSTIN", SITE["gstin"])] if SITE.get("gstin") else []),
        ("Headquarters", SITE["address"]["display"]),
        ("What we do", "AI voice calling, IVR, voice broadcast, cloud and WebRTC calling, business PBX, WhatsApp, SMS, RCS, missed call, CRM and HRMS"),
        ("How we deliver", "On-premise setup at the client's office or data center, or as a managed service from us"),
        ("Also supply", "Servers, workstations, GSM and PRI gateways, IP phones, networking and headsets for on-premise setups"),
        ("Support", SITE["hours"]),
        ("Website", SITE["domain"]),
    ]
    rows = "".join(f'<div style="display:grid;grid-template-columns:minmax(120px,200px) 1fr;gap:14px;padding:14px 0;border-top:1px solid rgba(15,42,53,.1)"><b style="font-size:13.5px;color:var(--muted)">{e(k)}</b><span>{e(v)}</span></div>' for k, v in profile)
    values = [
        ("shield", "Reliability first", "Voice systems can't go down at 11 a.m. on a Monday. We build with failover and monitor around the clock."),
        ("user", "One accountable team", "Hardware, software, telecom and support from the same people, so problems don't bounce between vendors."),
        ("building", "Your premises, your data", "When the system lives in your office, your data stays in your network and under your control."),
        ("tools", "Practical engineering", "We deploy what fits your volumes and budget, and explain the trade-offs plainly."),
    ]
    vals = "".join(f'<div class="card tcard"><span class="ico">{ICONS[i]}</span><h3 class="h3">{e(t)}</h3><p>{e(d)}</p></div>' for i, t, d in values)
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">About us</span><h1 class="h1" id="h1">Communication platforms, built by an IT infrastructure team</h1></div>
  <div class="grid g2" style="align-items:start">
    <div style="display:flex;flex-direction:column;gap:14px">
      <p class="lead">{e(SITE['legal_name'])} started as an IT solutions company supplying and supporting servers, networking, telephony hardware and business software for offices across the NCR.</p>
      <p class="lead">Year after year, our customers' most critical system was the one that handled their calls. So we went deeper: dialers, IVRs, gateways and PBXs, and now AI voice agents and business messaging on WhatsApp, SMS and RCS.</p>
      <p class="lead">Today we deliver these platforms two ways: installed on the customer's own premises, or run for them as a managed service. The same engineers handle both.</p>
    </div>
    <div class="aside">
      <h2>Company profile</h2>
      <div>{rows}</div>
    </div>
  </div>
</section>
<section class="band glass" aria-labelledby="v-h">
  <div class="sec-head"><span class="eyebrow">How we work</span><h2 class="h2" id="v-h">What you can expect from us</h2></div>
  <div class="grid g4">{vals}</div>
</section>
<section class="band glass" aria-labelledby="dl-h">
  <div class="sec-head"><span class="eyebrow">In-house &amp; managed</span><h2 class="h2" id="dl-h">At your office, or from ours</h2>
  <p class="lead">Some clients want the system inside their own office. Others want to use it directly from us. We provide both.</p></div>
  {models_html(c)}
</section>
{cta_band(c, "Meet the team", "Talk to the engineers who'll actually set up and support your system.")}
</div>'''
    return c, layout(c, title="About Us & Company Profile", description="About Agile Tech Experts Pvt. Ltd.: an IT infrastructure team delivering AI calling, IVR, cloud telephony and business messaging, on-premise or managed.",
                     body=body, active="about", schema=[crumb_schema(items), org_schema()])


def page_team():
    c = Ctx(PAGES["team"])
    items = [("Home", ""), ("Team", PAGES["team"])]
    cards = []
    for m in TEAM["members"]:
        name = m.get("name", "").strip()
        if m.get("photo"):
            av = '<img class="avatar" src="%s" alt="%s" width="84" height="84" loading="lazy">' % (c.asset("team/" + m["photo"]), e(name))
        else:
            initials = "".join(w[0] for w in name.split()[:2]).upper() if name else ""
            av = '<span class="avatar" aria-hidden="true">%s</span>' % (e(initials) if initials else ICONS["user"])
        nm = '<h2 class="h3">%s</h2>' % e(name) if name else '<h2 class="h3">%s</h2>' % e(m["role"])
        role = '<span class="role">%s</span>' % e(m["role"]) if name else ""
        bio = '<p>%s</p>' % e(m["bio"]) if m.get("bio") else ('<p class="soon">Profile coming soon</p>' if not name else "")
        li = ('<a class="more" href="%s" target="_blank" rel="noopener">%s LinkedIn</a>' % (e(m["linkedin"]), ICONS["linkedin"])) if m.get("linkedin") else ""
        cards.append(f'<article class="card person tcard">{av}{nm}{role}{bio}{li}</article>')
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Our team</span><h1 class="h1" id="h1">The people behind your calls and messages</h1>
  <p class="lead">Engineers, project leads and support staff who design, install and run every system we deliver.</p></div>
  <div class="grid g3">{''.join(cards)}</div>
</section>
{cta_band(c, "Want to work with us?", "Send your profile through the inquiry form and mention the role you're interested in.")}
</div>'''
    return c, layout(c, title="Our Team", description="Meet the Agile Tech Expert team: voice and AI engineers, cloud and DevOps, field installation and customer success.",
                     body=body, active="team", schema=[crumb_schema(items)])


def page_gallery():
    c = Ctx(PAGES["gallery"])
    items = [("Home", ""), ("Gallery", PAGES["gallery"])]
    btns = '<button type="button" data-cat="all" aria-pressed="true">All</button>' + "".join(
        '<button type="button" data-cat="%s" aria-pressed="false">%s</button>' % (e(cat), e(cat)) for cat in GALLERY["categories"])
    shots = []
    for it in GALLERY["items"]:
        if it.get("src"):
            media = '<img src="%s" alt="%s" loading="lazy" width="800" height="600">' % (c.asset("gallery/" + it["src"]), e(it["title"]))
        else:
            media = '<div class="ph">%s</div>' % ICONS["photo"]
        shots.append(f'<figure class="shot" data-cat="{e(it["category"])}">{media}<figcaption>{e(it["title"])}<span>{e(it["category"])}</span></figcaption></figure>')
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Gallery</span><h1 class="h1" id="h1">Installations, server rooms and our team at work</h1></div>
  <div class="filters" role="group" aria-label="Filter photos">{btns}</div>
  <div class="gallery">{''.join(shots)}</div>
</section>
</div>'''
    return c, layout(c, title="Gallery", description="Photos of Agile Tech Expert on-site installations, server rooms, call center setups, team and events.",
                     body=body, active="gallery", schema=[crumb_schema(items)])


def page_contact():
    c = Ctx(PAGES["contact"])
    items = [("Home", ""), ("Contact", PAGES["contact"])]
    opts = "".join("<option>%s</option>" % e(s["name"]) for s in SERVICES)
    phones = " · ".join('<a href="tel:%s">%s</a>' % (p.replace(" ", ""), e(p)) for p in SITE["phones"])
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <div class="sec-head"><span class="eyebrow">Contact</span><h1 class="h1" id="h1">Send us an inquiry</h1>
  <p class="lead">Tell us what you need and how you'd like it delivered. We reply the same working day, usually with a call.</p></div>
  <div class="grid g2" style="align-items:start;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)">
    <form class="form" data-lead novalidate>
      <div class="field"><label for="f-name">Name</label><input id="f-name" name="name" autocomplete="name" required></div>
      <div class="field"><label for="f-phone">Phone / WhatsApp</label><input id="f-phone" name="phone" inputmode="tel" autocomplete="tel" required placeholder="+91"></div>
      <div class="field"><label for="f-email">Email (optional)</label><input id="f-email" name="email" type="email" autocomplete="email"></div>
      <div class="field"><label for="f-company">Company (optional)</label><input id="f-company" name="company" autocomplete="organization"></div>
      <div class="field full"><label for="f-service">Service</label><select id="f-service" name="service"><option value="">Choose a service</option>{opts}<option>Something else</option></select></div>
      <fieldset class="field full" style="border:0;padding:0;margin:0"><legend style="font-size:13px;font-weight:600;color:var(--ink-2);margin-bottom:6px">How do you want it delivered?</legend>
        <div class="radio-row">
          <label><input type="radio" name="mode" value="On-premise setup" id="m1"> On-premise at my office</label>
          <label><input type="radio" name="mode" value="Managed service" id="m2"> Managed by Agile</label>
          <label><input type="radio" name="mode" value="Not sure yet" id="m3" checked> Not sure yet</label>
        </div></fieldset>
      <div class="field full"><label for="f-msg">Your requirement</label><textarea id="f-msg" name="message" placeholder="e.g. 20-seat outbound team, WhatsApp follow-ups, Hindi AI agent for lead qualification"></textarea></div>
      <div style="position:absolute;left:-9999px" aria-hidden="true"><label for="f-web">Website</label><input id="f-web" name="website" tabindex="-1" autocomplete="off"></div>
      <div class="field full"><button class="btn btn-p" type="submit">Send inquiry {ICONS['arrow']}</button></div>
      <p class="status" role="status" hidden></p>
      <p class="muted full" style="grid-column:1/-1;margin:0;font-size:12.5px">By sending this form you agree to be contacted about your inquiry and accept our <a href="{c.link('terms/')}" style="text-decoration:underline">terms</a> and <a href="{c.link(PAGES['privacy'])}" style="text-decoration:underline">privacy policy</a>.</p>
    </form>
    <aside class="aside">
      <h2>Reach us directly</h2>
      <ul class="contact-list">
        <li><span class="ico">{ICONS['phone']}</span><div><b>Phone</b>{phones}</div></li>
        <li><span class="ico">{ICONS['whatsapp']}</span><div><b>WhatsApp</b><a href="https://wa.me/{SITE['whatsapp']}" target="_blank" rel="noopener">+{SITE['whatsapp'][:2]} {SITE['whatsapp'][2:7]} {SITE['whatsapp'][7:]}</a></div></li>
        <li><span class="ico">{ICONS['mail']}</span><div><b>Email</b><a href="mailto:{e(SITE['email'])}">{e(SITE['email'])}</a></div></li>
        <li><span class="ico">{ICONS['pin']}</span><div><b>Office</b>{e(SITE['address']['display'])}<br><a href="{e(SITE['maps_url'])}" target="_blank" rel="noopener" style="text-decoration:underline">Open in Google Maps</a></div></li>
        <li><span class="ico">{ICONS['clock']}</span><div><b>Hours</b>{e(SITE['hours'])}</div></li>
      </ul>
      <button class="btn btn-d" type="button" data-voice>{ICONS['mic']} Prefer to talk? Ask the voice assistant</button>
    </aside>
  </div>
</section>
</div>'''
    schema = [crumb_schema(items), {"@context": "https://schema.org", "@type": "ContactPage", "name": "Contact " + SITE["brand"], "url": BASE + "/" + PAGES["contact"]}]
    return c, layout(c, title="Contact Us", description="Contact Agile Tech Expert for AI calling, IVR, cloud telephony, WhatsApp, SMS and RCS. Phone, WhatsApp, email and office address in Greater Noida West.",
                     body=body, active="contact", schema=schema)


LEGAL = SITE.get("legal", {})


def legal_vars():
    off = LEGAL.get("grievance_officer") or ""
    return {"legal_name": SITE["legal_name"].replace("Pvt. Ltd.", "Private Limited"), "gstin": SITE.get("gstin", ""),
            "registered_address": LEGAL.get("registered_address", SITE["address"]["display"]), "email": SITE["email"],
            "phone": SITE["phones"][0], "site": SITE["domain"], "jurisdiction": LEGAL.get("jurisdiction", "Noida, Uttar Pradesh"),
            "abuse_email": LEGAL.get("abuse_email", SITE["email"]), "grievance_email": LEGAL.get("grievance_email", SITE["email"]),
            "grievance_officer_name": (": " + off) if off else ""}


def md_html(c, text):
    """Tiny markdown: ## headings, - lists, paragraphs, **bold**, [text](/path/) links, {{var}} placeholders."""
    import re as _re
    for k, v in legal_vars().items():
        text = text.replace("{{%s}}" % k, v)

    def inline(t):
        t = e(t)
        t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

        def link(m):
            href = m.group(2)
            if href.startswith("/"):
                href = c.link(href.lstrip("/"))
            return '<a href="%s">%s</a>' % (href, m.group(1))
        return _re.sub(r"\[(.+?)\]\((.+?)\)", link, t)
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para))); para.clear()
        if items:
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in items)); items.clear()
    for line in text.splitlines():
        ln = line.rstrip()
        if not ln.strip():
            flush(); continue
        if ln.startswith("## "):
            flush(); out.append('<h2 id="%s">%s</h2>' % (_re.sub(r"[^a-z0-9]+", "-", ln[3:].lower()).strip("-"), inline(ln[3:]))); continue
        if ln.startswith("- "):
            if para:
                flush()
            items.append(ln[2:]); continue
        if items:
            flush()
        para.append(ln.strip())
    flush()
    return "\n".join(out)


def page_legal_doc(p):
    c = Ctx(p["path"])
    items = [("Home", ""), ("Legal & compliance", PAGES["legal"]), (p["title"], p["path"])]
    others = "".join('<li><a href="%s"%s>%s</a></li>' % (c.link(x["path"]), ' aria-current="page"' if x is p else "", e(x["title"])) for x in LEGAL_PAGES)
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise legal" aria-labelledby="h1">
  {crumbs(c, items)}
  <h1 class="h1" id="h1">{e(p["title"])}</h1>
  <p class="muted">Effective date: {e(LEGAL.get("effective_date", TODAY))} · {e(legal_vars()["legal_name"])}</p>
  <div class="legal-grid"><article class="legal-body">{md_html(c, p["body"])}</article>
  <aside class="legal-nav"><h2>Policies</h2><ul>{others}</ul></aside></div>
</section></div>'''
    return c, layout(c, title=p["title"], description=p["description"], body=body, schema=[crumb_schema(items)])


def page_legal_hub():
    c = Ctx(PAGES["legal"])
    items = [("Home", ""), ("Legal & compliance", PAGES["legal"])]
    v = legal_vars()
    cards = "".join(f'<a class="legal-card glass" href="{c.link(x["path"])}"><h2 class="h3">{e(x["title"])}</h2><p class="muted">{e(x["description"])}</p></a>' for x in LEGAL_PAGES)
    facts = [("Legal name", v["legal_name"]), ("GSTIN", v["gstin"])] + ([("CIN", LEGAL["cin"])] if LEGAL.get("cin") else []) + [
        ("Registered office", v["registered_address"]), ("Grievance contact", v["grievance_email"] + " · " + v["phone"]),
        ("Report spam or misuse", v["abuse_email"])]
    rows = "".join(f'<div class="fact"><b>{e(k)}</b><span>{e(x)}</span></div>' for k, x in facts)
    commits = ["Every client is KYC-verified before any number, trunk, header or account is activated.",
               "Telecom connectivity comes only from licensed telecom carriers; clients register on DLT in their own name.",
               "Promotional calls only from 140-series numbers and service/transactional calls from 160-series numbers, as TRAI requires.",
               "Zero tolerance for spam, CLI spoofing, fraud and impersonation — misuse is suspended immediately and reported.",
               "Records are kept as the law requires, and we cooperate fully with TRAI, DoT, carriers and law-enforcement agencies.",
               "Personal data is handled under the Digital Personal Data Protection Act, 2023."]
    body = f'''<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" aria-labelledby="h1">
  {crumbs(c, items)}
  <h1 class="h1" id="h1">Legal &amp; compliance</h1>
  <p class="lead">Agile Tech Expert provides calling, messaging and IT technology for lawful business use only. These policies explain how we work within TRAI, DoT and Indian law, what we expect from every client, and how to reach us.</p>
  <ul class="legal-commit">{"".join("<li>%s</li>" % e(x) for x in commits)}</ul>
  <div class="legal-cards">{cards}</div>
  <h2 class="h3" style="margin-top:26px">Company details</h2>
  <div class="facts">{rows}</div>
</section></div>'''
    return c, layout(c, title="Legal & Compliance — TRAI, DoT, Privacy & Terms",
                     description="Agile Tech Experts Private Limited policies: terms of service, acceptable use and anti-spam, telecom compliance under TRAI and DoT, privacy under the DPDP Act, refunds and grievance redressal.",
                     body=body, schema=[crumb_schema(items)])


def page_portal():
    c = Ctx(PAGES["portal"])
    body = f'''<div class="portal-wrap"><div class="pick rise">
  <a class="model glass tcard" href="{c.link(PAGES['client'])}">
    <span class="chip tag">{ICONS['building']} Clients</span>
    <h1 class="h2" style="font-size:26px">Client portal</h1>
    <p class="muted" style="margin:0">For customers: campaigns, reports, recordings, numbers and invoices.</p>
    <span class="btn btn-p" style="align-self:flex-start">Client login {ICONS['arrow']}</span>
  </a>
  <a class="model dark tcard" href="{c.link(PAGES['employee'])}">
    <span class="chip tag">{ICONS['lock']} Staff only</span>
    <h2 class="h2" style="font-size:26px">Employee portal</h2>
    <p style="margin:0">For Agile Tech Experts employees: leads, tickets, deployments and HR.</p>
    <span class="btn btn-g" style="align-self:flex-start">Employee login {ICONS['arrow']}</span>
  </a>
</div></div>'''
    return c, layout(c, title="Login", description="Sign in to the Agile Tech Expert client or employee portal.", body=body, noindex=True)


def auth_page(kind):
    staff = kind == "employee"
    c = Ctx(PAGES[kind])
    other = "client" if staff else "employee"
    body = f'''<div class="portal-wrap"><section class="auth {'staff' if staff else 'glass'} rise" aria-labelledby="h1">
  <span class="chip">{ICONS['lock'] if staff else ICONS['building']} {'Employees only' if staff else 'Client portal'}</span>
  <h1 class="h2" id="h1" style="margin-top:14px">{'Employee sign in' if staff else 'Client sign in'}</h1>
  <p class="muted" style="margin:6px 0 0">{'Use your Agile employee ID or work email.' if staff else 'Use the login your account manager shared with you.'}</p>
  <form data-auth="{kind}" novalidate>
    <div class="field"><label for="u">{'Employee ID or work email' if staff else 'Email or client ID'}</label>
      <input id="u" name="username" autocomplete="username" required></div>
    <div class="field"><label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required></div>
    <div class="row"><label><input type="checkbox" name="remember" id="rem"> Keep me signed in</label>
      <span class="muted">{'Forgot password? Ask your admin.' if staff else 'Forgot password? Contact support.'}</span></div>
    <button class="btn {'btn-p' if staff else 'btn-d'}" type="submit">Sign in {ICONS['arrow']}</button>
    <p class="status" role="status" hidden></p>
    <p class="muted" style="font-size:12px;margin:4px 0 0">By signing in you agree to our <a href="{c.link('terms/')}" style="text-decoration:underline">Terms</a>, <a href="{c.link('acceptable-use-policy/')}" style="text-decoration:underline">Acceptable Use Policy</a> and <a href="{c.link('telecom-compliance/')}" style="text-decoration:underline">Telecom Compliance Policy</a>.</p>
  </form>
  <p class="switch">{'Not an employee?' if staff else 'Agile employee?'} <a href="{c.link(PAGES[other])}">{'Client login' if staff else 'Employee login'}</a></p>
</section></div>'''
    title = "Employee Login" if staff else "Client Login"
    return c, layout(c, title=title, description="Sign in to the Agile Tech Expert %s portal." % kind, body=body, noindex=True)


def page_404():
    c = Ctx("404/")
    c.prefix = "/" if not PREVIEW else ""
    body = f'''<div class="portal-wrap"><section class="band glass" style="text-align:center;max-width:620px">
  <span class="eyebrow">404</span><h1 class="h1" style="margin-top:10px">This page doesn't exist</h1>
  <p class="lead" style="margin:14px auto 22px">The link may be old or mistyped. Try the services list or ask the assistant.</p>
  <div class="ctas" style="justify-content:center"><a class="btn btn-p" href="/">Go to home</a><a class="btn btn-g" href="/services/">All services</a></div>
</section></div>'''
    return layout(c, title="Page not found", description="Page not found.", body=body, noindex=True)


# ---------------------------------------------------------------- static files
def write(path, text):
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def config_js():
    pages = {k: (v + ("index.html" if PREVIEW else "")) for k, v in PAGES.items()}
    cfg = {
        "apiBase": SITE["api_base"],
        "assistantEndpoint": "/api/assistant",
        "voiceEndpoint": "/api/voice",
        "voiceDefault": "female",
        "whatsapp": SITE["whatsapp"],
        "phones": SITE["phones"],
        "address": SITE["address"]["display"],
        "mapsUrl": SITE["maps_url"],
        "pages": pages,
        "services": [{"slug": s["slug"], "name": s["name"], "short": s["short"], "category_name": CATS[s["category"]]["name"],
                      "url": svc_path(s) + ("index.html" if PREVIEW else "")} for s in SERVICES],
    }
    return ("/* Generated by tools/build.py - edit content/*.json instead.\n"
            "   Set assistantEndpoint to e.g. \"/api/assistant\" once the AI engine is live. */\n"
            "window.ATE = %s;\n" % json.dumps(cfg, ensure_ascii=False, indent=1))


def make_images():
    """Social share image (1200x630) built from the logo. App icons and favicons are static files in src/assets/img."""
    from PIL import Image, ImageDraw, ImageFont
    img_dir = OUT / "assets/img"
    tw, th = 1200, 630
    og = Image.new("RGB", (tw, th), (16, 22, 26))
    d = ImageDraw.Draw(og)
    for x in range(tw):  # soft teal glow on the left
        t = max(0.0, 1 - abs(x - 300) / 700)
        d.line([(x, 0), (x, th)], fill=(int(16 + 10 * t), int(22 + 40 * t), int(26 + 38 * t)))
    logo = Image.open(SRC / "assets/img/logo-full.jpg").convert("RGB").resize((560, 560), Image.LANCZOS)
    og.paste(logo, (35, 35))

    def font(size, bold=True):
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), size)
        except OSError:
            return ImageFont.load_default()
    d.text((640, 170), "AGILE TECH EXPERT", font=font(34), fill=(127, 240, 226))
    d.text((640, 230), "AI Calling, IVR &", font=font(46), fill=(255, 255, 255))
    d.text((640, 288), "Business Messaging", font=font(46), fill=(255, 255, 255))
    d.text((640, 372), "On your premises or fully managed", font=font(24, False), fill=(185, 214, 210))
    d.text((640, 410), "Fast, Reliable, Secure", font=font(24, False), fill=(185, 214, 210))
    d.text((640, 470), "agiletechexpert.com", font=font(26), fill=(127, 240, 226))
    og.save(img_dir / "og.jpg", "JPEG", quality=84, optimize=True, progressive=True)


FAVICON = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#26e0c8"/><stop offset="1" stop-color="#0b6f6a"/></linearGradient></defs><rect width="64" height="64" rx="14" fill="url(#g)"/><path d="M17 49L32 14l15 35" fill="none" stroke="#fff" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M23.5 37h17" stroke="#fff" stroke-width="5" stroke-linecap="round"/></svg>'''


def page_leads():
    """Old staff URL: now a tab inside the admin portal."""
    c = Ctx("portal/leads/")
    target = c.link(PAGES["admin"]) + "#leads"
    body = ('<div class="stack" style="margin-top:30px"><section class="band glass">'
            '<p class="lead">Leads moved to the <a href="%s" style="text-decoration:underline">staff portal</a>.</p>'
            '</section></div><script>location.replace(%s)</script>') % (target, json.dumps(target))
    return c, layout(c, title="Leads", description="Staff portal.", body=body, noindex=True)


def page_admin():
    c = Ctx(PAGES["admin"])
    body = f'''<link rel="stylesheet" href="{c.asset('css/admin.css')}?v={ASSET_VER}">
<div class="adm" id="adm"><nav class="adm-nav" aria-label="Portal sections"></nav>
<section class="adm-main" tabindex="-1" aria-live="polite"><p class="empty">Loading…</p></section></div>
<div class="cdrawer" id="convDrawer" hidden><div class="cdrawer-in" role="dialog" aria-label="Conversation"></div></div>
<script src="{c.asset('js/billing.js')}?v={ASSET_VER}" defer></script>
<script src="{c.asset('js/docs.js')}?v={ASSET_VER}" defer></script>
<script src="{c.asset('js/admin.js')}?v={ASSET_VER}" defer></script>'''
    return c, layout(c, title="Staff Portal", description="Agile Tech Expert staff and admin portal.", body=body, noindex=True)


def page_client_home():
    c = Ctx("portal/client/home/")
    login = c.link(PAGES["client"])
    head = f'''<link rel="stylesheet" href="{c.asset('css/admin.css')}?v={ASSET_VER}">
<div class="stack" style="margin-top:clamp(20px,3vw,34px)">
<section class="band glass rise" id="area" hidden>
  <div class="sec-head"><span class="eyebrow">Client portal</span><h1 class="h1">Welcome<span id="who"></span></h1>
  <p class="lead">Your invoices and account details. Campaigns, reports and recordings will appear here as your services go live.</p></div>
  <div class="kpis" id="ck"></div>
  <div class="tblw"><table class="tbl" id="ci"></table></div>
  <div class="ctas" style="margin-top:18px">
    <a class="btn btn-p" href="{c.link(PAGES['contact'])}">Contact your manager</a>
    <button class="btn btn-g" id="logout" type="button">Log out</button>
  </div>
</section></div>'''
    script = r'''<script>
(function(){
  var API=(window.ATE&&window.ATE.apiBase)||'/api';
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function inr(n){return '\u20b9'+Number(n||0).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}
  function day(s){var d=new Date(s);return isNaN(d)?'':d.toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}
  Promise.all([fetch(API+'/client/overview',{credentials:'include'}),fetch(API+'/client/billing',{credentials:'include'})]).then(function(rs){
    if(!rs[0].ok||!rs[1].ok)throw 0;return Promise.all([rs[0].json(),rs[1].json()])}).then(function(res){
    var d=res[0],b=res[1];
    document.getElementById('area').hidden=false;
    if(d.client.company){document.getElementById('who').textContent=', '+d.client.company}
    var open=b.invoices.filter(function(x){return x.status!=='paid'}).length;
    document.getElementById('ck').innerHTML='<div class="kpi '+(b.balance>0?'warn':'good')+'"><small>Balance due</small><b>'+inr(b.balance)+'</b><em>'+open+' invoice'+(open===1?'':'s')+' not fully paid</em></div>'+
      '<div class="kpi"><small>Account</small><b style="font-size:17px">'+esc(d.client.username)+'</b><em>'+esc(d.client.contact_name||'')+'</em></div>';
    var P={paid:'good',partial:'warn',unpaid:'warn'};
    var h='<thead><tr><th>Document</th><th>Date</th><th class="num">Amount</th><th>Status</th><th></th></tr></thead><tbody>';
    if(!b.invoices.length&&!b.receipts.length)h+='<tr><td colspan="5" class="empty">No invoices yet.</td></tr>';
    b.invoices.forEach(function(x){h+='<tr><td><b>'+esc(x.number)+'</b><br><span class="muted2">Tax invoice · due '+day(x.due_date)+'</span></td><td>'+day(x.inv_date)+'</td><td class="num"><b>'+inr(x.total)+'</b>'+(x.paid?'<br><span class="muted2">received '+inr(x.paid)+'</span>':'')+'</td><td><span class="pill '+(P[x.status]||'')+'">'+esc(x.status)+'</span></td><td><a class="abtn sm g" target="_blank" rel="noopener" href="'+API+'/client/billing/invoices/'+x.id+'/pdf">PDF</a></td></tr>'});
    b.receipts.forEach(function(x){h+='<tr><td><b>'+esc(x.number)+'</b><br><span class="muted2">Payment receipt · '+esc((x.mode||'').toUpperCase())+'</span></td><td>'+day(x.rcp_date)+'</td><td class="num"><b>'+inr(x.amount)+'</b></td><td><span class="pill good">received</span></td><td><a class="abtn sm g" target="_blank" rel="noopener" href="'+API+'/client/billing/receipts/'+x.id+'/pdf">PDF</a></td></tr>'});
    document.getElementById('ci').innerHTML=h+'</tbody>';
  }).catch(function(){location.replace('LOGIN_URL')});
  var lo=document.getElementById('logout');
  if(lo)lo.addEventListener('click',function(){fetch(API+'/auth/logout',{method:'POST',credentials:'include'}).then(function(){location.replace('LOGIN_URL')},function(){location.replace('LOGIN_URL')})});
})();
</script>'''.replace("LOGIN_URL", login)
    return c, layout(c, title="Client Portal", description="Agile Tech Expert client dashboard.", body=head + script, noindex=True)


def llms_txt():
    """Plain summary for AI assistants and AI search (llmstxt.org format)."""
    out = ["# Agile Tech Expert", "",
           "> Agile Tech Expert (also called Agile; legal name %s, GSTIN %s) is an Indian IT and telecom-technology company "
           "based in Greater Noida / Noida, Uttar Pradesh. It builds and runs AI voice calling, IVR, voice broadcast, cloud and "
           "WebRTC calling, business PBX, WhatsApp Business API, SMS, RCS, missed call, CRM and HRMS solutions, on the client's "
           "premises or as a managed service, and supplies IT hardware, rentals and software licences." % (SITE["legal_name"], SITE.get("gstin", "")),
           "", "Slogan: Fast, Reliable, Secure.",
           "Contact: %s, %s. Website: %s" % (SITE["email"], ", ".join(SITE["phones"]), BASE), "", "## Services", ""]
    out += ["- [%s](%s/%s): %s" % (x["name"], BASE, svc_path(x), x.get("short") or x.get("tagline") or "") for x in SERVICES]
    out += ["", "## Company", "",
            "- [About](%s/about/)" % BASE, "- [Hardware & rentals](%s/hardware/)" % BASE, "- [Software & licensing](%s/software/)" % BASE,
            "- [Contact](%s/contact/)" % BASE, "", "## Policies", ""]
    out += ["- [%s](%s/%s)" % (p["title"], BASE, p["path"]) for p in LEGAL_PAGES]
    return "\n".join(out) + "\n"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(SRC / "assets", OUT / "assets")
    write("assets/js/config.js", config_js())
    shutil.copy(SRC / "assets/img/favicon.ico", OUT / "favicon.ico")
    make_images()

    built = [page_home(), page_services(), page_about(), page_team(), page_gallery(), page_contact(), page_legal_hub(),
             page_portal(), auth_page("employee"), auth_page("client"), page_leads(), page_admin(), page_client_home(), page_hardware(), page_software()]
    built += [page_service(s) for s in SERVICES]
    built += [page_legal_doc(p) for p in LEGAL_PAGES]
    for c, html in built:
        write(c.path + "index.html", html)
    write("404.html", page_404())

    public = ["", PAGES["services"], PAGES["hardware"], PAGES["software"]] + [svc_path(s) for s in SERVICES] + [PAGES[k] for k in ("about", "team", "gallery", "contact", "legal")] + [p["path"] for p in LEGAL_PAGES]
    prio = {"": "1.0", PAGES["services"]: "0.9", PAGES["contact"]: "0.8"}
    urls = "".join("<url><loc>%s/%s</loc><lastmod>%s</lastmod><changefreq>%s</changefreq><priority>%s</priority></url>\n" % (
        BASE, p, TODAY, "weekly" if p in ("", PAGES["services"]) else "monthly",
        prio.get(p, "0.8" if p.startswith("services/") else "0.6")) for p in public)
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
    ai_bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
               "Perplexity-User", "Google-Extended", "Applebot-Extended", "Bingbot", "CCBot"]
    robots = "User-agent: *\nAllow: /\nDisallow: /portal/\nDisallow: /api/\n\n"
    robots += "".join("User-agent: %s\nAllow: /\nDisallow: /portal/\nDisallow: /api/\n\n" % b for b in ai_bots)
    write("robots.txt", robots + "Sitemap: %s/sitemap.xml\n" % BASE)
    write("llms.txt", llms_txt())
    write("site.webmanifest", json.dumps({
        "name": SITE["brand"], "short_name": "Agile", "start_url": "/", "display": "standalone",
        "background_color": "#9fd3e6", "theme_color": "#0b7d76",
        "icons": [{"src": "/assets/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/assets/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/assets/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}, indent=1))
    n = sum(1 for _ in OUT.rglob("index.html"))
    print("Built %d pages into %s" % (n, OUT.relative_to(ROOT)))


if __name__ == "__main__":
    main()
