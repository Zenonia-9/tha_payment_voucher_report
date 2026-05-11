from odoo import _, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def action_open_payment_voucher_print_wizard(self):
        self.ensure_one()
        if self.state not in ("in_process", "paid"):
            raise UserError(_("You can only print vouchers for posted payments."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Print"),
            "res_model": "payment.voucher.print.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payment_id": self.id,
                'active_ids': self.ids,
                'active_model': 'account.move',
            },
        }

    def _get_payment_voucher_report_ref(self, paper_format):
        self.ensure_one()
        if paper_format not in ("a4", "a5"):
            raise UserError(_("Please select a valid paper format."))

        report_by_payment = {
            ("outbound", "supplier", "a4"): "tha_payment_voucher_report.action_report_vendor_payment_voucher_a4",
            ("outbound", "supplier", "a5"): "tha_payment_voucher_report.action_report_vendor_payment_voucher_a5",
            ("inbound", "customer", "a4"): "tha_payment_voucher_report.action_report_customer_receipt_voucher_a4",
            ("inbound", "customer", "a5"): "tha_payment_voucher_report.action_report_customer_receipt_voucher_a5",
        }
        report_ref = report_by_payment.get((self.payment_type, self.partner_type, paper_format))
        if not report_ref:
            raise UserError(
                _(
                    "This voucher can only be printed for vendor payments "
                    "and customer receipts."
                )
            )
        return report_ref
