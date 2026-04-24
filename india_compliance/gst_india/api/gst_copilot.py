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
        frappe.throw(
            _(
                "Local LLM service is unavailable. Please ensure Ollama is running and model is pulled."
            )
        )


@frappe.whitelist(allow_guest=True)
def gst_copilot_suggested_questions():
    return {"questions": SUGGESTED_QUESTIONS}


@frappe.whitelist(allow_guest=True)
def gst_copilot_chat(question):
    question = (question or "").strip()
    if not question:
        frappe.throw(_("Question is required"))

    knowledge = _load_knowledge()
    context = _best_context_sections(question, knowledge)

    if not context:
        return {
            "answer": "I don't have enough verified GST context to answer that safely.",
            "suggest_verify": True,
        }

    answer = _call_ollama(question, context)
    if not answer:
        answer = "I don't have enough verified GST context to answer that safely."

    return {
        "answer": answer,
        "suggest_verify": True,
    }
