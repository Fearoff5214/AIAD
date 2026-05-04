import base64
from io import BytesIO
import json
import os
import csv
import io
import re

import frappe
from frappe import _
from frappe.utils.password import update_password
from frappe.utils import now_datetime


TAILORED_FEATURES = {
    "Manufacturing": [
        "Accounting", "GST India", "Buying", "Selling",
        "Manufacturing", "Stock", "Quality", "Projects", "Support", "CRM",
        "GST and E-Invoice Automation", "E-Way Bill",
    ],
    "Sales": [
        "Accounting", "GST India", "Selling", "CRM",
        "Pricing Rules", "Stock", "Support",
        "GST and E-Invoice Automation",
    ],
    "Service": [
        "Accounting", "GST India", "Selling", "Support",
        "Projects", "CRM", "HR",
        "GST and E-Invoice Automation",
    ],
    "Retail": [
        "Accounting", "GST India", "Selling", "Buying",
        "Stock", "Pricing Rules", "CRM",
        "GST and E-Invoice Automation",
    ],
    "Wholesale": [
        "Accounting", "GST India", "Buying", "Selling",
        "Stock", "CRM", "Pricing Rules",
        "GST and E-Invoice Automation", "E-Way Bill",
    ],
    "Other": [
        "Accounting", "GST India", "Selling", "Buying",
        "Stock", "CRM",
        "GST and E-Invoice Automation",
    ],
}

# Maps each industry type to its dedicated frontend dashboard URL
INDUSTRY_DASHBOARD_URLS = {
    "Manufacturing": "/user-dashboard-manufacturing",
    "Sales": "/user-dashboard-sales",
    "Service": "/user-dashboard-service",
    "Retail": "/user-dashboard-retail",
    "Wholesale": "/user-dashboard-wholesale",
    "Other": "/user-dashboard-other",
}


def _ensure_system_manager():
    if not frappe.has_permission("Portal Tenant", "write"):
        frappe.throw(_("Only an administrator can perform this action"), frappe.PermissionError)


def _get_tenant_for_user(user):
    return frappe.db.get_value("Portal Tenant", {"user": user, "is_active": 1}, "name")


def _safe_json_dumps(data):
    return json.dumps(data, ensure_ascii=True)


def _log_usage(user, event_type, route=None, metadata=None):
    if not user or user == "Guest":
        return

    tenant = _get_tenant_for_user(user)
    frappe.get_doc(
        {
            "doctype": "Portal Usage Log",
            "user": user,
            "portal_tenant": tenant,
            "event_type": event_type,
            "route": route,
            "metadata_json": _safe_json_dumps(metadata or {}),
        }
    ).insert(ignore_permissions=True)


def _ensure_logged_in():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _seed_demo_invoices():
    return [
        {
            "invoice_number": "INV-1001",
            "gstin": "29ABCDE1234F2Z5",
            "date": "2026-04-24",
            "amount": 10000,
            "gst": 1800,
            "status": "matched",
        },
        {
            "invoice_number": "INV-1002",
            "gstin": "27AAJCS2418Q1ZV",
            "date": "2026-04-24",
            "amount": 8500,
            "gst": 1530,
            "status": "mismatch",
        },
    ]


def _decode_base64_file(file_data):
    if not file_data:
        frappe.throw(_("OCR image data is required"))

    if "," in file_data and file_data.startswith("data:"):
        file_data = file_data.split(",", 1)[1]

    return base64.b64decode(file_data)


def _parse_invoice_text(text):
    normalized_text = re.sub(r"\s+", " ", text or "").strip()

    def _first_match(pattern):
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _first_amount(patterns):
        for pattern in patterns:
            match = re.search(pattern, normalized_text, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
        return 0

    invoice_number = _first_match(r"(?:invoice(?:\s*(?:no|number))?|bill(?:\s*no|\s*number)?|inv(?:oice)?)\s*[:#-]?\s*([A-Z0-9\-/]+)")
    gstin = _first_match(r"\b([0-9A-Z]{15})\b")
    date_value = _first_match(
        r"(?:date|invoice date)\s*[:#-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})"
    )

    taxable_value = _first_amount(
        [
            r"(?:taxable\s*value|taxable\s*amount|assessable\s*value|tax\s*value)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"(?:subtotal|sub\s*total)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ]
    )
    cgst_amount = _first_amount(
        [r"(?:cgst)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)"]
    )
    sgst_amount = _first_amount(
        [r"(?:sgst)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)"]
    )
    igst_amount = _first_amount(
        [r"(?:igst)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)"]
    )
    total_tax = _first_amount(
        [
            r"(?:gst\s*amount|tax\s*amount|total\s*gst|gst)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            r"(?:tax)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ]
    )
    total_amount = _first_amount(
        [
            r"(?:grand\s*total|invoice\s*total|total\s*amount|net\s*amount|amount\s*due)\s*[:#-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        ]
    )

    if not total_tax and (cgst_amount or sgst_amount or igst_amount):
        total_tax = round(cgst_amount + sgst_amount + igst_amount, 2)

    if not total_amount and taxable_value and total_tax:
        total_amount = round(taxable_value + total_tax, 2)

    amount_value = total_amount or taxable_value

    payload = {
        "invoice_number": invoice_number,
        "gstin": gstin,
        "date": date_value,
        "taxable_value": taxable_value,
        "cgst": cgst_amount,
        "sgst": sgst_amount,
        "igst": igst_amount,
        "gst": total_tax,
        "tax_amount": total_tax,
        "total_amount": total_amount,
        "amount": amount_value,
        "status": "pending",
        "source": "gst_invoice_ai_ocr",
        "extracted_text": normalized_text,
    }

    if payload["gstin"]:
        payload["gstin"] = payload["gstin"].upper()

    return payload


@frappe.whitelist(allow_guest=True)
def gst_ocr_invoice(image_base64=None, filename=None):
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        import pytesseract
    except ImportError as exc:
        frappe.throw(
            _(
                "OCR dependencies are missing. Please install Pillow, pytesseract, and the Tesseract OCR engine."
            )
        )

    raw_bytes = _decode_base64_file(image_base64)

    try:
        image = Image.open(BytesIO(raw_bytes))
        image = image.convert("RGB")
        image = ImageOps.grayscale(image)
        image = ImageEnhance.Contrast(image).enhance(2.0)
        image = image.filter(ImageFilter.SHARPEN)
    except Exception as exc:
        frappe.throw(_("Unable to read uploaded image for OCR: {0}").format(exc))

    text = pytesseract.image_to_string(image, config="--psm 6")
    parsed = _parse_invoice_text(text)
    parsed["filename"] = filename

    return {
        "success": True,
        "data": parsed,
        "message": "OCR completed",
    }


@frappe.whitelist()
def gst_upload_invoice(file_url=None, invoice_json=None):
    _ensure_logged_in()

    tenant = _get_tenant_for_user(frappe.session.user)
    if not tenant:
        return {"success": False, "error": "No active tenant", "code": 400}

    payload = {}
    if invoice_json:
        try:
            payload = json.loads(invoice_json)
        except Exception:
            return {"success": False, "error": "Invalid invoice_json", "code": 400}

    data = {
        "invoice_number": payload.get("invoice_number", f"INV-{frappe.generate_hash(length=6).upper()}"),
        "gstin": payload.get("gstin", "29ABCDE1234F2Z5"),
        "date": payload.get("date", str(now_datetime().date())),
        "amount": float(payload.get("amount", 0) or 0),
        "gst": float(payload.get("gst", 0) or 0),
        "status": payload.get("status", "pending"),
        "file_url": file_url,
    }

    return {"success": True, "data": data, "message": "Invoice uploaded"}


@frappe.whitelist()
def gst_invoice_list():
    _ensure_logged_in()
    return {"success": True, "data": _seed_demo_invoices(), "message": "OK"}


@frappe.whitelist()
def gst_reconcile_run():
    _ensure_logged_in()

    invoices = _seed_demo_invoices()
    matched = [row for row in invoices if row.get("status") == "matched"]
    mismatched = [row for row in invoices if row.get("status") == "mismatch"]
    missing = []

    return {
        "success": True,
        "data": {"matched": matched, "mismatched": mismatched, "missing": missing},
        "message": "Reconciliation completed",
    }


@frappe.whitelist()
def gst_reconcile_results():
    return gst_reconcile_run()


@frappe.whitelist()
def gst_dashboard_summary():
    _ensure_logged_in()

    invoices = _seed_demo_invoices()
    total = len(invoices)
    matched = len([row for row in invoices if row.get("status") == "matched"])
    mismatched = len([row for row in invoices if row.get("status") == "mismatch"])
    missing = 0
    compliance_score = round((matched / total) * 100, 2) if total else 0

    return {
        "success": True,
        "data": {
            "total_invoices": total,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "compliance_score": compliance_score,
        },
        "message": "OK",
    }


@frappe.whitelist()
def gst_notifications():
    _ensure_logged_in()

    return {
        "success": True,
        "data": [
            {"severity": "warning", "message": "1 invoice has tax mismatch"},
            {"severity": "info", "message": "Daily reconciliation is available"},
        ],
        "message": "OK",
    }


@frappe.whitelist()
def gst_report_export():
    _ensure_logged_in()

    output = io.StringIO()
    fieldnames = ["invoice_number", "gstin", "date", "amount", "gst", "status"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in _seed_demo_invoices():
        writer.writerow(row)

    return {
        "success": True,
        "data": {"csv": output.getvalue()},
        "message": "Export ready",
    }


@frappe.whitelist(allow_guest=True)
def register_portal_user(full_name, email, password, company_name, industry_type, website_slug):
    if frappe.db.exists("User", email):
        frappe.throw(_("A user with this email already exists"))

    industry_type = (industry_type or "Other").strip().title()
    if industry_type not in TAILORED_FEATURES:
        industry_type = "Other"

    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": full_name,
            "enabled": 1,
            "new_password": password,
            "send_welcome_email": 0,
            "user_type": "Website User",
        }
    )
    user.insert(ignore_permissions=True)

    tenant = frappe.get_doc(
        {
            "doctype": "Portal Tenant",
            "company_name": company_name,
            "industry_type": industry_type,
            "website_slug": website_slug,
            "user": email,
            "enabled_features_json": _safe_json_dumps(TAILORED_FEATURES[industry_type]),
            "is_active": 1,
        }
    )
    tenant.insert(ignore_permissions=True)

    dashboard_url = INDUSTRY_DASHBOARD_URLS.get(industry_type, "/user-portal")

    return {
        "message": "Account created successfully",
        "tenant": tenant.name,
        "industry_type": industry_type,
        "enabled_features": TAILORED_FEATURES[industry_type],
        "dashboard_url": dashboard_url,
        "login_url": f"/login?redirect-to={dashboard_url}",
    }


@frappe.whitelist()
def get_user_dashboard_page():
    """Return the correct dashboard URL for the logged-in user's industry type."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

    tenant_name = _get_tenant_for_user(frappe.session.user)
    if not tenant_name:
        return {"dashboard_url": "/user-portal", "industry_type": None}

    tenant = frappe.get_doc("Portal Tenant", tenant_name)
    industry_type = tenant.industry_type or "Other"
    dashboard_url = INDUSTRY_DASHBOARD_URLS.get(industry_type, "/user-portal")

    return {
        "dashboard_url": dashboard_url,
        "industry_type": industry_type,
        "company_name": tenant.company_name,
        "website_slug": tenant.website_slug,
        "enabled_features": json.loads(tenant.enabled_features_json or "[]"),
    }


@frappe.whitelist()
def get_my_portal_features():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

    tenant_name = _get_tenant_for_user(frappe.session.user)
    if not tenant_name:
        return {"tenant": None, "enabled_features": []}

    tenant = frappe.get_doc("Portal Tenant", tenant_name)
    _log_usage(
        frappe.session.user,
        event_type="feature_access",
        route="/api/method/india_compliance.gst_india.api.portal_management.get_my_portal_features",
        metadata={"tenant": tenant_name},
    )

    return {
        "tenant": tenant.name,
        "company_name": tenant.company_name,
        "industry_type": tenant.industry_type,
        "assigned_admin": tenant.assigned_admin,
        "enabled_features": json.loads(tenant.enabled_features_json or "[]"),
    }


@frappe.whitelist()
def assign_admin_to_tenant(tenant_name, admin_user):
    _ensure_system_manager()

    if not frappe.db.exists("Portal Tenant", tenant_name):
        frappe.throw(_("Portal Tenant not found"))

    if not frappe.db.exists("User", admin_user):
        frappe.throw(_("Admin user does not exist"))

    tenant = frappe.get_doc("Portal Tenant", tenant_name)
    tenant.assigned_admin = admin_user
    tenant.save(ignore_permissions=True)

    _log_usage(
        frappe.session.user,
        event_type="assign_admin",
        route="/api/method/india_compliance.gst_india.api.portal_management.assign_admin_to_tenant",
        metadata={"tenant": tenant_name, "admin_user": admin_user},
    )

    return {"message": _("Admin assigned"), "tenant": tenant_name, "admin_user": admin_user}


@frappe.whitelist()
def grant_admin_access(user_email, role="System Manager"):
    _ensure_system_manager()

    if not frappe.db.exists("User", user_email):
        frappe.throw(_("User does not exist"))

    user = frappe.get_doc("User", user_email)
    user.add_roles(role)

    _log_usage(
        frappe.session.user,
        event_type="grant_admin_access",
        route="/api/method/india_compliance.gst_india.api.portal_management.grant_admin_access",
        metadata={"target_user": user_email, "role": role},
    )

    return {"message": _("Admin access granted"), "user": user_email, "role": role}


@frappe.whitelist()
def track_usage(event_type, route=None, metadata_json=None):
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

    metadata = {}
    if metadata_json:
        metadata = json.loads(metadata_json)

    _log_usage(
        frappe.session.user,
        event_type=event_type,
        route=route,
        metadata=metadata,
    )

    return {"message": _("Usage tracked")}


@frappe.whitelist()
def list_portal_users(industry_type=None):
    _ensure_system_manager()

    filters = {"is_active": 1}
    if industry_type:
        filters["industry_type"] = industry_type.strip().title()

    return frappe.get_all(
        "Portal Tenant",
        fields=["name", "company_name", "industry_type", "user", "assigned_admin", "is_active"],
        filters=filters,
        order_by="modified desc",
    )


def ensure_create_account_nav_item():
    settings = frappe.get_single("Website Settings")

    desired_items = [
        {"label": "Home", "url": "/user-portal"},
        {"label": "GST Copilot", "url": "/gst-copilot"},
        {"label": "Create Account", "url": "/user-register"},
    ]

    existing = list(settings.get("top_bar_items") or [])
    labels_to_item = {}
    for item in existing:
        labels_to_item[(item.label or "").strip().lower()] = item

    for nav_item in desired_items:
        item = labels_to_item.get(nav_item["label"].lower())
        if item:
            item.url = nav_item["url"]
            item.right = 0
            item.open_in_new_tab = 0
        else:
            settings.append(
                "top_bar_items",
                {
                    "label": nav_item["label"],
                    "url": nav_item["url"],
                    "right": 0,
                    "open_in_new_tab": 0,
                },
            )

    settings.save(ignore_permissions=True)

    return {
        "message": _("Portal navigation ensured"),
        "updated": True,
    }


def set_platform_branding():
    """Override Frappe's default app name with 'GST Compliance Platform' across System and Website Settings."""
    APP_TITLE = "GST Compliance Platform"

    # System Settings – controls the 'Login to <app_name>' heading
    try:
        sys_settings = frappe.get_single("System Settings")
        sys_settings.app_name = APP_TITLE
        sys_settings.save(ignore_permissions=True)
    except Exception:
        pass

    # Website Settings – controls browser tab title, header, and login page heading
    try:
        web_settings = frappe.get_single("Website Settings")
        web_settings.app_name = APP_TITLE
        web_settings.title = APP_TITLE
        web_settings.save(ignore_permissions=True)
    except Exception:
        pass

    frappe.db.commit()
    return {"message": _("Platform branding set"), "title": APP_TITLE}


def ensure_primary_admin_account():
    email = os.getenv("PRIMARY_ADMIN_EMAIL", "parameshlogaa@gmail.com").strip().lower()
    password = os.getenv("PRIMARY_ADMIN_PASSWORD", "PE42026")
    full_name = os.getenv("PRIMARY_ADMIN_NAME", "Paramesh Logaa")

    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.first_name = full_name
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": full_name,
                "enabled": 1,
                "new_password": password,
                "send_welcome_email": 0,
                "user_type": "System User",
            }
        )
        user.insert(ignore_permissions=True)

    user.add_roles("System Manager")
    update_password(email, password)

    for tenant_name in frappe.get_all("Portal Tenant", filters={"is_active": 1}, pluck="name"):
        tenant = frappe.get_doc("Portal Tenant", tenant_name)
        tenant.assigned_admin = email
        tenant.save(ignore_permissions=True)

    ensure_create_account_nav_item()
    set_platform_branding()

    return {"message": _("Primary admin account ensured"), "email": email}


def ensure_demo_portal_accounts():
    demo_accounts = [
        {
            "full_name": "Test Manufacturer",
            "email": "test_manufacturer@example.com",
            "password": "Test@12345",
            "company_name": "Test_Manufacturer",
            "industry_type": "Manufacturing",
            "website_slug": "test-manufacturer",
        },
        {
            "full_name": "Test Wholesaler",
            "email": "test_wholesaler@example.com",
            "password": "Test@12345",
            "company_name": "Test_Wholesaler",
            "industry_type": "Wholesale",
            "website_slug": "test-wholesaler",
        },
        {
            "full_name": "Test Sales Agent",
            "email": "test_sales@example.com",
            "password": "Test@12345",
            "company_name": "Test_Sales",
            "industry_type": "Sales",
            "website_slug": "test-sales",
        },
        {
            "full_name": "Test Service Provider",
            "email": "test_service@example.com",
            "password": "Test@12345",
            "company_name": "Test_Service",
            "industry_type": "Service",
            "website_slug": "test-service",
        },
        {
            "full_name": "Test Retailer",
            "email": "test_retail@example.com",
            "password": "Test@12345",
            "company_name": "Test_Retail",
            "industry_type": "Retail",
            "website_slug": "test-retail",
        },
    ]

    created = []
    for account in demo_accounts:
        industry_type = account["industry_type"]
        if industry_type not in TAILORED_FEATURES:
            industry_type = "Other"
        account["industry_type"] = industry_type

        if frappe.db.exists("User", account["email"]):
            user = frappe.get_doc("User", account["email"])
            user.enabled = 1
            user.first_name = account["full_name"]
            user.user_type = "Website User"
            user.save(ignore_permissions=True)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": account["email"],
                    "first_name": account["full_name"],
                    "enabled": 1,
                    "new_password": account["password"],
                    "send_welcome_email": 0,
                    "user_type": "Website User",
                }
            )
            user.insert(ignore_permissions=True)

        if frappe.db.exists("Portal Tenant", {"user": account["email"]}):
            tenant = frappe.get_doc(
                "Portal Tenant", _get_tenant_for_user(account["email"])
            )
            tenant.company_name = account["company_name"]
            tenant.industry_type = industry_type
            tenant.website_slug = account["website_slug"]
            tenant.enabled_features_json = _safe_json_dumps(TAILORED_FEATURES[industry_type])
            tenant.is_active = 1
            tenant.save(ignore_permissions=True)
        else:
            tenant = frappe.get_doc(
                {
                    "doctype": "Portal Tenant",
                    "company_name": account["company_name"],
                    "industry_type": industry_type,
                    "website_slug": account["website_slug"],
                    "user": account["email"],
                    "enabled_features_json": _safe_json_dumps(
                        TAILORED_FEATURES[industry_type]
                    ),
                    "is_active": 1,
                }
            )
            tenant.insert(ignore_permissions=True)

        created.append({"email": account["email"], "tenant": tenant.name})

    return {"message": _("Demo portal accounts ensured"), "accounts": created}
