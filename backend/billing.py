"""Billing: inventory, customer accounts, GST invoices, receipts, ledgers and period reports.

Who can use it: employees with role 'admin' or 'accounts'.

Money is computed on the server with Decimal (2 decimals, half-up). GST per invoice line:
  taxable = qty x rate
  CGST = taxable x rate/2   (if CGST is ticked)
  SGST = taxable x rate/2   (if SGST is ticked)
  IGST = taxable x rate     (if IGST is ticked)
The person billing decides which of CGST / SGST / IGST apply (the form pre-ticks CGST+SGST for the
company's own state and IGST otherwise). Numbers follow the Indian financial year (April-March):
INV/2026-27/0001, RCP/2026-27/0001. Item codes: HW-0001 hardware, SW-0001 software, SV-0001 services.
Accounts: ACC-0001. Every account keeps its full history (ledger) for as long as it exists.
"""
import csv
import io
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

TWO = Decimal("0.01")
CATEGORIES = {"hardware": "HW", "software": "SW", "service": "SV"}
MODES = ("cash", "upi", "bank", "cheque", "card", "other")
DEFAULT_SETTINGS = {
    "company_name": "Agile Tech Experts Pvt. Ltd.",
    "address": "Casa Greens 1, Greater Noida West, opp. BLS World School, Uttar Pradesh",
    "state": "Uttar Pradesh", "state_code": "09", "gstin": "", "pan": "",
    "phone": "+91 98100 57579", "email": "info@agiletechexpert.com",
    "bank_name": "", "bank_account": "", "bank_ifsc": "", "upi": "",
    "invoice_prefix": "INV", "receipt_prefix": "RCP",
    "terms": "Goods once sold will not be taken back. Payment due as per the due date. Subject to local jurisdiction.",
    "round_off": "1",
}


def D(x):
    try:
        return Decimal(str(x if x not in (None, "") else 0)).quantize(TWO, rounding=ROUND_HALF_UP)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid number: %s" % x)


IST = timezone(timedelta(hours=5, minutes=30))


def today_ist():
    return datetime.now(IST).date()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fy_of(d):
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    start = d.year if d.month >= 4 else d.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def fy_range(fy, period="FY"):
    start_year = int(fy.split("-")[0])
    q = {"Q1": (4, 6, 0), "Q2": (7, 9, 0), "Q3": (10, 12, 0), "Q4": (1, 3, 1),
         "H1": (4, 9, 0), "H2": (10, 3, 0), "FY": (4, 3, 0)}
    if period not in q:
        raise HTTPException(status_code=422, detail="Period must be Q1, Q2, Q3, Q4, H1, H2 or FY.")
    m1, m2, y_off = q[period]
    y1 = start_year + y_off
    begin = date(y1, m1, 1)
    y2 = y1 if m2 >= m1 else y1 + 1
    end = (date(y2 + (m2 == 12), (m2 % 12) + 1, 1) - timedelta(days=1))
    return begin, end


def inr(x):
    """Indian digit grouping: 1,23,45,678.90"""
    x = D(x)
    neg = x < 0
    s = "%.2f" % abs(x)
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + "." + frac


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n):
    h, r = divmod(n, 100)
    return ((_ONES[h] + " Hundred" + (" " if r else "")) if h else "") + (_two(r) if r else "")


def words(amount):
    """Rupees in words, Indian system (crore, lakh, thousand)."""
    amount = D(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    if rupees == 0:
        out = "Zero"
    else:
        parts = []
        crore, rupees_left = divmod(rupees, 10000000)
        lakh, rupees_left = divmod(rupees_left, 100000)
        thousand, rest = divmod(rupees_left, 1000)
        if crore:
            parts.append(words_int(crore) + " Crore")
        if lakh:
            parts.append(_two(lakh) + " Lakh")
        if thousand:
            parts.append(_two(thousand) + " Thousand")
        if rest:
            parts.append(_three(rest))
        out = " ".join(parts)
    return "Rupees " + out + ((" and " + _two(paise) + " Paise") if paise else "") + " Only"


def words_int(n):
    return words(n).replace("Rupees ", "").replace(" Only", "")


# ------------------------------------------------------------------ schema
def init_tables(db):
    with closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS bill_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS bill_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT NOT NULL, gstin TEXT,
            state TEXT, state_code TEXT, address TEXT, phone TEXT, email TEXT, client_id INTEGER,
            opening_balance REAL DEFAULT 0, active INTEGER DEFAULT 1, created_at TEXT, created_by TEXT);
        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL,
            hsn TEXT, unit TEXT DEFAULT 'pcs', price REAL DEFAULT 0, gst_rate REAL DEFAULT 18,
            track_stock INTEGER DEFAULT 0, stock REAL DEFAULT 0, active INTEGER DEFAULT 1,
            created_at TEXT, created_by TEXT);
        CREATE TABLE IF NOT EXISTS bill_stock_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, qty REAL NOT NULL, reason TEXT,
            ref TEXT, at TEXT, by_user TEXT);
        CREATE TABLE IF NOT EXISTS bill_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, fy TEXT, seq INTEGER, party_id INTEGER NOT NULL,
            inv_date TEXT NOT NULL, due_date TEXT, place_of_supply TEXT,
            apply_cgst INTEGER DEFAULT 0, apply_sgst INTEGER DEFAULT 0, apply_igst INTEGER DEFAULT 0,
            subtotal REAL, cgst REAL, sgst REAL, igst REAL, round_off REAL, total REAL,
            paid REAL DEFAULT 0, status TEXT DEFAULT 'unpaid', notes TEXT, created_by TEXT, created_at TEXT,
            cancelled_by TEXT, cancelled_at TEXT);
        CREATE TABLE IF NOT EXISTS bill_invoice_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, item_id INTEGER, code TEXT,
            name TEXT, hsn TEXT, unit TEXT, qty REAL, rate REAL, gst_rate REAL, taxable REAL,
            cgst REAL, sgst REAL, igst REAL, total REAL);
        CREATE TABLE IF NOT EXISTS bill_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, fy TEXT, seq INTEGER, party_id INTEGER NOT NULL,
            invoice_id INTEGER, rcp_date TEXT NOT NULL, amount REAL NOT NULL, mode TEXT, reference TEXT,
            notes TEXT, status TEXT DEFAULT 'ok', created_by TEXT, created_at TEXT, cancelled_by TEXT, cancelled_at TEXT);
        CREATE INDEX IF NOT EXISTS ix_binv_party ON bill_invoices(party_id);
        CREATE INDEX IF NOT EXISTS ix_brcp_party ON bill_receipts(party_id);
        CREATE INDEX IF NOT EXISTS ix_bline_inv ON bill_invoice_lines(invoice_id);
        """)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO bill_settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()


def settings(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM bill_settings")}


def next_seq(conn, table, fy):
    return (conn.execute("SELECT COALESCE(MAX(seq), 0) FROM %s WHERE fy=?" % table, (fy,)).fetchone()[0] or 0) + 1


def next_code(conn, table, prefix):
    rows = conn.execute("SELECT code FROM %s WHERE code LIKE ?" % table, (prefix + "-%",)).fetchall()
    n = max([int(r[0].split("-")[-1]) for r in rows if r[0].split("-")[-1].isdigit()] or [0]) + 1
    return "%s-%04d" % (prefix, n)


def refresh_invoice_status(conn, invoice_id):
    inv = conn.execute("SELECT total, status FROM bill_invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv or inv["status"] == "cancelled":
        return
    paid = D(conn.execute("SELECT COALESCE(SUM(amount),0) FROM bill_receipts WHERE invoice_id=? AND status='ok'",
                          (invoice_id,)).fetchone()[0])
    total = D(inv["total"])
    status = "paid" if paid >= total else ("partial" if paid > 0 else "unpaid")
    conn.execute("UPDATE bill_invoices SET paid=?, status=? WHERE id=?", (float(paid), status, invoice_id))


def party_balance(conn, party_id):
    p = conn.execute("SELECT opening_balance FROM bill_parties WHERE id=?", (party_id,)).fetchone()
    inv = conn.execute("SELECT COALESCE(SUM(total),0) FROM bill_invoices WHERE party_id=? AND status!='cancelled'",
                       (party_id,)).fetchone()[0]
    rcp = conn.execute("SELECT COALESCE(SUM(amount),0) FROM bill_receipts WHERE party_id=? AND status='ok'",
                       (party_id,)).fetchone()[0]
    return D(p[0] if p else 0) + D(inv) - D(rcp)


def compute_lines(lines, apply_cgst, apply_sgst, apply_igst):
    out, sub, cg, sg, ig = [], D(0), D(0), D(0), D(0)
    for ln in lines:
        qty = Decimal(str(ln["qty"]))
        rate = D(ln["rate"])
        gst = Decimal(str(ln["gst_rate"]))
        taxable = (qty * rate).quantize(TWO, rounding=ROUND_HALF_UP)
        c = (taxable * gst / 200).quantize(TWO, rounding=ROUND_HALF_UP) if apply_cgst else D(0)
        s = (taxable * gst / 200).quantize(TWO, rounding=ROUND_HALF_UP) if apply_sgst else D(0)
        i = (taxable * gst / 100).quantize(TWO, rounding=ROUND_HALF_UP) if apply_igst else D(0)
        out.append({**ln, "taxable": taxable, "cgst": c, "sgst": s, "igst": i, "total": taxable + c + s + i})
        sub, cg, sg, ig = sub + taxable, cg + c, sg + s, ig + i
    return out, sub, cg, sg, ig


# ------------------------------------------------------------------ request models
class SettingsIn(BaseModel):
    values: dict


class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    gstin: str = Field(default="", max_length=15)
    state: str = Field(default="", max_length=60)
    state_code: str = Field(default="", max_length=2)
    address: str = Field(default="", max_length=400)
    phone: str = Field(default="", max_length=25)
    email: str = Field(default="", max_length=160)
    client_id: int | None = None
    opening_balance: float = 0


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="hardware", max_length=20)
    hsn: str = Field(default="", max_length=10)
    unit: str = Field(default="pcs", max_length=20)
    price: float = Field(default=0, ge=0)
    gst_rate: float = Field(default=18, ge=0, le=28)
    track_stock: bool = False
    stock: float = 0


class StockIn(BaseModel):
    qty: float
    reason: str = Field(default="purchase", max_length=40)
    ref: str = Field(default="", max_length=80)


class LineIn(BaseModel):
    item_id: int | None = None
    name: str = Field(default="", max_length=200)
    hsn: str = Field(default="", max_length=10)
    unit: str = Field(default="pcs", max_length=20)
    qty: float = Field(gt=0, le=1000000)
    rate: float = Field(ge=0, le=100000000)
    gst_rate: float = Field(ge=0, le=28)
    add_to_inventory: bool = False
    category: str = Field(default="hardware", max_length=20)


class InvoiceIn(BaseModel):
    party_id: int
    inv_date: str = ""
    due_days: int = Field(default=15, ge=0, le=365)
    place_of_supply: str = Field(default="", max_length=60)
    apply_cgst: bool = False
    apply_sgst: bool = False
    apply_igst: bool = False
    notes: str = Field(default="", max_length=1000)
    lines: list[LineIn] = Field(min_length=1, max_length=100)


class ReceiptIn(BaseModel):
    party_id: int
    invoice_id: int | None = None
    rcp_date: str = ""
    amount: float = Field(gt=0, le=1000000000)
    mode: str = Field(default="bank", max_length=10)
    reference: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=500)


# ------------------------------------------------------------------ PDFs
def _pdf_doc(buf, title):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.units import mm
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                             bottomMargin=12 * mm, title=title, author="Agile Tech Expert")


def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib import colors
    ss = getSampleStyleSheet()
    teal = colors.HexColor("#0b6f6a")
    return {
        "h": ParagraphStyle("h", parent=ss["Title"], fontSize=15, textColor=teal, alignment=0, spaceAfter=2),
        "t": ParagraphStyle("t", parent=ss["Heading2"], fontSize=12, textColor=teal, spaceBefore=4, spaceAfter=4),
        "n": ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=11),
        "b": ParagraphStyle("b", parent=ss["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"),
        "s": ParagraphStyle("s", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4b6b70")),
        "teal": teal,
    }


def _esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(data, widths, header=True, right_cols=(), bold_last=False):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9dcda")),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6f6a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8)]
    for c in right_cols:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if bold_last:
        st.append(("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8))
    t.setStyle(TableStyle(st))
    return t


def _company_block(S, st):
    from reportlab.platypus import Paragraph
    lines = [_esc(S.get("address"))]
    if S.get("gstin"):
        lines.append("GSTIN: %s" % _esc(S["gstin"]) + (" &nbsp; State: %s (%s)" % (_esc(S.get("state")), _esc(S.get("state_code"))) if S.get("state") else ""))
    lines.append(" &nbsp; ".join(x for x in [_esc(S.get("phone")), _esc(S.get("email"))] if x))
    return [Paragraph(_esc(S.get("company_name")), st["h"]), Paragraph("<br/>".join(lines), st["n"])]


def invoice_pdf(conn, inv_id):
    from reportlab.platypus import Paragraph, Spacer, Table
    from reportlab.lib.units import mm
    inv = conn.execute("SELECT * FROM bill_invoices WHERE id=?", (inv_id,)).fetchone()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    p = conn.execute("SELECT * FROM bill_parties WHERE id=?", (inv["party_id"],)).fetchone()
    lines = conn.execute("SELECT * FROM bill_invoice_lines WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    S, st = settings(conn), _styles()
    buf = io.BytesIO()
    doc = _pdf_doc(buf, inv["number"])
    title = "TAX INVOICE" + ("  (CANCELLED)" if inv["status"] == "cancelled" else "")
    head = Table([[_company_block(S, st),
                   [Paragraph(title, st["t"]),
                    Paragraph("<b>Invoice No:</b> %s<br/><b>Date:</b> %s<br/><b>Due date:</b> %s<br/><b>Place of supply:</b> %s"
                              % (_esc(inv["number"]), inv["inv_date"], inv["due_date"] or "-", _esc(inv["place_of_supply"] or "-")), st["n"])]]],
                 colWidths=[110 * mm, 76 * mm])
    bill_to = Paragraph("<b>Bill to:</b> %s (%s)<br/>%s%s%s" % (
        _esc(p["name"]), _esc(p["code"]), _esc(p["address"]) + "<br/>" if p["address"] else "",
        ("GSTIN: %s &nbsp; " % _esc(p["gstin"])) if p["gstin"] else "",
        ("State: %s" % _esc(p["state"])) if p["state"] else ""), st["n"])
    cols = ["#", "Code", "Item", "HSN/SAC", "Qty", "Rate", "Taxable", "GST %"]
    show = [("CGST", inv["apply_cgst"]), ("SGST", inv["apply_sgst"]), ("IGST", inv["apply_igst"])]
    cols += [n for n, on in show if on] + ["Amount"]
    data = [cols]
    for i, ln in enumerate(lines, 1):
        row = [str(i), ln["code"] or "-", Paragraph(_esc(ln["name"]), st["n"]), ln["hsn"] or "-",
               "%g %s" % (ln["qty"], ln["unit"] or ""), inr(ln["rate"]), inr(ln["taxable"]), "%g" % ln["gst_rate"]]
        row += [inr(ln[n.lower()]) for n, on in show if on] + [inr(ln["total"])]
        data.append(row)
    n_tax = sum(1 for _, on in show if on)
    fixed = [7, 16, 0, 15, 14, 18, 20, 12] + [17] * n_tax + [21]
    item_w = 186 - sum(fixed)
    widths = [w * mm for w in fixed]
    widths[2] = item_w * mm
    right = list(range(4, len(cols)))
    totals = [["Taxable value", inr(inv["subtotal"])]]
    for n, on in show:
        if on:
            totals.append([n, inr(inv[n.lower()])])
    if D(inv["round_off"]) != 0:
        totals.append(["Round off", inr(inv["round_off"])])
    totals.append(["Total (INR)", inr(inv["total"])])
    if D(inv["paid"]) > 0:
        totals += [["Received", inr(inv["paid"])], ["Balance due", inr(D(inv["total"]) - D(inv["paid"]))]]
    bank = []
    if S.get("bank_name") or S.get("bank_account") or S.get("upi"):
        bank.append(Paragraph("<b>Bank:</b> %s &nbsp; <b>A/c:</b> %s &nbsp; <b>IFSC:</b> %s%s" % (
            _esc(S.get("bank_name")), _esc(S.get("bank_account")), _esc(S.get("bank_ifsc")),
            (" &nbsp; <b>UPI:</b> " + _esc(S["upi"])) if S.get("upi") else ""), st["n"]))
    story = [head, Spacer(1, 4 * mm), bill_to, Spacer(1, 4 * mm),
             _table(data, widths, right_cols=right), Spacer(1, 3 * mm),
             Table([[Paragraph("<b>Amount in words:</b> %s" % words(inv["total"]), st["n"]),
                     _table(totals, [32 * mm, 30 * mm], header=False, right_cols=(1,), bold_last=False)]],
                   colWidths=[122 * mm, 64 * mm]),
             Spacer(1, 4 * mm)] + bank
    if inv["notes"]:
        story.append(Paragraph("<b>Notes:</b> " + _esc(inv["notes"]), st["n"]))
    if S.get("terms"):
        story += [Spacer(1, 2 * mm), Paragraph("<b>Terms:</b> " + _esc(S["terms"]), st["s"])]
    story += [Spacer(1, 12 * mm), Paragraph("For %s<br/><br/><br/>Authorised Signatory" % _esc(S.get("company_name")), st["n"]),
              Spacer(1, 4 * mm), Paragraph("This is a computer-generated invoice.", st["s"])]
    doc.build(story)
    return buf.getvalue()


def receipt_pdf(conn, rcp_id):
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import mm
    r = conn.execute("SELECT * FROM bill_receipts WHERE id=?", (rcp_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    p = conn.execute("SELECT * FROM bill_parties WHERE id=?", (r["party_id"],)).fetchone()
    inv = conn.execute("SELECT number FROM bill_invoices WHERE id=?", (r["invoice_id"],)).fetchone() if r["invoice_id"] else None
    S, st = settings(conn), _styles()
    buf = io.BytesIO()
    doc = _pdf_doc(buf, r["number"])
    rows = [["Receipt No", r["number"]], ["Date", r["rcp_date"]], ["Received from", "%s (%s)" % (p["name"], p["code"])],
            ["Amount (INR)", inr(r["amount"])], ["In words", Paragraph(words(r["amount"]), st["n"])],
            ["Mode", (r["mode"] or "").upper()], ["Reference", r["reference"] or "-"],
            ["Against invoice", inv["number"] if inv else "On account"],
            ["Account balance today", inr(party_balance(conn, r["party_id"]))]]
    if r["status"] == "cancelled":
        rows.insert(0, ["Status", "CANCELLED"])
    story = _company_block(S, st) + [Spacer(1, 5 * mm), Paragraph("PAYMENT RECEIPT", st["t"]),
                                     _table(rows, [55 * mm, 120 * mm], header=False), Spacer(1, 4 * mm)]
    if r["notes"]:
        story.append(Paragraph("<b>Notes:</b> " + _esc(r["notes"]), st["n"]))
    story += [Spacer(1, 14 * mm), Paragraph("For %s<br/><br/><br/>Authorised Signatory" % _esc(S.get("company_name")), st["n"])]
    doc.build(story)
    return buf.getvalue()


def ledger_rows(conn, party_id, dfrom="", dto=""):
    p = conn.execute("SELECT * FROM bill_parties WHERE id=?", (party_id,)).fetchone()
    if not p:
        raise HTTPException(status_code=404, detail="Account not found.")
    ev = []
    for i in conn.execute("SELECT id, number, inv_date d, total FROM bill_invoices WHERE party_id=? AND status!='cancelled'", (party_id,)):
        ev.append((i["d"], 0, i["id"], "Sales invoice", i["number"], D(i["total"]), D(0)))
    for r in conn.execute("SELECT id, number, rcp_date d, amount, mode FROM bill_receipts WHERE party_id=? AND status='ok'", (party_id,)):
        ev.append((r["d"], 1, r["id"], "Receipt (%s)" % (r["mode"] or "").upper(), r["number"], D(0), D(r["amount"])))
    ev.sort()
    bal = D(p["opening_balance"])
    rows, bf = [], None
    for d, _, _, part, ref, dr, cr in ev:
        if dfrom and d < dfrom:
            bal += dr - cr
            continue
        if dto and d > dto:
            continue
        if bf is None:
            bf = bal
        bal += dr - cr
        rows.append({"date": d, "particulars": part, "ref": ref, "debit": dr, "credit": cr, "balance": bal})
    opening = bf if bf is not None else bal
    return p, opening, rows, bal


def ledger_pdf(conn, party_id, dfrom, dto):
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import mm
    p, opening, rows, closing_bal = ledger_rows(conn, party_id, dfrom, dto)
    S, st = settings(conn), _styles()
    buf = io.BytesIO()
    doc = _pdf_doc(buf, "Ledger %s" % p["code"])
    data = [["Date", "Particulars", "Ref No", "Debit", "Credit", "Balance"],
            [dfrom or "-", "Opening balance", "", "", "", inr(opening)]]
    tdr = tcr = D(0)
    for r in rows:
        tdr, tcr = tdr + r["debit"], tcr + r["credit"]
        data.append([r["date"], r["particulars"], r["ref"], inr(r["debit"]) if r["debit"] else "",
                     inr(r["credit"]) if r["credit"] else "", inr(r["balance"])])
    data.append(["", "Total / Closing balance", "", inr(tdr), inr(tcr), inr(closing_bal)])
    story = _company_block(S, st) + [Spacer(1, 4 * mm), Paragraph("ACCOUNT LEDGER", st["t"]),
             Paragraph("<b>%s</b> (%s)%s<br/>Period: %s to %s" % (_esc(p["name"]), _esc(p["code"]),
                       (" &nbsp; GSTIN: " + _esc(p["gstin"])) if p["gstin"] else "", dfrom or "start", dto or "today"), st["n"]),
             Spacer(1, 3 * mm),
             _table(data, [22 * mm, 52 * mm, 34 * mm, 26 * mm, 26 * mm, 26 * mm], right_cols=(3, 4, 5), bold_last=True),
             Spacer(1, 3 * mm), Paragraph("Positive balance = amount receivable from the customer.", st["s"])]
    doc.build(story)
    return buf.getvalue()


def report_data(conn, fy, period):
    begin, end = fy_range(fy, period)
    b, e = begin.isoformat(), end.isoformat()
    invs = conn.execute("SELECT i.*, p.name party, p.gstin pgstin, p.state pstate, p.code pcode FROM bill_invoices i "
                        "JOIN bill_parties p ON p.id=i.party_id WHERE i.inv_date BETWEEN ? AND ? ORDER BY i.inv_date, i.seq",
                        (b, e)).fetchall()
    live = [i for i in invs if i["status"] != "cancelled"]
    tot = {k: sum((D(i[k]) for i in live), D(0)) for k in ("subtotal", "cgst", "sgst", "igst", "round_off", "total")}
    rcps = conn.execute("SELECT * FROM bill_receipts WHERE status='ok' AND rcp_date BETWEEN ? AND ?", (b, e)).fetchall()
    by_mode = {}
    for r in rcps:
        by_mode[r["mode"] or "other"] = by_mode.get(r["mode"] or "other", D(0)) + D(r["amount"])
    months = {}
    for i in live:
        m = i["inv_date"][:7]
        mm_ = months.setdefault(m, {"invoices": 0, "taxable": D(0), "tax": D(0), "total": D(0), "received": D(0)})
        mm_["invoices"] += 1
        mm_["taxable"] += D(i["subtotal"])
        mm_["tax"] += D(i["cgst"]) + D(i["sgst"]) + D(i["igst"])
        mm_["total"] += D(i["total"])
    for r in rcps:
        months.setdefault(r["rcp_date"][:7], {"invoices": 0, "taxable": D(0), "tax": D(0), "total": D(0), "received": D(0)})["received"] += D(r["amount"])
    cats = {}
    for row in conn.execute("SELECT COALESCE(it.category, 'other') cat, SUM(l.taxable) t FROM bill_invoice_lines l "
                            "JOIN bill_invoices i ON i.id=l.invoice_id LEFT JOIN bill_items it ON it.id=l.item_id "
                            "WHERE i.status!='cancelled' AND i.inv_date BETWEEN ? AND ? GROUP BY cat", (b, e)):
        cats[row["cat"]] = D(row["t"])
    outstanding = sum((party_balance(conn, r[0]) for r in conn.execute("SELECT id FROM bill_parties")), D(0))
    return {"fy": fy, "period": period, "from": b, "to": e, "invoices": len(live), "cancelled": len(invs) - len(live),
            "totals": tot, "received": sum(by_mode.values(), D(0)), "received_by_mode": by_mode,
            "months": dict(sorted(months.items())), "by_category": cats, "outstanding_now": outstanding,
            "register": invs}


def report_pdf(conn, fy, period):
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import mm
    r = report_data(conn, fy, period)
    S, st = settings(conn), _styles()
    buf = io.BytesIO()
    doc = _pdf_doc(buf, "Sales report %s %s" % (fy, period))
    t = r["totals"]
    summary = [["Invoices", str(r["invoices"]) + (" (+%d cancelled)" % r["cancelled"] if r["cancelled"] else "")],
               ["Taxable value", inr(t["subtotal"])], ["CGST", inr(t["cgst"])], ["SGST", inr(t["sgst"])],
               ["IGST", inr(t["igst"])], ["Round off", inr(t["round_off"])], ["Total invoiced", inr(t["total"])],
               ["Received in period", inr(r["received"])], ["Outstanding (all accounts, today)", inr(r["outstanding_now"])]]
    months = [["Month", "Invoices", "Taxable", "GST", "Total", "Received"]] + [
        [m, str(v["invoices"]), inr(v["taxable"]), inr(v["tax"]), inr(v["total"]), inr(v["received"])] for m, v in r["months"].items()]
    reg = [["Date", "Invoice", "Account / GSTIN", "Taxable", "CGST", "SGST", "IGST", "Total", "Status"]] + [
        [i["inv_date"], i["number"], Paragraph(_esc(i["party"]) + ("<br/>" + _esc(i["pgstin"]) if i["pgstin"] else ""), st["s"]),
         inr(i["subtotal"]), inr(i["cgst"]), inr(i["sgst"]), inr(i["igst"]), inr(i["total"]), i["status"]] for i in r["register"]]
    label = {"FY": "Financial year", "H1": "Half year 1 (Apr-Sep)", "H2": "Half year 2 (Oct-Mar)"}.get(period, "Quarter " + period)
    story = _company_block(S, st) + [Spacer(1, 4 * mm), Paragraph("SALES &amp; GST REPORT", st["t"]),
             Paragraph("FY %s &nbsp; %s &nbsp; (%s to %s)" % (fy, label, r["from"], r["to"]), st["n"]), Spacer(1, 3 * mm),
             _table(summary, [70 * mm, 45 * mm], header=False, right_cols=(1,)), Spacer(1, 4 * mm),
             Paragraph("Month-wise", st["b"]), Spacer(1, 1 * mm),
             _table(months, [24 * mm, 18 * mm, 30 * mm, 28 * mm, 30 * mm, 30 * mm], right_cols=(1, 2, 3, 4, 5)),
             Spacer(1, 4 * mm), Paragraph("Invoice register", st["b"]), Spacer(1, 1 * mm),
             _table(reg, [17 * mm, 27 * mm, 36 * mm, 20 * mm, 17 * mm, 17 * mm, 17 * mm, 20 * mm, 15 * mm],
                    right_cols=(3, 4, 5, 6, 7))]
    doc.build(story)
    return buf.getvalue()


def _pdf_response(data, name):
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="%s.pdf"' % name.replace("/", "-")})


def _csv_response(rows, name):
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return PlainTextResponse("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="%s.csv"' % name.replace("/", "-")})


# ------------------------------------------------------------------ API
def register(app, db, get_session, audit):
    init_tables(db)

    def staff(request: Request, roles=("admin", "accounts")):
        s = get_session(request.cookies.get("ate_emp"))
        if not s or s["user_type"] != "employee":
            raise HTTPException(status_code=401, detail="Please sign in.")
        with closing(db()) as conn:
            u = conn.execute("SELECT id, username, role, active FROM employees WHERE id=?", (s["user_id"],)).fetchone()
        if not u or not u["active"]:
            raise HTTPException(status_code=401, detail="Please sign in.")
        if u["role"] not in roles:
            raise HTTPException(status_code=403, detail="Billing is only for admin and accounts users.")
        return dict(u)

    def today():
        return today_ist().isoformat()

    def valid_date(s):
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except Exception:
            raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD.")

    # ---- settings
    @app.get("/api/billing/settings")
    def get_settings(request: Request):
        staff(request)
        with closing(db()) as conn:
            return {"settings": settings(conn), "today": today(), "fy": fy_of(today_ist())}

    @app.put("/api/billing/settings")
    def put_settings(body: SettingsIn, request: Request):
        u = staff(request, ("admin",))
        with closing(db()) as conn:
            for k, v in body.values.items():
                if k in DEFAULT_SETTINGS:
                    conn.execute("INSERT INTO bill_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 (k, str(v)[:600]))
            conn.commit()
        audit(u["username"], "billing.settings", ", ".join(k for k in body.values if k in DEFAULT_SETTINGS))
        return {"ok": True}

    # ---- accounts
    @app.get("/api/billing/parties")
    def list_parties(request: Request):
        staff(request)
        with closing(db()) as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM bill_parties ORDER BY name")]
            for r in rows:
                r["balance"] = float(party_balance(conn, r["id"]))
        return {"items": rows}

    @app.post("/api/billing/parties")
    def create_party(body: PartyIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            code = next_code(conn, "bill_parties", "ACC")
            cur = conn.execute("INSERT INTO bill_parties (code,name,gstin,state,state_code,address,phone,email,client_id,"
                               "opening_balance,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (code, body.name.strip(), body.gstin.strip().upper(), body.state.strip(), body.state_code.strip(),
                                body.address.strip(), body.phone.strip(), body.email.strip(), body.client_id,
                                float(D(body.opening_balance)), now_iso(), u["username"]))
            conn.commit()
        audit(u["username"], "billing.account.create", "%s %s" % (code, body.name))
        return {"ok": True, "id": cur.lastrowid, "code": code}

    @app.patch("/api/billing/parties/{pid}")
    def update_party(pid: int, body: PartyIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            cur = conn.execute("UPDATE bill_parties SET name=?, gstin=?, state=?, state_code=?, address=?, phone=?, email=?, "
                               "client_id=?, opening_balance=? WHERE id=?",
                               (body.name.strip(), body.gstin.strip().upper(), body.state.strip(), body.state_code.strip(),
                                body.address.strip(), body.phone.strip(), body.email.strip(), body.client_id,
                                float(D(body.opening_balance)), pid))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Account not found.")
        audit(u["username"], "billing.account.update", "account %d" % pid)
        return {"ok": True}

    @app.get("/api/billing/parties/{pid}/ledger")
    def ledger(pid: int, request: Request, dfrom: str = "", dto: str = ""):
        staff(request)
        with closing(db()) as conn:
            p, opening, rows, bal = ledger_rows(conn, pid, dfrom, dto)
        return {"party": dict(p), "opening": float(opening), "closing": float(bal),
                "rows": [{**r, "debit": float(r["debit"]), "credit": float(r["credit"]), "balance": float(r["balance"])} for r in rows]}

    @app.get("/api/billing/parties/{pid}/ledger.csv")
    def ledger_csv(pid: int, request: Request, dfrom: str = "", dto: str = ""):
        staff(request)
        with closing(db()) as conn:
            p, opening, rows, bal = ledger_rows(conn, pid, dfrom, dto)
        out = [["Account", p["name"], "Code", p["code"], "GSTIN", p["gstin"] or ""],
               ["Period", dfrom or "start", "to", dto or "today"], [],
               ["Date", "Particulars", "Ref No", "Debit", "Credit", "Balance"],
               [dfrom or "", "Opening balance", "", "", "", "%.2f" % opening]]
        for r in rows:
            out.append([r["date"], r["particulars"], r["ref"], "%.2f" % r["debit"] if r["debit"] else "",
                        "%.2f" % r["credit"] if r["credit"] else "", "%.2f" % r["balance"]])
        out.append(["", "Closing balance", "", "%.2f" % sum((r["debit"] for r in rows), D(0)),
                    "%.2f" % sum((r["credit"] for r in rows), D(0)), "%.2f" % bal])
        return _csv_response(out, "ledger-%s" % p["code"])

    @app.get("/api/billing/parties/{pid}/ledger.pdf")
    def ledger_pdf_ep(pid: int, request: Request, dfrom: str = "", dto: str = ""):
        staff(request)
        with closing(db()) as conn:
            data = ledger_pdf(conn, pid, dfrom, dto)
            code = conn.execute("SELECT code FROM bill_parties WHERE id=?", (pid,)).fetchone()[0]
        return _pdf_response(data, "ledger-%s" % code)

    # ---- inventory
    @app.get("/api/billing/items")
    def list_items(request: Request):
        staff(request)
        with closing(db()) as conn:
            return {"items": [dict(r) for r in conn.execute("SELECT * FROM bill_items ORDER BY code")]}

    def create_item_row(conn, body, user):
        cat = body.category if body.category in CATEGORIES else "hardware"
        code = next_code(conn, "bill_items", CATEGORIES[cat])
        cur = conn.execute("INSERT INTO bill_items (code,name,category,hsn,unit,price,gst_rate,track_stock,stock,created_at,created_by) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (code, body.name.strip(), cat, body.hsn.strip(), body.unit.strip() or "pcs", float(D(body.price)),
                            float(body.gst_rate), 1 if body.track_stock else 0, float(body.stock or 0), now_iso(), user))
        if body.track_stock and body.stock:
            conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                         (cur.lastrowid, float(body.stock), "opening", "", now_iso(), user))
        return cur.lastrowid, code

    @app.post("/api/billing/items")
    def create_item(body: ItemIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            iid, code = create_item_row(conn, body, u["username"])
            conn.commit()
        audit(u["username"], "billing.item.create", "%s %s" % (code, body.name))
        return {"ok": True, "id": iid, "code": code}

    @app.patch("/api/billing/items/{iid}")
    def update_item(iid: int, body: ItemIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            cur = conn.execute("UPDATE bill_items SET name=?, hsn=?, unit=?, price=?, gst_rate=?, track_stock=? WHERE id=?",
                               (body.name.strip(), body.hsn.strip(), body.unit.strip() or "pcs", float(D(body.price)),
                                float(body.gst_rate), 1 if body.track_stock else 0, iid))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Item not found.")
        audit(u["username"], "billing.item.update", "item %d" % iid)
        return {"ok": True}

    @app.post("/api/billing/items/{iid}/stock")
    def adjust_stock(iid: int, body: StockIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            it = conn.execute("SELECT code FROM bill_items WHERE id=?", (iid,)).fetchone()
            if not it:
                raise HTTPException(status_code=404, detail="Item not found.")
            conn.execute("UPDATE bill_items SET stock = stock + ?, track_stock=1 WHERE id=?", (body.qty, iid))
            conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                         (iid, body.qty, body.reason, body.ref, now_iso(), u["username"]))
            conn.commit()
            stock = conn.execute("SELECT stock FROM bill_items WHERE id=?", (iid,)).fetchone()[0]
        audit(u["username"], "billing.stock", "%s %+g (%s)" % (it["code"], body.qty, body.reason))
        return {"ok": True, "stock": stock}

    @app.get("/api/billing/items/{iid}/moves")
    def stock_moves(iid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            return {"items": [dict(r) for r in conn.execute(
                "SELECT * FROM bill_stock_moves WHERE item_id=? ORDER BY id DESC LIMIT 200", (iid,))]}

    # ---- invoices
    @app.get("/api/billing/invoices")
    def list_invoices(request: Request, party_id: int = 0, status: str = "", q: str = ""):
        staff(request)
        where, args = ["1=1"], []
        if party_id:
            where.append("i.party_id=?"); args.append(party_id)
        if status in ("unpaid", "partial", "paid", "cancelled"):
            where.append("i.status=?"); args.append(status)
        if q.strip():
            where.append("(i.number LIKE ? OR p.name LIKE ?)"); args += ["%" + q.strip() + "%"] * 2
        with closing(db()) as conn:
            rows = conn.execute("SELECT i.*, p.name party, p.code party_code FROM bill_invoices i JOIN bill_parties p ON "
                                "p.id=i.party_id WHERE " + " AND ".join(where) + " ORDER BY i.inv_date DESC, i.id DESC LIMIT 500",
                                args).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.post("/api/billing/invoices")
    def create_invoice(body: InvoiceIn, request: Request):
        u = staff(request)
        inv_date = valid_date(body.inv_date) if body.inv_date else today()
        if not (body.apply_cgst or body.apply_sgst or body.apply_igst) and any(l.gst_rate > 0 for l in body.lines):
            raise HTTPException(status_code=422, detail="Tick CGST + SGST or IGST (or set GST % to 0).")
        with closing(db()) as conn:
            S = settings(conn)
            party = conn.execute("SELECT * FROM bill_parties WHERE id=?", (body.party_id,)).fetchone()
            if not party:
                raise HTTPException(status_code=404, detail="Account not found.")
            prepared, created_items = [], []
            for ln in body.lines:
                if ln.item_id:
                    it = conn.execute("SELECT * FROM bill_items WHERE id=?", (ln.item_id,)).fetchone()
                    if not it:
                        raise HTTPException(status_code=404, detail="Item %d not found." % ln.item_id)
                    prepared.append({"item_id": it["id"], "code": it["code"], "name": ln.name.strip() or it["name"],
                                     "hsn": ln.hsn.strip() or it["hsn"] or "", "unit": ln.unit or it["unit"], "qty": ln.qty,
                                     "rate": ln.rate, "gst_rate": ln.gst_rate, "track": it["track_stock"]})
                else:
                    if not ln.name.strip():
                        raise HTTPException(status_code=422, detail="Each manual line needs a name.")
                    item_id, code = None, ""
                    if ln.add_to_inventory:
                        item_id, code = create_item_row(conn, ItemIn(name=ln.name, category=ln.category, hsn=ln.hsn,
                                                                     unit=ln.unit, price=ln.rate, gst_rate=ln.gst_rate),
                                                        u["username"])
                        created_items.append(code)
                    prepared.append({"item_id": item_id, "code": code, "name": ln.name.strip(), "hsn": ln.hsn.strip(),
                                     "unit": ln.unit or "pcs", "qty": ln.qty, "rate": ln.rate, "gst_rate": ln.gst_rate, "track": 0})
            lines, sub, cg, sg, ig = compute_lines(prepared, body.apply_cgst, body.apply_sgst, body.apply_igst)
            gross = sub + cg + sg + ig
            rnd = (gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - gross) if S.get("round_off", "1") == "1" else D(0)
            total = gross + rnd
            fy = fy_of(inv_date)
            seq = next_seq(conn, "bill_invoices", fy)
            number = "%s/%s/%04d" % (S.get("invoice_prefix") or "INV", fy, seq)
            due = (date.fromisoformat(inv_date) + timedelta(days=body.due_days)).isoformat()
            cur = conn.execute(
                "INSERT INTO bill_invoices (number,fy,seq,party_id,inv_date,due_date,place_of_supply,apply_cgst,apply_sgst,"
                "apply_igst,subtotal,cgst,sgst,igst,round_off,total,paid,status,notes,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'unpaid',?,?,?)",
                (number, fy, seq, party["id"], inv_date, due, body.place_of_supply.strip() or party["state"] or "",
                 int(body.apply_cgst), int(body.apply_sgst), int(body.apply_igst), float(sub), float(cg), float(sg),
                 float(ig), float(rnd), float(total), body.notes.strip(), u["username"], now_iso()))
            inv_id = cur.lastrowid
            for ln in lines:
                conn.execute("INSERT INTO bill_invoice_lines (invoice_id,item_id,code,name,hsn,unit,qty,rate,gst_rate,taxable,"
                             "cgst,sgst,igst,total) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (inv_id, ln["item_id"], ln["code"], ln["name"], ln["hsn"], ln["unit"], ln["qty"], float(D(ln["rate"])),
                              ln["gst_rate"], float(ln["taxable"]), float(ln["cgst"]), float(ln["sgst"]), float(ln["igst"]),
                              float(ln["total"])))
                if ln["item_id"] and ln["track"]:
                    conn.execute("UPDATE bill_items SET stock = stock - ? WHERE id=?", (ln["qty"], ln["item_id"]))
                    conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                                 (ln["item_id"], -ln["qty"], "invoice", number, now_iso(), u["username"]))
            conn.commit()
        audit(u["username"], "billing.invoice.create", "%s %s total %s" % (number, party["code"], total))
        return {"ok": True, "id": inv_id, "number": number, "total": float(total), "new_items": created_items}

    @app.get("/api/billing/invoices/{iid}")
    def get_invoice(iid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            inv = conn.execute("SELECT i.*, p.name party, p.code party_code FROM bill_invoices i JOIN bill_parties p ON "
                               "p.id=i.party_id WHERE i.id=?", (iid,)).fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            lines = [dict(r) for r in conn.execute("SELECT * FROM bill_invoice_lines WHERE invoice_id=? ORDER BY id", (iid,))]
            rcps = [dict(r) for r in conn.execute("SELECT * FROM bill_receipts WHERE invoice_id=? ORDER BY id", (iid,))]
        return {"invoice": dict(inv), "lines": lines, "receipts": rcps}

    @app.post("/api/billing/invoices/{iid}/cancel")
    def cancel_invoice(iid: int, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            inv = conn.execute("SELECT * FROM bill_invoices WHERE id=?", (iid,)).fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            if inv["status"] == "cancelled":
                return {"ok": True}
            if conn.execute("SELECT COUNT(*) FROM bill_receipts WHERE invoice_id=? AND status='ok'", (iid,)).fetchone()[0]:
                raise HTTPException(status_code=422, detail="Cancel the receipts against this invoice first.")
            for ln in conn.execute("SELECT l.item_id, l.qty, it.track_stock FROM bill_invoice_lines l LEFT JOIN bill_items it "
                                   "ON it.id=l.item_id WHERE l.invoice_id=?", (iid,)).fetchall():
                if ln["item_id"] and ln["track_stock"]:
                    conn.execute("UPDATE bill_items SET stock = stock + ? WHERE id=?", (ln["qty"], ln["item_id"]))
                    conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                                 (ln["item_id"], ln["qty"], "invoice cancelled", inv["number"], now_iso(), u["username"]))
            conn.execute("UPDATE bill_invoices SET status='cancelled', cancelled_by=?, cancelled_at=? WHERE id=?",
                         (u["username"], now_iso(), iid))
            conn.commit()
        audit(u["username"], "billing.invoice.cancel", inv["number"])
        return {"ok": True}

    @app.get("/api/billing/invoices/{iid}/pdf")
    def invoice_pdf_ep(iid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            data = invoice_pdf(conn, iid)
            num = conn.execute("SELECT number FROM bill_invoices WHERE id=?", (iid,)).fetchone()[0]
        return _pdf_response(data, num)

    # ---- receipts
    @app.get("/api/billing/receipts")
    def list_receipts(request: Request, party_id: int = 0):
        staff(request)
        with closing(db()) as conn:
            rows = conn.execute("SELECT r.*, p.name party, p.code party_code, i.number invoice_number FROM bill_receipts r "
                                "JOIN bill_parties p ON p.id=r.party_id LEFT JOIN bill_invoices i ON i.id=r.invoice_id "
                                + ("WHERE r.party_id=? " if party_id else "") + "ORDER BY r.rcp_date DESC, r.id DESC LIMIT 500",
                                (party_id,) if party_id else ()).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.post("/api/billing/receipts")
    def create_receipt(body: ReceiptIn, request: Request):
        u = staff(request)
        rdate = valid_date(body.rcp_date) if body.rcp_date else today()
        mode = body.mode if body.mode in MODES else "other"
        with closing(db()) as conn:
            S = settings(conn)
            if not conn.execute("SELECT 1 FROM bill_parties WHERE id=?", (body.party_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Account not found.")
            if body.invoice_id:
                inv = conn.execute("SELECT party_id, status FROM bill_invoices WHERE id=?", (body.invoice_id,)).fetchone()
                if not inv or inv["party_id"] != body.party_id:
                    raise HTTPException(status_code=422, detail="That invoice does not belong to this account.")
                if inv["status"] == "cancelled":
                    raise HTTPException(status_code=422, detail="That invoice is cancelled.")
            fy = fy_of(rdate)
            seq = next_seq(conn, "bill_receipts", fy)
            number = "%s/%s/%04d" % (S.get("receipt_prefix") or "RCP", fy, seq)
            cur = conn.execute("INSERT INTO bill_receipts (number,fy,seq,party_id,invoice_id,rcp_date,amount,mode,reference,notes,"
                               "created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (number, fy, seq, body.party_id, body.invoice_id, rdate, float(D(body.amount)), mode,
                                body.reference.strip(), body.notes.strip(), u["username"], now_iso()))
            if body.invoice_id:
                refresh_invoice_status(conn, body.invoice_id)
            conn.commit()
        audit(u["username"], "billing.receipt.create", "%s amount %s" % (number, D(body.amount)))
        return {"ok": True, "id": cur.lastrowid, "number": number}

    @app.post("/api/billing/receipts/{rid}/cancel")
    def cancel_receipt(rid: int, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            r = conn.execute("SELECT * FROM bill_receipts WHERE id=?", (rid,)).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            conn.execute("UPDATE bill_receipts SET status='cancelled', cancelled_by=?, cancelled_at=? WHERE id=?",
                         (u["username"], now_iso(), rid))
            if r["invoice_id"]:
                refresh_invoice_status(conn, r["invoice_id"])
            conn.commit()
        audit(u["username"], "billing.receipt.cancel", r["number"])
        return {"ok": True}

    @app.get("/api/billing/receipts/{rid}/pdf")
    def receipt_pdf_ep(rid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            data = receipt_pdf(conn, rid)
            num = conn.execute("SELECT number FROM bill_receipts WHERE id=?", (rid,)).fetchone()[0]
        return _pdf_response(data, num)

    # ---- reports
    @app.get("/api/billing/report")
    def report(request: Request, fy: str = "", period: str = "FY"):
        staff(request)
        fy = fy or fy_of(today_ist())
        with closing(db()) as conn:
            r = report_data(conn, fy, period)
        f = lambda v: float(v)
        return {**{k: r[k] for k in ("fy", "period", "from", "to", "invoices", "cancelled")},
                "totals": {k: f(v) for k, v in r["totals"].items()}, "received": f(r["received"]),
                "received_by_mode": {k: f(v) for k, v in r["received_by_mode"].items()},
                "months": {m: {k: (f(v) if isinstance(v, Decimal) else v) for k, v in d.items()} for m, d in r["months"].items()},
                "by_category": {k: f(v) for k, v in r["by_category"].items()}, "outstanding_now": f(r["outstanding_now"])}

    @app.get("/api/billing/report.csv")
    def report_csv(request: Request, fy: str = "", period: str = "FY"):
        staff(request)
        fy = fy or fy_of(today_ist())
        with closing(db()) as conn:
            r = report_data(conn, fy, period)
        out = [["Sales & GST register", "FY " + fy, period, r["from"], r["to"]], [],
               ["Date", "Invoice No", "Account code", "Account", "GSTIN", "State", "Taxable", "CGST", "SGST", "IGST",
                "Round off", "Total", "Received", "Status"]]
        for i in r["register"]:
            out.append([i["inv_date"], i["number"], i["pcode"], i["party"], i["pgstin"] or "", i["pstate"] or "",
                        "%.2f" % i["subtotal"], "%.2f" % i["cgst"], "%.2f" % i["sgst"], "%.2f" % i["igst"],
                        "%.2f" % i["round_off"], "%.2f" % i["total"], "%.2f" % (i["paid"] or 0), i["status"]])
        t = r["totals"]
        out += [[], ["Totals (excluding cancelled)", "", "", "", "", "", "%.2f" % t["subtotal"], "%.2f" % t["cgst"],
                     "%.2f" % t["sgst"], "%.2f" % t["igst"], "%.2f" % t["round_off"], "%.2f" % t["total"]],
                ["Received in period", "%.2f" % r["received"]], ["Outstanding (all accounts, today)", "%.2f" % r["outstanding_now"]]]
        return _csv_response(out, "sales-register-%s-%s" % (fy, period))

    @app.get("/api/billing/report.pdf")
    def report_pdf_ep(request: Request, fy: str = "", period: str = "FY"):
        staff(request)
        fy = fy or fy_of(today_ist())
        with closing(db()) as conn:
            data = report_pdf(conn, fy, period)
        return _pdf_response(data, "sales-report-%s-%s" % (fy, period))

    # ---- client portal: own invoices and receipts
    def client(request):
        s = get_session(request.cookies.get("ate_cli"))
        if not s or s["user_type"] != "client":
            raise HTTPException(status_code=401, detail="Please sign in.")
        return s["user_id"]

    @app.get("/api/client/billing")
    def client_billing(request: Request):
        cid = client(request)
        with closing(db()) as conn:
            parties = [r["id"] for r in conn.execute("SELECT id FROM bill_parties WHERE client_id=?", (cid,))]
            if not parties:
                return {"invoices": [], "receipts": [], "balance": 0}
            marks = ",".join("?" * len(parties))
            invs = [dict(r) for r in conn.execute("SELECT id, number, inv_date, due_date, total, paid, status FROM bill_invoices "
                                                  "WHERE status!='cancelled' AND party_id IN (%s) ORDER BY inv_date DESC" % marks, parties)]
            rcps = [dict(r) for r in conn.execute("SELECT id, number, rcp_date, amount, mode FROM bill_receipts WHERE status='ok' "
                                                  "AND party_id IN (%s) ORDER BY rcp_date DESC" % marks, parties)]
            bal = sum((party_balance(conn, p) for p in parties), D(0))
        return {"invoices": invs, "receipts": rcps, "balance": float(bal)}

    @app.get("/api/client/billing/invoices/{iid}/pdf")
    def client_invoice_pdf(iid: int, request: Request):
        cid = client(request)
        with closing(db()) as conn:
            ok = conn.execute("SELECT i.number FROM bill_invoices i JOIN bill_parties p ON p.id=i.party_id "
                              "WHERE i.id=? AND p.client_id=? AND i.status!='cancelled'", (iid, cid)).fetchone()
            if not ok:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            data = invoice_pdf(conn, iid)
        return _pdf_response(data, ok[0])

    @app.get("/api/client/billing/receipts/{rid}/pdf")
    def client_receipt_pdf(rid: int, request: Request):
        cid = client(request)
        with closing(db()) as conn:
            ok = conn.execute("SELECT r.number FROM bill_receipts r JOIN bill_parties p ON p.id=r.party_id "
                              "WHERE r.id=? AND p.client_id=? AND r.status='ok'", (rid, cid)).fetchone()
            if not ok:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            data = receipt_pdf(conn, rid)
        return _pdf_response(data, ok[0])
