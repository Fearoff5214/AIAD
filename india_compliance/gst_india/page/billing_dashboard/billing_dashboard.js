frappe.pages["billing-dashboard"].on_page_load = function (wrapper) {
    new BillingDashboardPage(wrapper);
};

class BillingDashboardPage {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: "Billing Dashboard",
            single_column: true,
        });

        this.companyFilter = this.page.add_field({
            label: "Company",
            fieldname: "company",
            fieldtype: "Link",
            options: "Company",
            change: () => this.refresh(),
        });

        this.page.set_primary_action("New Invoice", () => this.openNewInvoiceDialog());
        this.page.set_secondary_action("Record Payment", () => this.openPaymentDialog());

        this.renderShell();
        this.refresh();
    }

    renderShell() {
        this.page.main.html(`
            <div class="billing-dashboard">
                <div id="billing-kpis" class="row" style="margin-bottom: 16px;"></div>
                <div class="frappe-card" style="padding: 12px;">
                    <h4 style="margin-top: 0;">Recent Invoices</h4>
                    <div id="billing-invoice-table"></div>
                </div>
            </div>
        `);

        this.kpiContainer = this.page.main.find("#billing-kpis");
        this.tableContainer = this.page.main.find("#billing-invoice-table");
    }

    async refresh() {
        this.page.set_indicator("Loading", "orange");

        try {
            const response = await frappe.call({
                method: "india_compliance.gst_india.utils.billing.get_billing_overview",
                args: {
                    company: this.companyFilter.get_value(),
                },
            });

            const data = response.message || {};
            this.renderKpis(data.totals || {});
            this.renderInvoiceTable(data.recent_invoices || []);
            this.page.set_indicator("Ready", "green");
        } catch (error) {
            this.page.set_indicator("Error", "red");
            frappe.msgprint({
                title: "Billing Error",
                message: error.message || "Failed to fetch billing overview.",
                indicator: "red",
            });
        }
    }

    renderKpis(totals) {
        const cards = [
            { label: "Invoices", value: totals.invoice_count || 0 },
            { label: "Billed Amount", value: formatCurrency(totals.billed_amount || 0) },
            {
                label: "Outstanding",
                value: formatCurrency(totals.outstanding_amount || 0),
            },
            {
                label: "Overdue Invoices",
                value: totals.overdue_invoice_count || 0,
            },
        ];

        this.kpiContainer.html(
            cards
                .map(
                    (card) => `
                    <div class="col-md-3" style="margin-bottom: 12px;">
                        <div class="frappe-card" style="padding: 12px; min-height: 90px;">
                            <div style="font-size: 12px; color: #6b7280;">${frappe.utils.escape_html(card.label)}</div>
                            <div style="font-size: 24px; font-weight: 600; margin-top: 8px;">${frappe.utils.escape_html(String(card.value))}</div>
                        </div>
                    </div>
                `
                )
                .join("")
        );
    }

    renderInvoiceTable(invoices) {
        if (!invoices.length) {
            this.tableContainer.html('<div class="text-muted">No invoices found.</div>');
            return;
        }

        const rows = invoices
            .map((invoice) => {
                return `
                <tr>
                    <td><a href="/app/sales-invoice/${encodeURIComponent(invoice.name)}">${frappe.utils.escape_html(invoice.name)}</a></td>
                    <td>${frappe.utils.escape_html(invoice.customer || "")}</td>
                    <td>${frappe.utils.escape_html(invoice.posting_date || "")}</td>
                    <td>${formatCurrency(invoice.rounded_total || 0)}</td>
                    <td>${formatCurrency(invoice.outstanding_amount || 0)}</td>
                    <td>${frappe.utils.escape_html(invoice.status || "")}</td>
                </tr>
            `;
            })
            .join("");

        this.tableContainer.html(`
            <table class="table table-bordered" style="margin-bottom: 0;">
                <thead>
                    <tr>
                        <th>Invoice</th>
                        <th>Customer</th>
                        <th>Date</th>
                        <th>Total</th>
                        <th>Outstanding</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `);
    }

    openNewInvoiceDialog() {
        const dialog = new frappe.ui.Dialog({
            title: "Create Billing Invoice",
            fields: [
                {
                    label: "Customer",
                    fieldname: "customer",
                    fieldtype: "Link",
                    options: "Customer",
                    reqd: 1,
                },
                {
                    label: "Company",
                    fieldname: "company",
                    fieldtype: "Link",
                    options: "Company",
                    reqd: 1,
                    default: this.companyFilter.get_value() || undefined,
                },
                {
                    label: "Item",
                    fieldname: "item_code",
                    fieldtype: "Link",
                    options: "Item",
                    reqd: 1,
                },
                {
                    label: "Quantity",
                    fieldname: "qty",
                    fieldtype: "Float",
                    reqd: 1,
                    default: 1,
                },
                {
                    label: "Rate",
                    fieldname: "rate",
                    fieldtype: "Currency",
                    reqd: 1,
                },
                {
                    label: "Submit Invoice",
                    fieldname: "submit",
                    fieldtype: "Check",
                    default: 1,
                },
            ],
            primary_action_label: "Create",
            primary_action: async (values) => {
                await frappe.call({
                    method: "india_compliance.gst_india.utils.billing.create_billing_invoice",
                    args: {
                        customer: values.customer,
                        company: values.company,
                        submit: values.submit,
                        items: JSON.stringify([
                            {
                                item_code: values.item_code,
                                qty: values.qty,
                                rate: values.rate,
                            },
                        ]),
                    },
                });

                dialog.hide();
                frappe.show_alert({ message: "Invoice created", indicator: "green" });
                if (values.company && !this.companyFilter.get_value()) {
                    this.companyFilter.set_value(values.company);
                }
                this.refresh();
            },
        });

        dialog.show();
    }

    openPaymentDialog() {
        const dialog = new frappe.ui.Dialog({
            title: "Record Payment",
            fields: [
                {
                    label: "Sales Invoice",
                    fieldname: "sales_invoice",
                    fieldtype: "Link",
                    options: "Sales Invoice",
                    reqd: 1,
                },
                {
                    label: "Paid Amount",
                    fieldname: "paid_amount",
                    fieldtype: "Currency",
                    reqd: 1,
                },
                {
                    label: "Mode of Payment",
                    fieldname: "mode_of_payment",
                    fieldtype: "Link",
                    options: "Mode of Payment",
                },
                {
                    label: "Submit Payment",
                    fieldname: "submit",
                    fieldtype: "Check",
                    default: 1,
                },
            ],
            primary_action_label: "Record",
            primary_action: async (values) => {
                await frappe.call({
                    method: "india_compliance.gst_india.utils.billing.record_billing_payment",
                    args: {
                        sales_invoice: values.sales_invoice,
                        paid_amount: values.paid_amount,
                        mode_of_payment: values.mode_of_payment,
                        submit: values.submit,
                    },
                });

                dialog.hide();
                frappe.show_alert({ message: "Payment recorded", indicator: "green" });
                this.refresh();
            },
        });

        dialog.show();
    }
}

function formatCurrency(value) {
    return format_currency(flt(value || 0));
}
