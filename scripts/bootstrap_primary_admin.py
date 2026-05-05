import argparse

import frappe


def main():
    parser = argparse.ArgumentParser(description="Seed the primary admin account")
    parser.add_argument("site", help="Frappe site name")
    args = parser.parse_args()

    frappe.init(site=args.site)
    frappe.connect()

    from india_compliance.gst_india.api.portal_management import ensure_primary_admin_account

    result = ensure_primary_admin_account()
    print(result)
    frappe.destroy()


if __name__ == "__main__":
    main()