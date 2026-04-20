import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def _coerce_payload(payload, field_name):
    if payload is None:
        return None

    if isinstance(payload, str):
        payload = frappe.parse_json(payload)

    if payload is None:
        frappe.throw(_("Invalid JSON payload for {0}").format(field_name))

    return payload


def _validate_line_item(item, idx):
    item_code = item.get("item_code")
    qty = flt(item.get("qty"))
    rate = flt(item.get("rate"))

    if not item_code:
        frappe.throw(_("Row {0}: item_code is required").format(idx))

    if qty <= 0:
        frappe.throw(_("Row {0}: qty must be greater than zero").format(idx))

    if rate < 0:
        frappe.throw(_("Row {0}: rate cannot be negative").format(idx))


@frappe.whitelist()
def create_billing_invoice(
    customer,
    company,
    items,
    posting_date=None,
    due_date=None,
    currency=None,
    taxes_and_charges=None,
    submit=1,
):
    """Create a Sales Invoice using a simple billing payload."""

    if not customer or not company:
        frappe.throw(_("customer and company are required"))

    parsed_items = _coerce_payload(items, "items")
    if not isinstance(parsed_items, list) or not parsed_items:
        frappe.throw(_("items must be a non-empty list"))

    invoice = frappe.new_doc("Sales Invoice")
    invoice.customer = customer
    invoice.company = company
    invoice.posting_date = posting_date or nowdate()

    if due_date:
        invoice.due_date = getdate(due_date)

    if currency:
        invoice.currency = currency

    if taxes_and_charges:
        invoice.taxes_and_charges = taxes_and_charges

    for idx, item in enumerate(parsed_items, start=1):
        item = frappe._dict(item)
        _validate_line_item(item, idx)

        invoice.append(
            "items",
            {
                "item_code": item.item_code,
                "item_name": item.get("item_name"),
                "description": item.get("description"),
                "qty": flt(item.qty),
                "uom": item.get("uom"),
                "rate": flt(item.rate),
                "cost_center": item.get("cost_center"),
                "warehouse": item.get("warehouse"),
            },
        )

    invoice.insert()

    if frappe.utils.cint(submit):
        invoice.submit()

    return {
        "invoice": invoice.name,
        "docstatus": invoice.docstatus,
        "posting_date": str(invoice.posting_date),
        "due_date": str(invoice.due_date) if invoice.due_date else None,
        "grand_total": flt(invoice.grand_total),
        "outstanding_amount": flt(invoice.outstanding_amount),
    }


@frappe.whitelist()
def record_billing_payment(
    sales_invoice,
    paid_amount,
    mode_of_payment=None,
    posting_date=None,
    reference_no=None,
    reference_date=None,
    submit=1,
):
    """Create and optionally submit a Payment Entry against a Sales Invoice."""

    if not sales_invoice:
        frappe.throw(_("sales_invoice is required"))

    paid_amount = flt(paid_amount)
    if paid_amount <= 0:
        frappe.throw(_("paid_amount must be greater than zero"))

    invoice = frappe.get_doc("Sales Invoice", sales_invoice)
    if invoice.docstatus != 1:
        frappe.throw(_("Only submitted Sales Invoices can be paid"))

    if invoice.outstanding_amount <= 0:
        frappe.throw(_("Sales Invoice {0} has no outstanding amount").format(invoice.name))

    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    payment_entry = get_payment_entry("Sales Invoice", invoice.name, party_amount=paid_amount)

    if posting_date:
        payment_entry.posting_date = getdate(posting_date)

    if mode_of_payment:
        payment_entry.mode_of_payment = mode_of_payment

    if reference_no:
        payment_entry.reference_no = reference_no

    if reference_date:
        payment_entry.reference_date = getdate(reference_date)

    payment_entry.insert()

    if frappe.utils.cint(submit):
        payment_entry.submit()

    invoice.reload()

    return {
        "payment_entry": payment_entry.name,
        "docstatus": payment_entry.docstatus,
        "paid_amount": flt(payment_entry.paid_amount),
        "sales_invoice": invoice.name,
        "invoice_outstanding_amount": flt(invoice.outstanding_amount),
    }


@frappe.whitelist()
def get_billing_overview(company=None, customer=None, from_date=None, to_date=None):
    """Return billing KPIs and recent invoices for dashboard usage."""

    filters = ["docstatus = 1"]
    values = {}

    if company:
        filters.append("company = %(company)s")
        values["company"] = company

    if customer:
        filters.append("customer = %(customer)s")
        values["customer"] = customer

    if from_date:
        filters.append("posting_date >= %(from_date)s")
        values["from_date"] = getdate(from_date)

    if to_date:
        filters.append("posting_date <= %(to_date)s")
        values["to_date"] = getdate(to_date)

    where_clause = " and ".join(filters)

    totals = frappe.db.sql(
        f"""
        select
            count(name) as invoice_count,
            sum(base_grand_total) as billed_amount,
            sum(outstanding_amount) as outstanding_amount
        from `tabSales Invoice`
        where {where_clause}
        """,
        values,
        as_dict=True,
    )[0]

    recent_invoices = frappe.db.sql(
        f"""
        select
            name,
            customer,
            posting_date,
            due_date,
            rounded_total,
            outstanding_amount,
            status
        from `tabSales Invoice`
        where {where_clause}
        order by posting_date desc, creation desc
        limit 20
        """,
        values,
        as_dict=True,
    )

    overdue_count = frappe.db.count(
        "Sales Invoice",
        {
            "docstatus": 1,
            "status": ["not in", ["Paid", "Cancelled"]],
            "due_date": ["<", nowdate()],
            **({"company": company} if company else {}),
            **({"customer": customer} if customer else {}),
        },
    )

    return {
        "totals": {
            "invoice_count": totals.invoice_count or 0,
            "billed_amount": flt(totals.billed_amount),
            "outstanding_amount": flt(totals.outstanding_amount),
            "overdue_invoice_count": overdue_count,
        },
        "recent_invoices": recent_invoices,
    }
