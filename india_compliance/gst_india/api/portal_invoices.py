"""
Saved invoices for the portal: confirm a bill, list it, check it, export it.

Every call is scoped to the signed-in user's own active Portal Tenant, so one
business can never read or write another's invoices. Amounts are always
recomputed here from quantity x price x GST rate. The browser's totals are
never trusted.
"""

import csv
import io
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _

SOURCES = {"voice_billing": "VB", "ocr_billing": "OB"}
VALID_GST_RATES = {Decimal(r) for r in ("0", "0.25", "3", "5", "12", "18", "28")}
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
MAX_ITEMS = 200
CENT = Decimal("0.01")


# ── Pure logic (no database) ────────────────────────────────────────────────

def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _num(value, label):
    try:
        number = Decimal(str(value if value not in (None, "") else 0))
    except Exception:
        raise ValueError(f"{label} must be a number")
    if not number.is_finite():
        raise ValueError(f"{label} must be a number")
    return number


def compute_invoice(items, supply_type="intra"):
    """Return normalised lines and totals, or raise ValueError with a fix-it message."""
    if not isinstance(items, list) or not items:
        raise ValueError("Add at least one item before saving.")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"An invoice can have at most {MAX_ITEMS} items.")
    if supply_type not in ("intra", "inter"):
        supply_type = "intra"

    lines, taxable_total, tax_total = [], Decimal(0), Decimal(0)
    for position, raw in enumerate(items, start=1):
        name = str((raw or {}).get("name") or "").strip()
        if not name:
            raise ValueError(f"Item {position} needs a name.")
        quantity = _num(raw.get("quantity", 1), f"Quantity for {name}")
        price = _num(raw.get("price", 0), f"Price for {name}")
        rate = _num(raw.get("gst_rate", 0), f"GST rate for {name}")
        if quantity <= 0:
            raise ValueError(f"Quantity for {name} must be more than 0.")
        if price < 0:
            raise ValueError(f"Price for {name} cannot be negative.")
        if rate not in VALID_GST_RATES:
            raise ValueError(f"GST rate {rate}% for {name} is not a valid slab (0, 3, 5, 12, 18 or 28).")

        taxable = _money(quantity * price)
        tax = _money(taxable * rate / 100)
        if supply_type == "inter":
            igst, cgst, sgst = tax, Decimal(0), Decimal(0)
        else:
            cgst = _money(tax / 2)
            sgst = tax - cgst  # remainder, so the halves always add back to the line tax
            igst = Decimal(0)

        taxable_total += taxable
        tax_total += tax
        lines.append({
            "name": name[:140],
            "quantity": float(quantity),
            "unit": str(raw.get("unit") or "pcs")[:20],
            "price": float(price),
            "hsn_code": str(raw.get("hsn_code") or "")[:20],
            "gst_rate": float(rate),
            "taxable_amount": float(taxable),
            "gst_amount": float(tax),
            "cgst_amount": float(cgst),
            "sgst_amount": float(sgst),
            "igst_amount": float(igst),
            "total": float(taxable + tax),
        })

    return {
        "lines": lines,
        "taxable_value": float(taxable_total),
        "tax_amount": float(tax_total),
        "total_amount": float(taxable_total + tax_total),
        "supply_type": supply_type,
    }


def check_invoice(lines, party_gstin, taxable_value, tax_amount, total_amount):
    """Internal consistency check. Returns ("matched" | "mismatch", [notes])."""
    notes = []
    if party_gstin and not GSTIN_RE.match(party_gstin):
        notes.append(f"GSTIN {party_gstin} is not in a valid format.")
    for line in lines:
        if not line["hsn_code"]:
            notes.append(f"{line['name']} has no HSN code.")
    if abs(round(taxable_value + tax_amount - total_amount, 2)) > 0.01:
        notes.append("Taxable value plus tax does not equal the total.")
    line_tax = round(sum(l["cgst_amount"] + l["sgst_amount"] + l["igst_amount"] for l in lines), 2)
    if abs(line_tax - round(tax_amount, 2)) > 0.01:
        notes.append("Tax split does not add up to the total tax.")
    return ("mismatch" if notes else "matched"), notes


def _csv_safe(value):
    """Stop spreadsheet apps treating user text as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


# ── Database-backed endpoints ───────────────────────────────────────────────

def _tenant_for_session():
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("Please sign in to continue."), frappe.PermissionError)
    tenant = frappe.db.get_value("Portal Tenant", {"user": user, "is_active": 1}, "name")
    if not tenant:
        frappe.throw(
            _("Your login has no active business account. Create one at /user-register or ask your admin."),
            frappe.PermissionError,
        )
    return tenant


def _row(doc_like):
    get = doc_like.get
    return {
        "invoice_number": get("invoice_number"),
        "customer": get("customer") or "",
        "gstin": get("party_gstin") or "",
        "date": str(get("invoice_date") or ""),
        "amount": get("total_amount") or 0,
        "gst": get("tax_amount") or 0,
        "status": get("check_status") or "matched",
        "source": get("source") or "",
    }


_LIST_FIELDS = [
    "invoice_number", "customer", "party_gstin", "invoice_date",
    "total_amount", "tax_amount", "check_status", "check_notes", "source",
    "taxable_value",
]


def _tenant_invoices(tenant, limit=200):
    return frappe.get_all(
        "Portal Invoice",
        filters={"portal_tenant": tenant},
        fields=_LIST_FIELDS,
        order_by="invoice_date desc, creation desc",
        limit_page_length=limit,
    )


@frappe.whitelist()
def save_invoice(invoice_json, source):
    """Confirm and store a reviewed bill. Returns the saved invoice."""
    tenant = _tenant_for_session()
    if source not in SOURCES:
        return {"success": False, "error": "Unknown bill source."}
    try:
        payload = json.loads(invoice_json or "{}")
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        return {"success": False, "error": "The invoice data could not be read. Reload and try again."}

    try:
        computed = compute_invoice(payload.get("items"), payload.get("supply_type", "intra"))
    except ValueError as err:
        return {"success": False, "error": str(err)}

    gstin = str(payload.get("gstin") or "").strip().upper()[:15]
    number = str(payload.get("invoice_number") or "").strip()[:60] or (
        f"{SOURCES[source]}-{frappe.generate_hash(length=8).upper()}"
    )
    if frappe.db.exists("Portal Invoice", {"portal_tenant": tenant, "invoice_number": number}):
        return {"success": False, "error": f"Invoice {number} is already saved."}

    try:
        invoice_date = date.fromisoformat(str(payload.get("date") or "")[:10])
    except ValueError:
        invoice_date = date.today()

    status, notes = check_invoice(
        computed["lines"], gstin, computed["taxable_value"], computed["tax_amount"], computed["total_amount"]
    )
    doc = frappe.get_doc({
        "doctype": "Portal Invoice",
        "invoice_number": number,
        "portal_tenant": tenant,
        "user": frappe.session.user,
        "source": source,
        "customer": str(payload.get("customer") or "")[:140],
        "party_gstin": gstin,
        "invoice_date": invoice_date,
        "supply_type": computed["supply_type"],
        "taxable_value": computed["taxable_value"],
        "tax_amount": computed["tax_amount"],
        "total_amount": computed["total_amount"],
        "check_status": status,
        "check_notes": "\n".join(notes),
        "items_json": json.dumps(computed["lines"]),
    })
    doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "message": f"Invoice {number} saved",
        "invoice": {**_row(doc.as_dict() if hasattr(doc, "as_dict") else doc), "notes": notes,
                    "total": computed["total_amount"]},
    }


@frappe.whitelist()
def list_invoices():
    tenant = _tenant_for_session()
    return {"success": True, "data": [_row(r) for r in _tenant_invoices(tenant)]}


@frappe.whitelist()
def dashboard_summary():
    tenant = _tenant_for_session()
    rows = _tenant_invoices(tenant, limit=1000)
    total = len(rows)
    matched = sum(1 for r in rows if r.get("check_status") == "matched")
    return {"success": True, "data": {
        "total_invoices": total,
        "matched": matched,
        "mismatched": total - matched,
        "missing": 0,
        "compliance_score": round(matched / total * 100, 1) if total else 0,
    }}


@frappe.whitelist()
def reconcile():
    """Re-check every saved invoice. Matches against GSTR-2B data are not available yet."""
    tenant = _tenant_for_session()
    rows = _tenant_invoices(tenant, limit=1000)
    return {"success": True, "data": {
        "matched": [_row(r) for r in rows if r.get("check_status") == "matched"],
        "mismatched": [dict(_row(r), notes=(r.get("check_notes") or "").split("\n")) for r in rows
                       if r.get("check_status") != "matched"],
    }}


@frappe.whitelist()
def export_csv():
    tenant = _tenant_for_session()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["invoice_number", "customer", "gstin", "date", "taxable_value", "gst", "total", "status", "source"])
    for r in _tenant_invoices(tenant, limit=5000):
        writer.writerow([_csv_safe(v) for v in (
            r.get("invoice_number"), r.get("customer"), r.get("party_gstin"), r.get("invoice_date"),
            r.get("taxable_value"), r.get("tax_amount"), r.get("total_amount"),
            r.get("check_status"), r.get("source"))])
    return {"success": True, "data": {"csv": out.getvalue()}}
