# Fearoff AIAD – GST Compliance & Smart Billing Platform

A production-ready ERPNext (Frappe v15) application with AI-powered GST compliance tools, multi-tenant user management, voice billing, OCR bill scanning, and a role-based portal suite.

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
scripts\run_fearoff_aiad.bat
```

Or manually:

```bash
docker compose up -d
```

Wait ~60 seconds for Frappe to initialise, then open:

**http://localhost:8085/gst-login**

---

## 📁 Project Structure

```
Fearoff_AIAD/
│
├── india_compliance/              ← Main Frappe app (mounted live into containers)
│   │
│   ├── gst_india/
│   │   ├── api/                   ← Backend API layer
│   │   │   ├── voice_billing.py   ← Voice NLP parser, HSN lookup, invoice builder
│   │   │   ├── ocr_billing.py     ← PaddleOCR / Tesseract pipeline
│   │   │   ├── gst_copilot.py     ← RAG-based GST AI assistant (Ollama)
│   │   │   └── portal_management.py ← Tenant CRUD, auth, session, activity log
│   │   │
│   │   ├── data/
│   │   │   └── gst_compliance_knowledge.md  ← RAG knowledge base for Copilot
│   │   │
│   │   └── doctype/               ← Frappe DocTypes
│   │       ├── portal_tenant/     ← Multi-tenant record
│   │       └── portal_usage_log/  ← User activity audit trail
│   │
│   ├── www/                       ← Frappe web pages (URL = filename without ext)
│   │   │
│   │   ├── gst-login.html/.py     ← Role-based login (Admin → panel, User → dashboard)
│   │   ├── user-register.html/.py ← Self-service tenant registration
│   │   ├── user-portal.html/.py   ← Portal home / industry selector
│   │   │
│   │   ├── user-dashboard-manufacturing.html/.py   ← 🏭 Manufacturing workspace
│   │   ├── user-dashboard-sales.html/.py           ← 💼 Sales workspace
│   │   ├── user-dashboard-service.html/.py         ← 🛠️ Service workspace
│   │   ├── user-dashboard-retail.html/.py          ← 🏪 Retail workspace
│   │   ├── user-dashboard-wholesale.html/.py       ← 📦 Wholesale workspace
│   │   ├── user-dashboard-other.html/.py           ← 🔹 Other workspace
│   │   │
│   │   ├── smart-billing.html/.py  ← ⚡ Voice + OCR billing UI
│   │   ├── gst-copilot.html/.py    ← 🤖 GST AI Copilot chat
│   │   ├── gst-demo.html           ← 📄 GST compliance demo
│   │   └── admin-user-management.html/.py  ← ⚙️ Admin panel (tenant mgmt + activity)
│   │
│   └── public/
│       ├── css/
│       │   └── ud-shared.css       ← Shared dark-teal dashboard styles
│       ├── js/                     ← Frappe bundle JS
│       └── images/                 ← Static images
│
├── scripts/                        ← Dev & ops utilities
│   ├── bootstrap_primary_admin.py  ← Seed admin account on first run
│   ├── start_frappe_server.py      ← Site initialisation helper
│   ├── run_fearoff_aiad.bat        ← Windows one-click launcher
│   ├── verify_db.py                ← Check DB schema + tenant records
│   ├── debug_ocr.py                ← Debug OCR pipeline output
│   ├── read_errors.py              ← Parse Frappe error logs
│   ├── evaluate_model_metrics.py   ← OCR accuracy / F1 evaluation
│   └── tests/
│       ├── test_all_features.py    ← Full feature integration tests
│       ├── test_ocr_live.py        ← Live OCR pipeline tests
│       └── test_paddle_ocr.py      ← PaddleOCR model tests
│
├── docs/                           ← Setup & troubleshooting guides
│   ├── SETUP_AND_STARTUP.md        ← Full Docker + Frappe setup guide
│   ├── STARTUP_TROUBLESHOOTING.md  ← Common errors and fixes
│   └── credentials.txt             ← Local dev credentials (⚠️ keep private)
│
├── docker-compose.yml              ← Full stack orchestration
├── Dockerfile                      ← Custom image (Tesseract + PaddleOCR)
├── setup_assets.sh                 ← Asset symlink script (runs at container start)
├── setup.py / pyproject.toml       ← Python package metadata
└── README.md                       ← This file
```

---

## 🌐 Portal Pages

| URL | Page | Access |
|-----|------|--------|
| `/gst-login` | **🔑 Login** | Everyone — routes by role |
| `/user-register` | **➕ Register** | Guest |
| `/user-portal` | **🏠 Portal Home** | Authenticated users |
| `/user-dashboard-manufacturing` | **🏭 Manufacturing** | Manufacturing tenants |
| `/user-dashboard-sales` | **💼 Sales** | Sales tenants |
| `/user-dashboard-service` | **🛠️ Service** | Service tenants |
| `/user-dashboard-retail` | **🏪 Retail** | Retail tenants |
| `/user-dashboard-wholesale` | **📦 Wholesale** | Wholesale tenants |
| `/smart-billing` | **⚡ Smart Billing** | All authenticated users |
| `/gst-copilot` | **🤖 GST Copilot** | All authenticated users |
| `/gst-demo` | **📄 GST Demo** | All authenticated users |
| `/admin-user-management` | **⚙️ Admin Panel** | System Manager only |
| `/app` | **📋 ERP Desk** | System Manager only |

---

## 🔐 Multi-Tenant Auth

The platform uses **role-based routing** on login:

- **Admin** (System Manager role) → `/admin-user-management`
  - Full tenant management, user activity log, live session monitor
  - Assign admins to tenants, grant roles, activate/deactivate tenants

- **User** (Portal Tenant record) → their industry dashboard
  - Scoped to their company's industry type
  - Cannot access other tenants' dashboards or the admin panel

Both accounts have visible **logout buttons** in the sidebar that clear the Frappe session and redirect to `/gst-login`.

---

## ⚡ Smart Billing (Voice + OCR)

### 🎤 Voice Billing
1. Navigate to `/smart-billing`
2. Select supply type: **Intra-State (CGST+SGST)** or **Inter-State (IGST)**
3. Tap the **🎤 mic button** or type in the transcript box
4. Speak naturally — supports **Hinglish** (Hindi + English mixed):
   - *"2 kg basmati rice 120 and 1 litre sunflower oil 95"*
   - *"3 soap 45 rupees and 500 gm paneer 80"*
   - *"Remove last item / Generate bill"*
5. Review parsed items — auto-filled **HSN codes + GST%**
6. Check the **🛡️ GST Compliance** score (A/B/C/F grade)
7. Click **✅ Confirm & Save**

**HSN Coverage:** 200+ items across grains, vegetables, dairy, spices, electronics, clothing, medicines, hardware, fuel and more.

### 📷 OCR Bill Scanning
1. Click the **Scan Bill** tab
2. Upload a bill image (JPEG/PNG/WEBP)
3. Click **🔍 Scan & Extract**
4. Review extracted items (editable)
5. Click **✅ Confirm & Save**

---

## 🛡️ GST Compliance Validator

The Smart Billing page automatically runs a compliance check after every parse:

| Check | What it validates |
|---|---|
| GSTIN format | 15-char regex, state code prefix |
| Supply type | Intra vs inter-state CGST/SGST vs IGST |
| Nil-rated items | Flags 0% GST items for confirmation |
| Unknown HSN | Warns when item defaults to HSN 9999 / 18% |
| ITC block | Flags food, beverages, club services |
| E-invoice threshold | Alerts if invoice ≥ ₹5 lakh |
| E-way bill | Alerts if goods value > ₹50,000 |

---

## 🤖 GST Copilot

AI assistant powered by **Ollama (DeepSeek-R1:7b)** running locally.

**Knowledge base covers:** GST rates & slabs, GSTR-1/2B/3B/9 filing, RCM, e-invoice, e-way bill, SAC codes, ITC rules, HSN lookup, Input Service Distributor, QRMP scheme.

---

## 🔐 Demo Accounts

| Email | Password | Role |
|-------|----------|------|
| `parameshlogaa@gmail.com` | `PE42026` | Primary Admin |
| `test_manufacturer@example.com` | `Test@12345` | Manufacturing User |
| `test_wholesaler@example.com` | `Test@12345` | Wholesale User |

---

## 🏗️ Docker Architecture

```
docker-compose.yml
├── backend        ← Gunicorn + Frappe/ERPNext (port 8000 internal)
├── frontend       ← NGINX reverse proxy (port 8085 external)
├── db             ← MariaDB 10.6
├── redis-cache    ← Redis cache
├── redis-queue    ← Redis job queue
├── scheduler      ← Frappe background scheduler
├── queue-long     ← Long-running background workers
├── queue-short    ← Short-running background workers
└── websocket      ← Socket.IO real-time server
```

**LLM:** Local Ollama on host → accessed via `host.docker.internal:11434`

---

## 🔌 Key API Endpoints

### Auth & Tenant
```
GET  /api/method/...portal_management.get_current_user_info
POST /api/method/...portal_management.portal_logout
POST /api/method/...portal_management.list_portal_users       (admin only)
POST /api/method/...portal_management.update_tenant           (admin only)
POST /api/method/...portal_management.admin_get_activity_log  (admin only)
POST /api/method/...portal_management.admin_get_active_sessions (admin only)
```

### Voice Billing
```
POST /api/method/...voice_billing.process_voice
POST /api/method/...voice_billing.confirm_voice_invoice
POST /api/method/...voice_billing.validate_gst_invoice
GET  /api/method/...voice_billing.get_item_suggestions?query=rice
GET  /api/method/...voice_billing.get_gst_by_hsn?hsn_code=1006
```

### OCR & Copilot
```
POST /api/method/...ocr_billing.process_ocr
POST /api/method/...gst_copilot.gst_copilot_chat
GET  /api/method/...gst_copilot.gst_copilot_suggested_questions
```

---

## 🛠️ Troubleshooting

See [`docs/STARTUP_TROUBLESHOOTING.md`](docs/STARTUP_TROUBLESHOOTING.md) for full details.

### Quick fixes

```bash
# 502 Bad Gateway
docker exec fearoff_aiad-frontend-1 nginx -s reload

# Clear Frappe cache after template changes
docker exec fearoff_aiad-backend-1 bash -c "cd /home/frappe/frappe-bench && bench --site frontend clear-cache"

# Full reset
docker compose down
docker volume rm fearoff_aiad_sites fearoff_aiad_db-data
docker compose up -d
```

---

## 📝 GST Compliance Notes

- Voice billing auto-maps items to **HSN codes** using exact → substring → fuzzy matching
- All invoices show **CGST + SGST** (intra-state) or **IGST** (inter-state) split
- OCR parsing extracts GSTIN, invoice number, date, line items, and tax amounts
- Extracted data is **never auto-saved** — user must review and confirm
- Admin can see all tenant activity (logins, page views, logouts) in the **Activity Log**

---

*Fearoff AIAD — Built with Frappe v15, ERPNext, Ollama DeepSeek-R1, PaddleOCR / Tesseract*
