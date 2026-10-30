"""Techno-commercial proposals: a cover page, any number of editable sections, pricing options with GST,
an acceptance block and a contact page. Everything in a proposal is data (JSON) that staff can edit in the portal.

Section types:
  text      - paragraphs (blank line = new paragraph, **bold**)
  bullets   - one point per line
  numbered  - one point per line, numbered
  pricing   - an option table: rows of description / details / qty / unit / rate / GST %, with a grand total
  table     - any table: columns + rows (cells separated by " | ")
  pagebreak - start the next section on a new page
"""
import io
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import billing as B

HERE = Path(__file__).resolve().parent
FONTS = HERE / "assets" / "fonts"
ROOT = HERE.parent
LOGO_FULL = ROOT / "public" / "assets" / "img" / "logo-full.jpg"
MARK = ROOT / "public" / "assets" / "img" / "logo-mark-print.png"
TEAL, DEEP, INK, MUTED, TINT = "#0b6f6a", "#0d2a30", "#11262b", "#55727a", "#e9f5f3"

_fonts_ready = False


def fonts():
    """Register Poppins (bundled). Falls back to Helvetica if the files are missing."""
    global _fonts_ready
    if _fonts_ready:
        return True
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        for name, f in (("Pop", "Regular"), ("Pop-Md", "Medium"), ("Pop-Bd", "Bold"), ("Pop-It", "Italic"), ("Pop-Lt", "Light")):
            pdfmetrics.registerFont(TTFont(name, str(FONTS / ("Poppins-%s.ttf" % f))))
        addMapping("Pop", 0, 0, "Pop"); addMapping("Pop", 1, 0, "Pop-Bd"); addMapping("Pop", 0, 1, "Pop-It"); addMapping("Pop", 1, 1, "Pop-Bd")
        _fonts_ready = True
    except Exception:
        _fonts_ready = False
    return _fonts_ready


def F(kind="r"):
    ok = fonts()
    if not ok:
        return {"r": "Helvetica", "m": "Helvetica-Bold", "b": "Helvetica-Bold", "i": "Helvetica-Oblique", "l": "Helvetica"}[kind]
    return {"r": "Pop", "m": "Pop-Md", "b": "Pop-Bd", "i": "Pop-It", "l": "Pop-Lt"}[kind]


# ------------------------------------------------------------------ built-in proposal templates (Agile's own wording)
ABOUT = ("Agile Tech Expert (Agile Tech Experts Private Limited) designs, installs and supports business communication systems for "
         "Indian companies: AI voice agents, dialers and call centers, IVR, cloud and WebRTC calling, business PBX, WhatsApp, SMS and RCS. "
         "We deliver on your own servers or as a fully managed service, with a support team based in Noida.")
WHY = ["Your choice of delivery: on-premise in your office or data center, or hosted and managed by us",
       "Open-source Linux stack on the server, so there is no per-server operating-system licence cost",
       "Agents work in a web browser (WebRTC) - no softphone to install, on Windows, Linux or Mac",
       "AI voice agent add-on that talks in Hindi, English and Hinglish and hands over to a live agent",
       "Your data and recordings stay on your servers in the on-premise model",
       "Set up to follow TRAI and DoT rules: DLT, 140-series for promotional and 160-series for service calls",
       "Local engineering and support team in Noida, Monday to Saturday, 10:00 to 19:00",
       "High-availability (primary + standby) option for critical operations"]
DIALER_SCOPE = ["Agent panel with click-to-call, call scripts, dispositions and callbacks",
                "Predictive, progressive and preview dialing modes",
                "Inbound IVR with queues, skill-based routing and business-hours rules",
                "Lead upload (CSV/Excel), list management and DND / duplicate filtering",
                "Supervisor tools: live monitoring, listen, whisper and barge",
                "Call recording with search and download",
                "Real-time wallboard and MIS reports (agent, campaign, disposition, hourly)",
                "CRM integration through REST API and webhooks",
                "Role-based access: admin, supervisor, agent"]
COMMON_TERMS = ["Prices are in Indian Rupees. GST is charged extra at the applicable rate, as shown.",
                "This proposal is valid for {valid_days} days from the date on the cover.",
                "Telecom connectivity (SIP trunk, DID/140/160-series numbers, PRI) is provided by licensed carriers and billed at actuals or as quoted.",
                "Activation is subject to client KYC, a signed Client Compliance Undertaking and DLT registration in the client's name.",
                "Minimum term for rental plans is 6 months; either party may end the service after that with 30 days' written notice.",
                "Services are governed by the Terms of Service, Acceptable Use Policy and Telecom Compliance Policy at agiletechexpert.com/legal/."]
PAYMENT = ["One-time installation and orientation charges: 100% in advance with the purchase order",
           "Rental plans: one month in advance, plus one month's rental as a refundable security deposit",
           "One-time licence: 50% with the purchase order, 50% after installation and user training",
           "Hardware: 100% in advance",
           "Payment by bank transfer or UPI to the account printed on our invoice only"]
CLIENT_REQ = {"columns": ["Item", "Requirement", "Quantity"],
              "rows": [["Agent desktop / laptop", "Dual-core CPU, 4 GB RAM, latest Google Chrome", "One per agent"],
                       ["Headset", "USB, noise-cancelling", "One per agent"],
                       ["Server (on-premise only)", "8-core CPU, 32 GB RAM, 2 x 1 TB SSD (RAID 1), Ubuntu Server LTS", "One (two for HA)"],
                       ["Internet", "Static public IP for remote support; 100 kbps per concurrent call", "One"],
                       ["Telecom line", "SIP trunk / PRI / GSM gateway from a licensed carrier", "As per channels"],
                       ["Power", "Online UPS for server and network devices", "As required"]]}
TIMELINE = {"columns": ["Phase", "Activity", "Time"],
            "rows": [["1. Kick-off", "PO, advance, KYC and requirement sign-off", "Day 0"],
                     ["2. Set-up", "Server set-up, dialer installation, carrier integration", "3 - 5 working days"],
                     ["3. Configuration", "Campaigns, IVR, users, reports, CRM API", "3 - 5 working days"],
                     ["4. Training & go-live", "Admin, supervisor and agent training; live support on day one", "1 - 2 working days"]]}
SUPPORT = ["Support window: Monday to Saturday, 10:00 to 19:00 IST, by phone, WhatsApp, e-mail and remote session",
           "Response within 30 minutes for critical issues during the support window",
           "Software updates and security patches during the rental / AMC period",
           "Monthly uptime target of 99.5% for the dialer application (excludes carrier, internet, power and client hardware)",
           "Named account manager for teams of 50 seats or more",
           "On-site visits outside Delhi NCR are charged at actuals (travel and stay)"]
EXCLUSIONS = ["Server and desktop hardware, operating-system licences for client machines, and network devices unless quoted",
              "Carrier charges: SIP trunk, numbers, call minutes, DLT registration fees",
              "Custom development beyond the agreed scope - quoted separately per man-day",
              "Downtime caused by carrier, internet, power or client-side hardware issues"]
COMPLIANCE = ("Agile sets up every calling system to follow TRAI's Telecom Commercial Communications Customer Preference Regulations and DoT rules. "
              "The client registers as a Principal Entity on DLT in its own name, uses 140-series numbers for promotional calls and 160-series "
              "numbers for service and transactional calls, calls only people who have consented, and remains responsible for its campaigns and content.")


def _row(desc, details, qty, unit, rate=0, gst=18):
    return {"desc": desc, "details": details, "qty": qty, "unit": unit, "rate": rate, "gst": gst}


TEMPLATES = [
    {"key": "dialer", "name": "AI Dialer & Call Center", "title": "Techno-Commercial Proposal", "subject": "AI Dialer & Call Center Solution",
     "blocks": [
         {"type": "text", "title": "About Agile Tech Expert", "body": ABOUT},
         {"type": "bullets", "title": "Why choose Agile", "items": WHY},
         {"type": "bullets", "title": "Solution scope", "items": DIALER_SCOPE},
         {"type": "pagebreak"},
         {"type": "pricing", "title": "Option A - On-premise, monthly rental", "note": "Dialer installed on your server; software on monthly rental.",
          "rows": [_row("Dialer user licence - rental", "Agent login with all standard modules; per user per month", 10, "user"),
                   _row("Installation, configuration & training", "One-time", 1, "job")]},
         {"type": "pricing", "title": "Option B - On-premise, one-time licence", "note": "Perpetual licence with first-year support included.",
          "rows": [_row("Dialer user licence - one-time", "Per user, includes 12 months support and updates", 10, "user"),
                   _row("Installation, configuration & training", "One-time", 1, "job"),
                   _row("Annual maintenance (from year 2)", "Per year, optional", 1, "year")]},
         {"type": "pricing", "title": "Option C - Cloud hosted, fully managed", "note": "We host, run and monitor everything; you only need browsers and headsets.",
          "rows": [_row("Cloud dialer seat", "Primary + standby servers, firewall, monitoring; per user per month", 10, "user"),
                   _row("SIP trunk channels", "From a licensed carrier, per channel per month (call minutes extra)", 5, "channel"),
                   _row("Set-up & onboarding", "One-time", 1, "job")]},
         {"type": "numbered", "title": "Commercial terms", "items": COMMON_TERMS},
         {"type": "bullets", "title": "Payment terms", "items": PAYMENT},
         {"type": "table", "title": "What the client provides", **CLIENT_REQ},
         {"type": "table", "title": "Delivery timeline", **TIMELINE},
         {"type": "bullets", "title": "Support & service levels", "items": SUPPORT},
         {"type": "bullets", "title": "Not included", "items": EXCLUSIONS},
         {"type": "text", "title": "Regulatory compliance", "body": COMPLIANCE}]},
    {"key": "ai-agent", "name": "AI Voice Agent", "title": "Techno-Commercial Proposal", "subject": "AI Voice Agent for Inbound & Outbound Calls",
     "blocks": [
         {"type": "text", "title": "About Agile Tech Expert", "body": ABOUT},
         {"type": "bullets", "title": "What the AI voice agent does", "items": [
             "Answers inbound calls 24 x 7 and places outbound calls from your lead lists",
             "Speaks naturally in Hindi, English and Hinglish, and understands callers who mix languages",
             "Qualifies leads, books appointments, collects feedback and answers FAQs from your knowledge base",
             "Hands the call to a live agent with a short summary when the caller asks or the case needs a human",
             "Saves every conversation as a transcript with outcome, rating and lead details in your CRM",
             "Tells callers they are speaking with an automated assistant, as good practice requires"]},
         {"type": "pricing", "title": "Commercials", "note": "Minutes are billed on actual AI conversation time.",
          "rows": [_row("AI agent set-up", "Script design, knowledge base, voice selection, CRM integration, testing", 1, "job"),
                   _row("AI agent platform", "Hosting, monitoring, reports and support; per month", 1, "month"),
                   _row("AI conversation minutes", "Per minute", 1000, "min")]},
         {"type": "numbered", "title": "Commercial terms", "items": COMMON_TERMS},
         {"type": "bullets", "title": "Payment terms", "items": PAYMENT[:2] + PAYMENT[4:]},
         {"type": "bullets", "title": "Support & service levels", "items": SUPPORT[:4]},
         {"type": "text", "title": "Regulatory compliance", "body": COMPLIANCE}]},
    {"key": "ivr", "name": "IVR & Cloud Telephony", "title": "Techno-Commercial Proposal", "subject": "IVR & Cloud Telephony Solution",
     "blocks": [
         {"type": "text", "title": "About Agile Tech Expert", "body": ABOUT},
         {"type": "bullets", "title": "Solution scope", "items": [
             "Multi-level IVR with keypad and speech input, in any language", "Time-based and skill-based routing to teams or mobiles",
             "Missed-call alerts by SMS / WhatsApp", "Call recording and call detail reports", "Virtual numbers / toll-free from licensed carriers",
             "Web dashboard and REST API"]},
         {"type": "pricing", "title": "Commercials", "note": "",
          "rows": [_row("IVR set-up & call-flow design", "One-time", 1, "job"), _row("IVR platform", "Per month", 1, "month"),
                   _row("Virtual number", "Per number per month", 1, "number")]},
         {"type": "numbered", "title": "Commercial terms", "items": COMMON_TERMS},
         {"type": "bullets", "title": "Support & service levels", "items": SUPPORT[:4]},
         {"type": "text", "title": "Regulatory compliance", "body": COMPLIANCE}]},
    {"key": "blank", "name": "Blank proposal", "title": "Techno-Commercial Proposal", "subject": "",
     "blocks": [{"type": "text", "title": "Introduction", "body": ""},
                {"type": "pricing", "title": "Commercials", "note": "", "rows": [_row("", "", 1, "pcs")]},
                {"type": "numbered", "title": "Terms & conditions", "items": COMMON_TERMS[:2]}]},
]


# ------------------------------------------------------------------ calculations
def price_rows(block):
    out, sub, tax = [], Decimal(0), Decimal(0)
    for r in block.get("rows") or []:
        if not str(r.get("desc") or "").strip():
            continue
        q = Decimal(str(r.get("qty") or 0))
        amt = (q * B.D(r.get("rate") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        g = (amt * Decimal(str(r.get("gst") or 0)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({**r, "amount": amt, "gst_amt": g, "total": amt + g})
        sub, tax = sub + amt, tax + g
    return out, sub, tax, sub + tax


def clean(data):
    """Validate and normalise proposal JSON from the portal."""
    from fastapi import HTTPException
    allowed = {"text", "bullets", "numbered", "pricing", "table", "pagebreak"}
    blocks = []
    for i, b in enumerate((data.get("blocks") or [])[:60], 1):
        t = b.get("type")
        if t not in allowed:
            raise HTTPException(status_code=422, detail="Section %d has an unknown type." % i)
        nb = {"type": t, "title": str(b.get("title") or "")[:160]}
        if t == "text":
            nb["body"] = str(b.get("body") or "")[:8000]
        elif t in ("bullets", "numbered"):
            nb["items"] = [str(x)[:600] for x in (b.get("items") or []) if str(x).strip()][:80]
        elif t == "pricing":
            nb["note"] = str(b.get("note") or "")[:600]
            nb["hide_total"] = bool(b.get("hide_total"))
            rows = []
            for r in (b.get("rows") or [])[:80]:
                try:
                    q, rt, g = float(r.get("qty") or 0), float(r.get("rate") or 0), float(r.get("gst") or 0)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail="Section %d has an invalid number." % i)
                if q < 0 or rt < 0 or not 0 <= g <= 28:
                    raise HTTPException(status_code=422, detail="Section %d: check quantity, rate and GST %%." % i)
                rows.append({"desc": str(r.get("desc") or "")[:200], "details": str(r.get("details") or "")[:600], "qty": q,
                             "unit": str(r.get("unit") or "")[:20], "rate": rt, "gst": g})
            nb["rows"] = rows
        elif t == "table":
            cols = [str(c)[:60] for c in (b.get("columns") or []) if str(c).strip()][:6]
            nb["columns"] = cols or ["Item", "Details"]
            nb["rows"] = [[str(c)[:400] for c in row][:len(nb["columns"])] for row in (b.get("rows") or [])[:80] if any(str(c).strip() for c in row)]
        blocks.append(nb)
    out = {k: str(data.get(k) or "")[:400] for k in ("title", "subject", "client_name", "attention", "client_address", "signatory",
                                                     "designation", "purpose", "template", "intro")}
    out["client_address"] = str(data.get("client_address") or "")[:800]
    out["intro"] = str(data.get("intro") or "")[:3000]
    try:
        out["valid_days"] = max(1, min(365, int(data.get("valid_days") or 30)))
    except (TypeError, ValueError):
        out["valid_days"] = 30
    out["doc_date"] = str(data.get("doc_date") or "")[:10]
    out["party_id"] = data.get("party_id") if isinstance(data.get("party_id"), int) else None
    for k in ("show_gst", "contact_page", "acceptance"):
        out[k] = bool(data.get(k, True))
    out["blocks"] = blocks
    if not out["client_name"].strip():
        raise HTTPException(status_code=422, detail="Enter the client name.")
    return out


# ------------------------------------------------------------------ PDF
def proposal_pdf(S, rec, d):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, ListFlowable, ListItem, NextPageTemplate,
                                    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
    fonts()
    W, H = A4
    teal, deep, ink, muted, tint = (colors.HexColor(x) for x in (TEAL, DEEP, INK, MUTED, TINT))
    st = {
        "body": ParagraphStyle("body", fontName=F("r"), fontSize=9.6, leading=15, textColor=ink),
        "small": ParagraphStyle("small", fontName=F("r"), fontSize=8, leading=11.5, textColor=muted),
        "cell": ParagraphStyle("cell", fontName=F("r"), fontSize=8.6, leading=12, textColor=ink),
        "cellb": ParagraphStyle("cellb", fontName=F("m"), fontSize=8.8, leading=12.5, textColor=ink),
        "cellr": ParagraphStyle("cellr", fontName=F("r"), fontSize=8.6, leading=12, textColor=ink, alignment=TA_RIGHT),
        "cellrb": ParagraphStyle("cellrb", fontName=F("b"), fontSize=9, leading=12.5, textColor=ink, alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName=F("m"), fontSize=8.2, leading=11, textColor=colors.white),
        "thr": ParagraphStyle("thr", fontName=F("m"), fontSize=8.2, leading=11, textColor=colors.white, alignment=TA_RIGHT),
        "h": ParagraphStyle("h", fontName=F("b"), fontSize=14.5, leading=19, textColor=deep),
        "num": ParagraphStyle("num", fontName=F("b"), fontSize=11, leading=14, textColor=teal),
        "note": ParagraphStyle("note", fontName=F("i"), fontSize=8.6, leading=12.5, textColor=muted),
    }
    number, ddate = rec["number"], rec["doc_date"]
    valid = (date.fromisoformat(ddate) + timedelta(days=int(d.get("valid_days") or 30))).isoformat()
    company = S.get("company_name") or ""
    vars_ = {"valid_days": d.get("valid_days") or 30, "client": d.get("client_name") or "", "company": company}

    def fill(t):
        for k, v in vars_.items():
            t = t.replace("{%s}" % k, str(v))
        return t

    def rich(t):
        import re
        x = B._esc(fill(t))
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", x)

    # ---- page furniture
    def cover(c, doc):
        c.saveState()
        c.setFillColor(colors.HexColor("#0c171b")); c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#10272b")); c.circle(W * 0.85, H * 0.88, 120 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#0e2125")); c.circle(W * 0.05, H * 0.12, 90 * mm, stroke=0, fill=1)
        c.setFillColor(teal); c.rect(0, H - 6 * mm, W, 6 * mm, stroke=0, fill=1)
        if LOGO_FULL.exists():
            c.drawImage(str(LOGO_FULL), (W - 92 * mm) / 2, H - 120 * mm, width=92 * mm, height=92 * mm, preserveAspectRatio=True)
        c.setFillColor(colors.HexColor("#7ff0e2")); c.setFont(F("m"), 10.5)
        c.drawCentredString(W / 2, H - 136 * mm, (d.get("title") or "Techno-Commercial Proposal").upper())
        c.setFillColor(colors.white); c.setFont(F("b"), 21)
        subj = fill(d.get("subject") or "")
        lines, cur = [], ""
        for w_ in subj.split():
            t = (cur + " " + w_).strip()
            if c.stringWidth(t, F("b"), 21) > W - 50 * mm:
                lines.append(cur); cur = w_
            else:
                cur = t
        if cur:
            lines.append(cur)
        y = H - 150 * mm
        for ln in lines[:3]:
            c.drawCentredString(W / 2, y, ln); y -= 9.5 * mm
        y -= 6 * mm
        c.setStrokeColor(teal); c.setLineWidth(1.4); c.line(W / 2 - 20 * mm, y, W / 2 + 20 * mm, y)
        y -= 12 * mm
        c.setFillColor(colors.HexColor("#9fc3c0")); c.setFont(F("r"), 9.5); c.drawCentredString(W / 2, y, "PREPARED FOR")
        y -= 7.5 * mm
        c.setFillColor(colors.white); c.setFont(F("m"), 14); c.drawCentredString(W / 2, y, d.get("client_name") or "")
        if d.get("attention"):
            y -= 6.5 * mm
            c.setFont(F("r"), 10); c.setFillColor(colors.HexColor("#cfe6e3")); c.drawCentredString(W / 2, y, "Kind attention: " + d["attention"])
        # meta strip
        y = 48 * mm
        boxes = [("PROPOSAL NO.", number), ("DATE", B.tdate(ddate)), ("VALID TILL", B.tdate(valid))]
        bw = 52 * mm
        x0 = (W - bw * 3 - 8 * mm) / 2
        for i, (k, v) in enumerate(boxes):
            x = x0 + i * (bw + 4 * mm)
            c.setFillColor(colors.HexColor("#132a2f")); c.roundRect(x, y, bw, 16 * mm, 3 * mm, stroke=0, fill=1)
            c.setFillColor(colors.HexColor("#7ff0e2")); c.setFont(F("m"), 7.2); c.drawCentredString(x + bw / 2, y + 10.5 * mm, k)
            c.setFillColor(colors.white); c.setFont(F("m"), 9.6); c.drawCentredString(x + bw / 2, y + 4.5 * mm, v)
        c.setFillColor(colors.HexColor("#9fc3c0")); c.setFont(F("r"), 7.8)
        c.drawCentredString(W / 2, 30 * mm, company + "  |  GSTIN " + (S.get("gstin") or "") + "  |  agiletechexpert.com")
        c.setFont(F("r"), 6.8); c.setFillColor(colors.HexColor("#6f9893"))
        c.drawCentredString(W / 2, 18.5 * mm, "Confidential - prepared for the named client only.")
        c.drawCentredString(W / 2, 14.5 * mm, "No part of this document may be shared or reproduced without the written permission of " + company + ".")
        c.restoreState()

    def page(c, doc):
        c.saveState()
        if MARK.exists():
            c.drawImage(str(MARK), 16 * mm, H - 19 * mm, width=11 * mm, height=10 * mm, mask="auto", preserveAspectRatio=True)
        c.setFillColor(deep); c.setFont(F("b"), 10.5); c.drawString(29 * mm, H - 13.5 * mm, "AGILE TECH EXPERT")
        c.setFillColor(muted); c.setFont(F("r"), 7.4); c.drawString(29 * mm, H - 17.2 * mm, "Fast, Reliable, Secure")
        c.setFont(F("r"), 7.8); c.drawRightString(W - 16 * mm, H - 13.5 * mm, number)
        c.drawRightString(W - 16 * mm, H - 17.2 * mm, (fill(d.get("subject") or "")[:70]))
        c.setStrokeColor(teal); c.setLineWidth(1); c.line(16 * mm, H - 21 * mm, W - 16 * mm, H - 21 * mm)
        c.setFillColor(deep); c.rect(0, 0, W, 12 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#cfe6e3")); c.setFont(F("r"), 7.6)
        c.drawString(16 * mm, 4.8 * mm, "agiletechexpert.com   |   %s   |   %s" % (S.get("phone") or "", S.get("email") or ""))
        c.setFillColor(colors.HexColor("#7ff0e2")); c.setFont(F("m"), 7.6)
        c.drawRightString(W - 16 * mm, 4.8 * mm, "Page %d" % doc.page)
        c.restoreState()

    frame_cover = Frame(0, 0, W, H, id="cover")
    frame_body = Frame(16 * mm, 18 * mm, W - 32 * mm, H - 44 * mm, id="body", leftPadding=0, rightPadding=0)
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, title="%s - %s" % (number, d.get("client_name")), author=company)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame_cover], onPage=cover),
                          PageTemplate(id="body", frames=[frame_body], onPage=page)])
    CW = W - 32 * mm

    def heading(n, title):
        t = Table([[Paragraph("%02d" % n, st["num"]), Paragraph(B._esc(fill(title)), st["h"])]], colWidths=[11 * mm, CW - 11 * mm])
        t.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 2.4, teal), ("LEFTPADDING", (0, 0), (0, 0), 6), ("LEFTPADDING", (1, 0), (1, 0), 2),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return t

    def bullet_list(items, numbered=False):
        if numbered:
            return ListFlowable([ListItem(Paragraph(rich(x), st["body"]), leftIndent=16) for x in items], bulletType="1", leftIndent=16,
                                bulletFontName=F("b"), bulletFontSize=9, bulletColor=teal, spaceBefore=2)
        return ListFlowable([ListItem(Paragraph(rich(x), st["body"]), leftIndent=14) for x in items], bulletType="bullet",
                            start="\u2022", leftIndent=14, bulletFontName=F("b"), bulletFontSize=11, bulletColor=teal, bulletOffsetY=-0.5)

    def pricing(block):
        rows, sub, tax, total = price_rows(block)
        show_gst = d.get("show_gst", True)
        hdr = ["#", "Description", "Qty", "Rate (INR)", "Amount"] + (["GST", "Total (INR)"] if show_gst else [])
        widths = [8, 0, 20, 25, 26] + ([24, 28] if show_gst else [])
        widths[1] = CW / mm - sum(widths)
        data = [[Paragraph(h_, st["thr"] if i >= 2 else st["th"]) for i, h_ in enumerate(hdr)]]
        for i, r in enumerate(rows, 1):
            desc = "<font name='%s'>%s</font>" % (F("m"), B._esc(fill(r["desc"])))
            if r.get("details"):
                desc += "<br/><font size=7.8 color='%s'>%s</font>" % (MUTED, B._br(fill(r["details"])))
            line = [Paragraph(str(i), st["cell"]), Paragraph(desc, st["cell"]),
                    Paragraph("%s %s" % (B.qty_txt(r["qty"]), B._esc(r.get("unit") or "")), st["cellr"]),
                    Paragraph(B.inr(r["rate"]), st["cellr"]), Paragraph(B.inr(r["amount"]), st["cellr"])]
            if show_gst:
                line += [Paragraph("%s<br/><font size=7 color='%s'>@ %s%%</font>" % (B.inr(r["gst_amt"]), MUTED, B.qty_txt(r["gst"])), st["cellr"]),
                         Paragraph(B.inr(r["total"]), st["cellrb"])]
            data.append(line)
        style = [("BACKGROUND", (0, 0), (-1, 0), teal), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#d5e7e4"))]
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6fbfa")))
        if not block.get("hide_total") and rows:
            tot_line = [Paragraph("", st["cell"]), Paragraph("<font name='%s'>Total for this option</font>" % F("b"), st["cell"]), "", "",
                        Paragraph(B.inr(sub), st["cellrb"])]
            if show_gst:
                tot_line += [Paragraph(B.inr(tax), st["cellrb"]), Paragraph("<font color='%s'>%s</font>" % (TEAL, B.inr(total)), ParagraphStyle("gt", parent=st["cellrb"], fontSize=10.5))]
            data.append(tot_line)
            n = len(data) - 1
            style += [("BACKGROUND", (0, n), (-1, n), tint), ("LINEABOVE", (0, n), (-1, n), 1, teal), ("SPAN", (1, n), (3, n))]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle(style))
        out = [t]
        if not block.get("hide_total") and rows:
            out += [Spacer(1, 3), Paragraph("Amount in words: %s" % B.words(total if show_gst else sub), st["small"])]
        return out

    def table(block):
        cols = block.get("columns") or []
        n = len(cols)
        data = [[Paragraph(B._esc(c_), st["th"]) for c_ in cols]] + [[Paragraph(rich(x), st["cellb"] if j == 0 else st["cell"]) for j, x in enumerate(r + [""] * (n - len(r)))] for r in block.get("rows") or []]
        first = min(55, CW / mm / n * 1.1) if n > 1 else CW / mm
        widths = [first] + [(CW / mm - first) / (n - 1)] * (n - 1) if n > 1 else [CW / mm]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), deep), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#d5e7e4"))]
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6fbfa")))
        t.setStyle(TableStyle(style))
        return t

    story = [NextPageTemplate("body"), PageBreak()]
    # opening letter-style block
    intro = d.get("intro") or ("Dear %s,\n\nThank you for the opportunity to propose a solution for %s. This document describes the solution, "
                               "commercial options and terms. We would be glad to walk you through it and adapt it to your needs."
                               % ((d.get("attention") or "Sir / Madam").split(",")[0], (d.get("client_name") or "your organisation").rstrip(".")))
    to = "<font name='%s'>%s</font>" % (F("b"), B._esc(d.get("client_name")))
    if d.get("attention"):
        to += "<br/>Kind attention: %s" % B._esc(d["attention"])
    if d.get("client_address"):
        to += "<br/>" + B._br(d["client_address"])
    meta = "<font color='%s'>Proposal no.</font><br/><font name='%s'>%s</font><br/><font color='%s'>Date</font><br/><font name='%s'>%s</font>" % (
        MUTED, F("m"), B._esc(number), MUTED, F("m"), B.tdate(ddate))
    box = Table([[Paragraph("<font color='%s' size=7.5>PREPARED FOR</font><br/>%s" % (MUTED, to), st["body"]), Paragraph(meta, st["body"])]],
                colWidths=[CW - 50 * mm, 50 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), tint), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                             ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LINEBEFORE", (0, 0), (0, 0), 3, teal)]))
    story += [box, Spacer(1, 10)]
    for para in fill(intro).split("\n\n"):
        story += [Paragraph(rich(para).replace("\n", "<br/>"), st["body"]), Spacer(1, 5)]
    story.append(Spacer(1, 8))
    n = 0
    for b in d.get("blocks") or []:
        t = b["type"]
        if t == "pagebreak":
            story.append(PageBreak()); continue
        n += 1
        head = [heading(n, b.get("title") or ""), Spacer(1, 6)]
        if t == "text":
            body = [Paragraph(rich(p_).replace("\n", "<br/>"), st["body"]) for p_ in (b.get("body") or "").split("\n\n") if p_.strip()]
            parts = []
            for p_ in body:
                parts += [p_, Spacer(1, 5)]
        elif t in ("bullets", "numbered"):
            parts = [bullet_list(b.get("items") or [], t == "numbered")]
        elif t == "pricing":
            parts = ([Paragraph(rich(b["note"]), st["note"]), Spacer(1, 4)] if b.get("note") else []) + pricing(b)
        else:
            parts = [table(b)]
        if t in ("pricing", "table"):
            story += [CondPageBreak(45 * mm), KeepTogether(head + parts), Spacer(1, 14)]   # KeepTogether splits normally if longer than a page
        else:
            story += [CondPageBreak(45 * mm), KeepTogether(head + parts[:1])] + parts[1:] + [Spacer(1, 14)]
    # acceptance
    if d.get("acceptance", True):
        stamp = B._stamp_image(S, 32 * mm, 18 * mm)
        left = [Paragraph("<font name='%s'>For %s</font>" % (F("b"), B._esc(company)), st["body"])]
        left += [stamp] if stamp else [Spacer(1, 18 * mm)]
        if stamp:
            stamp.hAlign = "LEFT"
        left += [Paragraph("Authorised signatory", st["small"])]
        if d.get("signatory"):
            left.append(Paragraph("<font name='%s'>%s</font><br/>%s" % (F("m"), B._esc(d["signatory"]), B._esc(d.get("designation") or "")), st["body"]))
        right = [Paragraph("<font name='%s'>Accepted by %s</font>" % (F("b"), B._esc(d.get("client_name"))), st["body"]), Spacer(1, 18 * mm),
                 Paragraph("Signature &amp; seal", st["small"]), Spacer(1, 4),
                 Paragraph("Name: ______________________<br/>Designation: _________________<br/>Date: ______________________", st["body"])]
        acc = Table([[left, right]], colWidths=[CW / 2 - 3 * mm, CW / 2 - 3 * mm], spaceBefore=4)
        acc.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.6, colors.HexColor("#bcd9d4")), ("BOX", (1, 0), (1, 0), 0.6, colors.HexColor("#bcd9d4")),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        n += 1
        story += [CondPageBreak(70 * mm), KeepTogether([heading(n, "Acceptance"), Spacer(1, 6),
                  Paragraph("To proceed, please sign below or send your purchase order referring to proposal %s." % B._esc(number), st["body"]),
                  Spacer(1, 8), acc])]
    # contact page
    if d.get("contact_page", True):
        addr = B._br(S.get("address"))
        bank = "<br/>".join(B._esc(x) for x in [S.get("bank_name"), ("A/c " + S["bank_account"]) if S.get("bank_account") else "",
                                                  ("IFSC " + S["bank_ifsc"]) if S.get("bank_ifsc") else "", ("UPI " + S["upi"]) if S.get("upi") else ""] if x)
        rows = [("Registered office", addr), ("Phone / WhatsApp", B._esc(S.get("phone"))), ("E-mail", B._esc(S.get("email"))),
                ("Website", "www.agiletechexpert.com"), ("GSTIN / PAN", "%s / %s" % (B._esc(S.get("gstin")), B._esc(S.get("pan")))),
                ("Bank", bank), ("Policies", "agiletechexpert.com/legal/")]
        ct = Table([[Paragraph("<font color='%s'>%s</font>" % (MUTED, k), st["body"]), Paragraph(v, st["body"])] for k, v in rows],
                   colWidths=[42 * mm, CW - 42 * mm])
        ct.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#d5e7e4")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        thanks = ParagraphStyle("ty", parent=st["h"], fontSize=24, leading=30, textColor=deep)
        story += [PageBreak(), Spacer(1, 30 * mm), Paragraph("Thank you", thanks), Spacer(1, 4),
                  Paragraph("We look forward to working with %s. For any question about this proposal, reach us below." % B._esc(d.get("client_name")), st["body"]),
                  Spacer(1, 14), ct]
    doc.build(story)
    return buf.getvalue()


def proposal_totals(d):
    """Sum of all pricing options' first totals is not meaningful; return the first option's total for the register."""
    for b in d.get("blocks") or []:
        if b["type"] == "pricing":
            return float(price_rows(b)[3])
    return None
