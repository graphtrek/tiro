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
          <exchangeRate>1</exchangeRate>
          <paymentMethod>TRANSFER</paymentMethod>
          <paymentDate>2026-05-26</paymentDate>
          <invoiceAppearance>ELECTRONIC</invoiceAppearance>
        </invoiceDetail>
      </invoiceHead>
      <invoiceLines>
        <mergedItemIndicator>false</mergedItemIndicator>
        <line>
          <lineNumber>1</lineNumber>
          <lineExpressionIndicator>false</lineExpressionIndicator>
          <lineDescription>Consulting</lineDescription>
          <quantity>2</quantity>
          <unitPrice>100</unitPrice>
          <lineAmountsNormal>
            <lineNetAmountData>
              <lineNetAmount>200</lineNetAmount>
              <lineNetAmountHUF>200</lineNetAmountHUF>
            </lineNetAmountData>
            <lineVatRate>
              <vatPercentage>0.27</vatPercentage>
            </lineVatRate>
          </lineAmountsNormal>
        </line>
        <line>
          <lineNumber>2</lineNumber>
          <lineExpressionIndicator>false</lineExpressionIndicator>
          <lineDescription>Widget</lineDescription>
          <quantity>5</quantity>
          <unitOfMeasure>db</unitOfMeasure>
          <unitPrice>50</unitPrice>
          <lineAmountsNormal>
            <lineNetAmountData>
              <lineNetAmount>250</lineNetAmount>
              <lineNetAmountHUF>250</lineNetAmountHUF>
            </lineNetAmountData>
            <lineVatRate>
              <vatPercentage>0.05</vatPercentage>
            </lineVatRate>
            <lineVatData>
              <lineVatAmount>12.5</lineVatAmount>
              <lineVatAmountHUF>12.5</lineVatAmountHUF>
            </lineVatData>
            <lineGrossAmountData>
              <lineGrossAmountNormal>262.5</lineGrossAmountNormal>
              <lineGrossAmountNormalHUF>262.5</lineGrossAmountNormalHUF>
            </lineGrossAmountData>
          </lineAmountsNormal>
        </line>
      </invoiceLines>
      <invoiceSummary>
        <summaryNormal>
          <summaryByVatRate>
            <vatRate>
              <vatPercentage>0.27</vatPercentage>
            </vatRate>
            <vatRateNetData>
              <vatRateNetAmount>200</vatRateNetAmount>
              <vatRateNetAmountHUF>200</vatRateNetAmountHUF>
            </vatRateNetData>
            <vatRateVatData>
              <vatRateVatAmount>54</vatRateVatAmount>
              <vatRateVatAmountHUF>54</vatRateVatAmountHUF>
            </vatRateVatData>
          </summaryByVatRate>
          <summaryByVatRate>
            <vatRate>
              <vatPercentage>0.05</vatPercentage>
            </vatRate>
            <vatRateNetData>
              <vatRateNetAmount>250</vatRateNetAmount>
              <vatRateNetAmountHUF>250</vatRateNetAmountHUF>
            </vatRateNetData>
            <vatRateVatData>
              <vatRateVatAmount>12.5</vatRateVatAmount>
              <vatRateVatAmountHUF>12.5</vatRateVatAmountHUF>
            </vatRateVatData>
          </summaryByVatRate>
          <invoiceNetAmount>450</invoiceNetAmount>
          <invoiceNetAmountHUF>450</invoiceNetAmountHUF>
          <invoiceVatAmount>66.5</invoiceVatAmount>
          <invoiceVatAmountHUF>66.5</invoiceVatAmountHUF>
        </summaryNormal>
        <summaryGrossData>
          <invoiceGrossAmount>516.5</invoiceGrossAmount>
          <invoiceGrossAmountHUF>516.5</invoiceGrossAmountHUF>
        </summaryGrossData>
      </invoiceSummary>
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
    assert detail.invoice_category == "NORMAL"
    assert detail.delivery_date == "2026-05-12"
    assert detail.currency_code == "HUF"
    assert detail.exchange_rate == 1.0
    assert detail.invoice_appearance == "ELECTRONIC"
    assert detail.invoice_net_amount == 450.0
    assert detail.invoice_vat_amount == 66.5
    assert detail.invoice_gross_amount == 516.5


def test_parse_invoice_data_extracts_line_items():
    detail = parse_invoice_data(_SAMPLE_XML, invoice_number="TEST-2026-1")

    assert len(detail.lines) == 2

    line1 = detail.lines[0]
    assert line1.line_number == "1"
    assert line1.line_description == "Consulting"
    assert line1.quantity == 2.0
    assert line1.unit_of_measure == ""
    assert line1.unit_price == 100.0
    assert line1.line_net_amount == 200.0
    assert line1.line_vat_rate == 0.27
    assert line1.line_vat_amount is None
    assert line1.line_gross_amount is None

    line2 = detail.lines[1]
    assert line2.line_number == "2"
    assert line2.line_description == "Widget"
    assert line2.quantity == 5.0
    assert line2.unit_of_measure == "db"
    assert line2.unit_price == 50.0
    assert line2.line_net_amount == 250.0
    assert line2.line_vat_rate == 0.05
    assert line2.line_vat_amount == 12.5
    assert line2.line_gross_amount == 262.5


def test_parse_invoice_data_extracts_vat_summary():
    detail = parse_invoice_data(_SAMPLE_XML, invoice_number="TEST-2026-1")

    assert len(detail.vat_summary) == 2

    row1 = detail.vat_summary[0]
    assert row1.vat_rate == 0.27
    assert row1.vat_rate_net_amount == 200.0
    assert row1.vat_rate_vat_amount == 54.0

    row2 = detail.vat_summary[1]
    assert row2.vat_rate == 0.05
    assert row2.vat_rate_net_amount == 250.0
    assert row2.vat_rate_vat_amount == 12.5


def test_parse_invoice_data_extracts_simple_address():
    """simpleAddress (used e.g. for domestic parties without a structured
    street breakdown) keeps its street-level line in additionalAddressDetail —
    make sure that isn't silently dropped."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<InvoiceData xmlns="http://schemas.nav.gov.hu/OSA/3.0/data" xmlns:ns2="http://schemas.nav.gov.hu/OSA/3.0/base">
  <invoiceMain>
    <invoice>
      <invoiceHead>
        <customerInfo>
          <customerName>Customer Kft.</customerName>
          <customerAddress>
            <ns2:simpleAddress>
              <ns2:countryCode>HU</ns2:countryCode>
              <ns2:postalCode>1082</ns2:postalCode>
              <ns2:city>Budapest</ns2:city>
              <ns2:additionalAddressDetail>Kisfaludy utca 23-25. fszt 1. ajtó</ns2:additionalAddressDetail>
            </ns2:simpleAddress>
          </customerAddress>
        </customerInfo>
      </invoiceHead>
    </invoice>
  </invoiceMain>
</InvoiceData>
"""
    detail = parse_invoice_data(xml, invoice_number="TEST-2026-3")

    assert detail.customer_address == "1082, Budapest, Kisfaludy utca 23-25. fszt 1. ajtó"


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
    assert detail.invoice_category == ""
    assert detail.delivery_date == ""
    assert detail.currency_code == ""
    assert detail.exchange_rate is None
    assert detail.invoice_appearance == ""
    assert detail.invoice_net_amount is None
    assert detail.invoice_vat_amount is None
    assert detail.invoice_gross_amount is None
    assert detail.lines == []
    assert detail.vat_summary == []
