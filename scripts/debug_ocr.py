"""
Debug script: creates a synthetic invoice image, runs Tesseract, then
runs our item-parsing logic so we can see exactly what is going wrong.
"""
import sys
sys.path.insert(0, "/home/frappe/frappe-bench/apps/india_compliance")

try:
    from PIL import Image, ImageDraw
    import pytesseract, io, re
    print("[OK] PIL and pytesseract imported")
except Exception as e:
    print("[ERROR] Import failed:", e)
    sys.exit(1)

# ── 1. Build a tiny synthetic invoice ────────────────────────────────────────
img = Image.new("RGB", (900, 300), color=(255, 255, 255))
draw = ImageDraw.Draw(img)
invoice_lines = [
    "GUJARAT FREIGHT TOOLS",
    "TAX INVOICE No: GFT/2024/001",
    "Description             HSN   Qty   Rate     Taxable   CGST  SGST  Total",
    "Panch Tool Kit          8205   5   250.00   1250.00   112.50 112.50 1475.00",
    "Plastic Extractor Kit   3926   2   350.00    700.00    63.00  63.00  826.00",
    "Grand Total                                                         2301.00",
]
y = 10
for line in invoice_lines:
    draw.text((10, y), line, fill=(0, 0, 0))
    y += 40

# ── 2. Run Tesseract ──────────────────────────────────────────────────────────
raw_text = pytesseract.image_to_string(img, config="--psm 6")
print("\n=== RAW TESSERACT OUTPUT ===")
for i, ln in enumerate(raw_text.splitlines()):
    print(f"  {i:02d}: {repr(ln)}")

# ── 3. Run our parser ─────────────────────────────────────────────────────────
# Import the actual parser function
import importlib.util, os
spec = importlib.util.spec_from_file_location(
    "ocr_billing",
    "/home/frappe/frappe-bench/apps/india_compliance/india_compliance/gst_india/api/ocr_billing.py"
)
mod = importlib.util.load_from_spec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

lines = raw_text.splitlines()
items = mod._parse_line_items(lines)
print("\n=== PARSED ITEMS ===")
for it in items:
    print(" ", it)
if not items:
    print("  [NONE DETECTED]")
