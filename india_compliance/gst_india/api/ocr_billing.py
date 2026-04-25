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

MAX_OCR_PX = 2400  # max dimension — high enough for dense invoice tables
MIN_OCR_PX = 1600  # minimum — aggressively upscale compressed/thumbnail images


def _preprocess_image(raw_bytes):
    """
    Image preprocessing pipeline optimised for scanned Indian invoices.
    Steps: grayscale → aggressive upscale → contrast → sharpness boost.
    """
    try:
        from PIL import Image, ImageEnhance, ImageOps, ImageFilter
    except ImportError:
        frappe.throw(_("Install Pillow: pip install Pillow"))

    img = Image.open(BytesIO(raw_bytes)).convert("RGB")

    # 1. Grayscale
    img = ImageOps.grayscale(img)

    # 2. Resize: upscale small images aggressively, cap huge ones
    w, h = img.size
    longest = max(w, h)
    if longest < MIN_OCR_PX:
        scale = MIN_OCR_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    elif longest > MAX_OCR_PX:
        scale = MAX_OCR_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # 3. Contrast boost — helps text stand out from background
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # 4. Sharpness boost — critical for small/compressed text
    img = ImageEnhance.Sharpness(img).enhance(2.5)

    return img


# Singleton — initialise once per worker process (model download only on first use)
_PADDLE_OCR = None

def _get_paddle():
    """Lazy-load PaddleOCR singleton to avoid slow startup."""
    global _PADDLE_OCR
    if _PADDLE_OCR is None:
        try:
            import logging
            import os
            # Skip slow connectivity check (models cached after first run)
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            # Suppress verbose logs
            for _noisy in ("ppocr", "paddleocr", "paddle", "root"):
                logging.getLogger(_noisy).setLevel(logging.WARNING)

            from paddleocr import PaddleOCR
            # v2 API: use_angle_cls corrects rotated scans
            _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        except TypeError:
            # show_log removed in some builds — retry without it
            from paddleocr import PaddleOCR
            _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang='en')
        except ImportError:
            pass
    return _PADDLE_OCR


def _run_paddleocr(img):
    """
    Run PaddleOCR v2 on a PIL Image and return a plain text string.
    Falls back to Tesseract if PaddleOCR is unavailable or errors.
    """
    import numpy as np

    ocr = _get_paddle()
    if ocr is None:
        return _run_tesseract(img)

    img_array = np.array(img.convert("RGB"))

    try:
        # PaddleOCR v2 API
        result = ocr.ocr(img_array, cls=True)
    except Exception:
        return _run_tesseract(img)

    # result is a list of pages; result[0] is list of [bbox, (text, conf)]
    if not result or not result[0]:
        return ""

    lines = []
    for item in result[0]:
        try:
            bbox, (text, conf) = item
            if not text or not text.strip():
                continue
            y_centre = (bbox[0][1] + bbox[2][1]) / 2
            x_left = bbox[0][0]
            lines.append((y_centre, x_left, text.strip()))
        except Exception:
            pass

    if not lines:
        return ""

    # Sort top-to-bottom (15px row bands), then left-to-right
    lines.sort(key=lambda t: (round(t[0] / 15) * 15, t[1]))

    # Merge tokens on the same row into single text lines
    grouped = []
    prev_y = None
    row_tokens = []
    for y, x, text in lines:
        if prev_y is None or abs(y - prev_y) > 15:
            if row_tokens:
                grouped.append(" ".join(row_tokens))
            row_tokens = [text]
            prev_y = y
        else:
            row_tokens.append(text)
    if row_tokens:
        grouped.append(" ".join(row_tokens))

    return "\n".join(grouped)





def _run_tesseract(img):
    """Run Tesseract OCR (fallback). psm 4 handles multi-column invoice tables."""
    try:
        import pytesseract
    except ImportError:
        frappe.throw(_("Neither PaddleOCR nor pytesseract is installed."))

    config = "--psm 4 --oem 1"
    return pytesseract.image_to_string(img, config=config)


# ── Text cleaning + structuring ────────────────────────────────────────────────

def _normalize_text(text):
    """Clean raw OCR output."""
    # Remove non-printable characters except ₹ and newlines
    text = re.sub(r"[^\x20-\x7E₹\n]", " ", text)
    # Collapse multiple spaces into one
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Fix common OCR number mistakes in clearly numeric contexts only
    # Note: Do NOT replace O→0 globally — corrupts item names like "Tools"
    text = text.replace("|", "I")
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
    Dual-mode OCR line item parser.
    Mode A (Service Invoice): Detects "Label: Amount" rows — e.g. packers/movers, freight bills.
    Mode B (Product Invoice): Token-based column extractor for tabular product invoices.
    Auto-detects which mode to use based on invoice structure.
    """
    # Words that indicate a summary/tax row — skip these as line items
    SKIP_ALWAYS = {"total", "grand", "subtotal", "sgst", "cgst", "igst",
                   "thank", "rupees", "note", "interest", "gstin", "bill no",
                   "invoice no", "date", "mobile", "website", "email"}

    # Words that indicate a service charge row — valid line items in Mode A
    SERVICE_CHARGE_WORDS = {
        "packing", "transportation", "transport", "loading", "unloading",
        "delivery", "handling", "labour", "insurance", "service", "bilty",
        "freight", "octroi", "toll", "ngt", "fuel", "surcharge", "charge"
    }

    # ── Detect invoice mode ───────────────────────────────────────────────────
    # Count how many lines look like "Label: Amount" (service mode)
    service_score = sum(
        1 for ln in lines
        if re.search(r'[A-Za-z\s]{4,}\s*[:@]?\s*(?:Rs\.?|₹)?\s*[\d,]+(?:\.\d{1,2})?', ln)
        and any(w in ln.lower() for w in SERVICE_CHARGE_WORDS)
    )
    # Count lines that look like multi-column product rows: 3+ numbers on one line
    product_score = sum(
        1 for ln in lines
        if len(re.findall(r'\b\d+(?:\.\d+)?\b', ln)) >= 3
    )
    service_mode = service_score >= 2 or (service_score >= 1 and service_score >= product_score // 2)

    items = []

    # ── MODE A: Service / Freight Invoice ─────────────────────────────────────
    if service_mode:
        charge_pattern = re.compile(
            r'([A-Za-z][A-Za-z\s&]{2,}?)\s*(?:Charge|Tax|Fee|Cost)?\s*[@:]?\s*'
            r'(?:\d+\s*%\s*)?'        # optional percentage like "5%"
            r'(?:Rs\.?|₹)?\s*'
            r'([\d,]+(?:\.\d{1,2})?)',
            re.IGNORECASE
        )
        for line in lines:
            line = line.strip()
            if len(line) < 4:
                continue
            lw = line.lower()
            # Always skip summary/tax lines
            if any(w in lw for w in SKIP_ALWAYS):
                continue
            # Must contain a service charge keyword
            if not any(w in lw for w in SERVICE_CHARGE_WORDS):
                continue
            # Skip lines that say "include" instead of an amount
            if "include" in lw or "inclusive" in lw:
                continue

            m = charge_pattern.search(line)
            if m:
                label = m.group(1).strip().title()
                raw_amount = m.group(2).replace(",", "")
                try:
                    amount = float(raw_amount)
                except ValueError:
                    continue
                if amount <= 0:
                    continue
                items.append({
                    "name": label,
                    "quantity": 1.0,
                    "unit": "service",
                    "price": amount
                })
        return items

    # ── MODE B: Product / Columnar Invoice ───────────────────────────────────
    skip_words = {"total", "grand", "subtotal", "gst", "cgst", "sgst", "igst",
                  "tax", "bill", "invoice", "amount", "balance", "discount",
                  "thank", "phone", "gstin", "date", "name", "addr", "freight"}

    for line in lines:
        line = line.strip()
        if len(line) < 5:
            continue
        first_words = " ".join(line.split()[:3]).lower()
        if any(w in first_words for w in skip_words):
            continue

        tokens = line.split()
        text_parts = []
        trailing_numbers = []
        found_text = False

        for t in reversed(tokens):
            clean_t = re.sub(r'[₹,]', '', t).replace('Rs.', '').replace('Rs', '')
            is_num = False
            try:
                val = float(clean_t)
                is_num = True
            except ValueError:
                pass
            if is_num and not found_text:
                trailing_numbers.insert(0, val)
            else:
                if t.lower() not in ['pcs', 'nos', 'kg', 'ltr', 'x', 'gm', '-']:
                    found_text = True
                    text_parts.insert(0, t)

        if len(text_parts) > 0 and len(trailing_numbers) >= 2:
            name = " ".join(text_parts)
            name = re.sub(r'^\d+[\.)]?\s*', '', name).strip()
            if len(name) < 3:
                continue
            start_idx = 0
            if len(trailing_numbers) >= 3 and trailing_numbers[0] >= 1000 and trailing_numbers[0].is_integer():
                start_idx = 1
            qty = trailing_numbers[start_idx]
            if qty <= 0:
                qty = 1.0
            price = trailing_numbers[start_idx + 1] if len(trailing_numbers) > start_idx + 1 else trailing_numbers[-1]
            items.append({
                "name": name.title(),
                "quantity": float(qty),
                "unit": "nos",
                "price": float(price)
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
    """Add HSN + GST rate to each extracted item.
    Priority:
    1. GST rate encoded in the item name (e.g. 'Walnuts 5% Tax Item' → 5%)
       Also handles Tesseract % misreads: '5%6', '56', '3 6 Tax'
    2. HSN-based lookup from voice_billing knowledge base
    3. Default 18% fallback
    """
    try:
        from india_compliance.gst_india.api.voice_billing import _get_hsn_and_gst
    except Exception:
        _get_hsn_and_gst = lambda n: ("9999", 18)  # noqa

    # Known valid GST rates as a set for validation
    VALID_GST_RATES = {0, 3, 5, 12, 18, 28}

    def _extract_gst_from_name(name):
        """
        Try several patterns to extract GST rate from an item name.
        Tesseract commonly misreads '%' as '6', '%6', or nothing.
        Returns (rate_float, cleaned_name) or (None, name).
        """
        # Pattern 1: clean "5%" or "12%" with actual percent sign
        m = re.search(r'\b(\d{1,2})\s*%', name)
        if m:
            rate = float(m.group(1))
            if rate in VALID_GST_RATES:
                clean = re.sub(r'\s*[@]?\s*\d{1,2}\s*%\s*(?:Tax\s*(?:Item)?|GST\s*(?:Item)?|Item)?',
                               '', name, flags=re.IGNORECASE).strip().title()
                return rate, clean or name

        # Pattern 2: Tesseract reads "3%" as "396" or "5%" as "596" — digit followed by 6 before "Tax"
        m2 = re.search(r'\b(\d)\s*9?6\s+(?:Tax|Gst)\s*(?:Item)?', name, re.IGNORECASE)
        if m2:
            rate = float(m2.group(1)) * 10 if float(m2.group(1)) > 5 else float(m2.group(1))
            # try exact: single digit before "6 Tax" → that digit is the rate
            rate = float(m2.group(1))
            if rate in VALID_GST_RATES:
                clean = re.sub(r'\s*\d\s*9?6\s+(?:Tax|Gst)\s*(?:Item)?', '', name, flags=re.IGNORECASE).strip().title()
                return rate, clean or name

        # Pattern 3: "5 Tax Item" or "12 Tax Item" — number directly before Tax keyword
        m3 = re.search(r'\b(\d{1,2})\s+(?:Tax|Gst)\s*(?:Item)?\b', name, re.IGNORECASE)
        if m3:
            rate = float(m3.group(1))
            if rate in VALID_GST_RATES:
                clean = re.sub(r'\s*\d{1,2}\s+(?:Tax|Gst)\s*(?:Item)?', '', name, flags=re.IGNORECASE).strip().title()
                return rate, clean or name

        return None, name

    enriched = []
    for item in items:
        raw_name = item.get("name", "")

        rate, clean_name = _extract_gst_from_name(raw_name)
        if rate is not None:
            gst_rate = rate
            if len(clean_name) < 3:
                clean_name = raw_name
            hsn, _ = _get_hsn_and_gst(clean_name)
        else:
            clean_name = raw_name
            hsn, gst_rate = _get_hsn_and_gst(raw_name)

        qty = item.get("quantity", 1)
        price = item.get("price", 0)
        taxable = round(qty * price, 2)
        gst_amt = round(taxable * gst_rate / 100, 2)
        enriched.append({
            **item,
            "name": clean_name,
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

    # OCR  — PaddleOCR primary, Tesseract fallback
    raw_text = _run_paddleocr(img)
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
