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
    # ── Grains & Staples (0%) ─────────────────────────────────────────────
    "rice": ("1006", 0), "basmati": ("1006", 0), "wheat": ("1001", 0),
    "jowar": ("1007", 0), "bajra": ("1008", 0), "maize": ("1005", 0),
    "corn": ("1005", 0), "ragi": ("1008", 0), "oats": ("1104", 5),
    "atta": ("1101", 5), "maida": ("1101", 5), "suji": ("1103", 0),
    "semolina": ("1103", 0), "besan": ("1106", 5), "gram flour": ("1106", 5),
    "rice flour": ("1102", 0), "wheat flour": ("1101", 5),
    # ── Pulses & Lentils (0%) ─────────────────────────────────────────────
    "dal": ("0713", 0), "pulses": ("0713", 0), "chana": ("0713", 0),
    "moong": ("0713", 0), "masoor": ("0713", 0), "urad": ("0713", 0),
    "rajma": ("0713", 0), "kidney beans": ("0713", 0), "soybean": ("1201", 0),
    # ── Spices (5-12%) ────────────────────────────────────────────────────
    "salt": ("2501", 0), "pepper": ("0904", 5), "turmeric": ("0910", 5),
    "haldi": ("0910", 5), "jeera": ("0909", 5), "cumin": ("0909", 5),
    "coriander": ("0909", 5), "cardamom": ("0908", 5), "clove": ("0907", 5),
    "cinnamon": ("0906", 5), "ginger": ("0910", 5), "garlic": ("0703", 0),
    "chilli": ("0904", 5), "chili": ("0904", 5), "mustard": ("1207", 5),
    "fennel": ("0909", 5), "ajwain": ("0909", 5), "methi": ("0910", 5),
    "masala": ("0910", 5), "biryani masala": ("0910", 5),
    # ── Vegetables (0%) ──────────────────────────────────────────────────
    "vegetable": ("0709", 0), "onion": ("0703", 0), "potato": ("0701", 0),
    "tomato": ("0702", 0), "cabbage": ("0704", 0), "carrot": ("0706", 0),
    "peas": ("0708", 0), "beans": ("0708", 0), "brinjal": ("0709", 0),
    "lady finger": ("0709", 0), "okra": ("0709", 0), "spinach": ("0709", 0),
    "palak": ("0709", 0), "cucumber": ("0707", 0), "gourd": ("0709", 0),
    "lauki": ("0709", 0), "cauliflower": ("0704", 0), "broccoli": ("0704", 0),
    # ── Fruits (0%) ───────────────────────────────────────────────────────
    "fruit": ("0803", 0), "banana": ("0803", 0), "apple": ("0808", 0),
    "mango": ("0804", 0), "orange": ("0805", 0), "grapes": ("0806", 0),
    "papaya": ("0807", 0), "pineapple": ("0804", 0), "watermelon": ("0807", 0),
    "guava": ("0804", 0), "lemon": ("0805", 0), "coconut": ("0801", 0),
    # ── Dairy & Eggs (0-12%) ──────────────────────────────────────────────
    "milk": ("0401", 0), "curd": ("0403", 0), "yogurt": ("0403", 0),
    "dahi": ("0403", 0), "paneer": ("0406", 5), "cheese": ("0406", 12),
    "butter": ("0405", 12), "ghee": ("0405", 12), "cream": ("0401", 5),
    "egg": ("0407", 0), "eggs": ("0407", 0),
    # ── Meat & Seafood (0-5%) ─────────────────────────────────────────────
    "chicken": ("0207", 0), "mutton": ("0204", 0), "goat": ("0204", 0),
    "fish": ("0302", 0), "prawn": ("0306", 5), "shrimp": ("0306", 5),
    "crab": ("0306", 5), "meat": ("0201", 0),
    # ── Oils & Fats (5%) ──────────────────────────────────────────────────
    "oil": ("1512", 5), "cooking oil": ("1512", 5), "sunflower oil": ("1512", 5),
    "groundnut oil": ("1508", 5), "coconut oil": ("1513", 5),
    "mustard oil": ("1514", 5), "palm oil": ("1511", 5),
    "olive oil": ("1509", 5), "soya oil": ("1507", 5),
    # ── Sugar & Sweeteners (5-28%) ────────────────────────────────────────
    "sugar": ("1701", 5), "jaggery": ("1701", 0), "gur": ("1701", 0),
    "honey": ("0409", 5), "glucose": ("1702", 18),
    # ── Beverages (5-28%) ─────────────────────────────────────────────────
    "tea": ("0902", 5), "green tea": ("0902", 5), "coffee": ("0901", 5),
    "water": ("2201", 12), "mineral water": ("2201", 12),
    "soft drink": ("2202", 28), "cola": ("2202", 28), "juice": ("2009", 12),
    "fruit juice": ("2009", 12), "energy drink": ("2202", 28),
    "alcohol": ("2208", 0), "beer": ("2203", 0), "whiskey": ("2208", 0),
    # ── Packaged Foods (5-28%) ────────────────────────────────────────────
    "bread": ("1905", 5), "biscuit": ("1905", 18), "cookie": ("1905", 18),
    "chips": ("2106", 18), "namkeen": ("2106", 12), "noodles": ("1902", 18),
    "pasta": ("1902", 18), "vermicelli": ("1902", 18), "poha": ("1104", 0),
    "chocolate": ("1806", 28), "candy": ("1704", 18), "jam": ("2007", 12),
    "ketchup": ("2103", 12), "sauce": ("2103", 12), "pickle": ("2001", 12),
    "papad": ("1905", 5), "murmura": ("1904", 0), "puffed rice": ("1904", 0),
    "cornflakes": ("1904", 18), "muesli": ("1904", 18),
    "ice cream": ("2105", 18), "frozen food": ("2106", 18),
    # ── Personal Care (18-28%) ────────────────────────────────────────────
    "soap": ("3401", 18), "shampoo": ("3305", 18), "conditioner": ("3305", 18),
    "toothpaste": ("3306", 18), "toothbrush": ("9603", 18),
    "deodorant": ("3307", 18), "perfume": ("3303", 28),
    "face cream": ("3304", 18), "moisturizer": ("3304", 18),
    "sunscreen": ("3304", 18), "lipstick": ("3304", 28),
    "nail polish": ("3304", 18), "hair oil": ("3305", 18),
    "razor": ("8212", 18), "blade": ("8212", 18), "cotton": ("5201", 5),
    "sanitary pad": ("9619", 0), "diaper": ("9619", 12),
    # ── Household (12-28%) ────────────────────────────────────────────────
    "detergent": ("3402", 18), "washing powder": ("3402", 18),
    "dish soap": ("3402", 18), "phenyl": ("3808", 18),
    "toilet cleaner": ("3808", 18), "floor cleaner": ("3808", 18),
    "mosquito coil": ("3808", 18), "repellent": ("3808", 18),
    "candle": ("3406", 12), "matchbox": ("3605", 12),
    "tissue": ("4818", 18), "napkin": ("4818", 18),
    "garbage bag": ("3923", 18), "plastic bag": ("3923", 18),
    # ── Stationery & Paper (12-18%) ───────────────────────────────────────
    "notebook": ("4820", 12), "pen": ("9608", 12), "pencil": ("9609", 12),
    "eraser": ("4016", 18), "scale": ("9017", 18), "ruler": ("9017", 18),
    "stapler": ("8305", 18), "tape": ("3919", 18), "glue": ("3506", 18),
    "paper": ("4802", 12), "envelope": ("4817", 18), "marker": ("9608", 12),
    "highlighter": ("9608", 12), "file": ("4820", 12), "folder": ("4820", 12),
    # ── Electronics (18%) ────────────────────────────────────────────────
    "mobile": ("8517", 18), "phone": ("8517", 18), "smartphone": ("8517", 18),
    "laptop": ("8471", 18), "computer": ("8471", 18), "tablet": ("8471", 18),
    "monitor": ("8528", 18), "keyboard": ("8471", 18), "mouse": ("8471", 18),
    "printer": ("8443", 18), "scanner": ("8471", 18), "camera": ("8525", 18),
    "charger": ("8544", 18), "cable": ("8544", 18), "adapter": ("8504", 18),
    "earphone": ("8518", 18), "headphone": ("8518", 18), "speaker": ("8518", 18),
    "tv": ("8528", 28), "television": ("8528", 28), "refrigerator": ("8418", 28),
    "washing machine": ("8450", 28), "ac": ("8415", 28), "fan": ("8414", 18),
    "mixer": ("8509", 18), "grinder": ("8509", 18), "microwave": ("8516", 28),
    "iron": ("8516", 18), "toaster": ("8516", 18), "water heater": ("8516", 18),
    "bulb": ("8539", 12), "led": ("8539", 12), "tube light": ("8539", 12),
    "battery": ("8506", 18), "torch": ("8513", 18),
    # ── Hardware & Industrial (18-28%) ───────────────────────────────────
    "motor": ("8501", 18), "pump": ("8413", 18), "compressor": ("8414", 18),
    "bolt": ("7318", 18), "nut": ("7318", 18), "screw": ("7318", 18),
    "nail": ("7317", 18), "wire": ("8544", 18), "pipe": ("3917", 18),
    "pvc pipe": ("3917", 18), "hose": ("3917", 18), "valve": ("8481", 18),
    "switch": ("8536", 18), "socket": ("8536", 18), "fuse": ("8536", 18),
    "cement": ("2523", 28), "sand": ("2505", 0), "gravel": ("2517", 0),
    "brick": ("6901", 5), "tile": ("6907", 18), "paint": ("3210", 28),
    "varnish": ("3210", 28), "adhesive": ("3506", 18), "sealant": ("3214", 18),
    "steel": ("7213", 18), "iron rod": ("7214", 18), "aluminum": ("7601", 18),
    "copper": ("7401", 18), "brass": ("7401", 18), "sheet": ("7208", 18),
    "bearing": ("8482", 18), "gear": ("8483", 18), "chain": ("7315", 18),
    # ── Medicines & Health (5-12%) ────────────────────────────────────────
    "medicine": ("3004", 12), "tablet pc": ("3004", 12), "capsule": ("3004", 12),
    "syrup": ("3004", 12), "injection": ("3002", 5), "vaccine": ("3002", 5),
    "bandage": ("3005", 12), "glucose saline": ("3002", 5),
    "sanitizer": ("3808", 18), "mask": ("6307", 5), "gloves": ("3926", 12),
    "thermometer": ("9025", 12), "bp monitor": ("9018", 12),
    "glucometer": ("9027", 12), "oximeter": ("9018", 12),
    # ── Clothing & Textiles (5-12%) ───────────────────────────────────────
    "fabric": ("5208", 5), "cloth": ("5208", 5), "saree": ("5516", 5),
    "shirt": ("6205", 12), "pant": ("6203", 12), "trouser": ("6203", 12),
    "jeans": ("6203", 12), "kurta": ("6211", 5), "salwar": ("6211", 5),
    "dress": ("6204", 5), "t-shirt": ("6109", 12), "jacket": ("6201", 12),
    "sweater": ("6110", 12), "socks": ("6115", 12), "underwear": ("6107", 12),
    "bra": ("6212", 12), "saree blouse": ("6211", 5),
    "shoes": ("6402", 18), "sandal": ("6402", 5), "chappal": ("6402", 5),
    "boots": ("6403", 18), "bag": ("4202", 18), "purse": ("4202", 18),
    "wallet": ("4205", 18), "belt": ("4015", 18),
    # ── Fuel & Energy (0-28%) ────────────────────────────────────────────
    "petrol": ("2710", 0), "diesel": ("2710", 0), "lpg": ("2711", 5),
    "gas": ("2711", 5), "coal": ("2701", 5), "wood": ("4401", 0),
    # ── Agriculture & Seeds (0-5%) ────────────────────────────────────────
    "seed": ("1209", 0), "fertilizer": ("3102", 0), "pesticide": ("3808", 18),
    "tractor": ("8701", 12), "pump set": ("8413", 12),
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


def _fuzzy_score(a, b):
    """Simple character-bigram overlap score 0.0-1.0 (no external deps)."""
    def bigrams(s):
        return {s[i:i+2] for i in range(len(s)-1)}
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 1.0 if a == b else 0.0
    return len(ba & bb) / max(len(ba), len(bb))


def _get_hsn_and_gst(item_name):
    """Return (hsn_code, gst_rate) with exact → substring → fuzzy matching."""
    name_lower = item_name.lower().strip()
    # 1. Exact match
    if name_lower in _HSN_CACHE:
        return _HSN_CACHE[name_lower]
    # 2. Substring match (key inside name or name inside key)
    for key, val in _HSN_CACHE.items():
        if key in name_lower or name_lower in key:
            return val
    # 3. Word-level partial: any word in item matches a key word
    name_words = set(name_lower.split())
    for key, val in _HSN_CACHE.items():
        if name_words & set(key.split()):
            return val
    # 4. Fuzzy bigram match (threshold 0.45)
    best_score, best_val = 0.0, ("9999", 18)
    for key, val in _HSN_CACHE.items():
        score = _fuzzy_score(name_lower, key)
        if score > best_score:
            best_score, best_val = score, val
    if best_score >= 0.45:
        return best_val
    # 5. Default – 18% for unknown non-essential goods
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


def create_invoice(items, customer="Guest", date_str=None, supply_type="intra"):
    """
    Builds the invoice payload with CGST/SGST/IGST split.
    supply_type: 'intra' (within state) → CGST+SGST; 'inter' → IGST only.
    Does NOT save to DB — user must confirm.
    """
    date_str = date_str or str(date.today())
    invoice_number = f"VOICE-{frappe.generate_hash(length=6).upper()}"

    subtotal = round(sum(i.get("taxable_amount", 0) for i in items), 2)
    total_gst = round(sum(i.get("gst_amount", 0) for i in items), 2)
    grand_total = round(subtotal + total_gst, 2)

    # Compute CGST/SGST or IGST
    if supply_type == "inter":
        igst = total_gst
        cgst = sgst = 0.0
    else:
        cgst = round(total_gst / 2, 2)
        sgst = round(total_gst - cgst, 2)
        igst = 0.0

    # Add per-item CGST/SGST/IGST
    enriched_items = []
    for item in items:
        gst_amt = item.get("gst_amount", 0)
        enriched = dict(item)
        if supply_type == "inter":
            enriched.update({"igst_amount": round(gst_amt, 2), "cgst_amount": 0, "sgst_amount": 0})
        else:
            enriched.update({"cgst_amount": round(gst_amt/2, 2), "sgst_amount": round(gst_amt/2, 2), "igst_amount": 0})
        enriched_items.append(enriched)

    return {
        "invoice_number": invoice_number,
        "date": date_str,
        "customer": customer,
        "items": enriched_items,
        "subtotal": subtotal,
        "total_gst": total_gst,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "grand_total": grand_total,
        "supply_type": supply_type,
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


@frappe.whitelist(allow_guest=True)
def validate_gst_invoice(invoice_json, supplier_gstin=None, buyer_gstin=None, supply_type="intra"):
    """
    Real-time GST compliance validator.
    Checks: HSN accuracy, nil-rated items, GSTIN format, tax type correctness.
    Returns compliance_score 0-100 and structured issues/warnings.
    """
    import re as _re
    try:
        invoice = json.loads(invoice_json) if isinstance(invoice_json, str) else invoice_json
    except Exception:
        return {"success": False, "error": "Invalid invoice JSON"}

    items = invoice.get("items", [])
    issues, warnings = [], []
    score = 100
    GSTIN_RE = _re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")

    if supplier_gstin and not GSTIN_RE.match((supplier_gstin or "").upper()):
        issues.append("Invalid supplier GSTIN format"); score -= 15
    if buyer_gstin and not GSTIN_RE.match((buyer_gstin or "").upper()):
        issues.append("Invalid buyer GSTIN format"); score -= 10

    if supplier_gstin and buyer_gstin and len(supplier_gstin) >= 2 and len(buyer_gstin) >= 2:
        sup_st, buy_st = supplier_gstin[:2], buyer_gstin[:2]
        if sup_st == buy_st and supply_type == "inter":
            issues.append(f"Same state ({sup_st}) — use intra-state CGST+SGST, not IGST"); score -= 20
        elif sup_st != buy_st and supply_type == "intra":
            issues.append(f"Different states ({sup_st} vs {buy_st}) — use inter-state IGST"); score -= 20

    nil_rated, unknown_hsn = [], []
    for item in items:
        name = item.get("name", "?")
        hsn = item.get("hsn_code", "")
        gst_rate = float(item.get("gst_rate", 18))
        price = float(item.get("price", 0))
        if price <= 0:
            issues.append(f"'{name}': price is zero"); score -= 10
        if gst_rate == 0:
            nil_rated.append(name)
            warnings.append(f"'{name}' HSN {hsn}: nil-rated (0%) — confirm this is correct")
        if hsn == "9999":
            unknown_hsn.append(name)
            warnings.append(f"'{name}': HSN unknown, defaulted to 9999/18% — please verify"); score -= 5
        if any(k in name.lower() for k in ["food", "beverage", "club", "restaurant"]):
            warnings.append(f"'{name}': ITC may be blocked under Sec 17(5)")

    grand = invoice.get("grand_total", 0)
    if grand > 50000:
        warnings.append("Value >₹50,000: e-way bill required for goods movement")
    if grand >= 500000:
        warnings.append("Value ≥₹5 lakh: e-invoice via IRP may be mandatory if turnover >₹5 crore")

    score = max(0, score)
    return {
        "success": True,
        "compliance_score": score,
        "grade": "A" if score >= 90 else "B" if score >= 70 else "C" if score >= 50 else "F",
        "issues": issues,
        "warnings": warnings,
        "nil_rated_items": nil_rated,
        "unknown_hsn_items": unknown_hsn,
        "summary": f"{len(issues)} issue(s), {len(warnings)} warning(s) — score {score}/100",
    }
