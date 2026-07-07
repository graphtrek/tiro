"""Tests for the queryInvoiceData full-XML parser."""

from nav_invoice.invoice_data import parse_invoice_data

_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InvoiceData xmlns="http://schemas.nav.gov.hu/OSA/3.0/data">
  <invoiceNumber>TEST-2026-1</invoiceNumber>
  <invoiceIssueDate>2026-05-12</invoiceIssueDate>
  <invoiceMain>
    <invoice>
      <invoiceHead>
        <supplierInfo>
          <supplierTaxNumber>
            <taxpayerId>12345678</taxpayerId>
          </supplierTaxNumber>
          <supplierName>Supplier Kft.</supplierName>
          <supplierAddress>
            <detailedAddress>
              <postalCode>1011</postalCode>
              <city>Budapest</city>
              <streetName>Fő</streetName>
              <publicPlaceCategory>utca</publicPlaceCategory>
              <houseNumber>1</houseNumber>
            </detailedAddress>
          </supplierAddress>
          <supplierBankAccountNumber>HU42117730161111101800000000</supplierBankAccountNumber>
        </supplierInfo>
        <customerInfo>
          <customerVatData>
            <customerTaxNumber>
              <taxpayerId>87654321</taxpayerId>
            </customerTaxNumber>
          </customerVatData>
          <customerName>Customer Kft.</customerName>
          <customerAddress>
            <detailedAddress>
              <postalCode>1052</postalCode>
              <city>Budapest</city>
              <streetName>Váci</streetName>
              <publicPlaceCategory>utca</publicPlaceCategory>
              <houseNumber>10</houseNumber>
            </detailedAddress>
          </customerAddress>
          <customerBankAccountNumber>11773016-11111018-00000000</customerBankAccountNumber>
        </customerInfo>
        <invoiceDetail>
          <invoiceCategory>NORMAL</invoiceCategory>
          <invoiceDeliveryDate>2026-05-12</invoiceDeliveryDate>
          <currencyCode>HUF</currencyCode>
          <paymentMethod>TRANSFER</paymentMethod>
          <paymentDate>2026-05-26</paymentDate>
        </invoiceDetail>
      </invoiceHead>
    </invoice>
  </invoiceMain>
</InvoiceData>
"""


def test_parse_invoice_data_extracts_all_fields():
    detail = parse_invoice_data(_SAMPLE_XML, invoice_number="TEST-2026-1")

    assert detail.invoice_number == "TEST-2026-1"
    assert detail.supplier_address == "1011, Budapest, Fő utca 1"
    assert detail.supplier_bank_account == "HU42117730161111101800000000"
    assert detail.customer_address == "1052, Budapest, Váci utca 10"
    assert detail.customer_bank_account == "11773016-11111018-00000000"
    assert detail.payment_method == "TRANSFER"
    assert detail.payment_due_date == "2026-05-26"


def test_parse_invoice_data_missing_sections_returns_empty_strings():
    minimal_xml = """<?xml version="1.0" encoding="UTF-8"?>
<InvoiceData xmlns="http://schemas.nav.gov.hu/OSA/3.0/data">
  <invoiceMain>
    <invoice>
      <invoiceHead/>
    </invoice>
  </invoiceMain>
</InvoiceData>
"""
    detail = parse_invoice_data(minimal_xml, invoice_number="TEST-2026-2")

    assert detail.invoice_number == "TEST-2026-2"
    assert detail.supplier_address == ""
    assert detail.supplier_bank_account == ""
    assert detail.customer_address == ""
    assert detail.customer_bank_account == ""
    assert detail.payment_method == ""
    assert detail.payment_due_date == ""
