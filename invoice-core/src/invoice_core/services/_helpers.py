"""Small constants shared by more than one services/*.py module."""

from __future__ import annotations

# The company that runs this invoice-core instance ends up in its own
# suppliers/customers tables (e.g. it invoices itself, or appears as a
# counterparty on some bank transactions). Partner lists and "top supplier"
# reports should only show *other* companies, so every such query excludes
# any Supplier/Customer whose name contains this string.
OWN_COMPANY_NAME_FILTER = "%graphtrek%"
