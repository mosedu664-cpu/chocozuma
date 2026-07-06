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

    def _get_alerts(self, moves, moves_data):
        alerts = {}
        send_cron = self.env.ref('account.ir_cron_account_move_send', raise_if_not_found=False)
        if len(moves) > 1 and send_cron and not send_cron.sudo().active:
            has_cron_access = send_cron.has_access('write')
            has_access_message = _(
                "The scheduled action 'Send Invoices automatically' is archived. You won't be able to send invoices in batch.")
            no_access_addendum = _("\nPlease contact your administrator.")
            alerts['account_send_cron_archived'] = {
                'level': 'warning',
                'message': has_access_message if has_cron_access else has_access_message + no_access_addendum,
                'action_text': _("Check") if has_cron_access else None,
                'action': send_cron._get_records_action() if has_cron_access else None,
            }
        if len(moves) > 1 and (partners_without_mail := moves.filtered(
                lambda m: 'email' in moves_data[m]['sending_methods'] and not m.partner_id.email).partner_id
        ):
            # should only appear in mass invoice sending
            alerts['account_missing_email'] = {
                'level': 'warning',
                'message': _("Partner(s) should have an email address."),
                'action_text': _("View Partner(s)"),
                'action': partners_without_mail._get_records_action(name=_("Check Partner(s) Email(s)")),
            }
        if tr_partners_missing_address := moves.filtered(
                lambda m: 'tr_nilvera' in moves_data[m]['extra_edis'] and (
                        m.partner_id.country_code != 'TR' or not m.partner_id.city or not m.partner_id.state_id or not m.partner_id.street)
        ).partner_id:
            alerts["partner_data_missing"] = {
                "message": _(
                    "The following partner(s) are either not Turkish or are missing one of those fields: city, state and street."),
                "action_text": _("View Partner(s)"),
                "action": tr_partners_missing_address._get_records_action(name=_("Check data on Partner(s)")),
            }

        if tr_invalid_subscription_dates := moves.filtered(
                lambda move: move._l10n_tr_nilvera_einvoice_check_invalid_subscription_dates()
        ):
            alerts["critical_invalid_subscription_dates"] = {
                "message": _(
                    "The following invoice(s) need to have the same Start Date and End Date on all their respective Invoice Lines."),
                "action_text": _("View Invoice(s)"),
                "action": tr_invalid_subscription_dates._get_records_action(
                    name=_("Check data on Invoice(s)"),
                ),
                "level": "danger",
            }

        if tr_einvoice_partners_missing_ref := moves.partner_id.filtered(
                lambda p: p.l10n_tr_nilvera_customer_status == "einvoice" and not p.ref
        ):
            alerts["critical_partner_data_missing"] = {
                "message": _(
                    "The following E-Invoice partner(s) must have the reference field set to the tax office name."),
                "action_text": _("View Partner(s)"),
                "action": tr_einvoice_partners_missing_ref._get_records_action(name=_("Check reference on Partner(s)")
                                                                               ),
                "level": "danger",
            }

        return alerts
