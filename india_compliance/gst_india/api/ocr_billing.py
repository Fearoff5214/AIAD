"""
OCR Bill Scanning API
---------------------
POST /api/method/india_compliance.gst_india.api.ocr_billing.process_ocr
POST /api/method/india_compliance.gst_india.api.ocr_billing.confirm_ocr_invoice
"""

import base64
import json
import re
import os
from io import BytesIO
from datetime import date

import frappe
from frappe import _


# ── Image preprocessing + OCR ──────────────────────────────────────────────────

MAX_OCR_PX = 1800  # max dimension — big enough for accuracy, small enough for speed


def _preprocess_image(raw_bytes):
    """
    Fast pipeline: grayscale → cap size → mild contrast boost.
    Deskew and heavy filters removed — Tesseract handles slight skew fine.
    Target: <1s preprocessing on typical phone-camera bills.
    """
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        frappe.throw(_("Install Pillow: pip install Pillow"))

    img = Image.open(BytesIO(raw_bytes)).convert("RGB")

    # 1. Grayscale
    img = ImageOps.grayscale(img)

    # 2. Cap maximum dimension (avoids huge images killing Tesseract speed)
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_OCR_PX:
        scale = MAX_OCR_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
    elif longest < 800:
        # Scale up very small images so Tesseract can read them
        scale = 800 / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)

    # 3. Mild contrast boost (1.8x is enough; 2.2x can blow out detail)
    img = ImageEnhance.Contrast(img).enhance(1.8)

    return img


def _run_tesseract(img):
    """Run Tesseract OCR — psm 6 is the fastest reliable mode for structured bills."""
    try:
        import pytesseract
    except ImportError:
        frappe.throw(_("Install pytesseract: pip install pytesseract"))

    # psm 6: assume a single uniform block of text — fast and accurate for invoices
    config = "--psm 6 --oem 1"
    return pytesseract.image_to_string(img, config=config)


# ── Text cleaning + structuring ────────────────────────────────────────────────

def _normalize_text(text):
    """Clean raw OCR output."""
    # Remove non-printable
    text = re.sub(r"[^\x20-\x7E₹\n]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Fix common OCR mistakes
    text = text.replace("|", "1").replace("l", "l").replace("O", "0")
    return text.strip()


def _extract_number_from_token(tok):
    """Parse numbers like 1,200.50 or 1200"""
    tok = tok.replace(",", "").replace("₹", "").replace("Rs.", "").replace("rs.", "").strip()
    try:
        return float(tok)
    except ValueError:
        return None


def _parse_line_items(lines):
    """
    Heuristic line-item extractor.
    Looks for lines matching: [Item Name] [Qty] [Price]
    """
    items = []
    item_pattern = re.compile(
        r"^(.+?)\s+"                     # item name (greedy left)
        r"(\d+(?:\.\d+)?)\s*"            # quantity
        r"(?:kg|gm|ltr|ml|pcs|nos|x)?\s*"  # optional unit
        r"(\d{1,6}(?:\.\d{1,2})?)$",    # price
        re.IGNORECASE,
    )
    # Also match: "Rice 100" (qty=1 assumed) or "2 Rice 100"
    simple_price = re.compile(
        r"^(?:(\d+(?:\.\d+)?)\s+)?(.+?)\s+(\d{1,6}(?:\.\d{1,2})?)$",
        re.IGNORECASE,
    )

    skip_words = {"total", "grand", "subtotal", "gst", "cgst", "sgst", "igst",
                  "tax", "bill", "invoice", "amount", "balance", "discount",
                  "thank", "phone", "gstin", "date", "name", "addr"}

    for line in lines:
        line = line.strip()
        if len(line) < 4:
            continue
        # Skip header/footer lines
        first_word = line.split()[0].lower() if line.split() else ""
        if first_word in skip_words:
            continue

        m = item_pattern.match(line)
        if m:
            item_name, qty_str, price_str = m.group(1), m.group(2), m.group(3)
            items.append({
                "name": item_name.strip().title(),
                "quantity": float(qty_str),
                "unit": "pcs",
                "price": float(price_str),
            })
            continue

        m2 = simple_price.match(line)
        if m2:
            qty_str = m2.group(1)
            item_name = m2.group(2)
            price_str = m2.group(3)
            if item_name.lower().split()[0] in skip_words:
                continue
            qty = float(qty_str) if qty_str else 1.0
            items.append({
                "name": item_name.strip().title(),
                "quantity": qty,
                "unit": "pcs",
                "price": float(price_str),
            })

    return items


def _extract_totals(text):
    """Extract GST rate, total, and other summary fields from OCR text."""

    def _first_number(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return _extract_number_from_token(m.group(1) or m.group(0))
        return None

    gst_rate = _first_number(r"gst\s*[:\-]?\s*(\d+)\s*%")
    cgst = _first_number(r"cgst\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)")
    sgst = _first_number(r"sgst\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)")
    igst = _first_number(r"igst\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)")
    total = _first_number(
        r"(?:grand\s*total|total\s*amount|net\s*amount|amount\s*due|total)\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)"
    )
    taxable = _first_number(
        r"(?:taxable|subtotal|sub\s*total|taxable\s*value|taxable\s*amount)\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)"
    )
    gstin = None
    m = re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b", text, re.IGNORECASE)
    if m:
        gstin = m.group(1).upper()

    inv_no = None
    m2 = re.search(r"(?:invoice\s*(?:no|number)|inv\s*no|bill\s*no)[:\s#-]*([A-Z0-9\-/]+)", text, re.IGNORECASE)
    if m2:
        inv_no = m2.group(1).strip()

    inv_date = None
    m3 = re.search(r"(?:date)[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", text, re.IGNORECASE)
    if m3:
        inv_date = m3.group(1)

    # Recompute total_tax
    total_tax = 0.0
    if cgst or sgst:
        total_tax = round((cgst or 0) + (sgst or 0), 2)
    elif igst:
        total_tax = igst

    return {
        "gst_rate": gst_rate,
        "cgst": cgst or 0,
        "sgst": sgst or 0,
        "igst": igst or 0,
        "total_tax": total_tax,
        "total": total,
        "taxable": taxable,
        "gstin": gstin,
        "invoice_number": inv_no,
        "date": inv_date,
    }


def _classify_bill(items, totals, text):
    """
    Auto-classify as Purchase / Expense / Inventory.
    Simple heuristic.
    """
    text_l = text.lower()
    purchase_keywords = ["purchase", "bought", "received", "stock", "inventory", "goods received"]
    expense_keywords = ["electricity", "rent", "transport", "fuel", "travel", "hotel", "repair", "utility"]

    for kw in expense_keywords:
        if kw in text_l:
            return "Expense"
    for kw in purchase_keywords:
        if kw in text_l:
            return "Purchase"
    if totals.get("gstin"):
        return "Purchase"
    if len(items) > 3:
        return "Inventory"
    return "Purchase"  # safe default


def _enrich_items(items):
    """Add HSN + GST rate to each extracted item using the voice_billing cache."""
    try:
        from india_compliance.gst_india.api.voice_billing import _get_hsn_and_gst
    except Exception:
        _get_hsn_and_gst = lambda n: ("9999", 18)  # noqa

    enriched = []
    for item in items:
        hsn, gst_rate = _get_hsn_and_gst(item.get("name", ""))
        qty = item.get("quantity", 1)
        price = item.get("price", 0)
        taxable = round(qty * price, 2)
        gst_amt = round(taxable * gst_rate / 100, 2)
        enriched.append({
            **item,
            "hsn_code": hsn,
            "gst_rate": gst_rate,
            "taxable_amount": taxable,
            "gst_amount": gst_amt,
            "total": round(taxable + gst_amt, 2),
        })
    return enriched


def _validate_ocr_invoice(items, totals):
    """
    Validate the OCR-extracted data.
    Returns (is_valid, issues_list).
    Issues are surfaced to the user for manual review.
    """
    issues = []

    if not items:
        issues.append("No line items could be detected. Please enter items manually.")

    for idx, item in enumerate(items):
        row = idx + 1
        if item.get("price", 0) <= 0:
            issues.append(f"Row {row} '{item.get('name', '?')}': price missing or zero – verify")
        if item.get("quantity", 0) <= 0:
            issues.append(f"Row {row} '{item.get('name', '?')}': quantity missing – defaulted to 1")
            item["quantity"] = 1

    # Cross-check totals
    computed_taxable = round(sum(i.get("taxable_amount", 0) for i in items), 2)
    extracted_total = totals.get("total") or 0
    extracted_taxable = totals.get("taxable") or 0

    if extracted_taxable and abs(computed_taxable - extracted_taxable) > 5:
        issues.append(
            f"Taxable value mismatch: computed ₹{computed_taxable} vs extracted ₹{extracted_taxable}. "
            "Please verify items."
        )

    total_tax = round(sum(i.get("gst_amount", 0) for i in items), 2)
    computed_grand = round(computed_taxable + total_tax, 2)
    if extracted_total and abs(computed_grand - extracted_total) > 5:
        issues.append(
            f"Total mismatch: computed ₹{computed_grand} vs bill total ₹{extracted_total}. "
            "Recheck quantities or prices."
        )

    return (len(issues) == 0, issues)


def extract_ocr_data(image_base64, filename=None):
    """
    Full pipeline: decode → preprocess → OCR → parse → enrich → validate.
    """
    # Decode base64
    if not image_base64:
        frappe.throw(_("Image data required"))

    raw_b64 = image_base64
    if "," in raw_b64 and raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    raw_bytes = base64.b64decode(raw_b64)

    # Preprocess
    img = _preprocess_image(raw_bytes)

    # OCR
    raw_text = _run_tesseract(img)
    clean_text = _normalize_text(raw_text)

    # Parse
    lines = clean_text.splitlines()
    items = _parse_line_items(lines)
    totals = _extract_totals(clean_text)

    # Enrich with HSN + GST
    items = _enrich_items(items)

    # Classify
    bill_type = _classify_bill(items, totals, clean_text)

    # Validate
    is_valid, issues = _validate_ocr_invoice(items, totals)

    # Build summary totals
    subtotal = round(sum(i.get("taxable_amount", 0) for i in items), 2)
    total_gst = round(sum(i.get("gst_amount", 0) for i in items), 2)
    grand_total = totals.get("total") or round(subtotal + total_gst, 2)

    return {
        "filename": filename,
        "raw_text": clean_text,
        "items": items,
        "totals": {
            **totals,
            "computed_subtotal": subtotal,
            "computed_gst": total_gst,
            "computed_grand_total": grand_total,
        },
        "bill_type": bill_type,
        "validation": {
            "valid": is_valid,
            "issues": issues,
        },
    }


# ── Whitelisted API endpoints ──────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def process_ocr(image_base64, filename=None):
    """
    POST /api/method/india_compliance.gst_india.api.ocr_billing.process_ocr
    Body: { image_base64: "data:image/jpeg;base64,...", filename: "bill.jpg" }
    """
    try:
        result = extract_ocr_data(image_base64, filename)
        return {"success": True, "data": result}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "OCR Processing Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=True)
def confirm_ocr_invoice(invoice_json):
    """
    Called after user reviews OCR result and confirms.
    NEVER auto-saves — user must explicitly confirm.
    """
    try:
        data = json.loads(invoice_json)
    except Exception:
        return {"success": False, "error": "Invalid JSON"}

    items = data.get("items", [])
    totals = data.get("totals", {})

    is_valid, issues = _validate_ocr_invoice(items, totals)
    if not is_valid:
        return {
            "success": False,
            "error": "Validation failed",
            "issues": issues,
        }

    invoice_number = data.get("invoice_number") or f"OCR-{frappe.generate_hash(length=6).upper()}"
    saved = {
        **data,
        "invoice_number": invoice_number,
        "status": "confirmed",
        "source": "ocr_billing",
        "saved_at": str(frappe.utils.now_datetime()),
    }

    # TODO: Insert into ERPNext Purchase Invoice / Expense Claim here

    return {"success": True, "message": "Invoice confirmed", "invoice": saved}
