from odoo import _, fields, models
from odoo.exceptions import UserError


class PaymentVoucherPrintWizard(models.TransientModel):
    _name = "payment.voucher.print.wizard"
    _description = "Payment Voucher Print Wizard"

    payment_id = fields.Many2one(
        "account.payment",
        string="Payment",
        required=True,
        readonly=True,
    )
    paper_format = fields.Selection(
        selection=[
            ("a4", "A4"),
            ("a5", "A5"),
        ],
        string="Paper Format",
        required=True,
        default="a4",
    )
    company_id = fields.Many2one(
        related="payment_id.company_id",
        string="Company",
        readonly=True,
    )
    amount = fields.Monetary(
        related="payment_id.amount",
        string="Amount",
        readonly=True,
    )
    currency_id = fields.Many2one(
        related="payment_id.currency_id",
        readonly=True,
    )

    def action_print(self):
        self.ensure_one()
        payment = self.payment_id.exists()
        if not payment:
            raise UserError(_("Please select a payment to print."))
        if payment.state not in ("in_process", "paid"):
            raise UserError(_("You can only print vouchers for posted payments."))

        return self.env.ref(
            payment._get_payment_voucher_report_ref(self.paper_format)
        ).report_action(
            payment,
            data={
                "paper_format": self.paper_format,
                "payment_id": payment.id,
                "active_ids": payment.ids,
            },
        )
