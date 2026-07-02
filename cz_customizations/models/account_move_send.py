from odoo import _, models

class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    def _get_l10n_tr_tax_company_tax_office_alert(self, moves):
        try:
            return super()._get_l10n_tr_tax_company_tax_office_alert(moves)
        except AttributeError as e:
            if "'res.partner' object has no attribute 'reference'" in str(e):
                tr_companies_missing_tax_office = moves.company_id.partner_id.filtered(lambda p: not p.ref and p.country_code == 'TR')
                if tr_companies_missing_tax_office:
                    return {
                        'message': _('The following TR Company(s) must have the reference field set to the tax office name.'),
                        'action_text': _('View Company(s)'),
                        'action': tr_companies_missing_tax_office._get_records_action(name=_('TR Company(s)')),
                        'level': 'danger',
                    }
                return {}
            raise e
