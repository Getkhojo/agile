"""Quotations and letters on the company letterhead.

Who can use it: employees with role admin, accounts or staff.
Every quotation, letter and blank-letterhead download is saved as a numbered record (what, for whom, by whom, when),
so the PDF can be produced again later and there is a trail of every letterhead that left the company.
Numbers: QTN/2026-27/0001 (quotations), LTR/2026-27/0001 (letters), LH/2026-27/0001 (blank letterheads).
Company details come from the billing settings (Billing > Company settings).
"""
import io
import json
import re
from contextlib import closing
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import billing as B

ROOT = Path(__file__).resolve().parent.parent
MARK = ROOT / "public" / "assets" / "img" / "logo-mark-print.png"
TEAL = "#0b6f6a"
KINDS = {"quote": "QTN", "letter": "LTR", "blank": "LH"}
CLIENT_SIGNED = {"compliance-undertaking"}   # letters the client signs, not us

# ------------------------------------------------------------------ built-in templates
TELECOM_TERMS = [
    "Prices are in INR and exclusive of GST, which is charged extra as shown.",
    "This quotation is valid for {valid_days} days from the date above.",
    "Payment: 50% advance with the purchase order, balance before go-live, unless agreed otherwise in writing.",
    "Telecom connectivity (SIP/PRI, numbers, DLT, WhatsApp/SMS/RCS charges) is provided by licensed carriers and billed at actuals or as quoted.",
    "Activation is subject to completion of client KYC and a signed Client Compliance Undertaking. Clients must register on DLT in their own name and use 140-series numbers for promotional and 160-series numbers for service/transactional calls as per TRAI.",
    "Services are governed by our Terms of Service, Acceptable Use Policy and Telecom Compliance Policy at agiletechexpert.com/legal/.",
]
GOODS_TERMS = [
    "Prices are in INR and exclusive of GST, which is charged extra as shown.",
    "This quotation is valid for {valid_days} days from the date above, subject to stock availability.",
    "Payment: 100% against delivery unless agreed otherwise in writing.",
    "Delivery: within 7-10 working days of confirmed order and payment terms, subject to availability.",
    "Warranty as per the manufacturer's policy. Goods once sold will not be taken back.",
    "Installation, if required, is quoted separately.",
]
QUOTE_TEMPLATES = [
    {"key": "ai-calling", "name": "AI Voice Calling (setup + monthly)", "subject": "Quotation for AI Voice Calling solution",
     "intro": "Thank you for your interest in Agile Tech Expert. As discussed, please find below our quotation for an AI voice calling solution that answers and places calls in Hindi and English and hands over to your team when needed.",
     "lines": [{"name": "AI voice agent setup", "description": "Script design, knowledge base, voice selection, CRM/lead integration, testing and go-live", "hsn": "998313", "unit": "job", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "AI voice agent - monthly platform", "description": "Platform, monitoring, reports and support (per month)", "hsn": "998313", "unit": "month", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "AI calling minutes", "description": "Billed per minute of AI conversation", "hsn": "998413", "unit": "min", "qty": 1000, "rate": 0, "gst_rate": 18}],
     "terms": TELECOM_TERMS},
    {"key": "ivr", "name": "IVR Solution", "subject": "Quotation for IVR solution",
     "intro": "Thank you for your interest. Please find below our quotation for a multi-level IVR with time-based routing, call recording and reports.",
     "lines": [{"name": "IVR setup and configuration", "description": "Call flow design, prompts recording support, routing rules, testing", "hsn": "998313", "unit": "job", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "IVR platform - monthly", "description": "Hosted IVR platform with recording and reports (per month)", "hsn": "998313", "unit": "month", "qty": 1, "rate": 0, "gst_rate": 18}],
     "terms": TELECOM_TERMS},
    {"key": "call-center", "name": "Cloud Calling / Call Center", "subject": "Quotation for cloud call center solution",
     "intro": "Please find below our quotation for a cloud call center with agent logins, queues, call recording and live dashboards.",
     "lines": [{"name": "Call center setup", "description": "Account setup, number mapping, queues, IVR, CRM integration and training", "hsn": "998313", "unit": "job", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "Agent licence - monthly", "description": "Per agent per month", "hsn": "998313", "unit": "user", "qty": 10, "rate": 0, "gst_rate": 18}],
     "terms": TELECOM_TERMS},
    {"key": "messaging", "name": "Bulk SMS / WhatsApp / RCS", "subject": "Quotation for business messaging",
     "intro": "Please find below our quotation for business messaging. All messages are sent through DLT-registered headers and templates in your company's name.",
     "lines": [{"name": "WhatsApp Business API setup", "description": "Business verification support, templates and chatbot flow", "hsn": "998313", "unit": "job", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "SMS credits", "description": "DLT-compliant transactional / service SMS", "hsn": "998413", "unit": "sms", "qty": 100000, "rate": 0, "gst_rate": 18}],
     "terms": TELECOM_TERMS},
    {"key": "hardware", "name": "Hardware supply", "subject": "Quotation for IT hardware",
     "intro": "Please find below our quotation for the hardware you asked for.",
     "lines": [{"name": "DESKTOP", "description": "Make / model, processor, RAM, storage, OS, warranty", "hsn": "8471", "unit": "pcs", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "MONITOR", "description": "Size, make / model, warranty", "hsn": "8528", "unit": "pcs", "qty": 1, "rate": 0, "gst_rate": 18}],
     "terms": GOODS_TERMS},
    {"key": "software", "name": "Software licences", "subject": "Quotation for software licences",
     "intro": "Please find below our quotation for genuine software licences with setup support.",
     "lines": [{"name": "Microsoft 365 Business Standard", "description": "Per user per year", "hsn": "997331", "unit": "user", "qty": 1, "rate": 0, "gst_rate": 18},
               {"name": "Tally Prime", "description": "Edition, users, TSS period", "hsn": "997331", "unit": "license", "qty": 1, "rate": 0, "gst_rate": 18}],
     "terms": ["Prices are in INR and exclusive of GST, which is charged extra as shown.",
               "This quotation is valid for {valid_days} days from the date above; publisher prices may change.",
               "Payment: 100% advance for licence orders.",
               "Licences are subject to the publisher's licence terms and are non-refundable once issued."]},
    {"key": "blank", "name": "Blank quotation", "subject": "Quotation", "intro": "Please find below our quotation.",
     "lines": [{"name": "", "description": "", "hsn": "", "unit": "pcs", "qty": 1, "rate": 0, "gst_rate": 18}],
     "terms": ["Prices are in INR and exclusive of GST, which is charged extra as shown.",
               "This quotation is valid for {valid_days} days from the date above."]},
]
LETTER_TEMPLATES = [
    {"key": "blank", "name": "Blank letter", "subject": "", "body": ""},
    {"key": "compliance-undertaking", "name": "Client Compliance Undertaking (TRAI / DoT)",
     "subject": "Undertaking for use of calling, SMS and messaging services",
     "body": "We, [Client company name], having our registered office at [Client address], GSTIN [Client GSTIN], represented by our authorised signatory [Name, Designation], hereby confirm and undertake to {company} as follows:\n\n"
             "- We will use the numbers, headers, trunks, accounts and software provided or facilitated by {company} only for the purpose declared by us: [purpose of use].\n"
             "- We are registered / will register as a Principal Entity on the DLT platform in our own name, and will register all headers, templates, consent templates and robo-call declarations as required.\n"
             "- We will make promotional voice calls only from 140-series numbers and service / transactional voice calls only from 160-series or other designated numbers, as directed by TRAI.\n"
             "- We will contact only persons who have given valid consent or with whom we have a permitted relationship, honour DND preferences and opt-out requests, and keep consent records for at least one year.\n"
             "- We will not spoof or mask calling-line identity, impersonate any person or authority, or use the services for fraud, harassment or any unlawful purpose.\n"
             "- We are solely responsible for all content, calls and messages sent through the services assigned to us, including by our employees, agents and customers.\n"
             "- We will indemnify {company} against all complaints, penalties, disconnections, losses and costs arising from our use of the services or breach of this undertaking.\n"
             "- We accept that {company} may suspend or disconnect the services without notice on any complaint, carrier alert or direction from TRAI, DoT or any authority, and may share our KYC and records with them.\n"
             "- We have read and accept the Terms of Service, Acceptable Use Policy and Telecom Compliance Policy published at agiletechexpert.com/legal/.\n\n"
             "For [Client company name]\n\n\n\nAuthorised signatory: [Name]\nDesignation: [Designation]\nDate: [Date]   Place: [Place]\n(Company seal)"},
    {"key": "kyc-request", "name": "KYC documents request", "subject": "Documents required to activate your services",
     "body": "Dear [Name],\n\nThank you for choosing {company}. To activate your services as required by our telecom carriers and TRAI / DoT rules, please share the following documents:\n\n"
             "- Certificate of Incorporation / business registration\n- GST registration certificate\n- PAN of the company\n- ID and address proof of the authorised signatory\n"
             "- Authority letter or board resolution for the authorised signatory\n- Signed Client Compliance Undertaking (format attached)\n- DLT Principal Entity ID, headers and templates (for SMS / commercial calls)\n\n"
             "Services will be activated after the documents are verified. Please write to us if you need any help.\n\nRegards,"},
    {"key": "activation", "name": "Service activation confirmation", "subject": "Activation of [service name]",
     "body": "Dear [Name],\n\nWe are pleased to confirm that [service name] has been activated for [Client company name] with effect from [date].\n\n"
             "Account / reference: [account ID]\nNumbers / headers: [numbers]\n\n"
             "Please use the services only for the purpose declared in your undertaking and as per TRAI / DoT rules. For support, contact us at {phone} or {email}.\n\nRegards,"},
    {"key": "payment-reminder", "name": "Payment reminder", "subject": "Payment reminder for invoice [invoice no.]",
     "body": "Dear [Name],\n\nThis is a gentle reminder that payment of Rs. [amount] against invoice [invoice no.] dated [date] is due on [due date].\n\n"
             "Please make the payment to our account printed on the invoice or by UPI at {upi}. If you have already paid, kindly share the transaction reference so we can update our records.\n\nRegards,"},
    {"key": "authorisation", "name": "Authorisation letter", "subject": "Authorisation letter",
     "body": "To whomsoever it may concern,\n\nThis is to certify that [Name], [Designation], is authorised to [purpose] on behalf of {company}.\n\nThis authorisation is valid from [date] to [date].\n\nRegards,"},
]


class QuoteIn(BaseModel):
    party_id: int | None = None
    to_name: str = Field(min_length=1, max_length=160)
    to_address: str = Field(default="", max_length=600)
    to_gstin: str = Field(default="", max_length=15)
    to_state: str = Field(default="", max_length=60)
    attention: str = Field(default="", max_length=120)
    qt_date: str = ""
    valid_days: int = Field(default=15, ge=1, le=365)
    subject: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=3000)
    terms: str = Field(default="", max_length=5000)
    apply_cgst: bool = False
    apply_sgst: bool = False
    apply_igst: bool = False
    lines: list[dict] = Field(min_length=1, max_length=100)
    purpose: str = Field(default="", max_length=200)
    template: str = Field(default="", max_length=40)
    signatory: str = Field(default="", max_length=120)


class LetterIn(BaseModel):
    to_text: str = Field(default="", max_length=800)
    subject: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=12000)
    letter_date: str = ""
    purpose: str = Field(min_length=3, max_length=200)
    template: str = Field(default="", max_length=40)
    signatory: str = Field(default="", max_length=120)
    designation: str = Field(default="", max_length=120)


class BlankIn(BaseModel):
    purpose: str = Field(min_length=3, max_length=200)
    recipient: str = Field(default="", max_length=160)
    copies: int = Field(default=1, ge=1, le=20)
    fmt: str = Field(default="pdf", max_length=4)


class StatusIn(BaseModel):
    status: str


def init_tables(db):
    with closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS doc_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, number TEXT UNIQUE, fy TEXT, seq INTEGER,
            doc_date TEXT, party_id INTEGER, recipient TEXT, subject TEXT, purpose TEXT, template TEXT,
            data TEXT, total REAL, status TEXT DEFAULT 'draft', invoice_id INTEGER,
            created_by TEXT, created_at TEXT, updated_by TEXT, updated_at TEXT);
        CREATE INDEX IF NOT EXISTS ix_doc_kind ON doc_records(kind, doc_date);
        """)
        conn.commit()


def next_number(conn, kind, fy):
    seq = (conn.execute("SELECT COALESCE(MAX(seq),0) FROM doc_records WHERE kind=? AND fy=?", (kind, fy)).fetchone()[0] or 0) + 1
    return seq, "%s/%s/%04d" % (KINDS[kind], fy, seq)


def fill(text, S, extra=None):
    vals = {"company": S.get("company_name", ""), "phone": S.get("phone", ""), "email": S.get("email", ""),
            "upi": S.get("upi", ""), "gstin": S.get("gstin", "")}
    vals.update(extra or {})
    for k, v in vals.items():
        text = text.replace("{%s}" % k, str(v))
    return text


# ------------------------------------------------------------------ letterhead drawing
def _letterhead(S, ref_line=""):
    """Returns an onPage callback drawing the header (logo, name, contact) and footer (address, GSTIN) on every page."""
    def draw(canvas, doc):
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        w, h = doc.pagesize
        teal = colors.HexColor(TEAL)
        canvas.saveState()
        top = h - 12 * mm
        if MARK.exists():
            canvas.drawImage(str(MARK), 14 * mm, top - 20 * mm, width=22 * mm, height=20 * mm, mask="auto", preserveAspectRatio=True)
        canvas.setFillColor(teal)
        canvas.setFont("Helvetica-Bold", 15.5)
        canvas.drawString(40 * mm, top - 8 * mm, (S.get("company_name") or "").upper())
        canvas.setFillColor(colors.HexColor("#4b6b70"))
        canvas.setFont("Helvetica-Oblique", 8.5)
        canvas.drawString(40 * mm, top - 13 * mm, "Fast, Reliable, Secure  |  AI Calling, IVR, Cloud Telephony, Messaging & IT Solutions")
        canvas.setFont("Helvetica", 8.3)
        canvas.setFillColor(colors.black)
        contact = "  |  ".join(x for x in [S.get("phone"), S.get("email"), "www.agiletechexpert.com"] if x)
        canvas.drawString(40 * mm, top - 18 * mm, contact)
        canvas.setStrokeColor(teal)
        canvas.setLineWidth(1.6)
        canvas.line(14 * mm, top - 23 * mm, w - 14 * mm, top - 23 * mm)
        canvas.setLineWidth(0.4)
        canvas.line(14 * mm, top - 24.2 * mm, w - 14 * mm, top - 24.2 * mm)
        # footer
        canvas.setFillColor(teal)
        canvas.rect(0, 0, w, 15 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 7.6)
        canvas.drawCentredString(w / 2, 9.4 * mm, "Regd. Office: " + ", ".join(x.strip().rstrip(",") for x in (S.get("address") or "").splitlines() if x.strip()))
        canvas.setFont("Helvetica", 7.4)
        ids = "  |  ".join(x for x in ["GSTIN: " + S["gstin"] if S.get("gstin") else "", "CIN: " + S["cin"] if S.get("cin") else "",
                                        "PAN: " + S["pan"] if S.get("pan") else "", "agiletechexpert.com"] if x)
        canvas.drawCentredString(w / 2, 5 * mm, ids)
        if ref_line:
            canvas.setFillColor(colors.HexColor("#8aa3a6"))
            canvas.setFont("Helvetica", 6.3)
            canvas.drawRightString(w - 14 * mm, 16.5 * mm, ref_line)
        if doc.page > 1:
            canvas.setFillColor(colors.HexColor("#4b6b70"))
            canvas.setFont("Helvetica", 7.5)
            canvas.drawRightString(w - 14 * mm, top - 28 * mm, "Page %d" % doc.page)
        canvas.restoreState()
    return draw


def _doc(buf, title):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=44 * mm,
                             bottomMargin=24 * mm, title=title, author="Agile Tech Expert")


def _styles():
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.lib.styles import ParagraphStyle
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=9.6, leading=13.6)
    return {"base": base, "small": ParagraphStyle("s", parent=base, fontSize=8.2, leading=10.6),
            "bold": ParagraphStyle("bd", parent=base, fontName="Helvetica-Bold"),
            "right": ParagraphStyle("r", parent=base, alignment=TA_RIGHT),
            "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=TA_CENTER,
                                    textColor=TEAL, spaceAfter=4),
            "cell": ParagraphStyle("c", parent=base, fontSize=8.4, leading=10.6),
            "cellr": ParagraphStyle("cr", parent=base, fontSize=8.4, leading=10.6, alignment=TA_RIGHT)}


def _rich(text):
    """Escape and apply **bold**; keep line breaks."""
    t = B._esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def _body_flowables(body, st):
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer
    out, para, items = [], [], []

    def flush():
        if para:
            out.append(Paragraph("<br/>".join(_rich(x) for x in para), st["base"])); out.append(Spacer(1, 6)); para.clear()
        if items:
            out.append(ListFlowable([ListItem(Paragraph(_rich(x), st["base"]), leftIndent=12) for x in items],
                                    bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8))
            out.append(Spacer(1, 6)); items.clear()
    for line in (body or "").splitlines():
        if not line.strip():
            flush(); continue
        if line.lstrip().startswith("- "):
            if para:
                flush()
            items.append(line.lstrip()[2:]); continue
        if items:
            flush()
        para.append(line)
    flush()
    return out


def _sign_block(S, st, signatory="", designation=""):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    stamp = B._stamp_image(S, 34 * mm, 20 * mm)
    cell = [Paragraph("For <b>%s</b>" % B._esc(S.get("company_name")), st["base"])]
    if stamp:
        stamp.hAlign = "LEFT"
        cell.append(stamp)
    else:
        cell.append(Spacer(1, 16 * mm))
    cell.append(Paragraph("Authorised Signatory", st["base"]))
    if signatory:
        cell.append(Paragraph("<b>%s</b>%s" % (B._esc(signatory), ("<br/>" + B._esc(designation)) if designation else ""), st["base"]))
    t = Table([[cell]], colWidths=[90 * mm])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    t.hAlign = "LEFT"
    return t


def letter_pdf(S, rec, data):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    st = _styles()
    buf = io.BytesIO()
    doc = _doc(buf, rec["number"])
    head = Table([[Paragraph("Ref. No.: <b>%s</b>" % B._esc(rec["number"]), st["base"]),
                   Paragraph("Date: <b>%s</b>" % B.tdate(rec["doc_date"]), st["right"])]], colWidths=[89 * mm, 89 * mm])
    head.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [head, Spacer(1, 8)]
    if data.get("to_text", "").strip():
        story += [Paragraph("To,<br/>" + "<br/>".join(_rich(x) for x in data["to_text"].splitlines()), st["base"]), Spacer(1, 10)]
    if data.get("subject"):
        story += [Paragraph("<b>Subject: %s</b>" % B._esc(data["subject"]), st["base"]), Spacer(1, 10)]
    story += _body_flowables(data.get("body", ""), st)
    if data.get("template") in CLIENT_SIGNED:
        story += [Spacer(1, 10), Paragraph("<i>Format issued by %s. To be printed on the client's letterhead or signed and stamped by the "
                                            "client's authorised signatory, and returned with KYC documents.</i>" % B._esc(S.get("company_name")), st["small"])]
    else:
        story += [Spacer(1, 10), _sign_block(S, st, data.get("signatory", ""), data.get("designation", ""))]
    deco = _letterhead(S, "%s | generated %s" % (rec["number"], rec["created_at"][:10]))
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


def blank_pdf(S, rec, copies):
    from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    st = _styles()
    buf = io.BytesIO()
    doc = _doc(buf, rec["number"])
    story = []
    for i in range(copies):
        head = Table([[Paragraph("Ref. No.: <b>%s%s</b>" % (B._esc(rec["number"]), ("-%d" % (i + 1)) if copies > 1 else ""), st["base"]),
                       Paragraph("Date: ____________________", st["right"])]], colWidths=[89 * mm, 89 * mm])
        head.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story += [head, Spacer(1, 1)]
        if i < copies - 1:
            story.append(PageBreak())
    deco = _letterhead(S, "%s | issued %s to %s" % (rec["number"], rec["created_at"][:10], rec["created_by"]))
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


def blank_docx(S, rec):
    """Word letterhead (header/footer) for typing letters manually; carries the register number."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor
    d = Document()
    normal = d.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    sec = d.sections[0]
    sec.page_height, sec.page_width = Mm(297), Mm(210)
    sec.left_margin = sec.right_margin = Mm(16)
    sec.top_margin, sec.bottom_margin = Mm(40), Mm(24)
    sec.header_distance, sec.footer_distance = Mm(8), Mm(6)
    teal = RGBColor(0x0B, 0x6F, 0x6A)
    hdr = sec.header
    t = hdr.add_table(rows=1, cols=2, width=Mm(178))
    t.autofit = False
    tblPr = t._tbl.tblPr
    layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
    tblPr.append(layout)
    t.columns[0].width, t.columns[1].width = Mm(26), Mm(152)
    c0, c1 = t.rows[0].cells
    c0.width, c1.width = Mm(26), Mm(152)
    if MARK.exists():
        c0.paragraphs[0].add_run().add_picture(str(MARK), width=Mm(22))
    p = c1.paragraphs[0]
    r = p.add_run((S.get("company_name") or "").upper()); r.bold = True; r.font.size = Pt(14); r.font.color.rgb = teal
    p2 = c1.add_paragraph(); r = p2.add_run("Fast, Reliable, Secure  |  AI Calling, IVR, Cloud Telephony, Messaging & IT Solutions")
    r.italic = True; r.font.size = Pt(8.5)
    p3 = c1.add_paragraph(); r = p3.add_run("  |  ".join(x for x in [S.get("phone"), S.get("email"), "www.agiletechexpert.com"] if x)); r.font.size = Pt(8.5)
    line = hdr.add_paragraph(); r = line.add_run("_" * 98); r.font.color.rgb = teal; r.font.size = Pt(7)
    ftr = sec.footer
    fp = ftr.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Regd. Office: " + ", ".join(x.strip().rstrip(",") for x in (S.get("address") or "").splitlines() if x.strip())); r.bold = True; r.font.size = Pt(7.5); r.font.color.rgb = teal
    fp2 = ftr.add_paragraph(); fp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp2.add_run("  |  ".join(x for x in ["GSTIN: " + S["gstin"] if S.get("gstin") else "", "CIN: " + S["cin"] if S.get("cin") else "",
                                             "PAN: " + S["pan"] if S.get("pan") else "", "agiletechexpert.com"] if x))
    r.font.size = Pt(7.5); r.font.color.rgb = teal
    fp3 = ftr.add_paragraph(); fp3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = fp3.add_run("%s | issued %s to %s" % (rec["number"], rec["created_at"][:10], rec["created_by"])); r.font.size = Pt(6); r.font.color.rgb = RGBColor(0x8A, 0xA3, 0xA6)
    body = d.paragraphs[0] if d.paragraphs else d.add_paragraph()
    body.add_run("Ref. No.: %s\t\t\t\t\t\tDate: ______________" % rec["number"]).font.size = Pt(10)
    d.add_paragraph()
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def quote_pdf(S, rec, data):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, ListFlowable, ListItem, Paragraph, Spacer, Table, TableStyle
    st = _styles()
    K = colors.HexColor("#9fbfbc")
    teal = colors.HexColor(TEAL)
    buf = io.BytesIO()
    doc = _doc(buf, rec["number"])
    story = [Paragraph("QUOTATION", st["title"])]
    valid_till = (date.fromisoformat(rec["doc_date"]) + timedelta(days=int(data.get("valid_days") or 15))).isoformat()
    to = "<b>%s</b>" % B._esc(data.get("to_name"))
    if data.get("attention"):
        to += "<br/>Kind attn: %s" % B._esc(data["attention"])
    if data.get("to_address"):
        to += "<br/>" + B._br(data["to_address"])
    if data.get("to_gstin"):
        to += "<br/>GSTIN: %s" % B._esc(data["to_gstin"])
    if data.get("to_state"):
        to += "<br/>State: %s" % B._esc(data["to_state"])
    meta = ("Quotation No.: <b>%s</b><br/>Date: <b>%s</b><br/>Valid till: <b>%s</b>" % (B._esc(rec["number"]), B.tdate(rec["doc_date"]), B.tdate(valid_till)))
    box = Table([[Paragraph("<font size=7.6 color='#4b6b70'>TO</font><br/>" + to, st["base"]), Paragraph(meta, st["base"])]],
                colWidths=[110 * mm, 68 * mm])
    box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, K), ("LINEAFTER", (0, 0), (0, 0), 0.6, K), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [box, Spacer(1, 8)]
    if data.get("subject"):
        story += [Paragraph("<b>Subject: %s</b>" % B._esc(data["subject"]), st["base"]), Spacer(1, 5)]
    if data.get("intro"):
        story += _body_flowables(data["intro"], st)
    lines, sub, cg, sg, ig = B.compute_lines(data["lines"], data.get("apply_cgst"), data.get("apply_sgst"), data.get("apply_igst"))
    has_disc = any(float(l.get("discount_pct") or 0) for l in lines)
    cols = ["#", "Description", "HSN/SAC", "Qty", "Rate", "GST"] + (["Disc."] if has_disc else []) + ["Amount"]
    widths = [8, 0, 18, 20, 23, 12] + ([12] if has_disc else []) + [27]
    widths[1] = 178 - sum(widths)
    rows = [[Paragraph("<b>%s</b>" % c, st["cell"] if i < 2 else st["cellr"]) for i, c in enumerate(cols)]]
    for i, ln in enumerate(lines, 1):
        d = "<b>%s</b>" % B._esc(ln.get("name"))
        if (ln.get("description") or "").strip():
            d += "<br/><font size=7.6 color='#3b5a5f'>%s</font>" % B._br(ln["description"])
        r = [Paragraph(str(i), st["cell"]), Paragraph(d, st["cell"]), Paragraph(B._esc(ln.get("hsn")), st["cell"]),
             Paragraph("%s %s" % (B.qty_txt(ln["qty"]), B._esc((ln.get("unit") or "").upper())), st["cellr"]),
             Paragraph(B.inr(ln["rate"]), st["cellr"]), Paragraph("%s%%" % B.qty_txt(ln.get("gst_rate") or 0), st["cellr"])]
        if has_disc:
            r.append(Paragraph(("%s%%" % B.qty_txt(ln["discount_pct"])) if float(ln.get("discount_pct") or 0) else "", st["cellr"]))
        r.append(Paragraph(B.inr(ln["taxable"]), st["cellr"]))
        rows.append(r)
    it = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    it.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f3f1")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, teal),
                            ("LINEBELOW", (0, 1), (-1, -1), 0.3, K), ("BOX", (0, 0), (-1, -1), 0.6, K), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    story += [Spacer(1, 4), it]
    gross = sub + cg + sg + ig
    rnd = (gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - gross) if S.get("round_off", "1") == "1" else B.D(0)
    total = gross + rnd
    tot = [["Taxable value", B.inr(sub)]]
    gst_rates = sorted({float(l.get("gst_rate") or 0) for l in lines})
    rate_txt = ("@ %s%%" % B.qty_txt(gst_rates[0])) if len(gst_rates) == 1 else ""
    half_txt = ("@ %s%%" % B.qty_txt(gst_rates[0] / 2)) if len(gst_rates) == 1 else ""
    if data.get("apply_cgst"):
        tot.append(["CGST " + half_txt, B.inr(cg)])
    if data.get("apply_sgst"):
        tot.append(["SGST " + half_txt, B.inr(sg)])
    if data.get("apply_igst"):
        tot.append(["IGST " + rate_txt, B.inr(ig)])
    if rnd:
        tot.append(["Round off", B.inr(rnd)])
    tot.append(["Grand total (INR)", B.inr(total)])
    tt = Table([[Paragraph(a, st["cell"]), Paragraph(b, st["cellr"])] for a, b in tot[:-1]] +
               [[Paragraph("<b>%s</b>" % tot[-1][0], st["base"]), Paragraph("<b>%s</b>" % tot[-1][1], st["right"])]], colWidths=[45 * mm, 33 * mm])
    tt.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 1, teal), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    tt.hAlign = "RIGHT"
    story += [Spacer(1, 4), tt, Spacer(1, 3), Paragraph("<b>Amount in words:</b> %s" % B.words(total), st["small"]), Spacer(1, 8)]
    terms = [fill(x, S, {"valid_days": data.get("valid_days") or 15}) for x in (data.get("terms") or "").splitlines() if x.strip()]
    if terms:
        tl = ListFlowable([ListItem(Paragraph(B._esc(x), st["small"]), leftIndent=14) for x in terms], bulletType="1", leftIndent=14, bulletFontSize=8)
        story += [KeepTogether([Paragraph("<b>Terms &amp; conditions</b>", st["base"]), Spacer(1, 3), tl])]
    bank = [x for x in [("Bank", S.get("bank_name")), ("A/c No.", S.get("bank_account")), ("IFSC", S.get("bank_ifsc")),
                        ("Branch", S.get("bank_branch")), ("UPI", S.get("upi"))] if x[1]]
    if bank:
        story += [Spacer(1, 8), Paragraph("<b>Bank details:</b> " + " &nbsp;|&nbsp; ".join("%s: %s" % (a, B._esc(b)) for a, b in bank), st["small"])]
    story += [Spacer(1, 12), KeepTogether([_sign_block(S, st, data.get("signatory", ""))])]
    deco = _letterhead(S, "%s | generated %s" % (rec["number"], rec["created_at"][:10]))
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue(), float(total)


# ------------------------------------------------------------------ API
def register(app, db, get_session, audit):
    init_tables(db)

    def staff(request: Request):
        s = get_session(request.cookies.get("ate_emp"))
        if not s or s["user_type"] != "employee":
            raise HTTPException(status_code=401, detail="Please sign in.")
        with closing(db()) as conn:
            u = conn.execute("SELECT id, username, name, role, active FROM employees WHERE id=?", (s["user_id"],)).fetchone()
        if not u or not u["active"]:
            raise HTTPException(status_code=401, detail="Please sign in.")
        return dict(u)

    def day(s):
        if not s:
            return B.today_ist().isoformat()
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except Exception:
            raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD.")

    def clean_lines(lines):
        out = []
        for n, l in enumerate(lines, 1):
            name = str(l.get("name") or "").strip()[:200]
            if not name:
                raise HTTPException(status_code=422, detail="Line %d needs a name." % n)
            try:
                qty, rate = float(l.get("qty") or 0), float(l.get("rate") or 0)
                gst, disc = float(l.get("gst_rate") or 0), float(l.get("discount_pct") or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Line %d has an invalid number." % n)
            if qty <= 0 or rate < 0 or not 0 <= gst <= 28 or not 0 <= disc <= 100:
                raise HTTPException(status_code=422, detail="Line %d: check quantity, rate, GST % and discount." % n)
            out.append({"item_id": l.get("item_id"), "name": name, "description": str(l.get("description") or "")[:600],
                        "hsn": str(l.get("hsn") or "")[:10], "unit": str(l.get("unit") or "pcs")[:20], "qty": qty, "rate": rate,
                        "gst_rate": gst, "discount_pct": disc})
        return out

    @app.get("/api/docs/meta")
    def docs_meta(request: Request):
        staff(request)
        with closing(db()) as conn:
            S = B.settings(conn)
            parties = [dict(r) for r in conn.execute("SELECT id, code, name, gstin, state, state_code, address FROM bill_parties WHERE active=1 ORDER BY name")]
            items = [dict(r) for r in conn.execute("SELECT id, code, name, description, hsn, unit, price, gst_rate FROM bill_items WHERE active=1 ORDER BY code")]
        return {"quote_templates": QUOTE_TEMPLATES, "letter_templates": [{**t, "body": fill(t["body"], S), "subject": t["subject"]} for t in LETTER_TEMPLATES],
                "parties": parties, "items": items, "states": B.STATES, "company_state_code": S.get("state_code"), "company_state": S.get("state"),
                "today": B.today_ist().isoformat(), "round_off": S.get("round_off", "1")}

    @app.get("/api/docs")
    def list_docs(request: Request, kind: str = "", q: str = ""):
        staff(request)
        where, args = ["1=1"], []
        if kind in KINDS:
            where.append("kind=?"); args.append(kind)
        if q.strip():
            where.append("(number LIKE ? OR recipient LIKE ? OR subject LIKE ? OR purpose LIKE ?)"); args += ["%" + q.strip() + "%"] * 4
        with closing(db()) as conn:
            rows = conn.execute("SELECT id, kind, number, doc_date, recipient, subject, purpose, total, status, invoice_id, created_by, created_at, "
                                "updated_at FROM doc_records WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 500", args).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/docs/{rid}")
    def get_doc(rid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            r = conn.execute("SELECT * FROM doc_records WHERE id=?", (rid,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Not found.")
        d = dict(r)
        d["data"] = json.loads(d["data"] or "{}")
        return d

    def save(conn, kind, u, recipient, subject, purpose, template, data, doc_date, party_id=None, total=None, rid=None):
        if rid:
            conn.execute("UPDATE doc_records SET doc_date=?, party_id=?, recipient=?, subject=?, purpose=?, template=?, data=?, total=?, "
                         "updated_by=?, updated_at=? WHERE id=?", (doc_date, party_id, recipient, subject, purpose, template, json.dumps(data),
                                                                   total, u["username"], B.now_iso(), rid))
            return rid, conn.execute("SELECT number FROM doc_records WHERE id=?", (rid,)).fetchone()[0]
        fy = B.fy_of(doc_date)
        seq, number = next_number(conn, kind, fy)
        cur = conn.execute("INSERT INTO doc_records (kind, number, fy, seq, doc_date, party_id, recipient, subject, purpose, template, data, total, "
                           "status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (kind, number, fy, seq, doc_date, party_id, recipient, subject, purpose, template, json.dumps(data), total,
                            "issued" if kind != "quote" else "draft", u["username"], B.now_iso()))
        return cur.lastrowid, number

    def quote_data(body):
        d = body.model_dump()
        d["lines"] = clean_lines(body.lines)
        d["to_gstin"] = d["to_gstin"].strip().upper()
        if not (body.apply_cgst or body.apply_sgst or body.apply_igst) and any(l["gst_rate"] > 0 for l in d["lines"]):
            raise HTTPException(status_code=422, detail="Tick CGST + SGST or IGST (or set GST % to 0).")
        return d

    @app.post("/api/docs/quotes/preview")
    def preview_quote(body: QuoteIn, request: Request):
        u = staff(request)
        d = quote_data(body)
        with closing(db()) as conn:
            S = B.settings(conn)
            _, number = next_number(conn, "quote", B.fy_of(day(body.qt_date)))
        rec = {"number": number + " (PREVIEW)", "doc_date": day(body.qt_date), "created_at": B.now_iso()}
        pdf, _ = quote_pdf(S, rec, d)
        return B._pdf_response(pdf, "quotation-preview")

    @app.post("/api/docs/quotes")
    def create_quote(body: QuoteIn, request: Request, rid: int = 0):
        u = staff(request)
        d = quote_data(body)
        editing = bool(rid)
        with closing(db()) as conn:
            S = B.settings(conn)
            rec = {"number": "x", "doc_date": day(body.qt_date), "created_at": B.now_iso()}
            _, total = quote_pdf(S, rec, d)
            if rid:
                old = conn.execute("SELECT kind, status FROM doc_records WHERE id=?", (rid,)).fetchone()
                if not old or old["kind"] != "quote":
                    raise HTTPException(status_code=404, detail="Quotation not found.")
            rid, number = save(conn, "quote", u, body.to_name, body.subject, body.purpose, body.template, d, day(body.qt_date),
                               body.party_id, total, rid or None)
            conn.commit()
        audit(u["username"], "docs.quote.%s" % ("edit" if editing else "create"), "%s %s %s" % (number, body.to_name, total))
        return {"ok": True, "id": rid, "number": number, "total": total}

    @app.post("/api/docs/{rid}/status")
    def set_status(rid: int, body: StatusIn, request: Request):
        u = staff(request)
        if body.status not in ("draft", "sent", "accepted", "rejected", "converted"):
            raise HTTPException(status_code=422, detail="Unknown status.")
        with closing(db()) as conn:
            cur = conn.execute("UPDATE doc_records SET status=?, updated_by=?, updated_at=? WHERE id=? AND kind='quote'",
                               (body.status, u["username"], B.now_iso(), rid))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Quotation not found.")
        audit(u["username"], "docs.quote.status", "%d %s" % (rid, body.status))
        return {"ok": True}

    @app.post("/api/docs/letters/preview")
    def preview_letter(body: LetterIn, request: Request):
        staff(request)
        with closing(db()) as conn:
            S = B.settings(conn)
            _, number = next_number(conn, "letter", B.fy_of(day(body.letter_date)))
        rec = {"number": number + " (PREVIEW)", "doc_date": day(body.letter_date), "created_at": B.now_iso()}
        return B._pdf_response(letter_pdf(S, rec, body.model_dump()), "letter-preview")

    @app.post("/api/docs/letters")
    def create_letter(body: LetterIn, request: Request, rid: int = 0):
        u = staff(request)
        editing = bool(rid)
        if re.search(r"\[[^\]]{2,40}\]", body.body + body.subject + body.to_text):
            raise HTTPException(status_code=422, detail="Replace the [placeholders] in the letter before saving.")
        recipient = (body.to_text.strip().splitlines() or [""])[0][:160]
        with closing(db()) as conn:
            if rid:
                old = conn.execute("SELECT kind FROM doc_records WHERE id=?", (rid,)).fetchone()
                if not old or old["kind"] != "letter":
                    raise HTTPException(status_code=404, detail="Letter not found.")
            rid, number = save(conn, "letter", u, recipient, body.subject, body.purpose, body.template, body.model_dump(),
                               day(body.letter_date), rid=rid or None)
            conn.commit()
        audit(u["username"], "docs.letter.%s" % ("edit" if editing else "create"), "%s %s" % (number, body.purpose))
        return {"ok": True, "id": rid, "number": number}

    @app.post("/api/docs/blank")
    def create_blank(body: BlankIn, request: Request):
        u = staff(request)
        fmt = "docx" if body.fmt == "docx" else "pdf"
        with closing(db()) as conn:
            rid, number = save(conn, "blank", u, body.recipient.strip(), "Blank letterhead (%s)" % fmt.upper(), body.purpose.strip(), fmt,
                               {"copies": body.copies, "fmt": fmt}, day(""))
            conn.commit()
        audit(u["username"], "docs.blank", "%s %s x%d %s" % (number, fmt, body.copies, body.purpose))
        return {"ok": True, "id": rid, "number": number}

    @app.delete("/api/docs/{rid}")
    def delete_doc(rid: int, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            r = conn.execute("SELECT number, kind, created_by FROM doc_records WHERE id=?", (rid,)).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Not found.")
            if u["role"] != "admin" and r["created_by"] != u["username"]:
                raise HTTPException(status_code=403, detail="Only the person who made it or an admin can delete it.")
            conn.execute("DELETE FROM doc_records WHERE id=?", (rid,))
            conn.commit()
        audit(u["username"], "docs.delete", "%s (%s)" % (r["number"], r["kind"]))
        return {"ok": True}

    @app.get("/api/docs/{rid}/file")
    def doc_file(rid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            r = conn.execute("SELECT * FROM doc_records WHERE id=?", (rid,)).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Not found.")
            S = B.settings(conn)
        rec, data = dict(r), json.loads(r["data"] or "{}")
        name = rec["number"].replace("/", "-")
        if rec["kind"] == "quote":
            return B._pdf_response(quote_pdf(S, rec, data)[0], name)
        if rec["kind"] == "letter":
            return B._pdf_response(letter_pdf(S, rec, data), name)
        if data.get("fmt") == "docx":
            return Response(blank_docx(S, rec), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            headers={"Content-Disposition": 'attachment; filename="%s.docx"' % name})
        return B._pdf_response(blank_pdf(S, rec, int(data.get("copies") or 1)), name)
