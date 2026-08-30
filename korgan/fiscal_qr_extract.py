from __future__ import annotations

import asyncio
import io
import re
from typing import Iterable

import cv2
import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader

_RECEIPT_URL = re.compile(r"https://receipt\.kaspi\.kz/[^\s<>\]\[\"']+", re.IGNORECASE)
_MAX_IMAGE_PIXELS = 24_000_000
_MAX_QR_VARIANTS = 18
_MAX_PDF_PAGES = 3
_PDF_RENDER_SCALE = 2.0


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


def _decode_qr_array(image: np.ndarray) -> str:
    image = _bounded_image(image)
    if image is None:
        return ""
    detector = cv2.QRCodeDetector()
    for candidate in _qr_variants(image):
        found = _decode_candidate(detector, candidate)
        if found:
            return found
    return ""


def _decode_qr_image(data: bytes) -> str:
    if not data:
        return ""
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    return _decode_qr_array(image)


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


def _render_pdf_qr(data: bytes) -> str:
    """Render bounded PDF pages when the QR is drawn into page content.

    Kaspi electronic receipts often expose text to pypdf while the fiscal QR is
    not a standalone page image. In that shape ``page.images`` may contain only
    the Kaspi logo, so the complete page must be rasterized before OpenCV can
    see the QR. Rendering is page- and pixel-bounded to avoid unbounded CPU/RAM.
    """
    try:
        document = pdfium.PdfDocument(data)
    except Exception:
        return ""

    try:
        page_count = min(len(document), _MAX_PDF_PAGES)
        for index in range(page_count):
            page = None
            bitmap = None
            try:
                page = document[index]
                width, height = page.get_size()
                projected_pixels = int(width * _PDF_RENDER_SCALE) * int(height * _PDF_RENDER_SCALE)
                if projected_pixels <= 0 or projected_pixels > _MAX_IMAGE_PIXELS:
                    continue
                bitmap = page.render(scale=_PDF_RENDER_SCALE, rotation=0)
                rgb = np.asarray(bitmap.to_pil().convert("RGB"))
                image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                found = _decode_qr_array(image)
                if found:
                    return found
            except Exception:
                continue
            finally:
                try:
                    if bitmap is not None:
                        bitmap.close()
                except Exception:
                    pass
                try:
                    if page is not None:
                        page.close()
                except Exception:
                    pass
    finally:
        try:
            document.close()
        except Exception:
            pass
    return ""


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))

    text_parts: list[str] = []
    annotation_parts: list[str] = []
    for page in reader.pages[:_MAX_PDF_PAGES]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
        annotation_parts.extend(_annotation_urls(page))
    found = _first_receipt_url([*annotation_parts, *text_parts])
    if found:
        return found

    for page in reader.pages[:_MAX_PDF_PAGES]:
        try:
            for image in page.images:
                found = _decode_qr_image(image.data)
                if found:
                    return found
        except Exception:
            continue

    return _render_pdf_qr(data)


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
