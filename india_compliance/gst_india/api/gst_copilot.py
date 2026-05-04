import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import frappe
from frappe import _

SUGGESTED_QUESTIONS = [
    "What are the mandatory fields for an e-invoice under India GST?",
    "When should we generate e-way bill for a sales invoice?",
    "How can a manufacturing company stay compliant with GST invoice rules?",
    "What GST records should a wholesale company maintain monthly?",
    "How to handle credit note and debit note GST compliance?",
]


def _knowledge_file_path():
    return Path(
        frappe.get_app_path(
            "india_compliance",
            "gst_india",
            "data",
            "gst_compliance_knowledge.md",
        )
    )


def _load_knowledge():
    path = _knowledge_file_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _tokenize(text):
    return set(re.findall(r"[a-zA-Z0-9]+", (text or "").lower()))


def _best_context_sections(question, knowledge, top_k=4):
    chunks = [chunk.strip() for chunk in knowledge.split("\n## ") if chunk.strip()]
    question_tokens = _tokenize(question)
    scored = []

    for idx, chunk in enumerate(chunks):
        chunk_tokens = _tokenize(chunk)
        overlap = len(question_tokens.intersection(chunk_tokens))
        if overlap > 0:
            scored.append((overlap, idx, chunk))

    scored.sort(reverse=True)
    selected = [chunk for _, _, chunk in scored[:top_k]]
    return "\n\n".join(selected)


def _ollama_config():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")
    timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
    return base_url, model, timeout


def _build_prompt(question, context):
    return f"""You are a friendly India GST assistant helping business owners.

Rules:
1) Be SHORT. Max 4 bullet points. No long paragraphs.
2) Use simple plain English. No legal jargon.
3) Only use facts from the provided context or well-known GST rules.
4) If unsure, say: 'Please verify with a CA or CBIC notification.'
5) Never invent numbers, dates, or legal sections.

Context:
{context}

Question: {question}

Answer in 3-4 short bullet points:"""


def _call_ollama(question, context):
    base_url, model, timeout = _ollama_config()
    payload = {
        "model": model,
        "prompt": _build_prompt(question, context),
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.2,
        },
    }

    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
            data = json.loads(content)
            return data.get("response", "").strip()
    except urllib.error.URLError:
        return None  # Caller will handle gracefully
    except Exception:
        return None


@frappe.whitelist(allow_guest=True)
def gst_copilot_suggested_questions():
    return {"questions": SUGGESTED_QUESTIONS}



_DATA_PATTERNS = [
    (re.compile(r'\b(past|last)\s+(\d+)\s+(day|days)\b', re.I), 'days'),
    (re.compile(r'\b(today|today\'s)\b', re.I), 'today'),
    (re.compile(r'\b(recent|latest|new)\s*(bill|invoice|bills|invoices)\b', re.I), 'recent'),
    (re.compile(r'\b(show|list|get|give)\s+.*?(bill|invoice)\b', re.I), 'recent'),
]


def _handle_data_query(question):
    """
    Detect intent to retrieve billing/invoice data.
    Returns an answer string if handled, else None.
    """
    q_lower = question.lower()

    # Figure out time range
    days = None
    for pattern, intent in _DATA_PATTERNS:
        m = pattern.search(question)
        if m:
            if intent == 'days':
                try: days = int(m.group(2))
                except Exception: days = 7
            elif intent == 'today':
                days = 1
            else:
                days = 7
            break

    if days is None:
        return None  # Not a data query

    try:
        since = frappe.utils.add_days(frappe.utils.today(), -days)
        invoices = frappe.db.sql(
            """
            SELECT invoice_number, date, customer, grand_total, source
            FROM `tabOCR Invoice`
            WHERE date >= %s
            ORDER BY date DESC
            LIMIT 20
            """,
            (since,),
            as_dict=True,
        )

        if not invoices:
            return f"No invoices found in the past {days} day(s). Try scanning or creating one via Smart Billing."

        lines = [f"Found **{len(invoices)}** invoice(s) from the past {days} day(s):\n"]
        for inv in invoices:
            lines.append(
                f"• **{inv.get('invoice_number','?')}** | "
                f"{inv.get('date','')} | "
                f"₹{inv.get('grand_total',0):.2f} | "
                f"{inv.get('customer','') or 'Guest'}"
            )
        return "\n".join(lines)

    except Exception as e:
        err = str(e)
        if "doesn't exist" in err or "Table" in err:
            return (
                f"No billing records found yet. "
                "Use Smart Billing to scan or voice-enter invoices — they'll appear here once saved."
            )
        return f"Could not retrieve invoices: {err}"


@frappe.whitelist(allow_guest=True)
def gst_copilot_chat(question):
    question = (question or "").strip()
    if not question:
        return {"answer": "Please type a question.", "suggest_verify": False}

    # 1. Check if it's a data/invoice retrieval intent
    data_answer = _handle_data_query(question)
    if data_answer is not None:
        return {"answer": data_answer, "suggest_verify": False}

    # 2. Knowledge-base RAG for compliance questions
    knowledge = _load_knowledge()
    context = _best_context_sections(question, knowledge)

    if not context:
        return {
            "answer": (
                "I don't have verified GST context for that. "
                "Try asking about invoicing rules, e-way bills, GSTR filing, or HSN/SAC codes."
            ),
            "suggest_verify": True,
        }

    answer = _call_ollama(question, context)
    if not answer:
        # Ollama unavailable — return knowledge snippet directly
        snippet = context[:800].strip()
        answer = f"*(AI offline — showing reference)*\n\n{snippet}"

    return {
        "answer": answer,
        "suggest_verify": True,
    }
