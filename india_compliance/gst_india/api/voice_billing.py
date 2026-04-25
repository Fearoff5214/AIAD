"""
Voice Billing API
-----------------
POST /api/method/india_compliance.gst_india.api.voice_billing.parse_voice_input
POST /api/method/india_compliance.gst_india.api.voice_billing.create_invoice_from_voice
GET  /api/method/india_compliance.gst_india.api.voice_billing.get_item_suggestions
"""

import json
import re
import os
import urllib.request
import urllib.error
from datetime import date

import frappe
from frappe import _

# ── HSN + GST Rate lookup cache (in-process, no Redis needed) ──────────────────
_HSN_CACHE = {
    # common grocery / kirana items → (hsn, gst_rate%)
    "rice": ("1006", 0),
    "wheat": ("1001", 0),
    "atta": ("1101", 5),
    "maida": ("1101", 5),
    "oil": ("1512", 5),
    "cooking oil": ("1512", 5),
    "sugar": ("1701", 5),
    "salt": ("2501", 0),
    "milk": ("0401", 0),
    "ghee": ("0405", 12),
    "butter": ("0405", 12),
    "dal": ("0713", 0),
    "pulses": ("0713", 0),
    "tea": ("0902", 5),
    "coffee": ("0901", 5),
    "soap": ("3401", 18),
    "shampoo": ("3305", 18),
    "toothpaste": ("3306", 18),
    "biscuit": ("1905", 18),
    "chips": ("1905", 18),
    "chocolate": ("1806", 28),
    "soft drink": ("2202", 28),
    "water": ("2201", 12),
    "bread": ("1905", 5),
    "egg": ("0407", 0),
    "chicken": ("0207", 0),
    "fish": ("0302", 0),
    "paneer": ("0406", 5),
    "notebook": ("4820", 12),
    "pen": ("9608", 12),
    "pencil": ("9609", 12),
    "mobile": ("8517", 18),
    "phone": ("8517", 18),
    "laptop": ("8471", 18),
    "motor": ("8501", 18),
    "bolt": ("7318", 18),
    "wire": ("8544", 18),
    "pipe": ("3917", 18),
    "cement": ("2523", 28),
    "steel": ("7213", 18),
    "fabric": ("5208", 5),
    "cloth": ("5208", 5),
    "medicine": ("3004", 12),
    "tablet": ("3004", 12),
    "syrup": ("3004", 12),
    "vegetable": ("0709", 0),
    "fruit": ("0803", 0),
    "onion": ("0703", 0),
    "potato": ("0701", 0),
    "tomato": ("0702", 0),
    "garlic": ("0703", 0),
    "ginger": ("0910", 5),
}

# Word-to-number mapping for Hinglish spoken numbers
_WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
    # Hindi numerals (common Hinglish)
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "bees": 20, "tees": 30, "chalis": 40, "pachas": 50,
    "sau": 100, "hazaar": 1000,
    # price words
    "rupees": 1, "rupee": 1, "rs": 1, "rupe": 1, "paisa": 0.01,
}

_UNIT_WORDS = {
    "kg": "kg", "kilo": "kg", "kilogram": "kg",
    "gm": "gm", "gram": "gm",
    "litre": "ltr", "liter": "ltr", "ltr": "ltr", "l": "ltr",
    "ml": "ml", "millilitre": "ml",
    "piece": "pcs", "pcs": "pcs", "pc": "pcs", "nos": "pcs",
    "dozen": "doz", "doz": "doz",
    "packet": "pkt", "pkt": "pkt", "pack": "pkt",
    "box": "box", "bottle": "btl", "btl": "btl",
    "meter": "mtr", "mtr": "mtr", "foot": "ft", "ft": "ft",
}

_COMMAND_PATTERNS = [
    (r"\b(remove|delete|hatao)\s+(last|pichla)\s*(item|cheez)?\b", "remove_last"),
    (r"\b(clear|reset|saaf)\s*(all|sab)?\b", "clear_all"),
    (r"\b(generate|create|banao|bana)\s*(bill|invoice|challan)\b", "generate_bill"),
    (r"\b(show|bata|dikha)\s*(total|amount|kitna)\b", "show_total"),
    (r"\b(cancel|band|ruk)\b", "cancel"),
]


def _words_to_number(text):
    """Convert spoken word numbers to int/float."""
    text = text.lower().strip()
    # Pure digit (possibly with decimal)
    try:
        return float(text)
    except ValueError:
        pass
    # Word lookup
    parts = text.split()
    total = 0
    current = 0
    for p in parts:
        if p in _WORD_TO_NUM:
            n = _WORD_TO_NUM[p]
            if n in (100, 1000):
                current = max(current, 1) * n
                if n == 1000:
                    total += current
                    current = 0
            else:
                current += n
    return total + current or None


def _extract_number(text):
    """Pull first numeric value from a token string."""
    text = re.sub(r"[₹,]", "", text)
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return _words_to_number(text)


def _get_hsn_and_gst(item_name):
    """Return (hsn_code, gst_rate) from local cache with partial matching."""
    name_lower = item_name.lower().strip()
    # Exact
    if name_lower in _HSN_CACHE:
        return _HSN_CACHE[name_lower]
    # Partial
    for key, val in _HSN_CACHE.items():
        if key in name_lower or name_lower in key:
            return val
    # Default – 18% is safest unknown fallback for non-essential goods
    return ("9999", 18)


def _detect_command(text):
    """Check if the transcribed text is a voice command."""
    t = text.lower()
    for pattern, cmd in _COMMAND_PATTERNS:
        if re.search(pattern, t):
            return cmd
    return None


def _parse_item_segment(segment):
    """
    Parse a single item phrase like:
      "2 kg rice 100 rupees"
      "ek litre tel 150"
      "milk 50"
    Returns dict or None.
    """
    segment = segment.strip()
    if not segment:
        return None

    tokens = segment.split()

    qty = 1.0
    unit = "pcs"
    price = 0.0
    name_tokens = []

    i = 0
    qty_found = False
    price_found = False

    while i < len(tokens):
        tok = tokens[i].lower()

        # Try as number
        num = _extract_number(tok)

        if num is not None and not qty_found and not name_tokens:
            qty = num
            qty_found = True
            # Check next token for unit
            if i + 1 < len(tokens) and tokens[i + 1].lower() in _UNIT_WORDS:
                unit = _UNIT_WORDS[tokens[i + 1].lower()]
                i += 2
                continue

        elif num is not None and not price_found and name_tokens:
            # Likely price (number after item name)
            price = num
            price_found = True
            # Skip "rupees/rs" suffix tokens
            if i + 1 < len(tokens) and tokens[i + 1].lower() in ("rupees", "rupee", "rs", "rupe"):
                i += 2
                continue

        elif tok in _UNIT_WORDS and qty_found:
            unit = _UNIT_WORDS[tok]

        elif tok not in ("and", "aur", "tatha", "plus", "add", "rupees", "rupee", "rs", "rupe"):
            name_tokens.append(tokens[i])

        i += 1

    if not name_tokens:
        return None

    item_name = " ".join(name_tokens)
    hsn, gst_rate = _get_hsn_and_gst(item_name)

    return {
        "name": item_name,
        "quantity": qty,
        "unit": unit,
        "price": price,
        "hsn_code": hsn,
        "gst_rate": gst_rate,
        "taxable_amount": round(qty * price, 2),
        "gst_amount": round(qty * price * gst_rate / 100, 2),
        "total": round(qty * price * (1 + gst_rate / 100), 2),
    }


def parse_voice_input(text):
    """
    Main NLP parser. Returns:
    {
      "command": None | "remove_last" | "clear_all" | "generate_bill" | "show_total" | "cancel",
      "items": [...],
      "raw": text,
      "confidence": "high" | "medium" | "low"
    }
    """
    text = (text or "").strip()
    if not text:
        return {"command": None, "items": [], "raw": text, "confidence": "low"}

    # Detect command first
    command = _detect_command(text)
    if command:
        return {"command": command, "items": [], "raw": text, "confidence": "high"}

    # Strip prefix words
    text = re.sub(r"^\s*(add|jo|jo)\s+", "", text, flags=re.IGNORECASE)

    # Split on conjunctions to get item segments
    # Separators: "and", "aur", "&", ",", semicolons, "also"
    segments = re.split(r"\s+(?:and|aur|tatha|also|,|;)\s+|\s*,\s*", text, flags=re.IGNORECASE)

    items = []
    for seg in segments:
        seg = seg.strip()
        if seg:
            item = _parse_item_segment(seg)
            if item:
                items.append(item)

    # Confidence rating
    if not items:
        confidence = "low"
    elif all(i["price"] > 0 for i in items):
        confidence = "high"
    elif any(i["price"] > 0 for i in items):
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "command": None,
        "items": items,
        "raw": text,
        "confidence": confidence,
    }


def validate_invoice(items):
    """
    Validate parsed items. Returns (is_valid, errors_list).
    """
    errors = []
    for idx, item in enumerate(items):
        row = idx + 1
        if not item.get("name"):
            errors.append(f"Row {row}: Item name missing")
        if item.get("price", 0) <= 0:
            errors.append(f"Row {row}: '{item.get('name', '?')}' has no price – please confirm")
        if item.get("quantity", 0) <= 0:
            errors.append(f"Row {row}: '{item.get('name', '?')}' has invalid quantity")
    return (len(errors) == 0, errors)


def create_invoice(items, customer="Guest", date_str=None):
    """
    Builds the invoice payload (does NOT save to DB – user must confirm first).
    """
    date_str = date_str or str(date.today())
    invoice_number = f"VOICE-{frappe.generate_hash(length=6).upper()}"

    subtotal = round(sum(i.get("taxable_amount", 0) for i in items), 2)
    total_gst = round(sum(i.get("gst_amount", 0) for i in items), 2)
    grand_total = round(subtotal + total_gst, 2)

    return {
        "invoice_number": invoice_number,
        "date": date_str,
        "customer": customer,
        "items": items,
        "subtotal": subtotal,
        "total_gst": total_gst,
        "grand_total": grand_total,
        "status": "draft",
        "source": "voice_billing",
    }


# ── Whitelisted API endpoints ──────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def process_voice(text):
    """
    POST /api/method/india_compliance.gst_india.api.voice_billing.process_voice
    Body: { text: "2 kg rice 100 and 1 oil 150" }
    Returns parsed items + invoice preview.
    """
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "No transcription text provided"}

    result = parse_voice_input(text)

    if result.get("command"):
        return {
            "success": True,
            "type": "command",
            "command": result["command"],
            "message": f"Command detected: {result['command']}",
        }

    items = result["items"]
    is_valid, errors = validate_invoice(items)
    invoice = create_invoice(items)

    return {
        "success": True,
        "type": "invoice",
        "confidence": result["confidence"],
        "items": items,
        "invoice": invoice,
        "validation": {
            "valid": is_valid,
            "errors": errors,
        },
        "raw": result["raw"],
    }


@frappe.whitelist(allow_guest=True)
def confirm_voice_invoice(invoice_json):
    """
    Called after user reviews and confirms the parsed invoice.
    Simulates saving (extend to real Frappe doctype insert as needed).
    """
    try:
        invoice = json.loads(invoice_json)
    except Exception:
        return {"success": False, "error": "Invalid invoice JSON"}

    # Mark as confirmed
    invoice["status"] = "confirmed"
    invoice["saved_at"] = str(frappe.utils.now_datetime())

    # TODO: Insert into ERPNext Sales Invoice:
    # si = frappe.get_doc({"doctype": "Sales Invoice", ...})
    # si.insert()

    return {"success": True, "message": "Invoice confirmed", "invoice": invoice}


@frappe.whitelist(allow_guest=True)
def get_item_suggestions(query):
    """
    Returns HSN + GST suggestions for autocomplete as user types.
    """
    query = (query or "").lower().strip()
    if len(query) < 2:
        return {"suggestions": []}

    suggestions = []
    for item_name, (hsn, gst) in _HSN_CACHE.items():
        if query in item_name:
            suggestions.append({"name": item_name, "hsn": hsn, "gst_rate": gst})

    return {"suggestions": suggestions[:8]}

@frappe.whitelist(allow_guest=True)
def get_gst_by_hsn(hsn_code):
    """
    POST /api/method/india_compliance.gst_india.api.voice_billing.get_gst_by_hsn
    Returns GST rate for a given HSN code.
    """
    hsn_code = (hsn_code or "").strip()
    if not hsn_code:
        return {"success": False}

    # Reverse lookup in cache
    for item_name, (hsn, gst) in _HSN_CACHE.items():
        if hsn == hsn_code:
            return {"success": True, "hsn": hsn, "gst_rate": gst}

    # Common fallback chapters based on India GST
    if hsn_code.startswith("10") or hsn_code.startswith("07") or hsn_code.startswith("08") or hsn_code.startswith("0401"):
        return {"success": True, "hsn": hsn_code, "gst_rate": 0}
    if hsn_code.startswith("11") or hsn_code.startswith("15") or hsn_code.startswith("17"):
        return {"success": True, "hsn": hsn_code, "gst_rate": 5}
    if hsn_code.startswith("30") or hsn_code.startswith("48"):
        return {"success": True, "hsn": hsn_code, "gst_rate": 12}
    if hsn_code.startswith("2202") or hsn_code.startswith("2523"):
        return {"success": True, "hsn": hsn_code, "gst_rate": 28}

    # Default fallback
    return {"success": True, "hsn": hsn_code, "gst_rate": 18}
