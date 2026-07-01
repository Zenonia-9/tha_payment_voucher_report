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

        report_by_payment_type = {
            ("outbound", "a4"): "tha_payment_voucher_report.action_report_vendor_payment_voucher_a4",
            ("outbound", "a5"): "tha_payment_voucher_report.action_report_vendor_payment_voucher_a5",
            ("inbound", "a4"): "tha_payment_voucher_report.action_report_customer_receipt_voucher_a4",
            ("inbound", "a5"): "tha_payment_voucher_report.action_report_customer_receipt_voucher_a5",
        }
        report_ref = report_by_payment_type.get((self.payment_type, paper_format))
        if not report_ref:
            raise UserError(
                _(
                    "This voucher can only be printed for inbound or outbound payments."
                )
            )
        return report_ref

    def _get_payment_voucher_display_values(self):
        self.ensure_one()
        is_receipt = self.payment_type == "inbound"
        return {
            "title": _("Receipt Voucher") if is_receipt else _("Payment Voucher"),
            "document_label": _("Receipt Voucher") if is_receipt else _("Payment Voucher"),
            "amount_label": _("Receipt Amount") if is_receipt else _("Payment Amount"),
            "partner_label": _("Customer") if self.partner_type == "customer" else _("Supplier"),
        }

    def _get_payment_voucher_match_values(self):
        self.ensure_one()

        payment_currency = self.currency_id
        company_currency = self.company_id.currency_id
        payment_lines = self.move_id.line_ids.filtered(
            lambda line: line.account_type in ("asset_receivable", "liability_payable")
        )

        line_values_by_key = {}
        for payment_line in payment_lines:
            for partial in payment_line.matched_debit_ids + payment_line.matched_credit_ids:
                matched_line = (
                    partial.debit_move_id
                    if partial.debit_move_id != payment_line
                    else partial.credit_move_id
                )
                if (
                    matched_line.move_id == self.move_id
                    or matched_line.account_id != payment_line.account_id
                ):
                    continue

                line_values = self._prepare_payment_voucher_match_line(
                    matched_line,
                    payment_line,
                    company_currency,
                    partial=partial,
                )
                line_key = (line_values["row_type"], matched_line.move_id.id)
                existing_values = line_values_by_key.get(line_key)
                if existing_values:
                    existing_values["amount_company"] = company_currency.round(
                        existing_values["amount_company"] + line_values["amount_company"]
                    )
                    existing_values["amount_currency"] = line_values["line_currency"].round(
                        existing_values["amount_currency"] + line_values["amount_currency"]
                    )
                    existing_values["sequence"] = min(
                        existing_values["sequence"], line_values["sequence"]
                    )
                    existing_values["reference"] = self._merge_payment_voucher_references(
                        existing_values["reference"],
                        line_values["reference"],
                    )
                    continue

                line_values_by_key[line_key] = line_values

        lines = sorted(
            line_values_by_key.values(),
            key=lambda value: (
                0 if value["row_type"] == "invoice" else 1,
                value["date"] or self.date,
                value["document_number"] or "",
                value["sequence"],
            ),
        )
        matched_company_amount = sum(line["amount_company"] for line in lines)
        payment_company_amount = self._get_payment_voucher_company_amount(
            payment_lines,
            company_currency,
        )
        payment_display_amount, payment_display_currency = (
            self._get_payment_voucher_display_amount(
                payment_lines,
                payment_currency,
                company_currency,
            )
        )
        difference_company_amount = company_currency.round(
            payment_company_amount - matched_company_amount
        )

        return {
            "display_invoices": False,
            "display_match_lines": bool(lines),
            "lines": lines,
            "company_currency": company_currency,
            "payment_currency": payment_currency,
            "matched_company_amount": matched_company_amount,
            "payment_company_amount": payment_company_amount,
            "payment_display_amount": payment_display_amount,
            "payment_display_currency": payment_display_currency,
            "difference_company_amount": difference_company_amount,
            "show_pc_cc": any(line["pc_cc"] for line in lines),
            "show_foreign_currency": any(
                line["line_currency"] != company_currency for line in lines
            ),
        }

    def _prepare_payment_voucher_match_line(
        self,
        line,
        payment_line,
        company_currency,
        partial=None,
    ):
        move = line.move_id
        sign = 1 if self.payment_type == "inbound" else -1
        amount_company = sign * line.balance
        line_currency = line.currency_id or company_currency
        amount_currency = sign * (line.amount_currency if line.currency_id else line.balance)
        row_type = (
            "invoice"
            if move.move_type in self._get_payment_voucher_invoice_move_types()
            else "adjustment"
        )

        if partial:
            direction = 1 if amount_company >= 0 else -1
            amount_company = direction * partial.amount
            amount_currency = direction * self._get_payment_voucher_partial_currency_amount(
                line,
                partial,
                line_currency,
            )

        return {
            "sequence": line.id,
            "row_type": row_type,
            "date": move.invoice_date or move.date,
            "document_number": move.name,
            "reference": self._get_payment_voucher_line_reference(move, line),
            "pc_cc": self._get_payment_voucher_pc_cc(move),
            "company_currency": company_currency,
            "line_currency": line_currency,
            "amount_company": company_currency.round(amount_company),
            "amount_currency": line_currency.round(amount_currency),
        }

    def _get_payment_voucher_invoice_move_types(self):
        return ("out_invoice", "out_refund", "in_invoice", "in_refund")

    def _merge_payment_voucher_references(self, left_reference, right_reference):
        references = []
        for reference in (left_reference, right_reference):
            if not reference:
                continue
            if reference not in references:
                references.append(reference)
        return ", ".join(references)

    def _get_payment_voucher_company_amount(self, payment_lines, company_currency):
        payment_company_amount = abs(sum(payment_lines.mapped("balance")))
        if payment_company_amount:
            return payment_company_amount
        return company_currency.round(
            self.currency_id._convert(
                self.amount,
                company_currency,
                self.company_id,
                self.date,
            )
        )

    def _get_payment_voucher_display_amount(
        self,
        payment_lines,
        payment_currency,
        company_currency,
    ):
        if payment_currency and payment_currency != company_currency:
            foreign_amount = abs(
                sum(
                    payment_lines.filtered(
                        lambda line: line.currency_id == payment_currency
                    ).mapped("amount_currency")
                )
            )
            if foreign_amount:
                return payment_currency.round(foreign_amount), payment_currency
        return self._get_payment_voucher_company_amount(
            payment_lines,
            company_currency,
        ), company_currency

    def _get_payment_voucher_partial_currency_amount(self, line, partial, currency):
        if currency == self.company_id.currency_id:
            return partial.amount
        if line == partial.debit_move_id:
            return abs(partial.debit_amount_currency)
        return abs(partial.credit_amount_currency)

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
