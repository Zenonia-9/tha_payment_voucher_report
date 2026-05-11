from odoo import api, models


def _get_payment_voucher_report_values(report_model, docids, data=None):
    data = data or {}
    if not docids and data.get("active_ids"):
        docids = data.get("active_ids")
    elif not docids and data.get("payment_id"):
        docids = [data.get("payment_id")]

    docs = report_model.env["account.payment"].browse(docids).exists()
    return {
        "doc_ids": docs.ids,
        "doc_model": "account.payment",
        "docs": docs,
        "data": data,
    }


class VendorPaymentVoucherReport(models.AbstractModel):
    _name = "report.tha_payment_voucher_report.report_vendor_payment_voucher"
    _description = "Vendor Payment Voucher Report"
    # _table = "tpvr_report_vendor_payment"
    # _auto = False

    @api.model
    def _get_report_values(self, docids, data=None):
        return _get_payment_voucher_report_values(self, docids, data=data)


class CustomerReceiptVoucherReport(models.AbstractModel):
    _name = "report.tha_payment_voucher_report.report_customer_receipt_voucher"
    _description = "Customer Receipt Voucher Report"
    # _table = "tpvr_report_customer_receipt"
    # _auto = False

    @api.model
    def _get_report_values(self, docids, data=None):
        return _get_payment_voucher_report_values(self, docids, data=data)
