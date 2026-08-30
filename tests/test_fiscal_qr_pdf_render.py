from __future__ import annotations

import asyncio

import cv2

from korgan.fiscal_qr_extract import extract_kaspi_fiscal_qr_url


def _vector_qr_pdf(url: str) -> bytes:
    qr = cv2.QRCodeEncoder_create().encode(url)
    modules = int(qr.shape[0])
    module = 6
    quiet = 4 * module
    size = modules * module + 2 * quiet
    commands = ["0 0 0 rg"]
    for row in range(modules):
        for column in range(modules):
            if int(qr[row, column]) == 0:
                x = quiet + column * module
                y = quiet + (modules - 1 - row) * module
                commands.append(f"{x} {y} {module} {module} re f")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size} {size}] /Contents 4 0 R >>".encode(),
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_extracts_qr_drawn_into_pdf_page() -> None:
    expected = (
        "https://receipt.kaspi.kz/web/fiscal?"
        "i=557225556134&f=010103806424&s=1000.0&t=2026-08-30%2014%3A22%3A00"
    )
    pdf = _vector_qr_pdf(expected)
    actual = asyncio.run(extract_kaspi_fiscal_qr_url(pdf, "receipt.pdf", "application/pdf"))
    assert actual == expected
