from __future__ import annotations

import asyncio
import io
import re
from typing import Iterable

import cv2
import numpy as np
from pypdf import PdfReader

_RECEIPT_URL = re.compile(r"https://receipt\.kaspi\.kz/[^\s<>\]\[\"']+", re.IGNORECASE)
_MAX_IMAGE_PIXELS = 24_000_000
_MAX_QR_VARIANTS = 18


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip(".,);}")


def _first_receipt_url(values: Iterable[str]) -> str:
    for value in values:
        match = _RECEIPT_URL.search(str(value or ""))
        if match:
            return _clean_url(match.group(0))
    return ""


def _decode_candidate(detector: cv2.QRCodeDetector, image: np.ndarray) -> str:
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


def _bounded_image(image: np.ndarray) -> np.ndarray | None:
    if image is None or image.size == 0:
        return None
    height, width = image.shape[:2]
    if height <= 0 or width <= 0 or height * width > _MAX_IMAGE_PIXELS:
        return None
    return image


def _qr_variants(image: np.ndarray) -> list[np.ndarray]:
    image = _bounded_image(image)
    if image is None:
        return []

    variants: list[np.ndarray] = [image]
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        variants.append(gray)

        # Kaspi PDF/WhatsApp exports often make the QR relatively small. Upscale
        # only bounded images; this improves detector stability without OCR/AI.
        height, width = gray.shape[:2]
        longest = max(height, width)
        if longest < 2200:
            scale = 3 if longest < 900 else 2
            up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            if _bounded_image(up) is not None:
                variants.append(up)
                gray_for_threshold = up
            else:
                gray_for_threshold = gray
        else:
            gray_for_threshold = gray

        try:
            equalized = cv2.equalizeHist(gray_for_threshold)
            variants.append(equalized)
        except Exception:
            pass

        try:
            _threshold, otsu = cv2.threshold(
                gray_for_threshold,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )
            variants.append(otsu)
        except Exception:
            pass

        try:
            adaptive = cv2.adaptiveThreshold(
                gray_for_threshold,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )
            variants.append(adaptive)
        except Exception:
            pass
    except Exception:
        pass

    # Quiet-zone + rotation recovery. Limit total work so a hostile large image
    # cannot turn receipt verification into an unbounded CPU task.
    base = list(variants[:6])
    for candidate in base:
        if len(variants) >= _MAX_QR_VARIANTS:
            break
        try:
            padded = cv2.copyMakeBorder(candidate, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)
            if _bounded_image(padded) is not None:
                variants.append(padded)
        except Exception:
            pass
        for rotate_code in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
            if len(variants) >= _MAX_QR_VARIANTS:
                break
            try:
                rotated = cv2.rotate(candidate, rotate_code)
                if _bounded_image(rotated) is not None:
                    variants.append(rotated)
            except Exception:
                continue

    return variants[:_MAX_QR_VARIANTS]


def _decode_qr_image(data: bytes) -> str:
    if not data:
        return ""
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    image = _bounded_image(image)
    if image is None:
        return ""

    detector = cv2.QRCodeDetector()
    for candidate in _qr_variants(image):
        found = _decode_candidate(detector, candidate)
        if found:
            return found
    return ""


def _annotation_urls(page) -> Iterable[str]:  # noqa: ANN001
    try:
        annotations = page.get("/Annots") or []
    except Exception:
        annotations = []
    for ref in annotations:
        try:
            annotation = ref.get_object()
            action = annotation.get("/A") or {}
            uri = action.get("/URI")
            if uri:
                yield str(uri)
        except Exception:
            continue


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))

    # Prefer URL already present in PDF text/annotations. This is both faster and
    # more reliable than decoding pixels when Kaspi embeds the fiscal link.
    text_parts: list[str] = []
    annotation_parts: list[str] = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
        annotation_parts.extend(_annotation_urls(page))
    found = _first_receipt_url([*annotation_parts, *text_parts])
    if found:
        return found

    # Kaspi receipts commonly contain the fiscal QR as a raster image. Decode
    # only QR pixels; no OCR/model is involved.
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
