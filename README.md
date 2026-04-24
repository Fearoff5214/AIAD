# Fearoff AIAD – GST Compliance & Smart Billing Portal

A production-ready ERPNext (Frappe v15) application with AI-powered GST compliance tools, voice billing, OCR bill scanning, and a unified dark-teal portal suite.

---

## 🚀 Quick Start

### Prerequisites
- **Docker Desktop** (running)
- **Ollama** installed on the host with `deepseek-r1:7b` pulled

```bash
ollama pull deepseek-r1:7b
```

### Start the Application

```bash
# Windows – double-click or run:
run_fearoff_aiad.bat
```

Or manually:

```bash
cd Fearoff_AIAD
docker compose up -d
```

Wait ~60 seconds for Frappe to initialise, then open:

**http://localhost:8085**

---

## 🌐 Portal Pages

| URL | Page | Description |
|-----|------|-------------|
| `/user-portal` | **User Dashboard** | Sector-tailored dashboard with GST tools and feature tiles |
| `/smart-billing` | **⚡ Smart Billing** | Voice billing + OCR bill scanning (NEW) |
| `/gst-copilot` | **🤖 GST Copilot** | AI chat assistant for India GST compliance |
| `/gst-demo` | **📄 GST Demo** | Interactive correct vs. incorrect invoice comparison |
| `/user-register` | **➕ Register** | Self-service business account registration |
| `/admin-user-management` | **⚙️ Admin Panel** | Tenant management, user admin, usage analytics |
| `/app` | **📋 ERP Desk** | Full Frappe/ERPNext desk interface |

All pages share a unified **dark-teal navigation bar** with links to every section.

---

## ⚡ Smart Billing (Voice + OCR)

### 🎤 Voice Billing
1. Navigate to `/smart-billing`
2. Tap the **🎤 mic button** (or type in the transcript box)
3. Speak naturally — supports **Hinglish** (Hindi + English mixed):
   - *"2 kg rice 100 and 1 oil 150"*
   - *"Add 5 nos soap 45 rupees"*
   - *"Remove last item"*
   - *"Generate bill"*
4. Review the parsed items table (editable)
5. Click **✅ Confirm & Save**

**Voice Commands Supported:**
| Command | Action |
|---------|--------|
| "Remove last item / hatao" | Removes the last line |
| "Clear all / saaf" | Clears all items |
| "Generate bill / bana" | Confirms invoice |
| "Show total / kitna" | Refreshes totals |

### 📷 OCR Bill Scanning
1. Click the **Scan Bill** tab
2. Upload a photo or drag & drop a bill image (JPEG/PNG/WEBP)
3. Click **🔍 Scan & Extract**
4. Review the extracted items and totals (editable)
5. Click **✅ Confirm & Save**

**Pipeline:** `Image → Preprocess → Tesseract OCR → AI Parse → Validate → User Confirm → Save`

> ⚠️ OCR output is **never auto-saved** — you must review and confirm.

---

## 🤖 GST Copilot

AI assistant powered by **Ollama (DeepSeek-R1:7b)** running locally on your machine.

- Ask compliance questions in plain English
- Answers grounded in the GST knowledge base
- Supports voice input (mic button)

---

## 📄 GST Compliance Demo

Interactive educational tool embedded in the User Dashboard:

- **✅ Correct Invoice** — Example of a fully compliant GST invoice
- **❌ Invoice with Errors** — Common mistakes highlighted (wrong rate, exempt goods, value mismatch)
- **🧮 Live Validator** — Enter your own line items to check tax accuracy in real-time

---

## 🔐 Demo Accounts

| Email | Password | Role |
|-------|----------|------|
| `parameshlogaa@gmail.com` | `PE42026` | Primary Admin |
| `test_manufacturer@example.com` | `Test@12345` | Manufacturing User |
| `test_wholesaler@example.com` | `Test@12345` | Wholesale User |

---

## 🏗️ Architecture

```
docker-compose.yml
├── backend        ← Gunicorn + Frappe/ERPNext (port 8000 internal)
├── frontend       ← NGINX reverse proxy (port 8085 external)
├── db             ← MariaDB 10.6
├── redis-cache    ← Redis cache
├── redis-queue    ← Redis job queue
├── scheduler      ← Frappe scheduler
├── queue-long     ← Background workers
├── queue-short    ← Background workers
└── websocket      ← Socket.IO server
```

**LLM:** Local Ollama on host → accessed via `host.docker.internal:11434`

**Custom App:** `india_compliance/` (mounted live into all containers)

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `india_compliance/www/user-portal.html` | Main user dashboard |
| `india_compliance/www/smart-billing.html` | Voice + OCR billing UI |
| `india_compliance/www/gst-copilot.html` | AI copilot chat UI |
| `india_compliance/www/gst-demo.html` | GST compliance demo |
| `india_compliance/www/admin-user-management.html` | Admin panel UI |
| `india_compliance/gst_india/api/voice_billing.py` | Voice NLP parser + API |
| `india_compliance/gst_india/api/ocr_billing.py` | OCR pipeline + API |
| `india_compliance/gst_india/api/gst_copilot.py` | AI copilot backend |
| `india_compliance/gst_india/api/portal_management.py` | Tenant & admin APIs |
| `start_frappe_server.py` | Site init orchestrator |
| `run_fearoff_aiad.bat` | One-click startup script |
| `Dockerfile` | Custom image (includes Tesseract OCR) |
| `docker-compose.yml` | Full stack orchestration |

---

## 🔌 API Endpoints

### Voice Billing
```
POST /api/method/india_compliance.gst_india.api.voice_billing.process_voice
     Body: { "text": "2 kg rice 100 and 1 oil 150" }

POST /api/method/india_compliance.gst_india.api.voice_billing.confirm_voice_invoice
     Body: { "invoice_json": "..." }

GET  /api/method/india_compliance.gst_india.api.voice_billing.get_item_suggestions
     Query: ?query=rice
```

### OCR Billing
```
POST /api/method/india_compliance.gst_india.api.ocr_billing.process_ocr
     Body: { "image_base64": "data:image/jpeg;base64,...", "filename": "bill.jpg" }

POST /api/method/india_compliance.gst_india.api.ocr_billing.confirm_ocr_invoice
     Body: { "invoice_json": "..." }
```

### GST Copilot
```
POST /api/method/india_compliance.gst_india.api.gst_copilot.gst_copilot_chat
     Body: { "question": "What is the GST rate for rice?" }

GET  /api/method/india_compliance.gst_india.api.gst_copilot.gst_copilot_suggested_questions
```

---

## 🛠️ Troubleshooting

### 502 Bad Gateway
The nginx frontend must accept `localhost` as a server name. This is auto-patched in the Dockerfile. If it recurs:
```bash
docker exec -u root fearoff_aiad-frontend-1 \
  sed -i 's/server_name frontend;/server_name frontend localhost;/' \
  /etc/nginx/conf.d/frappe.conf
docker exec fearoff_aiad-frontend-1 nginx -s reload
```

### OCR Not Working
Ensure Tesseract is installed (it's in the Dockerfile):
```bash
docker exec fearoff_aiad-backend-1 tesseract --version
docker exec fearoff_aiad-backend-1 pip show pytesseract
```

### AI Copilot Not Responding
Ensure Ollama is running on your host:
```bash
ollama list           # should show deepseek-r1:7b
ollama run deepseek-r1:7b "hello"
```

### Full Reset (if state drifts)
```bash
docker compose down
docker volume rm fearoff_aiad_sites fearoff_aiad_db-data
docker compose up -d
```

---

## 📝 GST Compliance Notes

- Voice billing auto-suggests **HSN codes** and **GST rates** for 60+ common items
- OCR parsing extracts GSTIN, invoice number, date, line items, CGST/SGST/IGST
- All extracted data goes through validation before saving
- The GST Demo educates users on common errors: wrong rates, taxing exempt goods, value mismatches

---

*Fearoff AIAD — Built with Frappe v15, ERPNext, Ollama DeepSeek-R1, Tesseract OCR*
