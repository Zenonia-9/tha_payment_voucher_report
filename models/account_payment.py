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
                'active_model': 'account.payment',
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

    def _get_payment_voucher_match_values(self):
        self.ensure_one()

        sign = 1 if self.payment_type == "inbound" else -1
        payment_currency = self.currency_id
        company_currency = self.company_id.currency_id
        payment_lines = self.move_id.line_ids.filtered(
            lambda line: line.account_type in ("asset_receivable", "liability_payable")
        )

        line_values_by_id = {}
        for payment_line in payment_lines:
            if payment_line.full_reconcile_id:
                matched_lines = payment_line.full_reconcile_id.reconciled_line_ids
                for matched_line in matched_lines - self.move_id.line_ids:
                    if matched_line.account_id != payment_line.account_id:
                        continue
                    line_values_by_id[matched_line.id] = self._prepare_payment_voucher_match_line(
                        matched_line,
                        sign,
                        payment_currency,
                        company_currency,
                    )
                continue

            for partial in payment_line.matched_debit_ids + payment_line.matched_credit_ids:
                matched_line = (
                    partial.debit_move_id
                    if partial.debit_move_id != payment_line
                    else partial.credit_move_id
                )
                if matched_line.move_id == self.move_id:
                    continue
                line_values_by_id[matched_line.id] = self._prepare_payment_voucher_match_line(
                    matched_line,
                    sign,
                    payment_currency,
                    company_currency,
                    partial=partial,
                )

        lines = sorted(
            line_values_by_id.values(),
            key=lambda value: (
                value["date"] or self.date,
                value["document_number"] or "",
                value["sequence"],
            ),
        )
        matched_amount = sum(line["payment_currency_amount"] for line in lines)
        difference = payment_currency.round(self.amount - matched_amount)

        return {
            "display_invoices": False,
            "display_match_lines": bool(lines),
            "lines": lines,
            "matched_amount": matched_amount,
            "payment_amount": self.amount,
            "difference": difference,
            "show_pc_cc": any(line["pc_cc"] for line in lines),
            "other_currency": any(line["currency"] != payment_currency for line in lines),
        }

    def _prepare_payment_voucher_match_line(
        self,
        line,
        sign,
        payment_currency,
        company_currency,
        partial=None,
    ):
        move = line.move_id
        amount_company = sign * line.balance
        line_currency = line.currency_id or company_currency
        amount_currency = sign * (
            line.amount_currency if line.currency_id else line.balance
        )

        if partial:
            direction = 1 if amount_company >= 0 else -1
            amount_company = direction * partial.amount
            amount_currency = direction * self._get_payment_voucher_partial_currency_amount(
                line,
                partial,
                line_currency,
            )

        if line_currency == payment_currency:
            payment_currency_amount = amount_currency
        else:
            payment_currency_amount = company_currency._convert(
                amount_company,
                payment_currency,
                self.company_id,
                self.date,
            )

        return {
            "sequence": line.id,
            "date": move.invoice_date or move.date,
            "document_number": move.name,
            "document_type": self._get_payment_voucher_document_type(move),
            "reference": self._get_payment_voucher_line_reference(move, line),
            "pc_cc": self._get_payment_voucher_pc_cc(move),
            "currency": line_currency,
            "amount": amount_currency,
            "payment_currency_amount": payment_currency_amount,
        }

    def _get_payment_voucher_partial_currency_amount(self, line, partial, currency):
        if currency == self.company_id.currency_id:
            return partial.amount
        if line == partial.debit_move_id:
            return abs(partial.debit_amount_currency)
        return abs(partial.credit_amount_currency)

    def _get_payment_voucher_document_type(self, move):
        if move.move_type in ("out_invoice", "in_invoice", "out_receipt", "in_receipt"):
            return _("Invoice") if move.is_sale_document(True) else _("Bill")
        if move.move_type in ("out_refund", "in_refund"):
            return _("Credit Note") if move.is_sale_document(True) else _("Refund")
        return _("Journal Entry")

    def _get_payment_voucher_line_reference(self, move, line):
        if "vendor_ref" in move._fields and move.vendor_ref:
            return move.vendor_ref
        return move.ref or line.name or ""

    def _get_payment_voucher_pc_cc(self, move):
        analytic_names = []
        invoice_lines = move.invoice_line_ids.filtered(
            lambda invoice_line: invoice_line.display_type not in ("line_section", "line_note")
            and invoice_line.analytic_distribution
        )
        for invoice_line in invoice_lines:
            for analytic_key in invoice_line.analytic_distribution:
                for analytic_id in str(analytic_key).split(","):
                    if not analytic_id:
                        continue
                    analytic_account = self.env["account.analytic.account"].browse(int(analytic_id))
                    if analytic_account.exists() and analytic_account.name not in analytic_names:
                        analytic_names.append(analytic_account.name)
        return ", ".join(analytic_names)
