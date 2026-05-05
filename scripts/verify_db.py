import frappe, json
frappe.init("frontend", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()

tenants = frappe.db.get_all(
    "Portal Tenant",
    fields=["name", "company_name", "industry_type", "user", "is_active"],
    order_by="creation desc"
)
users = frappe.db.get_all(
    "User",
    filters=[["email", "like", "%fearoff%"]],
    fields=["email", "enabled", "first_name"]
)

print("\n=== Portal Tenants in DB ===")
for t in tenants:
    print(f"  Tenant: {t.company_name} | Industry: {t.industry_type} | User: {t.user} | Active: {t.is_active}")

print(f"\n=== Test Users in DB ===")
for u in users:
    print(f"  User: {u.email} | Name: {u.first_name} | Enabled: {u.enabled}")

print(f"\n  Total tenants: {len(tenants)}")
print(f"  Total test users: {len(users)}")
frappe.destroy()
