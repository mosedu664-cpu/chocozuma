from odoo import models


class PartnerCategory(models.Model):
    _inherit = "res.partner.category"

    def _get_categories_from_xml_ids(self, xml_ids_list):
        categories = self.env["res.partner.category"]
        for xml_id in xml_ids_list:
            record = self.env.ref(f"l10n_tr_nilvera_einvoice.{xml_id}", raise_if_not_found=False)
            if record is not None:
                categories |= record
        return categories
