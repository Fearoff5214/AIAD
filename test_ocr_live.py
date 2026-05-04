"""Run inside container to test the full OCR pipeline end-to-end."""
import base64
import sys
import os

# Minimal 1x1 white PNG (to test pipeline without a real image)
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
)

sys.path.insert(0, "/home/frappe/frappe-bench/apps/india_compliance")
os.chdir("/home/frappe/frappe-bench")

try:
    from india_compliance.gst_india.api.ocr_billing import (
        _preprocess_image,
        _run_paddleocr,
        _run_tesseract,
        extract_ocr_data,
    )
    print("✅ Import OK")
except Exception as e:
    print(f"❌ Import FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# Step 1: preprocess
try:
    raw = base64.b64decode(TINY_PNG_B64)
    img = _preprocess_image(raw)
    print(f"✅ Preprocess OK: {img.size}")
except Exception as e:
    print(f"❌ Preprocess FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# Step 2: PaddleOCR
try:
    text = _run_paddleocr(img)
    print(f"✅ PaddleOCR OK (empty image → '{text[:60]}')")
except Exception as e:
    print(f"❌ PaddleOCR FAILED: {e}")
    import traceback; traceback.print_exc()

# Step 3: Full pipeline via extract_ocr_data
try:
    result = extract_ocr_data(TINY_PNG_B64, filename="test.png")
    print(f"✅ extract_ocr_data OK: {len(result.get('items', []))} items")
except Exception as e:
    print(f"❌ extract_ocr_data FAILED: {e}")
    import traceback; traceback.print_exc()
