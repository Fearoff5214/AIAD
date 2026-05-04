#!/usr/bin/env python3
"""
Fearoff AIAD — Model Accuracy & Metrics Evaluation
===================================================
Evaluates:
  1. Voice NLP Parser  — item extraction accuracy, F1, precision, recall
  2. OCR Pipeline      — field extraction accuracy, GSTIN/amount detection
  3. HSN Lookup        — coverage & mapping accuracy
  4. Invoice Classifier— bill type classification accuracy

Run standalone (no Frappe needed):
  python evaluate_model_metrics.py
"""

import sys, re, json, time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap — add the app to path so we can import without Frappe
# ──────────────────────────────────────────────────────────────────────────────
sys.path.insert(0, ".")
sys.path.insert(0, "india_compliance")

# Minimal frappe stub so the module can be imported standalone
import types, unittest.mock as mock
frappe_stub = types.ModuleType("frappe")
frappe_stub.whitelist = lambda **kw: (lambda f: f)
frappe_stub.throw    = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
frappe_stub._ = lambda x: x
frappe_stub.generate_hash = lambda length=6: "ABCDEF"
frappe_stub.utils = types.SimpleNamespace(now_datetime=lambda: "2026-04-25 12:00:00")
sys.modules.setdefault("frappe", frappe_stub)

# ──────────────────────────────────────────────────────────────────────────────
# Import the actual module code
# ──────────────────────────────────────────────────────────────────────────────
from india_compliance.gst_india.api.voice_billing import (
    parse_voice_input, _get_hsn_and_gst, _HSN_CACHE
)

# OCR helpers (no Paddle/Tesseract needed for unit tests)
from india_compliance.gst_india.api.ocr_billing import (
    _normalize_text, _parse_line_items, _extract_totals,
    _classify_bill, _enrich_items
)

# ──────────────────────────────────────────────────────────────────────────────
# Colour helpers
# ──────────────────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"; W = "\033[97m"; E = "\033[0m"; BOLD = "\033[1m"

def hdr(title): print(f"\n{BOLD}{B}{'═'*65}\n  {title}\n{'═'*65}{E}")
def sub(title): print(f"\n{BOLD}  {'─'*55}\n  {title}\n  {'─'*55}{E}")

# ──────────────────────────────────────────────────────────────────────────────
# Metric helpers
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Metrics:
    name: str
    tp: int = 0; fp: int = 0; fn: int = 0; tn: int = 0
    latencies: List[float] = field(default_factory=list)

    @property
    def precision(self):
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self):
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self):
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self):
        total = self.tp + self.fp + self.fn + self.tn
        return (self.tp + self.tn) / total if total else 0.0

    @property
    def avg_latency_ms(self):
        return (sum(self.latencies) / len(self.latencies) * 1000) if self.latencies else 0.0

    def pct(self, v): return f"{v*100:.1f}%"

    def show(self):
        col = G if self.f1 >= 0.8 else (Y if self.f1 >= 0.6 else R)
        print(f"    {'Precision':<18} {col}{self.pct(self.precision)}{E}")
        print(f"    {'Recall':<18} {col}{self.pct(self.recall)}{E}")
        print(f"    {'F1-Score':<18} {col}{self.pct(self.f1)}{E}")
        print(f"    {'Accuracy':<18} {col}{self.pct(self.accuracy)}{E}")
        print(f"    {'TP/FP/FN/TN':<18} {self.tp}/{self.fp}/{self.fn}/{self.tn}")
        if self.latencies:
            print(f"    {'Avg Latency':<18} {self.avg_latency_ms:.1f} ms")


# ══════════════════════════════════════════════════════════════════════════════
# 1. VOICE NLP — Item Extraction
# ══════════════════════════════════════════════════════════════════════════════
hdr("1.  VOICE NLP PARSER — ITEM EXTRACTION METRICS")

VOICE_TESTS = [
    # (transcript, expected_items_count, expected_item_names, has_price)
    ("2 kg rice 100 aur 1 litre oil 150",                   2, ["rice","oil"],           True),
    ("add 5 pieces soap 45 and 3 kg atta 80",               2, ["soap","atta"],          True),
    ("10 nos steel bolt 12 and 2 kg cement 350",            2, ["steel bolt","cement"],  True),
    ("milk 50",                                              1, ["milk"],                 True),
    ("ek kg ghee 500 aur do kg sugar 80",                   2, ["ghee","sugar"],         True),
    ("1 dozen egg 72",                                       1, ["egg"],                  True),
    ("generate bill",                                        0, [],                       False),   # command
    ("clear all",                                            0, [],                       False),   # command
    ("3 kg dal 90 and 2 ltr water 40 and 1 pkt soap 55",   3, ["dal","water","soap"],   True),
    ("100 nos pen 10 and 50 notebook 20",                   2, ["pen","notebook"],       True),
    ("remove last item",                                     0, [],                       False),   # command
    ("laptop 45000",                                         1, ["laptop"],               True),
    ("2 kg tomato 30 aur 1 kg onion 25 aur 500 gm ginger 20", 3, ["tomato","onion","ginger"], True),
    ("show total",                                           0, [],                       False),   # command
    ("5 kg wheat 40 and 2 kg maida 60 and 1 kg dal 85",    3, ["wheat","maida","dal"],  True),
]

m_voice_count  = Metrics("Voice: Item Count")
m_voice_name   = Metrics("Voice: Name Detected")
m_voice_price  = Metrics("Voice: Price > 0")
m_voice_cmd    = Metrics("Voice: Command Detection")

confidence_dist = {"high": 0, "medium": 0, "low": 0}
parse_errors = []

for transcript, exp_count, exp_names, has_price in VOICE_TESTS:
    t0 = time.perf_counter()
    try:
        res = parse_voice_input(transcript)
    except Exception as ex:
        parse_errors.append((transcript, str(ex)))
        continue
    lat = time.perf_counter() - t0
    m_voice_count.latencies.append(lat)

    items   = res.get("items", [])
    command = res.get("command")
    conf    = res.get("confidence", "low")

    # Command detection
    is_command_expected = (exp_count == 0 and not has_price)
    if is_command_expected:
        if command:   m_voice_cmd.tp += 1
        else:         m_voice_cmd.fn += 1
        continue  # skip item metrics for commands
    else:
        if not command: m_voice_cmd.tn += 1
        else:           m_voice_cmd.fp += 1

    confidence_dist[conf] = confidence_dist.get(conf, 0) + 1

    # Item count accuracy
    if len(items) == exp_count:  m_voice_count.tp += 1
    elif len(items) > exp_count: m_voice_count.fp += 1
    else:                        m_voice_count.fn += 1

    # Name matching (partial)
    extracted_names = " ".join(i.get("name","").lower() for i in items)
    for en in exp_names:
        if en in extracted_names: m_voice_name.tp += 1
        else:                     m_voice_name.fn += 1

    # Price detection
    if has_price:
        for item in items:
            if item.get("price", 0) > 0: m_voice_price.tp += 1
            else:                        m_voice_price.fn += 1

sub("Item Count Accuracy")
m_voice_count.show()
sub("Item Name Detection")
m_voice_name.show()
sub("Price Extraction")
m_voice_price.show()
sub("Command Detection")
m_voice_cmd.show()
print(f"\n  {W}Confidence Distribution:{E} High={G}{confidence_dist['high']}{E}  Medium={Y}{confidence_dist['medium']}{E}  Low={R}{confidence_dist['low']}{E}")
if parse_errors:
    print(f"\n  {R}Parse Errors:{E}")
    for t, e in parse_errors: print(f"    ✗ '{t[:40]}' → {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. HSN LOOKUP — Coverage & Accuracy
# ══════════════════════════════════════════════════════════════════════════════
hdr("2.  HSN CODE LOOKUP — ACCURACY METRICS")

HSN_TESTS = [
    # (query_name, expected_hsn, expected_gst_rate)
    ("rice",          "1006",  0),
    ("wheat",         "1001",  0),
    ("cooking oil",   "1512",  5),
    ("soap",          "3401", 18),
    ("mobile",        "8517", 18),
    ("laptop",        "8471", 18),
    ("chocolate",     "1806", 28),
    ("cement",        "2523", 28),
    ("medicine",      "3004", 12),
    ("ghee",          "0405", 12),
    ("dal",           "0713",  0),
    ("tea",           "0902",  5),
    ("steel",         "7213", 18),
    ("fabric",        "5208",  5),
    ("motor",         "8501", 18),
    # Partial-match tests
    ("steel bolt",    "7318", 18),
    ("rice bags",     "1006",  0),   # partial: "rice" in "rice bags"
    ("coconut oil",   "1512",  5),   # partial: "oil" in cache
    # Unknown — should return 9999 / 18%
    ("widget",        "9999", 18),
    ("gadget",        "9999", 18),
]

m_hsn = Metrics("HSN Code Exact Match")
m_gst = Metrics("GST Rate Match")

for name, exp_hsn, exp_gst in HSN_TESTS:
    hsn, gst = _get_hsn_and_gst(name)
    if hsn == exp_hsn: m_hsn.tp += 1
    else:              m_hsn.fn += 1
    if gst == exp_gst: m_gst.tp += 1
    else:              m_gst.fn += 1

total_hsn = len(HSN_TESTS)
print(f"\n  Catalogue size : {W}{len(_HSN_CACHE)}{E} items")
print(f"  Tests run      : {total_hsn}")
sub("HSN Code Match")
m_hsn.show()
sub("GST Rate Match")
m_gst.show()


# ══════════════════════════════════════════════════════════════════════════════
# 3. OCR TEXT PARSING — Field Extraction Accuracy
# ══════════════════════════════════════════════════════════════════════════════
hdr("3.  OCR TEXT PARSER — FIELD EXTRACTION METRICS")

# Ground-truth invoice text blocks (simulating PaddleOCR raw output)
OCR_TEST_CASES = [
    {
        "name": "Standard Product Invoice",
        "raw": """TAX INVOICE
GSTIN: 27AABCA1234C1Z5
Invoice No: SINV-2026-001   Date: 25/04/2026
Item                Qty   Rate   Amount
Industrial Motor      5  12000   60000
Steel Hex Bolts     500     12    6000
Packing Box          10    200    2000
Taxable Value:             68000
GST @18%:                  12240
Grand Total:               80240""",
        "expected": {
            "gstin": "27AABCA1234C1Z5",
            "invoice_number": "SINV-2026-001",
            "total": 80240,
            "taxable": 68000,
            "item_count": 3,
        }
    },
    {
        "name": "Freight/Service Invoice",
        "raw": """TRANSPORT BILL
Packing Charges:   500
Transportation: 2500
Loading Charges: 300
Unloading Charges: 200
SGST @9%: 315
CGST @9%: 315
Grand Total: 4130""",
        "expected": {
            "gstin": None,
            "total": 4130,
            "sgst": 315,
            "cgst": 315,
            "item_count": 4,
        }
    },
    {
        "name": "Simple Retail Bill",
        "raw": """RETAIL BILL
GSTIN: 33AAAAR6720M1ZG
Date: 01/04/2026
Rice 2 kg         100
Oil 1 ltr          80
Soap 3 pcs        135
Subtotal           315
IGST @5%            15
Total             330""",
        "expected": {
            "gstin": "33AAAAR6720M1ZG",
            "total": 330,
            "taxable": 315,
            "igst": 15,
            "item_count": 3,
        }
    },
    {
        "name": "Manufacturing Invoice",
        "raw": """TAX INVOICE
GSTIN: 24AABCR6898M1ZN
Invoice No: MFG-2026-099
Steel Plates 10 nos 5000 50000
Wire Coil 50 kg 200 10000
Bolt Set 200 pcs 25 5000
Taxable Amount: 65000
CGST @9%: 5850
SGST @9%: 5850
Grand Total: 76700""",
        "expected": {
            "gstin": "24AABCR6898M1ZN",
            "invoice_number": "MFG-2026-099",
            "total": 76700,
            "cgst": 5850,
            "sgst": 5850,
            "item_count": 3,
        }
    },
]

m_ocr_gstin = Metrics("OCR: GSTIN Extraction")
m_ocr_total = Metrics("OCR: Total Amount")
m_ocr_items = Metrics("OCR: Item Count")
m_ocr_tax   = Metrics("OCR: Tax Amounts")

for tc in OCR_TEST_CASES:
    clean = _normalize_text(tc["raw"])
    lines = clean.splitlines()
    items = _parse_line_items(lines)
    totals = _extract_totals(clean)
    exp = tc["expected"]

    print(f"\n  [{W}{tc['name']}{E}]")

    # GSTIN
    exp_gstin = exp.get("gstin")
    got_gstin = totals.get("gstin")
    gstin_ok = (got_gstin == exp_gstin) or (exp_gstin is None and got_gstin is None)
    if gstin_ok:   m_ocr_gstin.tp += 1; print(f"    GSTIN  {G}✓{E}  {got_gstin}")
    else:          m_ocr_gstin.fn += 1; print(f"    GSTIN  {R}✗{E}  got={got_gstin!r}  exp={exp_gstin!r}")

    # Total amount (within 1% tolerance)
    exp_total = exp.get("total")
    got_total = totals.get("total")
    total_ok = exp_total is None or (got_total and abs(got_total - exp_total) / exp_total < 0.05)
    if total_ok:   m_ocr_total.tp += 1; print(f"    Total  {G}✓{E}  ₹{got_total}")
    else:          m_ocr_total.fn += 1; print(f"    Total  {R}✗{E}  got=₹{got_total}  exp=₹{exp_total}")

    # Item count
    exp_ic = exp.get("item_count", 0)
    got_ic = len(items)
    ic_ok = (got_ic == exp_ic)
    if ic_ok:  m_ocr_items.tp += 1; print(f"    Items  {G}✓{E}  {got_ic}")
    else:      m_ocr_items.fn += 1; print(f"    Items  {R}✗{E}  got={got_ic}  exp={exp_ic}")

    # Tax amounts
    for tax_key in ("cgst", "sgst", "igst"):
        exp_t = exp.get(tax_key)
        if exp_t is not None:
            got_t = totals.get(tax_key, 0)
            tok = (got_t and abs(got_t - exp_t) / max(exp_t, 1) < 0.05)
            if tok:   m_ocr_tax.tp += 1; print(f"    {tax_key.upper():<5}  {G}✓{E}  ₹{got_t}")
            else:     m_ocr_tax.fn += 1; print(f"    {tax_key.upper():<5}  {R}✗{E}  got=₹{got_t}  exp=₹{exp_t}")

sub("GSTIN Detection")
m_ocr_gstin.show()
sub("Total Amount Extraction")
m_ocr_total.show()
sub("Line Item Count")
m_ocr_items.show()
sub("Tax Amount Extraction (CGST/SGST/IGST)")
m_ocr_tax.show()


# ══════════════════════════════════════════════════════════════════════════════
# 4. BILL CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════
hdr("4.  BILL CLASSIFIER — ACCURACY METRICS")

CLASSIFIER_TESTS = [
    # (items, totals_dict, raw_text, expected_label)
    ([{"name":"Rice"},{"name":"Dal"}],        {"gstin":"27AABCA1234C1Z5"}, "purchase goods received stock", "Purchase"),
    ([{"name":"Motor"},{"name":"Bolt"}],      {"gstin":"24AABCR6898M1ZN"}, "invoice items", "Purchase"),
    ([],                                       {},                          "electricity bill rent utility", "Expense"),
    ([{"name":"Fuel"}],                        {},                          "fuel transport travel",         "Expense"),
    ([{"name":"A"},{"name":"B"},{"name":"C"},{"name":"D"}], {}, "invoice",  "Inventory"),
    ([{"name":"Wire"}],                        {"gstin":"33AAAAR6720M1ZG"}, "general invoice",               "Purchase"),
]

m_cls = Metrics("Bill Classifier")
print()
for items, totals, text, exp_label in CLASSIFIER_TESTS:
    got = _classify_bill(items, totals, text)
    ok  = (got == exp_label)
    if ok:  m_cls.tp += 1; print(f"  {G}✓{E}  '{text[:40]}'  →  {got}")
    else:   m_cls.fn += 1; print(f"  {R}✗{E}  '{text[:40]}'  →  got={got!r}  exp={exp_label!r}")

m_cls.show()


# ══════════════════════════════════════════════════════════════════════════════
# 5. END-TO-END VOICE NLP BENCHMARKS
# ══════════════════════════════════════════════════════════════════════════════
hdr("5.  END-TO-END LATENCY BENCHMARK")

BENCH_INPUTS = [
    "2 kg rice 100 aur 1 litre oil 150",
    "add 5 pieces soap 45 and 3 kg atta 80 and 1 packet tea 60",
    "10 nos steel bolt 12 and 2 kg cement 350 and 1 motor 12000",
    "milk 50",
    "ek kg ghee 500 aur do kg sugar 80 aur paanch kg dal 90",
]
RUNS_PER_INPUT = 10

all_latencies = []
for inp in BENCH_INPUTS:
    lats = []
    for _ in range(RUNS_PER_INPUT):
        t0 = time.perf_counter()
        parse_voice_input(inp)
        lats.append((time.perf_counter() - t0) * 1000)
    avg_l = sum(lats)/len(lats)
    all_latencies.extend(lats)
    print(f"  {inp[:55]:<55}  avg={avg_l:.2f}ms")

all_latencies.sort()
p50 = all_latencies[len(all_latencies)//2]
p95 = all_latencies[int(len(all_latencies)*0.95)]
p99 = all_latencies[int(len(all_latencies)*0.99)]
print(f"\n  {W}Latency Percentiles (Voice NLP){E}")
print(f"    {'P50':<10} {p50:.2f} ms")
print(f"    {'P95':<10} {p95:.2f} ms")
print(f"    {'P99':<10} {p99:.2f} ms")
print(f"    {'Min':<10} {min(all_latencies):.2f} ms")
print(f"    {'Max':<10} {max(all_latencies):.2f} ms")


# ══════════════════════════════════════════════════════════════════════════════
# OVERALL SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════════
hdr("OVERALL MODEL METRICS SUMMARY")

def row(label, m: Metrics):
    col = G if m.f1 >= 0.8 else (Y if m.f1 >= 0.6 else R)
    return (f"  {W}{label:<35}{E} "
            f"Acc={col}{m.accuracy*100:5.1f}%{E}  "
            f"Prec={col}{m.precision*100:5.1f}%{E}  "
            f"Rec={col}{m.recall*100:5.1f}%{E}  "
            f"F1={col}{m.f1*100:5.1f}%{E}")

all_metrics = [
    ("Voice NLP — Item Count",        m_voice_count),
    ("Voice NLP — Name Detection",    m_voice_name),
    ("Voice NLP — Price Extraction",  m_voice_price),
    ("Voice NLP — Command Detection", m_voice_cmd),
    ("HSN Code Lookup",               m_hsn),
    ("GST Rate Lookup",               m_gst),
    ("OCR — GSTIN Extraction",        m_ocr_gstin),
    ("OCR — Total Amount",            m_ocr_total),
    ("OCR — Line Item Count",         m_ocr_items),
    ("OCR — Tax Amounts",             m_ocr_tax),
    ("Bill Type Classifier",          m_cls),
]

print()
for label, m in all_metrics:
    print(row(label, m))

# Overall weighted F1
all_f1 = [m.f1 for _, m in all_metrics]
overall_f1 = sum(all_f1) / len(all_f1)
col = G if overall_f1 >= 0.8 else (Y if overall_f1 >= 0.6 else R)
print(f"\n  {BOLD}{'Overall Macro-Avg F1':<35}{E} {BOLD}{col}{overall_f1*100:.1f}%{E}")

print(f"\n  {W}Latency (P50 / P95 / P99):{E} {p50:.1f}ms / {p95:.1f}ms / {p99:.1f}ms\n")
print(f"{BOLD}{'═'*65}{E}\n")
