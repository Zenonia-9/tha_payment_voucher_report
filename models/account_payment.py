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
        direct_partials = self.env["account.partial.reconcile"]
        direct_matched_lines = self.env["account.move.line"]

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

                direct_partials |= partial
                direct_matched_lines |= matched_line
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

        reconcile_batch_partials = self._get_payment_voucher_reconcile_batch_partials(
            direct_partials
        ) | self._get_payment_voucher_direct_reversal_partials(
            direct_matched_lines,
            direct_partials,
        )
        for partial in reconcile_batch_partials:
            for reconcile_line in partial.debit_move_id | partial.credit_move_id:
                if (
                    reconcile_line.move_id == self.move_id
                    or reconcile_line in direct_matched_lines
                    or reconcile_line.move_id.origin_payment_id
                    or reconcile_line.account_id not in payment_lines.account_id
                ):
                    continue

                payment_line = payment_lines.filtered(
                    lambda line: line.account_id == reconcile_line.account_id
                )[:1]
                line_values = self._prepare_payment_voucher_match_line(
                    reconcile_line,
                    payment_line,
                    company_currency,
                    partial=partial,
                )
                line_values["row_type"] = "reconcile"
                if self._get_payment_voucher_line_values_for_move(
                    line_values_by_key,
                    reconcile_line.move_id.id,
                ):
                    continue

                counterpart_line = (
                    (partial.debit_move_id | partial.credit_move_id) - reconcile_line
                )[:1]
                counterpart_line_values = self._get_payment_voucher_line_values_for_move(
                    line_values_by_key,
                    counterpart_line.move_id.id,
                )
                if (
                    counterpart_line_values
                    and self._is_payment_voucher_invoice_reversal_pair(
                        counterpart_line.move_id,
                        reconcile_line.move_id,
                    )
                ):
                    # Expand the already displayed document by the linked
                    # bill/refund amount while retaining the counterpart as a
                    # separate row. This also supports multi-step reversal chains.
                    counterpart_line_values["amount_company"] = company_currency.round(
                        counterpart_line_values["amount_company"]
                        - line_values["amount_company"]
                    )
                    if (
                        counterpart_line_values["line_currency"]
                        == line_values["line_currency"]
                    ):
                        counterpart_line_values["amount_currency"] = (
                            counterpart_line_values["line_currency"].round(
                                counterpart_line_values["amount_currency"]
                                - line_values["amount_currency"]
                            )
                        )
                    line_values["include_in_payment_total"] = True
                else:
                    line_values["include_in_payment_total"] = False
                line_key = (line_values["row_type"], reconcile_line.move_id.id)
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

        for line_values in self._get_payment_voucher_adjustment_lines(company_currency):
            line_key = (line_values["row_type"], line_values["sequence"])
            line_values_by_key[line_key] = line_values

        row_type_order = {"invoice": 0, "reconcile": 1, "adjustment": 2}
        lines = sorted(
            line_values_by_key.values(),
            key=lambda value: (
                row_type_order.get(value["row_type"], 3),
                value["date"] or self.date,
                value["document_number"] or "",
                value["sequence"],
            ),
        )
        matched_company_amount = sum(
            line["amount_company"]
            for line in lines
            if line.get("include_in_payment_total", True)
        )
        payment_company_amount = self._get_payment_voucher_company_amount(company_currency)
        payment_display_amount, payment_display_currency = (
            self._get_payment_voucher_display_amount(
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
            "include_in_payment_total": True,
        }

    def _get_payment_voucher_reconcile_batch_partials(self, direct_partials):
        """Return only partials created in the current payment's reconcile batches."""
        relevant_partials = direct_partials
        for create_date in set(direct_partials.mapped("create_date")):
            if not create_date:
                continue

            batch_partials = direct_partials.filtered(
                lambda partial: partial.create_date == create_date
            )
            pending_lines = batch_partials.debit_move_id | batch_partials.credit_move_id
            visited_lines = self.env["account.move.line"]

            while pending_lines:
                current_lines = pending_lines - visited_lines
                if not current_lines:
                    break
                visited_lines |= current_lines
                current_lines = current_lines.filtered(
                    lambda line: (
                        line.move_id == self.move_id
                        or not line.move_id.origin_payment_id
                    )
                )
                if not current_lines:
                    break

                attached_partials = (
                    current_lines.matched_debit_ids
                    | current_lines.matched_credit_ids
                ).filtered(lambda partial: partial.create_date == create_date)
                new_partials = attached_partials - batch_partials
                if not new_partials:
                    break

                batch_partials |= new_partials
                pending_lines = (
                    new_partials.debit_move_id | new_partials.credit_move_id
                )

            relevant_partials |= batch_partials

        return relevant_partials

    def _get_payment_voucher_direct_reversal_partials(
        self,
        direct_matched_lines,
        direct_partials,
    ):
        """Return invoice/refund partials directly attached to payment-matched lines.

        A refund can be reconciled against a bill before its remaining balance is
        paid. That bill/refund partial belongs on the voucher even though it was
        not created in the later payment's reconcile batch. Restrict the lookup
        to the directly matched document and its invoice/refund counterpart so
        unrelated historical payment chains remain excluded.
        """
        reversal_partials = self.env["account.partial.reconcile"]
        latest_direct_create_date = max(direct_partials.mapped("create_date"), default=False)
        pending_lines = direct_matched_lines
        visited_lines = self.env["account.move.line"]
        while pending_lines:
            matched_lines = pending_lines - visited_lines
            if not matched_lines:
                break
            visited_lines |= matched_lines
            pending_lines = self.env["account.move.line"]
            for matched_line in matched_lines:
                for partial in matched_line.matched_debit_ids + matched_line.matched_credit_ids:
                    if (
                        latest_direct_create_date
                        and partial.create_date
                        and partial.create_date > latest_direct_create_date
                    ):
                        continue
                    counterpart_line = (
                        partial.debit_move_id
                        if partial.debit_move_id != matched_line
                        else partial.credit_move_id
                    )
                    if self._is_payment_voucher_invoice_reversal_pair(
                        matched_line.move_id,
                        counterpart_line.move_id,
                    ):
                        reversal_partials |= partial
                        pending_lines |= counterpart_line
        return reversal_partials

    def _get_payment_voucher_line_values_for_move(self, line_values_by_key, move_id):
        return next(
            (
                line_values
                for (_, line_move_id), line_values in line_values_by_key.items()
                if line_move_id == move_id
            ),
            False,
        )

    def _get_payment_voucher_invoice_move_types(self):
        return ("out_invoice", "out_refund", "in_invoice", "in_refund")

    def _is_payment_voucher_invoice_reversal_pair(self, first_move, second_move):
        return {first_move.move_type, second_move.move_type} in (
            {"out_invoice", "out_refund"},
            {"in_invoice", "in_refund"},
        )

    def _merge_payment_voucher_references(self, left_reference, right_reference):
        references = []
        for reference in (left_reference, right_reference):
            if not reference:
                continue
            if reference not in references:
                references.append(reference)
        return ", ".join(references)

    def _get_payment_voucher_company_amount(self, company_currency):
        liquidity_lines = self.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_cash"
        )
        payment_company_amount = abs(sum(liquidity_lines.mapped("balance")))
        if payment_company_amount:
            return company_currency.round(payment_company_amount)
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
        payment_currency,
        company_currency,
    ):
        if payment_currency and payment_currency != company_currency:
            return payment_currency.round(self.amount), payment_currency
        return self._get_payment_voucher_company_amount(company_currency), company_currency

    def _get_payment_voucher_partial_currency_amount(self, line, partial, currency):
        if currency == self.company_id.currency_id:
            return partial.amount
        if line == partial.debit_move_id:
            return abs(partial.debit_amount_currency)
        return abs(partial.credit_amount_currency)

    def _get_payment_voucher_adjustment_lines(self, company_currency):
        self.ensure_one()
        if not self.move_id:
            return []

        adjustment_lines = []
        for line in self.move_id.line_ids.filtered(
            lambda move_line: (
                move_line.account_id.account_type
                not in ("asset_cash", "asset_receivable", "liability_payable")
                and not company_currency.is_zero(move_line.balance)
            )
        ):
            line_currency = line.currency_id or company_currency
            raw_amount_currency = (
                line.amount_currency
                if line.currency_id
                else line.balance
            )
            adjustment_lines.append({
                "sequence": line.id,
                "row_type": "adjustment",
                "date": self.date,
                "document_number": self.name or self.move_id.name,
                "reference": line.name or line.account_id.display_name,
                "pc_cc": "",
                "company_currency": company_currency,
                "line_currency": line_currency,
                "amount_company": company_currency.round(abs(line.balance)),
                "amount_currency": line_currency.round(abs(raw_amount_currency)),
            })
        return adjustment_lines

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
