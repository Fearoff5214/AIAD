import frappe


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.user = frappe.session.user
    context.is_system_manager = frappe.has_permission("Portal Tenant", "write")
    return context
