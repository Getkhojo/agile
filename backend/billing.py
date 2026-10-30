"""Billing: inventory, customer accounts, GST invoices, receipts, ledgers and period reports.

Who can use it: employees with role 'admin' or 'accounts'.

Money is computed on the server with Decimal (2 decimals, half-up). GST per invoice line:
  taxable = qty x rate - discount
  CGST = taxable x rate/2   (if CGST is ticked)
  SGST = taxable x rate/2   (if SGST is ticked)
  IGST = taxable x rate     (if IGST is ticked)
The person billing decides which of CGST / SGST / IGST apply (the form pre-ticks CGST+SGST for the
company's own state and IGST otherwise). Numbers follow the Indian financial year (April-March) and a
format chosen in settings. Item codes: HW-0001 hardware, SW-0001 software, SV-0001 services.
Accounts: ACC-0001. Every account keeps its full history (ledger) for as long as it exists.
The tax invoice PDF follows the usual Tally layout.
"""
import base64
import csv
import io
import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

TWO = Decimal("0.01")
CATEGORIES = {"hardware": "HW", "software": "SW", "service": "SV"}
MODES = ("cash", "upi", "bank", "cheque", "card", "other")
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}
META_FIELDS = ("delivery_note", "payment_terms", "supplier_ref", "other_ref", "buyer_order_no", "buyer_order_date",
               "despatch_doc_no", "delivery_note_date", "despatched_through", "destination", "terms_of_delivery")
OLD_DEFAULTS = {"company_name": "Agile Tech Experts Pvt. Ltd.",
                "address": "Casa Greens 1, Greater Noida West, opp. BLS World School, Uttar Pradesh"}
DEFAULT_SETTINGS = {
    "company_name": "AGILE TECH EXPERTS PRIVATE LIMITED",
    "address": "1st Floor, A2-104, GH-04A, Casa Greens 1, Sector 16\nNoida, Gautam Buddha Nagar\nUttar Pradesh - 201306",
    "state": "Uttar Pradesh", "state_code": "09", "gstin": "09ABCCA0070G1Z2", "pan": "ABCCA0070G", "cin": "",
    "phone": "+91 98100 57579", "email": "info@agiletechexpert.com",
    "bank_name": "KOTAK MAHINDRA BANK LTD", "bank_account": "9917661331", "bank_ifsc": "KKBK0005032",
    "bank_branch": "NOIDA - SECTOR 62", "bank_address": "C-25/SG-16, Stellar IT Park, Noida 201309",
    "upi": "agiletech@kotak", "upi_qr": "1",
    "invoice_prefix": "AGILE", "receipt_prefix": "AGILE/RCP", "invoice_format": "{prefix}/{fy}/{seq}", "invoice_start": "1",
    "terms": "Goods once sold will not be taken back. Subject to Noida jurisdiction.",
    "declaration": "We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.",
    "round_off": "1", "stamp": "",
}
NUMBER_FORMATS = ("{prefix}/{fy}/{seq}", "{prefix}/{seq}/{fys}", "{prefix}/{fys}/{seq}", "{prefix}-{seq}")


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


def tdate(s):
    """2026-10-16 -> 16-Oct-2026 (Tally style)."""
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d-%b-%Y")
    except Exception:
        return str(s or "")


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


def qty_txt(q):
    return ("%.3f" % float(q)).rstrip("0").rstrip(".")


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n):
    h, r = divmod(n, 100)
    return ((_ONES[h] + " Hundred" + (" " if r else "")) if h else "") + (_two(r) if r else "")


def _int_words(n):
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10000000)
    lakh, n = divmod(n, 100000)
    thousand, rest = divmod(n, 1000)
    if crore:
        parts.append(_int_words(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if rest:
        parts.append(_three(rest))
    return " ".join(parts)


def words(amount):
    """Tally style: INR Ninety Thousand Eight Hundred Sixty Only."""
    amount = abs(D(amount))
    rupees = int(amount)
    paise = int(((amount - rupees) * 100).to_integral_value())
    return "INR " + _int_words(rupees) + ((" and " + _two(paise) + " paise") if paise else "") + " Only"


# ------------------------------------------------------------------ schema
def _add_columns(conn, table, cols):
    have = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    for name, decl in cols:
        if name not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))


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
        CREATE TABLE IF NOT EXISTS bill_serials (
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, serial TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_stock', origin TEXT DEFAULT 'stock', invoice_id INTEGER,
            added_at TEXT, added_by TEXT, UNIQUE(item_id, serial));
        CREATE INDEX IF NOT EXISTS ix_binv_party ON bill_invoices(party_id);
        CREATE INDEX IF NOT EXISTS ix_brcp_party ON bill_receipts(party_id);
        CREATE INDEX IF NOT EXISTS ix_bline_inv ON bill_invoice_lines(invoice_id);
        CREATE INDEX IF NOT EXISTS ix_bser_inv ON bill_serials(invoice_id);
        """)
        _add_columns(conn, "bill_items", [("description", "TEXT DEFAULT ''"), ("track_serial", "INTEGER DEFAULT 0")])
        _add_columns(conn, "bill_invoice_lines", [("description", "TEXT DEFAULT ''"), ("serials", "TEXT DEFAULT ''"),
                                                  ("discount_pct", "REAL DEFAULT 0")])
        _add_columns(conn, "bill_invoices", [("meta", "TEXT DEFAULT '{}'"), ("ship_to", "TEXT DEFAULT ''"),
                                             ("updated_by", "TEXT"), ("updated_at", "TEXT")])
        _add_columns(conn, "bill_stock_moves", [("rate", "REAL"), ("supplier", "TEXT")])
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO bill_settings (key, value) VALUES (?, ?)", (k, v))
        # one-time upgrade of the first version's placeholders to the registered company details
        cur = settings(conn)
        for k in ("gstin", "pan", "bank_name", "bank_account", "bank_ifsc", "bank_branch", "bank_address", "upi"):
            if not cur.get(k):
                conn.execute("UPDATE bill_settings SET value=? WHERE key=?", (DEFAULT_SETTINGS[k], k))
        if cur.get("invoice_prefix") == "INV":       # owner asked for AGILE/2026-27/0001
            conn.execute("UPDATE bill_settings SET value='AGILE' WHERE key='invoice_prefix'")
        if cur.get("receipt_prefix") == "RCP":       # every number starts with AGILE
            conn.execute("UPDATE bill_settings SET value='AGILE/RCP' WHERE key='receipt_prefix'")
        for k, old in OLD_DEFAULTS.items():
            if cur.get(k) == old:
                conn.execute("UPDATE bill_settings SET value=? WHERE key=?", (DEFAULT_SETTINGS[k], k))
        conn.commit()


def settings(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM bill_settings")}


def next_seq(conn, table, fy, start=1):
    n = (conn.execute("SELECT COALESCE(MAX(seq), 0) FROM %s WHERE fy=?" % table, (fy,)).fetchone()[0] or 0) + 1
    return max(n, start)


def format_number(fmt, prefix, fy, seq):
    fmt = fmt if fmt in NUMBER_FORMATS else NUMBER_FORMATS[0]
    return fmt.format(prefix=prefix, fy=fy, fys=fy[2:], seq="%04d" % seq)


def next_invoice_number(conn, S, fy):
    try:
        start = max(1, int(S.get("invoice_start") or 1))
    except ValueError:
        start = 1
    seq = next_seq(conn, "bill_invoices", fy, start)
    while True:
        number = format_number(S.get("invoice_format"), S.get("invoice_prefix") or "INV", fy, seq)
        if not conn.execute("SELECT 1 FROM bill_invoices WHERE number=?", (number,)).fetchone():
            return seq, number
        seq += 1


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
        gross = (qty * rate).quantize(TWO, rounding=ROUND_HALF_UP)
        disc = (gross * Decimal(str(ln.get("discount_pct") or 0)) / 100).quantize(TWO, rounding=ROUND_HALF_UP)
        taxable = gross - disc
        c = (taxable * gst / 200).quantize(TWO, rounding=ROUND_HALF_UP) if apply_cgst else D(0)
        s = (taxable * gst / 200).quantize(TWO, rounding=ROUND_HALF_UP) if apply_sgst else D(0)
        i = (taxable * gst / 100).quantize(TWO, rounding=ROUND_HALF_UP) if apply_igst else D(0)
        out.append({**ln, "taxable": taxable, "cgst": c, "sgst": s, "igst": i, "total": taxable + c + s + i})
        sub, cg, sg, ig = sub + taxable, cg + c, sg + s, ig + i
    return out, sub, cg, sg, ig


def split_serials(text):
    out, seen = [], set()
    for s in re.split(r"[\n,;]+", text or ""):
        s = s.strip()
        if s and s.upper() not in seen:
            seen.add(s.upper())
            out.append(s[:60])
    return out


def reset_billing(conn, scope="transactions"):
    """Delete billing entries (used to clear test data). scope: transactions | all. Company settings are kept."""
    for t in ("bill_invoice_lines", "bill_invoices", "bill_receipts", "bill_stock_moves", "bill_serials"):
        conn.execute("DELETE FROM %s" % t)
    if scope == "all":
        conn.execute("DELETE FROM bill_items")
        conn.execute("DELETE FROM bill_parties")
    else:
        conn.execute("UPDATE bill_items SET stock=0")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('bill_invoices','bill_invoice_lines','bill_receipts',"
                 "'bill_stock_moves','bill_serials'%s)" % (",'bill_items','bill_parties'" if scope == "all" else ""))
    conn.commit()


# ------------------------------------------------------------------ request models
class SettingsIn(BaseModel):
    values: dict


class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    gstin: str = Field(default="", max_length=15)
    state: str = Field(default="", max_length=60)
    state_code: str = Field(default="", max_length=2)
    address: str = Field(default="", max_length=600)
    phone: str = Field(default="", max_length=25)
    email: str = Field(default="", max_length=160)
    client_id: int | None = None
    opening_balance: float = 0


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="hardware", max_length=20)
    description: str = Field(default="", max_length=600)
    hsn: str = Field(default="", max_length=10)
    unit: str = Field(default="pcs", max_length=20)
    price: float = Field(default=0, ge=0)
    gst_rate: float = Field(default=18, ge=0, le=28)
    track_stock: bool = False
    track_serial: bool = False
    stock: float = 0


class StockIn(BaseModel):
    qty: float = 0
    reason: str = Field(default="purchase", max_length=40)
    ref: str = Field(default="", max_length=80)
    supplier: str = Field(default="", max_length=120)
    rate: float | None = None
    serials: str = Field(default="", max_length=20000)


class LineIn(BaseModel):
    item_id: int | None = None
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=600)
    serials: str = Field(default="", max_length=4000)
    hsn: str = Field(default="", max_length=10)
    unit: str = Field(default="pcs", max_length=20)
    qty: float = Field(gt=0, le=1000000)
    rate: float = Field(ge=0, le=100000000)
    discount_pct: float = Field(default=0, ge=0, le=100)
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
    ship_to: str = Field(default="", max_length=600)
    meta: dict = Field(default_factory=dict)
    number_seq: int | None = Field(default=None, ge=1, le=999999)   # manual invoice number (the running part)
    lines: list[LineIn] = Field(min_length=1, max_length=150)


class ReceiptIn(BaseModel):
    party_id: int
    invoice_id: int | None = None
    rcp_date: str = ""
    amount: float = Field(gt=0, le=1000000000)
    mode: str = Field(default="bank", max_length=10)
    reference: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=500)


def clean_meta(meta):
    return {k: str(meta.get(k) or "").strip()[:120] for k in META_FIELDS if str(meta.get(k) or "").strip()}


# ------------------------------------------------------------------ PDF helpers
def _pdf_doc(buf, title, on_page=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.units import mm
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                             bottomMargin=14 * mm, title=title, author="Agile Tech Expert")


def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib import colors
    ss = getSampleStyleSheet()
    teal = colors.HexColor("#0b6f6a")
    return {
        "h": ParagraphStyle("h", parent=ss["Title"], fontSize=13, alignment=0, spaceAfter=2, leading=16),
        "t": ParagraphStyle("t", parent=ss["Heading2"], fontSize=12, spaceBefore=4, spaceAfter=4),
        "n": ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=11),
        "b": ParagraphStyle("b", parent=ss["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"),
        "s": ParagraphStyle("s", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4b6b70")),
        "teal": teal,
    }


def _esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _br(s):
    return "<br/>".join(_esc(x) for x in str(s or "").splitlines() if x.strip())


def _table(data, widths, header=True, right_cols=(), bold_last=False):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8)]
    for c in right_cols:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if bold_last:
        st.append(("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8))
    t.setStyle(TableStyle(st))
    return t


def _company_block(S, st):
    from reportlab.platypus import Paragraph
    lines = [_br(S.get("address"))]
    if S.get("gstin"):
        lines.append("GSTIN/UIN: %s" % _esc(S["gstin"]) + (" &nbsp; State Name: %s, Code: %s" % (_esc(S.get("state")), _esc(S.get("state_code"))) if S.get("state") else ""))
    if S.get("pan"):
        lines.append("PAN: %s" % _esc(S["pan"]))
    lines.append(" &nbsp; ".join(x for x in [_esc(S.get("phone")), _esc(S.get("email"))] if x))
    return [Paragraph(_esc(S.get("company_name")), st["h"]), Paragraph("<br/>".join(lines), st["n"])]


def _rupee_font():
    """A TTF with the rupee sign if the server has one; otherwise None (we print 'INR' instead)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "ATE-Sans-Bold" in pdfmetrics.getRegisteredFontNames():
        return "ATE-Sans-Bold"
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("ATE-Sans-Bold", path))
            return "ATE-Sans-Bold"
        except Exception:
            continue
    return None


def _stamp_image(S, max_w, max_h):
    data = S.get("stamp") or ""
    if not data.startswith("data:image/"):
        return None
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image
        raw = base64.b64decode(data.split(",", 1)[1])
        ir = ImageReader(io.BytesIO(raw))
        w, h = ir.getSize()
        k = min(max_w / w, max_h / h)
        img = Image(io.BytesIO(raw), width=w * k, height=h * k)
        img.hAlign = "RIGHT"
        return img
    except Exception:
        return None


def _upi_qr(S, amount, note, size):
    """UPI payment QR (amount and invoice number pre-filled). None when no UPI ID or QR is switched off."""
    from urllib.parse import quote
    vpa = (S.get("upi") or "").strip()
    if not vpa or S.get("upi_qr", "1") != "1" or D(amount) <= 0:
        return None
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    uri = "upi://pay?pa=%s&pn=%s&am=%s&cu=INR&tn=%s" % (quote(vpa, safe="@."), quote(S.get("company_name") or ""),
                                                         "%.2f" % D(amount), quote(("Invoice " + note)[:50]))
    w = QrCodeWidget(uri)
    w.barLevel = "M"
    x1, y1, x2, y2 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    d.add(w)
    return d


def _page_decor(mark, footer="This is a Computer Generated Invoice", number=""):
    """Footer line, page number, and an optional diagonal watermark (CANCELLED / PREVIEW)."""
    def draw(canvas, doc):
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        w, h = doc.pagesize
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(w / 2, 8 * mm, footer)
        canvas.drawRightString(w - 12 * mm, 8 * mm, "Page %d" % canvas.getPageNumber())
        if number and canvas.getPageNumber() > 1:
            canvas.setFont("Helvetica-Bold", 8.5)
            canvas.drawString(12 * mm, h - 7 * mm, "Tax Invoice %s (continued)" % number)
        if mark:
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.18))
            canvas.setFont("Helvetica-Bold", 70)
            canvas.translate(w / 2, h / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, mark)
        canvas.restoreState()
    return draw


# ------------------------------------------------------------------ tax invoice (Tally layout)
def render_invoice(S, inv, party, lines, mark="", compact=False):
    """inv: dict with number, inv_date, place_of_supply, apply_*, subtotal, cgst, sgst, igst, round_off, total,
    notes, ship_to, meta (dict). party: dict. lines: list of dicts (name, description, serials, hsn, unit, qty,
    rate, discount_pct, gst_rate, taxable, cgst, sgst, igst)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    K = colors.black
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.2, leading=10)
    small = ParagraphStyle("small", parent=base, fontSize=7.3, leading=9)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    big = ParagraphStyle("big", parent=base, fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=TA_CENTER)
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    right_b = ParagraphStyle("rightb", parent=bold, alignment=TA_RIGHT)
    right_bi = ParagraphStyle("rightbi", parent=base, fontName="Helvetica-BoldOblique", alignment=TA_RIGHT)
    item_name = ParagraphStyle("iname", parent=base, fontName="Helvetica-Bold", fontSize=8.6, leading=10.5)
    meta = inv.get("meta") or {}
    W = 186 * mm
    pad0 = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
    story = [Paragraph("Tax Invoice", title), Spacer(1, 2 * mm)]

    # ---- header: seller / consignee / buyer on the left, voucher details on the right
    def seller():
        out = "<font size=9.5><b>%s</b></font><br/>%s" % (_esc(S.get("company_name")), _br(S.get("address")))
        if S.get("gstin"):
            out += "<br/>GSTIN/UIN: %s" % _esc(S["gstin"])
        out += "<br/>State Name : %s, Code : %s" % (_esc(S.get("state")), _esc(S.get("state_code")))
        if S.get("cin"):
            out += "<br/>CIN: %s" % _esc(S["cin"])
        contact = " &nbsp; ".join(x for x in ["Ph: " + _esc(S["phone"]) if S.get("phone") else "",
                                               "E-Mail : " + _esc(S["email"]) if S.get("email") else ""] if x)
        if contact:
            out += "<br/>" + contact
        return Paragraph(out, base)

    def buyer():
        p = party
        sc = p.get("state_code") or (p.get("gstin") or "")[:2]
        out = "<font size=7.3>Buyer (Bill to)</font><br/><font size=9.5><b>%s</b></font>" % _esc(p.get("name"))
        if p.get("address"):
            out += "<br/>" + _br(p["address"])
        out += "<br/>GSTIN/UIN &nbsp; &nbsp; : %s" % (_esc(p.get("gstin")) or "Unregistered")
        if p.get("state"):
            out += "<br/>State Name &nbsp; : %s%s" % (_esc(p["state"]), (", Code : %s" % _esc(sc)) if sc else "")
        out += "<br/>Place of Supply : %s" % _esc(inv.get("place_of_supply") or p.get("state") or "")
        if p.get("phone"):
            out += "<br/>Contact &nbsp; &nbsp; &nbsp; &nbsp; : %s" % _esc(p["phone"])
        return Paragraph(out, base)

    left_rows = [[seller()]]
    if (inv.get("ship_to") or "").strip():
        left_rows.append([Paragraph("<font size=7.3>Consignee (Ship to)</font><br/>%s" % _br(inv["ship_to"]), base)])
    left_rows.append([buyer()])
    left = Table(left_rows, colWidths=[98 * mm])
    left.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), 0.6, K), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    def cell(label, value, strong=False):
        v = _esc(value)
        return Paragraph("<font size=7.3>%s</font><br/>%s" % (label, ("<b>%s</b>" % v) if strong else ("<b>%s</b>" % v if v else "&nbsp;")), base)

    m = lambda k: meta.get(k, "")
    right_data = [
        [cell("Invoice No.", inv.get("number"), True), cell("Dated", tdate(inv.get("inv_date")), True)],
        [cell("Delivery Note", m("delivery_note")), cell("Mode/Terms of Payment", m("payment_terms"))],
        [cell("Supplier's Ref.", m("supplier_ref")), cell("Other Reference(s)", m("other_ref"))],
        [cell("Buyer's Order No.", m("buyer_order_no")), cell("Dated", tdate(m("buyer_order_date")) if m("buyer_order_date") else "")],
        [cell("Despatch Document No.", m("despatch_doc_no")), cell("Delivery Note Date", tdate(m("delivery_note_date")) if m("delivery_note_date") else "")],
        [cell("Despatched through", m("despatched_through")), cell("Destination", m("destination"))],
        [Paragraph("<font size=7.3>Terms of Delivery</font><br/>%s" % _br(m("terms_of_delivery")), base), ""],
    ]
    right_t = Table(right_data, colWidths=[44 * mm, 44 * mm])
    right_t.setStyle(TableStyle([("INNERGRID", (0, 0), (-1, -2), 0.6, K), ("LINEBELOW", (0, -2), (-1, -2), 0.6, K),
                                 ("SPAN", (0, -1), (1, -1)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    head = Table([[left, right_t]], colWidths=[98 * mm, 88 * mm])
    head.setStyle(TableStyle(pad0 + [("BOX", (0, 0), (-1, -1), 0.8, K), ("LINEAFTER", (0, 0), (0, 0), 0.6, K),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(head)

    # ---- items
    has_disc = any(float(l.get("discount_pct") or 0) for l in lines)
    cols = ["Sl\nNo.", "Description of Goods", "HSN/SAC", "GST\nRate", "Quantity", "Rate", "per"] + (["Disc. %"] if has_disc else []) + ["Amount"]
    widths = [8, 0, 18, 12, 19, 20, 10] + ([11] if has_disc else []) + [27]
    widths[1] = 186 - sum(widths)
    hdr = [Paragraph(c.replace("\n", "<br/>"), ParagraphStyle("hc", parent=small, alignment=TA_CENTER)) for c in cols]
    rows = [hdr]
    for i, ln in enumerate(lines, 1):
        desc = "<b>%s</b>" % _esc(ln.get("name"))
        if (ln.get("description") or "").strip():
            desc += "<br/><font size=7.6><i>%s</i></font>" % _br(ln["description"])
        sers = split_serials(ln.get("serials"))
        if sers:
            desc += "<br/><font size=7.3><i>Serial No.: %s</i></font>" % _esc(", ".join(sers))
        unit = (ln.get("unit") or "").upper()
        row = [Paragraph(str(i), base), Paragraph(desc, ParagraphStyle("d", parent=base, leading=10.2)), Paragraph(_esc(ln.get("hsn")), base),
               Paragraph("%s %%" % qty_txt(ln.get("gst_rate") or 0), right),
               Paragraph("<b>%s %s</b>" % (qty_txt(ln.get("qty")), _esc(unit)), right),
               Paragraph(inr(ln.get("rate")), right), Paragraph(_esc(unit), base)]
        if has_disc:
            row.append(Paragraph(("%s %%" % qty_txt(ln["discount_pct"])) if float(ln.get("discount_pct") or 0) else "", right))
        row.append(Paragraph("<b>%s</b>" % inr(ln.get("taxable")), right))
        rows.append(row)
    n_item_rows = len(rows)
    amt = len(cols) - 1
    blank = [""] * len(cols)
    # subtotal + tax lines in the "Description" column, Tally style
    sub_row = list(blank); sub_row[amt] = Paragraph(inr(inv.get("subtotal")), right)
    rows.append(sub_row)
    tax_rows = []
    for key, label in (("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST")):
        if inv.get("apply_" + key):
            r = list(blank); r[1] = Paragraph(label, right_bi); r[amt] = Paragraph("<b>%s</b>" % inr(inv.get(key)), right)
            rows.append(r); tax_rows.append(len(rows) - 1)
    if D(inv.get("round_off") or 0) != 0:
        ro = D(inv["round_off"])
        r = list(blank); r[1] = Paragraph("Round Off", right_bi)
        r[amt] = Paragraph(("(-)%s" % inr(-ro)) if ro < 0 else inr(ro), right)
        rows.append(r)
    # blank row that stretches so a short invoice fills exactly one page (measured after the story is built)
    rows.append(list(blank))
    units = {(l.get("unit") or "").upper() for l in lines}
    tq = sum(Decimal(str(l.get("qty") or 0)) for l in lines)
    total_row = list(blank)
    total_row[1] = Paragraph("Total", right)
    if len(units) == 1:
        total_row[4] = Paragraph("<b>%s %s</b>" % (qty_txt(tq), _esc(units.pop())), right)
    rf = _rupee_font()
    total_txt = "<b>%s</b>" % inr(inv.get("total")) + ((" <font name='%s'>₹</font>" % rf) if rf else "")
    total_row[amt] = Paragraph(total_txt, ParagraphStyle("tot", parent=right_b, fontSize=10, leading=12))
    rows.append(total_row)
    ist = [("BOX", (0, 0), (-1, -1), 0.8, K), ("LINEBELOW", (0, 0), (-1, 0), 0.6, K),
           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
           ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
           ("LINEABOVE", (amt, n_item_rows), (amt, n_item_rows), 0.6, K),
           ("LINEABOVE", (0, -1), (-1, -1), 0.6, K), ("LINEBELOW", (0, "splitlast"), (-1, "splitlast"), 0.8, K)]
    for c in range(1, len(cols)):
        ist.append(("LINEBEFORE", (c, 0), (c, -1), 0.6, K))

    def items_table(filler_pt):
        heights = [None] * len(rows)
        heights[-2] = filler_pt
        t = Table(rows, colWidths=[w * mm for w in widths], rowHeights=heights, repeatRows=1)
        t.setStyle(TableStyle(ist))
        return t
    items_at = len(story)
    story.append(items_table(4 * mm))

    # ---- amount in words
    words_t = Table([[Paragraph("<font size=7.3>Amount Chargeable (in words)</font>", base), Paragraph("<i>E. &amp; O.E</i>", right)],
                     [Paragraph("<b>%s</b>" % words(inv.get("total")), big), ""]], colWidths=[150 * mm, 36 * mm])
    words_t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, K), ("SPAN", (0, 1), (1, 1)),
                                 ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
    story.append(words_t)

    # ---- HSN/SAC summary
    groups = {}
    for ln in lines:
        k = (ln.get("hsn") or "", float(ln.get("gst_rate") or 0))
        g = groups.setdefault(k, {"taxable": D(0), "cgst": D(0), "sgst": D(0), "igst": D(0)})
        for f in g:
            g[f] += D(ln.get(f) or 0)
    taxes = [(k, n) for k, n in (("cgst", "Central Tax"), ("sgst", "State/UT Tax"), ("igst", "Integrated Tax")) if inv.get("apply_" + k)]
    hsn_w = 186 - 24 - 24 - 34 * len(taxes)
    head1 = [Paragraph("HSN/SAC", ParagraphStyle("c", parent=small, alignment=TA_CENTER)), Paragraph("Taxable<br/>Value", ParagraphStyle("c2", parent=small, alignment=TA_CENTER))]
    head2 = ["", ""]
    for _, name in taxes:
        head1 += [Paragraph(name, ParagraphStyle("c3", parent=small, alignment=TA_CENTER)), ""]
        head2 += [Paragraph("Rate", ParagraphStyle("c4", parent=small, alignment=TA_CENTER)), Paragraph("Amount", ParagraphStyle("c5", parent=small, alignment=TA_CENTER))]
    head1.append(Paragraph("Total<br/>Tax Amount", ParagraphStyle("c6", parent=small, alignment=TA_CENTER)))
    head2.append("")
    hrows = [head1, head2]
    tot = {"taxable": D(0), "cgst": D(0), "sgst": D(0), "igst": D(0)}
    for (hsn, rate), g in sorted(groups.items()):
        r = [Paragraph(_esc(hsn) or "-", base), Paragraph(inr(g["taxable"]), right)]
        tt = D(0)
        for k, _ in taxes:
            rr = rate / 2 if k in ("cgst", "sgst") else rate
            r += [Paragraph("%s%%" % qty_txt(rr), right), Paragraph(inr(g[k]), right)]
            tt += g[k]
        r.append(Paragraph(inr(tt), right))
        hrows.append(r)
        for f in tot:
            tot[f] += g[f]
    trow = [Paragraph("Total", right_b), Paragraph("<b>%s</b>" % inr(tot["taxable"]), right)]
    for k, _ in taxes:
        trow += ["", Paragraph("<b>%s</b>" % inr(tot[k]), right)]
    tax_total = sum((tot[k] for k, _ in taxes), D(0))
    trow.append(Paragraph("<b>%s</b>" % inr(tax_total), right))
    hrows.append(trow)
    hw = [hsn_w, 24] + [12, 22] * len(taxes) + [24]
    hsn_t = Table(hrows, colWidths=[w * mm for w in hw], repeatRows=2)
    hst = [("BOX", (0, 0), (-1, -1), 0.8, K), ("INNERGRID", (0, 0), (-1, 1), 0.6, K),
           ("LINEBEFORE", (1, 2), (-1, -1), 0.6, K), ("LINEABOVE", (0, -1), (-1, -1), 0.6, K),
           ("LINEBELOW", (0, 1), (-1, 1), 0.6, K), ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)),
           ("SPAN", (-1, 0), (-1, 1)), ("VALIGN", (0, 0), (-1, 1), "MIDDLE"),
           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
           ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5)]
    for i in range(len(taxes)):
        hst.append(("SPAN", (2 + 2 * i, 0), (3 + 2 * i, 0)))
    hsn_t.setStyle(TableStyle(hst))
    story.append(hsn_t)

    # ---- tax in words, PAN, declaration, bank, signature
    bank = []
    for label, key in (("Bank Name", "bank_name"), ("A/c No.", "bank_account"), ("Branch &amp; IFS Code", None), ("UPI", "upi")):
        if key is None:
            val = " &amp; ".join(_esc(x) for x in (S.get("bank_branch"), S.get("bank_ifsc")) if x)
        else:
            val = _esc(S.get(key))
        if val:
            bank.append("<font size=7.6>%s</font> : <b>%s</b>" % (label, val))
    left_f = "<font size=7.6>Company's PAN</font> &nbsp; : <b>%s</b>" % _esc(S.get("pan"))
    if inv.get("notes"):
        left_f = "<font size=7.6>Remarks:</font><br/>%s<br/><br/>" % _br(inv["notes"]) + left_f
    left_f += "<br/><u><font size=7.3>Declaration</font></u><br/><font size=7.3>%s</font>" % _esc(S.get("declaration"))
    if S.get("terms"):
        left_f += "<br/><font size=7.3>%s</font>" % _esc(S["terms"])
    if S.get("bank_address"):
        bank.append("<font size=7>%s</font>" % _esc(S["bank_address"]))
    right_f = Paragraph(("<font size=7.6>Company's Bank Details</font><br/>" + "<br/>".join(bank)) if bank else "", base)
    due = D(inv.get("total") or 0) - D(inv.get("paid") or 0)
    qr = _upi_qr(S, due, inv.get("number") or "", (19 if compact else 24) * mm) if mark != "CANCELLED" else None
    if qr:
        right_f = Table([[right_f, [qr, Paragraph("<font size=6.5>Scan to pay %s</font>" % inr(due), ParagraphStyle("q", parent=base, alignment=TA_CENTER))]]],
                        colWidths=[60 * mm, 27 * mm])
        right_f.setStyle(TableStyle(pad0 + [("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    foot = Table([[Paragraph("<font size=7.3>Tax Amount (in words) :</font> &nbsp; <b>%s</b>" % words(tax_total), base), ""],
                  [Paragraph(left_f, base), right_f]], colWidths=[98 * mm, 88 * mm])
    foot.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, K), ("SPAN", (0, 0), (1, 0)), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, 0), 3 if compact else 10)]))
    story.append(foot)
    stamp = _stamp_image(S, (28 if compact else 34) * mm, (13 if compact else 20) * mm)
    sign_right = [Paragraph("<b>for %s</b>" % _esc(S.get("company_name")), right_b)]
    sign_right += [stamp] if stamp else [Spacer(1, (10 if compact else 16) * mm)]
    sign_right.append(Paragraph("<font size=7.6>Authorised Signatory</font>", right))
    sign = Table([[Paragraph("<font size=7.6>Customer's Seal and Signature</font>", base), sign_right]],
                 colWidths=[98 * mm, 88 * mm], rowHeights=[(22 if compact else 30) * mm])
    sign.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, K), ("LINEAFTER", (0, 0), (0, 0), 0.6, K), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    story.append(sign)

    buf = io.BytesIO()
    doc = _pdf_doc(buf, inv.get("number") or "Invoice")
    # measure everything, then give the spare height of page 1 to the blank items row
    avail = doc.height - 12 - 4          # frame padding (6pt top + bottom) and a small safety margin
    used = 0
    for f in story:
        used += f.wrap(W, 100000)[1] + f.getSpaceBefore() + f.getSpaceAfter()
    spare = avail - used
    if spare < 0 and not compact and -spare < 40 * mm:   # only a little over: tighten the footer and try again
        return render_invoice(S, inv, party, lines, mark, compact=True)
    if spare > 0:
        story[items_at] = items_table(4 * mm + spare)
    deco = _page_decor(mark, number=inv.get("number") or "")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


def invoice_pdf(conn, inv_id):
    inv = conn.execute("SELECT * FROM bill_invoices WHERE id=?", (inv_id,)).fetchone()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    p = conn.execute("SELECT * FROM bill_parties WHERE id=?", (inv["party_id"],)).fetchone()
    lines = [dict(r) for r in conn.execute("SELECT * FROM bill_invoice_lines WHERE invoice_id=? ORDER BY id", (inv_id,))]
    d = dict(inv)
    try:
        d["meta"] = json.loads(inv["meta"] or "{}")
    except Exception:
        d["meta"] = {}
    return render_invoice(settings(conn), d, dict(p), lines, "CANCELLED" if inv["status"] == "cancelled" else "")


def receipt_pdf(conn, rcp_id):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    r = conn.execute("SELECT * FROM bill_receipts WHERE id=?", (rcp_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    p = conn.execute("SELECT * FROM bill_parties WHERE id=?", (r["party_id"],)).fetchone()
    inv = conn.execute("SELECT number FROM bill_invoices WHERE id=?", (r["invoice_id"],)).fetchone() if r["invoice_id"] else None
    S = settings(conn)
    K = colors.black
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11)
    center = ParagraphStyle("c", parent=base, alignment=TA_CENTER)
    right = ParagraphStyle("r", parent=base, alignment=TA_RIGHT)
    head = Paragraph("<font size=11><b>%s</b></font><br/>%s<br/>%s%s" % (
        _esc(S.get("company_name")), _br(S.get("address")),
        ("GSTIN/UIN: %s<br/>" % _esc(S["gstin"])) if S.get("gstin") else "",
        "State Name : %s, Code : %s" % (_esc(S.get("state")), _esc(S.get("state_code")))), center)
    stamp = _stamp_image(S, 34 * mm, 18 * mm)
    sign_cell = [Paragraph("<b>for %s</b>" % _esc(S.get("company_name")), right)] + ([stamp] if stamp else [Spacer(1, 14 * mm)]) + \
        [Paragraph("Authorised Signatory", right)]
    through = {"cash": "Cash", "upi": "UPI", "bank": "Bank", "cheque": "Cheque", "card": "Card"}.get(r["mode"] or "", "Other")
    part = "<b>Account :</b><br/>&nbsp; &nbsp; <b>%s</b> (%s)" % (_esc(p["name"]), _esc(p["code"]))
    part += "<br/><br/>&nbsp; &nbsp; <i>Agst Ref</i> &nbsp; %s" % (_esc(inv["number"]) if inv else "On Account")
    part += "<br/><br/><b>Through :</b><br/>&nbsp; &nbsp; %s%s" % (through, (" (Ref: %s)" % _esc(r["reference"])) if r["reference"] else "")
    if r["notes"]:
        part += "<br/><br/><b>On Account of :</b><br/>&nbsp; &nbsp; %s" % _esc(r["notes"])
    part += "<br/><br/><b>Amount (in words) :</b><br/>&nbsp; &nbsp; %s" % words(r["amount"])
    part += "<br/><br/><font size=7.5>Account balance today: %s</font>" % inr(party_balance(conn, r["party_id"]))
    t = Table([[head, ""],
               [Paragraph("<b>Receipt Voucher</b>%s" % (" &nbsp; (CANCELLED)" if r["status"] == "cancelled" else ""), center), ""],
               [Paragraph("No. : <b>%s</b>" % _esc(r["number"]), base), Paragraph("Dated : <b>%s</b>" % tdate(r["rcp_date"]), right)],
               [Paragraph("<b>Particulars</b>", base), Paragraph("<b>Amount</b>", right)],
               [Paragraph(part, base), Paragraph("<b>%s</b>" % inr(r["amount"]), right)],
               ["", Paragraph("<b>%s</b>" % inr(r["amount"]), right)],
               [Paragraph("Receiver's Signature", base), sign_cell]],
              colWidths=[120 * mm, 66 * mm], rowHeights=[None, None, None, None, 95 * mm, None, 32 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, K), ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 1), (1, 1)),
                           ("LINEBELOW", (0, 1), (-1, 1), 0.6, K), ("LINEBELOW", (0, 2), (-1, 2), 0.6, K),
                           ("LINEBELOW", (0, 3), (-1, 3), 0.6, K), ("LINEBEFORE", (1, 3), (1, 5), 0.6, K),
                           ("LINEABOVE", (1, 5), (1, 5), 0.6, K), ("LINEABOVE", (0, 6), (-1, 6), 0.6, K),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
    buf = io.BytesIO()
    doc = _pdf_doc(buf, r["number"])
    story = [t]
    deco = _page_decor("CANCELLED" if r["status"] == "cancelled" else "", "This is a Computer Generated Receipt")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
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
            S = settings(conn)
            fy = fy_of(today_ist())
            nseq, nxt = next_invoice_number(conn, S, fy)
        return {"settings": S, "today": today(), "fy": fy, "next_invoice": nxt, "next_seq": nseq, "states": STATES,
                "formats": [{"value": f, "example": format_number(f, S.get("invoice_prefix") or "INV", fy, 1)} for f in NUMBER_FORMATS]}

    @app.put("/api/billing/settings")
    def put_settings(body: SettingsIn, request: Request):
        u = staff(request, ("admin",))
        changed = []
        with closing(db()) as conn:
            for k, v in body.values.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                v = str(v if v is not None else "")
                if k == "stamp":
                    if v and (not re.match(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$", v) or len(v) > 700000):
                        raise HTTPException(status_code=422, detail="Stamp must be a PNG or JPG under 500 KB.")
                elif k == "invoice_format":
                    if v not in NUMBER_FORMATS:
                        raise HTTPException(status_code=422, detail="Unknown invoice number format.")
                elif k == "invoice_start":
                    if not v.isdigit() or not 1 <= int(v) <= 999999:
                        raise HTTPException(status_code=422, detail="Starting number must be 1 or more.")
                elif k in ("gstin", "pan"):
                    v = v.strip().upper()
                    if k == "gstin" and v and not re.match(r"^[0-9]{2}[A-Z0-9]{13}$", v):
                        raise HTTPException(status_code=422, detail="GSTIN must be 15 characters.")
                    if k == "pan" and v and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", v):
                        raise HTTPException(status_code=422, detail="PAN must look like ABCDE1234F.")
                else:
                    v = v[:800]
                conn.execute("INSERT INTO bill_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
                changed.append(k)
            conn.commit()
        audit(u["username"], "billing.settings", ", ".join(changed))
        return {"ok": True}

    # ---- accounts
    def party_values(body):
        gstin = body.gstin.strip().upper()
        if gstin and not re.match(r"^[0-9]{2}[A-Z0-9]{13}$", gstin):
            raise HTTPException(status_code=422, detail="GSTIN must be 15 characters (starts with the 2-digit state code).")
        sc = body.state_code.strip() or (gstin[:2] if gstin else "")
        state = body.state.strip() or STATES.get(sc, "")
        return (body.name.strip(), gstin, state, sc, body.address.strip(), body.phone.strip(), body.email.strip(),
                body.client_id, float(D(body.opening_balance)))

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
        vals = party_values(body)
        with closing(db()) as conn:
            code = next_code(conn, "bill_parties", "ACC")
            cur = conn.execute("INSERT INTO bill_parties (code,name,gstin,state,state_code,address,phone,email,client_id,"
                               "opening_balance,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (code,) + vals + (now_iso(), u["username"]))
            conn.commit()
        audit(u["username"], "billing.account.create", "%s %s" % (code, body.name))
        return {"ok": True, "id": cur.lastrowid, "code": code}

    @app.patch("/api/billing/parties/{pid}")
    def update_party(pid: int, body: PartyIn, request: Request):
        u = staff(request)
        vals = party_values(body)
        with closing(db()) as conn:
            cur = conn.execute("UPDATE bill_parties SET name=?, gstin=?, state=?, state_code=?, address=?, phone=?, email=?, "
                               "client_id=?, opening_balance=? WHERE id=?", vals + (pid,))
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
            rows = [dict(r) for r in conn.execute(
                "SELECT i.*, (SELECT COUNT(*) FROM bill_serials s WHERE s.item_id=i.id AND s.status='in_stock') serials_in_stock "
                "FROM bill_items i ORDER BY code")]
        return {"items": rows}

    def create_item_row(conn, body, user):
        cat = body.category if body.category in CATEGORIES else "hardware"
        code = next_code(conn, "bill_items", CATEGORIES[cat])
        track_stock = 1 if (body.track_stock or body.track_serial) else 0
        cur = conn.execute("INSERT INTO bill_items (code,name,category,description,hsn,unit,price,gst_rate,track_stock,track_serial,"
                           "stock,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (code, body.name.strip(), cat, body.description.strip(), body.hsn.strip(), body.unit.strip() or "pcs",
                            float(D(body.price)), float(body.gst_rate), track_stock, 1 if body.track_serial else 0,
                            float(body.stock or 0) if not body.track_serial else 0, now_iso(), user))
        if track_stock and body.stock and not body.track_serial:
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
            cur = conn.execute("UPDATE bill_items SET name=?, description=?, hsn=?, unit=?, price=?, gst_rate=?, track_stock=?, "
                               "track_serial=? WHERE id=?",
                               (body.name.strip(), body.description.strip(), body.hsn.strip(), body.unit.strip() or "pcs",
                                float(D(body.price)), float(body.gst_rate), 1 if (body.track_stock or body.track_serial) else 0,
                                1 if body.track_serial else 0, iid))
            conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Item not found.")
        audit(u["username"], "billing.item.update", "item %d" % iid)
        return {"ok": True}

    @app.post("/api/billing/items/{iid}/stock")
    def adjust_stock(iid: int, body: StockIn, request: Request):
        """Stock in (purchase / return / opening) or out (damage / correction). Serial numbers optional,
        required when the item tracks serials."""
        u = staff(request)
        sers = split_serials(body.serials)
        qty = body.qty
        out_reasons = ("damage", "correction-out", "lost", "used")
        with closing(db()) as conn:
            it = conn.execute("SELECT * FROM bill_items WHERE id=?", (iid,)).fetchone()
            if not it:
                raise HTTPException(status_code=404, detail="Item not found.")
            if sers and not qty:
                qty = -len(sers) if body.reason in out_reasons else len(sers)
            if not qty:
                raise HTTPException(status_code=422, detail="Enter a quantity or serial numbers.")
            if sers and abs(qty) != len(sers):
                raise HTTPException(status_code=422, detail="Quantity is %s but %d serial numbers were entered." % (qty_txt(abs(qty)), len(sers)))
            if it["track_serial"] and not sers:
                raise HTTPException(status_code=422, detail="This item tracks serial numbers: enter one serial number per piece.")
            for s in sers:
                row = conn.execute("SELECT status FROM bill_serials WHERE item_id=? AND serial=? COLLATE NOCASE", (iid, s)).fetchone()
                if qty > 0:
                    if row and row["status"] != "removed":
                        raise HTTPException(status_code=422, detail="Serial %s is already recorded (%s)." % (s, row["status"].replace("_", " ")))
                    if row:
                        conn.execute("UPDATE bill_serials SET status='in_stock', origin='stock', invoice_id=NULL, added_at=?, added_by=? "
                                     "WHERE item_id=? AND serial=? COLLATE NOCASE", (now_iso(), u["username"], iid, s))
                    else:
                        conn.execute("INSERT INTO bill_serials (item_id,serial,status,origin,added_at,added_by) VALUES (?,?,'in_stock','stock',?,?)",
                                     (iid, s, now_iso(), u["username"]))
                else:
                    if not row or row["status"] != "in_stock":
                        raise HTTPException(status_code=422, detail="Serial %s is not in stock." % s)
                    conn.execute("UPDATE bill_serials SET status='removed' WHERE item_id=? AND serial=? COLLATE NOCASE", (iid, s))
            conn.execute("UPDATE bill_items SET stock = stock + ?, track_stock=1 WHERE id=?", (qty, iid))
            ref = body.ref.strip() + ((" | S/N: " + ", ".join(sers)) if sers else "")
            conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user,rate,supplier) VALUES (?,?,?,?,?,?,?,?)",
                         (iid, qty, body.reason, ref[:900], now_iso(), u["username"],
                          float(D(body.rate)) if body.rate is not None else None, body.supplier.strip()))
            conn.commit()
            stock = conn.execute("SELECT stock FROM bill_items WHERE id=?", (iid,)).fetchone()[0]
        audit(u["username"], "billing.stock", "%s %+g (%s)" % (it["code"], qty, body.reason))
        return {"ok": True, "stock": stock}

    @app.get("/api/billing/items/{iid}/moves")
    def stock_moves(iid: int, request: Request):
        staff(request)
        with closing(db()) as conn:
            return {"items": [dict(r) for r in conn.execute(
                "SELECT * FROM bill_stock_moves WHERE item_id=? ORDER BY id DESC LIMIT 300", (iid,))]}

    @app.get("/api/billing/items/{iid}/serials")
    def item_serials(iid: int, request: Request, status: str = ""):
        staff(request)
        with closing(db()) as conn:
            q = "SELECT s.serial, s.status, s.added_at, i.number invoice FROM bill_serials s LEFT JOIN bill_invoices i ON i.id=s.invoice_id WHERE s.item_id=?"
            args = [iid]
            if status:
                q += " AND s.status=?"; args.append(status)
            return {"items": [dict(r) for r in conn.execute(q + " ORDER BY s.id DESC LIMIT 2000", args)]}

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

    @app.get("/api/billing/next-number")
    def next_number(request: Request, inv_date: str = ""):
        staff(request)
        d = valid_date(inv_date) if inv_date else today()
        with closing(db()) as conn:
            seq, number = next_invoice_number(conn, settings(conn), fy_of(d))
            return {"number": number, "seq": seq, "fy": fy_of(d)}

    def prepare(conn, body, user, invoice_id=None, dry=False):
        """Validate an invoice and compute it. Creates new inventory items for 'add to inventory' lines unless dry."""
        if not (body.apply_cgst or body.apply_sgst or body.apply_igst) and any(l.gst_rate > 0 for l in body.lines):
            raise HTTPException(status_code=422, detail="Tick CGST + SGST or IGST (or set GST % to 0).")
        party = conn.execute("SELECT * FROM bill_parties WHERE id=?", (body.party_id,)).fetchone()
        if not party:
            raise HTTPException(status_code=404, detail="Account not found.")
        prepared, created = [], []
        for n, ln in enumerate(body.lines, 1):
            sers = split_serials(ln.serials)
            if ln.item_id:
                it = conn.execute("SELECT * FROM bill_items WHERE id=?", (ln.item_id,)).fetchone()
                if not it:
                    raise HTTPException(status_code=404, detail="Line %d: item not found." % n)
                if len(sers) > ln.qty:
                    raise HTTPException(status_code=422, detail="Line %d (%s): %d serial numbers for quantity %s." % (n, it["name"], len(sers), qty_txt(ln.qty)))
                if it["track_serial"] and len(sers) != ln.qty:
                    raise HTTPException(status_code=422, detail="Line %d (%s): enter %s serial number(s), one per piece." % (n, it["name"], qty_txt(ln.qty)))
                for s in sers:
                    row = conn.execute("SELECT s.status, s.invoice_id, i.number FROM bill_serials s LEFT JOIN bill_invoices i ON i.id=s.invoice_id "
                                       "WHERE s.item_id=? AND s.serial=? COLLATE NOCASE", (it["id"], s)).fetchone()
                    if row and row["status"] == "sold" and row["invoice_id"] != invoice_id:
                        raise HTTPException(status_code=422, detail="Serial %s is already billed in %s." % (s, row["number"] or "another invoice"))
                    if row and row["status"] == "removed":
                        raise HTTPException(status_code=422, detail="Serial %s was removed from stock." % s)
                prepared.append({"item_id": it["id"], "code": it["code"], "name": ln.name.strip() or it["name"],
                                 "description": ln.description.strip(), "serials": ", ".join(sers),
                                 "hsn": ln.hsn.strip() or it["hsn"] or "", "unit": ln.unit or it["unit"], "qty": ln.qty,
                                 "rate": ln.rate, "discount_pct": ln.discount_pct, "gst_rate": ln.gst_rate,
                                 "track": it["track_stock"]})
            else:
                if not ln.name.strip():
                    raise HTTPException(status_code=422, detail="Line %d needs an item name." % n)
                item_id, code = None, ""
                if ln.add_to_inventory and not dry:
                    item_id, code = create_item_row(conn, ItemIn(name=ln.name, category=ln.category, description=ln.description,
                                                                 hsn=ln.hsn, unit=ln.unit, price=ln.rate, gst_rate=ln.gst_rate), user)
                    created.append(code)
                prepared.append({"item_id": item_id, "code": code, "name": ln.name.strip(), "description": ln.description.strip(),
                                 "serials": ", ".join(sers), "hsn": ln.hsn.strip(), "unit": ln.unit or "pcs", "qty": ln.qty,
                                 "rate": ln.rate, "discount_pct": ln.discount_pct, "gst_rate": ln.gst_rate, "track": 0})
        lines, sub, cg, sg, ig = compute_lines(prepared, body.apply_cgst, body.apply_sgst, body.apply_igst)
        gross = sub + cg + sg + ig
        rnd = (gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - gross) if settings(conn).get("round_off", "1") == "1" else D(0)
        return dict(party), lines, {"subtotal": sub, "cgst": cg, "sgst": sg, "igst": ig, "round_off": rnd, "total": gross + rnd}, created

    def release(conn, inv, user, why):
        """Undo an invoice's stock and serial effects (before edit or on cancel)."""
        for ln in conn.execute("SELECT l.item_id, l.qty, it.track_stock FROM bill_invoice_lines l LEFT JOIN bill_items it "
                               "ON it.id=l.item_id WHERE l.invoice_id=?", (inv["id"],)).fetchall():
            if ln["item_id"] and ln["track_stock"]:
                conn.execute("UPDATE bill_items SET stock = stock + ? WHERE id=?", (ln["qty"], ln["item_id"]))
                conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                             (ln["item_id"], ln["qty"], why, inv["number"], now_iso(), user))
        conn.execute("DELETE FROM bill_serials WHERE invoice_id=? AND origin='sale'", (inv["id"],))
        conn.execute("UPDATE bill_serials SET status='in_stock', invoice_id=NULL WHERE invoice_id=?", (inv["id"],))

    def write_lines(conn, inv_id, number, lines, user):
        for ln in lines:
            conn.execute("INSERT INTO bill_invoice_lines (invoice_id,item_id,code,name,description,serials,hsn,unit,qty,rate,"
                         "discount_pct,gst_rate,taxable,cgst,sgst,igst,total) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (inv_id, ln["item_id"], ln["code"], ln["name"], ln["description"], ln["serials"], ln["hsn"], ln["unit"],
                          ln["qty"], float(D(ln["rate"])), ln["discount_pct"], ln["gst_rate"], float(ln["taxable"]),
                          float(ln["cgst"]), float(ln["sgst"]), float(ln["igst"]), float(ln["total"])))
            if ln["item_id"] and ln["track"]:
                conn.execute("UPDATE bill_items SET stock = stock - ? WHERE id=?", (ln["qty"], ln["item_id"]))
                conn.execute("INSERT INTO bill_stock_moves (item_id,qty,reason,ref,at,by_user) VALUES (?,?,?,?,?,?)",
                             (ln["item_id"], -ln["qty"], "invoice", number, now_iso(), user))
            if ln["item_id"]:
                for s in split_serials(ln["serials"]):
                    row = conn.execute("SELECT id FROM bill_serials WHERE item_id=? AND serial=? COLLATE NOCASE", (ln["item_id"], s)).fetchone()
                    if row:
                        conn.execute("UPDATE bill_serials SET status='sold', invoice_id=? WHERE id=?", (inv_id, row["id"]))
                    else:
                        conn.execute("INSERT INTO bill_serials (item_id,serial,status,origin,invoice_id,added_at,added_by) "
                                     "VALUES (?,?,'sold','sale',?,?,?)", (ln["item_id"], s, inv_id, now_iso(), user))

    def header_values(body, party, t, inv_date):
        due = (date.fromisoformat(inv_date) + timedelta(days=body.due_days)).isoformat()
        return {"party_id": party["id"], "inv_date": inv_date, "due_date": due,
                "place_of_supply": body.place_of_supply.strip() or party["state"] or "",
                "apply_cgst": int(body.apply_cgst), "apply_sgst": int(body.apply_sgst), "apply_igst": int(body.apply_igst),
                "subtotal": float(t["subtotal"]), "cgst": float(t["cgst"]), "sgst": float(t["sgst"]), "igst": float(t["igst"]),
                "round_off": float(t["round_off"]), "total": float(t["total"]), "notes": body.notes.strip(),
                "ship_to": body.ship_to.strip(), "meta": json.dumps(clean_meta(body.meta))}

    @app.post("/api/billing/invoices")
    def create_invoice(body: InvoiceIn, request: Request):
        u = staff(request)
        inv_date = valid_date(body.inv_date) if body.inv_date else today()
        with closing(db()) as conn:
            party, lines, t, created = prepare(conn, body, u["username"])
            fy = fy_of(inv_date)
            S0 = settings(conn)
            if body.number_seq:
                seq = body.number_seq
                number = format_number(S0.get("invoice_format"), S0.get("invoice_prefix") or "AGILE", fy, seq)
                if conn.execute("SELECT 1 FROM bill_invoices WHERE number=?", (number,)).fetchone():
                    raise HTTPException(status_code=422, detail="Invoice number %s is already used." % number)
            else:
                seq, number = next_invoice_number(conn, S0, fy)
            h = header_values(body, party, t, inv_date)
            h.update({"number": number, "fy": fy, "seq": seq, "paid": 0, "status": "unpaid",
                      "created_by": u["username"], "created_at": now_iso()})
            cur = conn.execute("INSERT INTO bill_invoices (%s) VALUES (%s)" % (",".join(h), ",".join("?" * len(h))), list(h.values()))
            inv_id = cur.lastrowid
            write_lines(conn, inv_id, number, lines, u["username"])
            conn.commit()
        audit(u["username"], "billing.invoice.create", "%s %s total %s" % (number, party["code"], t["total"]))
        return {"ok": True, "id": inv_id, "number": number, "total": float(t["total"]), "new_items": created}

    @app.put("/api/billing/invoices/{iid}")
    def edit_invoice(iid: int, body: InvoiceIn, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            inv = conn.execute("SELECT * FROM bill_invoices WHERE id=?", (iid,)).fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            if inv["status"] == "cancelled":
                raise HTTPException(status_code=422, detail="A cancelled invoice cannot be edited.")
            inv_date = valid_date(body.inv_date) if body.inv_date else inv["inv_date"]
            if fy_of(inv_date) != inv["fy"]:
                raise HTTPException(status_code=422, detail="The date must stay in financial year %s (the invoice number belongs to it)." % inv["fy"])
            has_rcp = conn.execute("SELECT COUNT(*) FROM bill_receipts WHERE invoice_id=? AND status='ok'", (iid,)).fetchone()[0]
            if has_rcp and body.party_id != inv["party_id"]:
                raise HTTPException(status_code=422, detail="This invoice has receipts, so the account cannot be changed.")
            party, lines, t, created = prepare(conn, body, u["username"], invoice_id=iid)
            if D(t["total"]) < D(inv["paid"]):
                raise HTTPException(status_code=422, detail="New total %s is less than the %s already received." % (inr(t["total"]), inr(inv["paid"])))
            release(conn, inv, u["username"], "invoice edited")
            conn.execute("DELETE FROM bill_invoice_lines WHERE invoice_id=?", (iid,))
            h = header_values(body, party, t, inv_date)
            h.update({"updated_by": u["username"], "updated_at": now_iso()})
            if body.number_seq and body.number_seq != inv["seq"]:
                S0 = settings(conn)
                new_no = format_number(S0.get("invoice_format"), S0.get("invoice_prefix") or "AGILE", inv["fy"], body.number_seq)
                if conn.execute("SELECT 1 FROM bill_invoices WHERE number=? AND id!=?", (new_no, iid)).fetchone():
                    raise HTTPException(status_code=422, detail="Invoice number %s is already used." % new_no)
                h.update({"number": new_no, "seq": body.number_seq})
                inv = dict(inv); inv["number"] = new_no
            conn.execute("UPDATE bill_invoices SET %s WHERE id=?" % ", ".join(k + "=?" for k in h), list(h.values()) + [iid])
            write_lines(conn, iid, inv["number"], lines, u["username"])
            refresh_invoice_status(conn, iid)
            conn.commit()
        audit(u["username"], "billing.invoice.edit", "%s total %s" % (inv["number"], t["total"]))
        return {"ok": True, "id": iid, "number": inv["number"], "total": float(t["total"]), "new_items": created}

    @app.post("/api/billing/invoices/preview")
    def preview_invoice(body: InvoiceIn, request: Request, invoice_id: int = 0):
        u = staff(request)
        inv_date = valid_date(body.inv_date) if body.inv_date else today()
        with closing(db()) as conn:
            party, lines, t, _ = prepare(conn, body, u["username"], invoice_id=invoice_id or None, dry=True)
            S = settings(conn)
            if invoice_id:
                row = conn.execute("SELECT number FROM bill_invoices WHERE id=?", (invoice_id,)).fetchone()
                number = row["number"] if row else "PREVIEW"
            elif body.number_seq:
                number = format_number(S.get("invoice_format"), S.get("invoice_prefix") or "AGILE", fy_of(inv_date), body.number_seq)
            else:
                number = next_invoice_number(conn, S, fy_of(inv_date))[1]
        h = header_values(body, party, t, inv_date)
        h.update({"number": number, "meta": clean_meta(body.meta), "subtotal": t["subtotal"], "round_off": t["round_off"]})
        return _pdf_response(render_invoice(S, h, party, lines, "PREVIEW"), "preview")

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
        d = dict(inv)
        try:
            d["meta"] = json.loads(d.get("meta") or "{}")
        except Exception:
            d["meta"] = {}
        return {"invoice": d, "lines": lines, "receipts": rcps}

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
            release(conn, inv, u["username"], "invoice cancelled")
            conn.execute("UPDATE bill_invoices SET status='cancelled', cancelled_by=?, cancelled_at=? WHERE id=?",
                         (u["username"], now_iso(), iid))
            conn.commit()
        audit(u["username"], "billing.invoice.cancel", inv["number"])
        return {"ok": True}

    # ---- delete (records that are referenced elsewhere are protected)
    @app.delete("/api/billing/invoices/{iid}")
    def delete_invoice(iid: int, request: Request):
        u = staff(request, ("admin",))
        with closing(db()) as conn:
            inv = conn.execute("SELECT * FROM bill_invoices WHERE id=?", (iid,)).fetchone()
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            n = conn.execute("SELECT COUNT(*) FROM bill_receipts WHERE invoice_id=?", (iid,)).fetchone()[0]
            if n:
                raise HTTPException(status_code=422, detail="Delete the %d receipt(s) of this invoice first." % n)
            if inv["status"] != "cancelled":
                release(conn, inv, u["username"], "invoice deleted")
            conn.execute("DELETE FROM bill_invoice_lines WHERE invoice_id=?", (iid,))
            conn.execute("DELETE FROM bill_invoices WHERE id=?", (iid,))
            conn.commit()
        audit(u["username"], "billing.invoice.delete", "%s total %s (%s)" % (inv["number"], inv["total"], inv["status"]))
        return {"ok": True}

    @app.delete("/api/billing/receipts/{rid}")
    def delete_receipt(rid: int, request: Request):
        u = staff(request, ("admin",))
        with closing(db()) as conn:
            r = conn.execute("SELECT * FROM bill_receipts WHERE id=?", (rid,)).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            conn.execute("DELETE FROM bill_receipts WHERE id=?", (rid,))
            if r["invoice_id"]:
                refresh_invoice_status(conn, r["invoice_id"])
            conn.commit()
        audit(u["username"], "billing.receipt.delete", "%s amount %s" % (r["number"], r["amount"]))
        return {"ok": True}

    @app.delete("/api/billing/parties/{pid}")
    def delete_party(pid: int, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            p = conn.execute("SELECT code, name FROM bill_parties WHERE id=?", (pid,)).fetchone()
            if not p:
                raise HTTPException(status_code=404, detail="Account not found.")
            ni = conn.execute("SELECT COUNT(*) FROM bill_invoices WHERE party_id=?", (pid,)).fetchone()[0]
            nr = conn.execute("SELECT COUNT(*) FROM bill_receipts WHERE party_id=?", (pid,)).fetchone()[0]
            if ni or nr:
                raise HTTPException(status_code=422, detail="This account has %d invoice(s) and %d receipt(s). Delete those first; the ledger must stay complete." % (ni, nr))
            conn.execute("DELETE FROM bill_parties WHERE id=?", (pid,))
            conn.commit()
        audit(u["username"], "billing.account.delete", "%s %s" % (p["code"], p["name"]))
        return {"ok": True}

    @app.delete("/api/billing/items/{iid}")
    def delete_item(iid: int, request: Request):
        u = staff(request)
        with closing(db()) as conn:
            it = conn.execute("SELECT code, name FROM bill_items WHERE id=?", (iid,)).fetchone()
            if not it:
                raise HTTPException(status_code=404, detail="Item not found.")
            n = conn.execute("SELECT COUNT(*) FROM bill_invoice_lines WHERE item_id=?", (iid,)).fetchone()[0]
            if n:
                raise HTTPException(status_code=422, detail="This item is used in %d invoice line(s), so it can't be deleted." % n)
            for t in ("bill_stock_moves", "bill_serials"):
                conn.execute("DELETE FROM %s WHERE item_id=?" % t, (iid,))
            conn.execute("DELETE FROM bill_items WHERE id=?", (iid,))
            conn.commit()
        audit(u["username"], "billing.item.delete", "%s %s" % (it["code"], it["name"]))
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
