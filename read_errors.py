import frappe
frappe.init("localhost")
frappe.connect()
logs = frappe.get_all("Error Log", fields=["error","creation"], order_by="creation desc", limit=5)
for i, log in enumerate(logs):
    print(f"\n{'='*60}\n[{i+1}] {log.get('creation')}\n{'='*60}")
    print((log.get('error') or '')[:3000])
