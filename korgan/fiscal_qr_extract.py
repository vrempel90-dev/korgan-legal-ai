from __future__ import annotations

import asyncio
import io
import re
from typing import Iterable

import cv2
import numpy as np
from pypdf import PdfReader

_RECEIPT_URL = re.compile(r"https://receipt\.kaspi\.kz/[^\s<>\]\[\"']+", re.IGNORECASE)


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip(".,);}")


def _first_receipt_url(values: Iterable[str]) -> str:
    for value in values:
        match = _RECEIPT_URL.search(str(value or ""))
        if match:
            return _clean_url(match.group(0))
    return ""


def _decode_qr_image(data: bytes) -> str:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return ""
    detector = cv2.QRCodeDetector()
    try:
        ok, decoded, _points, _straight = detector.detectAndDecodeMulti(image)
        if ok:
            found = _first_receipt_url(str(value) for value in decoded if value)
            if found:
                return found
    except Exception:
        pass
    try:
        value, _points, _straight = detector.detectAndDecode(image)
        return _first_receipt_url([str(value or "")])
    except Exception:
        return ""


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    # First prefer an actual URL encoded in PDF text/annotations.
    text_parts: list[str] = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
    found = _first_receipt_url(text_parts)
    if found:
        return found

    # Kaspi receipts commonly contain the fiscal QR as a raster image. Decode
    # only the QR pixels; no OCR/model is involved.
    for page in reader.pages:
        try:
            for image in page.images:
                found = _decode_qr_image(image.data)
                if found:
                    return found
        except Exception:
            continue
    return ""


def _extract_sync(data: bytes, filename: str, mime_type: str) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf" or mime_type == "application/pdf":
        return _extract_pdf(data)
    return _decode_qr_image(data)


async def extract_kaspi_fiscal_qr_url(data: bytes, filename: str, mime_type: str) -> str:
    """Extract only an official receipt.kaspi.kz QR target, locally and without AI."""
    if not data:
        return ""
    return await asyncio.to_thread(_extract_sync, data, filename, mime_type)
