"""The pure statement parsers: tolerant of real-world mess, loud about the rest."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from hestia_api import statement_parse as sp

CSV_AMOUNT = """Date,Description,Amount
2026-08-01,ACH DEPOSIT ZELLE TENANT,"$1,450.00"
08/14/2026,DUKE ENERGY BILL PAY,(92.40)
8/20/26,HOME DEPOT #4821,-380.00
"""

CSV_DEBIT_CREDIT = """Posted Date,Payee,Debit,Credit
2026-08-01,ZELLE TENANT,,1450.00
2026-08-14,DUKE ENERGY,92.40,
"""

OFX_SAMPLE = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260801120000[-5:EST]
<TRNAMT>1450.00
<FITID>2026080101
<NAME>ZELLE TENANT AUG
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260814
<TRNAMT>-92.40
<FITID>2026081401
<MEMO>DUKE ENERGY BILL PAY
</STMTTRN>
</BANKTRANLIST>
</OFX>
"""


class TestCsv:
    def test_amount_column_with_real_world_notation(self) -> None:
        rows = sp.parse_csv(CSV_AMOUNT)
        assert [row.amount for row in rows] == [
            Decimal("1450.00"),
            Decimal("-92.40"),
            Decimal("-380.00"),
        ]
        assert rows[0].posted_on == dt.date(2026, 8, 1)
        assert rows[1].posted_on == dt.date(2026, 8, 14)  # MM/DD/YYYY
        assert rows[2].posted_on == dt.date(2026, 8, 20)  # M/D/YY
        assert rows[2].description == "HOME DEPOT #4821"
        assert rows[0].fitid is None

    def test_debit_credit_pair_signs_money_correctly(self) -> None:
        rows = sp.parse_csv(CSV_DEBIT_CREDIT)
        assert rows[0].amount == Decimal("1450.00")
        assert rows[1].amount == Decimal("-92.40")  # unsigned debit is money OUT

    def test_header_failures_name_the_problem(self) -> None:
        with pytest.raises(sp.StatementParseError, match="no rows"):
            sp.parse_csv("")
        with pytest.raises(sp.StatementParseError, match="no recognizable header"):
            sp.parse_csv("a,b,c\n1,2,3\n")
        with pytest.raises(sp.StatementParseError, match="no amount column"):
            sp.parse_csv("Date,Description\n2026-08-01,X\n")
        with pytest.raises(sp.StatementParseError, match="header but no transactions"):
            sp.parse_csv("Date,Description,Amount\n")

    def test_row_failures_carry_their_row_number(self) -> None:
        head = "Date,Description,Amount\n"
        with pytest.raises(sp.StatementParseError, match="row 2: unreadable date"):
            sp.parse_csv(head + "someday,X,1.00\n")
        with pytest.raises(sp.StatementParseError, match="row 2: unreadable amount"):
            sp.parse_csv(head + "2026-08-01,X,abc\n")
        with pytest.raises(sp.StatementParseError, match="row 2: empty amount"):
            sp.parse_csv(head + "2026-08-01,X,$\n")
        with pytest.raises(sp.StatementParseError, match="row 2: zero-dollar"):
            sp.parse_csv(head + "2026-08-01,X,0.00\n")
        with pytest.raises(sp.StatementParseError, match="row 2: empty description"):
            sp.parse_csv(head + "2026-08-01, ,1.00\n")
        with pytest.raises(sp.StatementParseError, match="row 2: too few columns"):
            sp.parse_csv(head + "2026-08-01\n")

    def test_debit_credit_row_failures(self) -> None:
        head = "Date,Description,Debit,Credit\n"
        with pytest.raises(sp.StatementParseError, match="both debit and credit"):
            sp.parse_csv(head + "2026-08-01,X,5.00,5.00\n")
        with pytest.raises(sp.StatementParseError, match="neither debit nor credit"):
            sp.parse_csv(head + "2026-08-01,X,,\n")


class TestOfx:
    def test_sgml_blocks_with_fitid_and_memo_fallback(self) -> None:
        rows = sp.parse_ofx(OFX_SAMPLE)
        assert len(rows) == 2
        assert rows[0].fitid == "2026080101"
        assert rows[0].description == "ZELLE TENANT AUG"
        assert rows[0].posted_on == dt.date(2026, 8, 1)
        assert rows[1].description == "DUKE ENERGY BILL PAY"  # MEMO fallback
        assert rows[1].amount == Decimal("-92.40")

    def test_ofx_failures(self) -> None:
        with pytest.raises(sp.StatementParseError, match="no STMTTRN"):
            sp.parse_ofx("<OFX></OFX>")
        with pytest.raises(sp.StatementParseError, match="unreadable DTPOSTED"):
            sp.parse_ofx("<STMTTRN><DTPOSTED>soon<TRNAMT>1.00<NAME>X</STMTTRN>")
        with pytest.raises(sp.StatementParseError, match="zero-dollar TRNAMT"):
            sp.parse_ofx("<STMTTRN><DTPOSTED>20260801<TRNAMT>0.00<NAME>X</STMTTRN>")
        with pytest.raises(sp.StatementParseError, match="no NAME or MEMO"):
            sp.parse_ofx("<STMTTRN><DTPOSTED>20260801<TRNAMT>1.00</STMTTRN>")


class TestDetection:
    def test_extension_wins_then_content_sniffs(self) -> None:
        assert sp.detect_format("a.qfx", "") == "qfx"
        assert sp.detect_format("a.OFX", "") == "ofx"
        assert sp.detect_format("a.csv", "OFXHEADER:100") == "csv"
        assert sp.detect_format("statement", "OFXHEADER:100\n...") == "ofx"
        assert sp.detect_format("statement", "junk <OFX> junk") == "ofx"
        assert sp.detect_format("statement", "Date,Description,Amount") == "csv"

    def test_parse_statement_routes_by_format(self) -> None:
        fmt, rows = sp.parse_statement("a.csv", CSV_AMOUNT)
        assert (fmt, len(rows)) == ("csv", 3)
        fmt, rows = sp.parse_statement("a.qfx", OFX_SAMPLE)
        assert (fmt, len(rows)) == ("qfx", 2)


def test_normalise_description() -> None:
    assert sp.normalise_description("  DUKE   ENERGY\tBILL ") == "duke energy bill"
