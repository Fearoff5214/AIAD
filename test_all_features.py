#!/usr/bin/env python3
"""
Fearoff AIAD — Full Feature Test & DB Population Script
Runs from inside the Frappe bench environment via:
  docker exec -u frappe fearoff_aiad-backend-1 \
    python /tmp/test_all_features.py
"""

import sys, json, time, base64, io, os

# ── Bootstrap Frappe ────────────────────────────────────────────────────────────
os.chdir("/home/frappe/frappe-bench")
sys.path.insert(0, "apps/frappe")
sys.path.insert(0, "apps/erpnext")
sys.path.insert(0, "apps/india_compliance")

import frappe
frappe.init(site="frontend", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

results = []

def ok(msg):  results.append(("PASS", msg)); print(f"  {PASS} {msg}")
def fail(msg, err=""): results.append(("FAIL", msg)); print(f"  {FAIL} {msg}: {err}")
def section(title): print(f"\n\033[1m{'─'*60}\n  {title}\n{'─'*60}\033[0m")


# ══════════════════════════════════════════════════════════════════════════════
# 1. USER REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════
section("1. USER REGISTRATION")

TEST_USERS = [
    dict(full_name="Arjun Sharma",   email="arjun_mfg@fearoff.test",   password="Fearoff@2026",
         company_name="Arjun Motors Pvt Ltd",     industry_type="Manufacturing", website_slug="arjun-motors"),
    dict(full_name="Priya Wholesale", email="priya_ws@fearoff.test",    password="Fearoff@2026",
         company_name="Priya Distributors LLP",   industry_type="Wholesale",     website_slug="priya-distrib"),
]

from india_compliance.gst_india.api.portal_management import register_portal_user

for u in TEST_USERS:
    try:
        # Clean up any previous test run
        if frappe.db.exists("User", u["email"]):
            frappe.delete_doc("User", u["email"], ignore_permissions=True)
        tenants = frappe.db.get_all("Portal Tenant", filters={"user": u["email"]})
        for t in tenants:
            frappe.delete_doc("Portal Tenant", t.name, ignore_permissions=True)
        frappe.db.commit()

        result = register_portal_user(**u)
        ok(f"Registered {u['full_name']} ({u['industry_type']}) → tenant={result.get('tenant')}")
    except Exception as e:
        fail(f"Register {u['full_name']}", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 2. VOICE BILLING — NLP PARSE
# ══════════════════════════════════════════════════════════════════════════════
section("2. VOICE BILLING — NLP PARSE")

from india_compliance.gst_india.api.voice_billing import process_voice

VOICE_TESTS = [
    "2 kg rice 100 aur 1 litre oil 150",
    "add 5 pieces soap 45 and 3 kg atta 80",
    "10 nos steel bolt 12 and 2 kg cement 350",
]

voice_results = []
for transcript in VOICE_TESTS:
    try:
        res = process_voice(transcript)
        if isinstance(res, str): res = json.loads(res)
        if not isinstance(res, dict): res = res
        items = res.get("items", []) if isinstance(res, dict) else []
        ok(f"'{transcript[:40]}…' → {len(items)} items parsed")
        voice_results.append(res)
    except Exception as e:
        fail(f"Voice parse: '{transcript[:30]}'", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 3. OCR BILLING — SYNTHETIC IMAGE
# ══════════════════════════════════════════════════════════════════════════════
section("3. OCR BILLING — SYNTHETIC IMAGE")

def make_test_invoice_image():
    """Generate a synthetic bill image in memory."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (600, 400), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        lines = [
            "TAX INVOICE",
            "GSTIN: 27AABCA1234C1Z5",
            "Invoice No: SINV-2026-TEST-01   Date: 25-Apr-2026",
            "",
            "Item                Qty   Rate   Amount",
            "Industrial Motor      5  12000   60000",
            "Steel Hex Bolts     500     12    6000",
            "Packing Box          10    200    2000",
            "",
            "Taxable Value:             68000",
            "GST @18%:                  12240",
            "Grand Total:               80240",
        ]
        y = 20
        for line in lines:
            d.text((30, y), line, fill=(0, 0, 0))
            y += 28
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        return None

from india_compliance.gst_india.api.ocr_billing import process_ocr, extract_ocr_data

img_data = make_test_invoice_image()
if img_data:
    try:
        t0 = time.time()
        res = process_ocr(image_base64=img_data, filename="test_invoice.png")
        elapsed = round(time.time() - t0, 1)
        if isinstance(res, str): res = json.loads(res)
        if res.get("success"):
            data = res["data"]
            items = data.get("items", [])
            totals = data.get("totals", {})
            ok(f"OCR completed in {elapsed}s → {len(items)} items, total=₹{totals.get('computed_grand_total', 0)}")
        else:
            fail("OCR process", res.get("error", "Unknown"))
    except Exception as e:
        fail("OCR process", str(e))
else:
    fail("OCR image generation", "PIL unavailable")


# ══════════════════════════════════════════════════════════════════════════════
# 4. GST COPILOT — KNOWLEDGE RETRIEVAL
# ══════════════════════════════════════════════════════════════════════════════
section("4. GST COPILOT — KNOWLEDGE RETRIEVAL")

from india_compliance.gst_india.api.gst_copilot import gst_copilot_chat

COPILOT_TESTS = [
    "What are the mandatory fields for a GST e-invoice?",
    "What is the GST rate for manufacturing goods?",
    "How to handle credit note compliance?",
]

for question in COPILOT_TESTS:
    try:
        res = gst_copilot_chat(question=question)
        if isinstance(res, str): res = json.loads(res)
        answer = res.get("answer", "") if isinstance(res, dict) else str(res)
        if answer and "don't have" not in answer.lower() and len(answer) > 30:
            ok(f"'{question[:45]}…' → answered ({len(answer)} chars)")
        else:
            fail(f"Copilot: '{question[:40]}'", f"Answer: {answer[:60]}")
    except Exception as e:
        fail(f"Copilot: '{question[:40]}'", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 5. PORTAL FEATURES — TENANT LOOKUP
# ══════════════════════════════════════════════════════════════════════════════
section("5. PORTAL TENANT FEATURES")

from india_compliance.gst_india.api.portal_management import get_my_portal_features, TAILORED_FEATURES

for u in TEST_USERS:
    try:
        frappe.set_user(u["email"])
        res = get_my_portal_features()
        if isinstance(res, str): res = json.loads(res)
        industry = res.get("industry_type", "?")
        features = res.get("enabled_features", [])
        ok(f"{u['email']} → industry={industry}, {len(features)} modules enabled")
    except Exception as e:
        fail(f"Portal features for {u['email']}", str(e))
    finally:
        frappe.set_user("Administrator")


# ══════════════════════════════════════════════════════════════════════════════
# 6. VERIFY DB — CHECK SAVED RECORDS
# ══════════════════════════════════════════════════════════════════════════════
section("6. DB VERIFICATION")

for u in TEST_USERS:
    user_exists = frappe.db.exists("User", u["email"])
    tenants = frappe.db.get_all("Portal Tenant", filters={"user": u["email"]},
                                 fields=["name", "company_name", "industry_type", "is_active"])
    if user_exists and tenants:
        t = tenants[0]
        ok(f"DB: User '{u['email']}' + Tenant '{t.company_name}' ({t.industry_type}) saved ✓")
    else:
        fail(f"DB: {u['email']}", f"user_exists={user_exists}, tenants={tenants}")

frappe.db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
section("SUMMARY")
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
total = len(results)
print(f"\n  Total: {total} | \033[92mPassed: {passed}\033[0m | \033[91mFailed: {failed}\033[0m\n")

if failed:
    print("  Failed tests:")
    for r in results:
        if r[0] == "FAIL":
            print(f"    ✗ {r[1]}")

frappe.destroy()
sys.exit(0 if failed == 0 else 1)
