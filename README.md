# Payment Voucher Report

![Odoo 19](https://img.shields.io/badge/Odoo-19.0-875A7B?style=flat-square)
![License](https://img.shields.io/badge/License-LGPL--3-blue?style=flat-square)
![Category](https://img.shields.io/badge/Category-Accounting-4ECDC4?style=flat-square)

Print payment vouchers and receipt vouchers from Odoo 19 payments.

This module adds a dedicated voucher-printing workflow on `account.payment`. It supports customer and vendor payments, validates that the payment is already posted, and provides voucher layouts in both A4 and A5 formats.

## Highlights

- Adds a print wizard on **payments**.
- Supports:
  - **Vendor Payment Voucher**
  - **Customer Receipt Voucher**
- Restricts printing to payments in **`in_process`** or **`paid`** state.
- Routes to the correct voucher template based on:
  - partner type
  - selected paper size
- Includes separate **A4** and **A5** outputs.
- Keeps layouts and report actions local to the addon.

## Workflow

1. Open a posted payment.
2. Launch the payment voucher print wizard.
3. Choose A4 or A5 format.
4. Print the appropriate voucher document.

## Technical Notes

- `models/account_payment.py`
  Adds the entry action and resolves the correct report action for each voucher scenario.
- `wizard/payment_voucher_print_wizard.py`
  Collects the selected payment and paper size before printing.
- `report/payment_voucher_report.py`
  Supplies report values for vendor-payment and customer-receipt voucher models.
- `report/payment_voucher_template.xml`
  Defines payment voucher output.
- `report/receipt_voucher_template.xml`
  Defines receipt voucher output.

## Module Layout

```text
tha_payment_voucher_report/
|-- models/
|-- wizard/
|-- report/
|-- security/
|-- views/
`-- __manifest__.py
```

## Dependencies

- `account`
- `web`

## Installation

1. Place the module in your custom addons path.
2. Update the Apps list in Odoo.
3. Install **Payment Voucher Report**.

## License

This module is licensed under `LGPL-3`.
