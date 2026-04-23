from frappe.model.document import Document


class PortalTenant(Document):
    def validate(self):
        if self.industry_type:
            self.industry_type = self.industry_type.strip().title()

        if self.company_name:
            self.company_name = self.company_name.strip()

        if self.website_slug:
            self.website_slug = self.website_slug.strip().lower()
