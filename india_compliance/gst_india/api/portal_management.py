import json
import os
import csv
import io

import frappe
from frappe import _
from frappe.utils.password import update_password
from frappe.utils import now_datetime


TAILORED_FEATURES = {
    "Manufacturing": [
        "Production Order Dashboard",
        "BOM and Material Planning",
        "Batch and Inventory Tracking",
        "GST and E-Invoice Automation",
    ],
    "Wholesale": [
        "Bulk Order Management",
        "Distributor Pricing Rules",
        "High-volume Invoicing",
        "GST and E-Way Bill Automation",
    ],
    "Other": [
        "Customer Management",
        "Sales and Purchase Tracking",
        "GST Returns Utilities",
    ],
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

    return {
        "message": "Account created successfully",
        "tenant": tenant.name,
        "industry_type": industry_type,
        "enabled_features": TAILORED_FEATURES[industry_type],
        "login_url": "/login?redirect-to=/user-portal",
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

    for item in settings.get("top_bar_items"):
        if (item.label or "").strip().lower() == "create account":
            item.url = "/user-register"
            item.right = 0
            item.open_in_new_tab = 0
            settings.save(ignore_permissions=True)
            return {
                "message": _("Create Account navigation ensured"),
                "updated": True,
            }

    settings.append(
        "top_bar_items",
        {
            "label": "Create Account",
            "url": "/user-register",
            "right": 0,
            "open_in_new_tab": 0,
        },
    )
    settings.save(ignore_permissions=True)

    return {
        "message": _("Create Account navigation ensured"),
        "updated": True,
    }


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

    return {"message": _("Primary admin account ensured"), "email": email}


def ensure_demo_portal_accounts():
    demo_accounts = [
        {
            "full_name": "Test Manufacturer",
            "email": "test_manufacturer@example.com",
            "password": "Test@12345",
            "company_name": "Test_Manufactuer",
            "industry_type": "Manufacturing",
            "website_slug": "test-manufactuer",
        },
        {
            "full_name": "Test Wholesaler",
            "email": "test_wholesaler@example.com",
            "password": "Test@12345",
            "company_name": "Test_Wholesaler",
            "industry_type": "Wholesale",
            "website_slug": "test-wholesaler",
        },
    ]

    created = []
    for account in demo_accounts:
        industry_type = account["industry_type"]
        if industry_type not in TAILORED_FEATURES:
            industry_type = "Other"

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
