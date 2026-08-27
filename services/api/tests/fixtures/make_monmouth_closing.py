"""Regenerates monmouth-closing.pdf, the canonical extraction fixture.

A minimal but fully valid two-page PDF (uncompressed content streams,
WinAnsi Helvetica) carrying an ALTA settlement statement for the demo
property. Every figure foots: capitalizable costs 712 + 450 + 250 + 46 +
325 = 1,783; cash due = 187,500 - 150,000 - 5,000 - 438.42 + 1,783 + 375
+ 80 = 34,299.58. Run from this directory: python3 make_monmouth_closing.py
"""

from __future__ import annotations

from pathlib import Path

PAGE1 = [
    "ALTA SETTLEMENT STATEMENT - BORROWER/BUYER",
    "Cardinal Point Title Agency, LLC",
    "File No.: NKY-19-04217",
    "Settlement Date: April 11, 2019",
    "Disbursement Date: April 11, 2019",
    "",
    "Property: 998 Monmouth St, Newport, KY 41071",
    "Parcel ID: 999-00-00-037.00",
    "Buyer: Delta Holdings LLC",
    "Seller: Harold Voss and Marlene Voss",
    "Lender: Licking Valley Savings Bank",
    "",
    "FINANCIAL SUMMARY",
    "Sale Price of Property                              $187,500.00",
    "Loan Amount                                         $150,000.00",
    "Deposit / Earnest Money                               $5,000.00",
    "County Property Tax Proration (01/01/19-04/10/19)       $438.42",
]

PAGE2 = [
    "ITEMIZED CHARGES - BORROWER/BUYER",
    "",
    "Title Charges",
    "Owner's Title Insurance Policy                          $712.00",
    "Lender's Title Insurance Policy                         $375.00",
    "Settlement or Closing Fee                               $450.00",
    "Title Search and Examination                            $250.00",
    "",
    "Government Recording and Transfer Charges",
    "Recording Fee: Deed                                      $46.00",
    "Recording Fee: Mortgage                                  $80.00",
    "",
    "Additional Charges",
    "Survey                                                  $325.00",
    "",
    "Totals",
    "Total Capitalizable Closing Costs                     $1,783.00",
    "Cash Due From Borrower                               $34,299.58",
]


def content_stream(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 10 Tf", "12 TL", "1 0 0 1 72 720 Tm"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"({escaped}) Tj T*")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def build() -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    streams = []
    for page_lines in (PAGE1, PAGE2):
        data = content_stream(page_lines)
        streams.append(
            add(b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream")
        )
    page_numbers = []
    for stream in streams:
        parent = len(objects) + (3 - len(page_numbers))
        page_numbers.append(
            add(
                b"<< /Type /Page /Parent " + str(parent).encode() + b" 0 R"
                b" /MediaBox [0 0 612 792] /Contents " + str(stream).encode() + b" 0 R"
                b" /Resources << /Font << /F1 " + str(font).encode() + b" 0 R >> >> >>"
            )
        )
    pages = add(
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{n} 0 R".encode() for n in page_numbers)
        + b"] /Count "
        + str(len(page_numbers)).encode()
        + b" >>"
    )
    catalog = add(b"<< /Type /Catalog /Pages " + str(pages).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


if __name__ == "__main__":
    target = Path(__file__).parent / "monmouth-closing.pdf"
    target.write_bytes(build())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
