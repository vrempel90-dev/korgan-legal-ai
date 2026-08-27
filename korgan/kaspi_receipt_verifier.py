from __future__ import annotations

import asyncio
import html
import io
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from pypdf import PdfReader

from korgan.config import Settings
from korgan.payment import ReceiptAnalyzer


@dataclass(frozen=True)
class KaspiReceiptCheck:
    readable: bool
    looks_like_kaspi: bool
    payment_successful: bool
    amount_kzt: int
    date_time: str
    merchant_or_recipient: str
    payer: str
    receipt_or_transaction_id: str
    rnm: str
    fp: str
    seller_bin: str
    qr_url: str
    official_verified: bool
    official_final_url: str
    source: str
    suspicious_signals: tuple[str, ...]
    notes: tuple[str, ...]


_AMOUNT_AFTER_SUCCESS = re.compile(
    r"(?:Оплата\s+совершена|Плат[её]ж\s+успешно\s+соверш[её]н)"
    r"\s*[\r\n]+\s*([\d\s\u00a0]+)\s*₸",
    re.IGNORECASE,
)
_RECEIPT_ID = re.compile(r"№\s*чека(?:\s*\(RRN\))?\s*:?\s*([A-ZА-Я0-9_-]+)", re.IGNORECASE)
_DATE_TIME = re.compile(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?)")
_SELLER_BIN = re.compile(r"ИИН\s*/\s*БИН\s+продавца\s*:?\s*(\d{12})", re.IGNORECASE)
_RNM = re.compile(r"\bРНМ\s*:?\s*(\d{8,16})", re.IGNORECASE)
_FP = re.compile(r"\bФП\s*:?\s*(\d{6,20})", re.IGNORECASE)
_PAYER = re.compile(r"ФИО\s+покупателя\s*:?\s*([^\r\n]+)", re.IGNORECASE)
_SUCCESS = re.compile(r"(?:Оплата\s+совершена|Плат[её]ж\s+успешно\s+соверш[её]н)", re.IGNORECASE)


def _clean_text(value: str) -> str:
    return value.replace("\u00a0", " ").replace("\r", "\n")


def _digits_amount(value: str) -> int:
    digits = re.sub(r"\D", "", value or "")
    return int(digits or 0)


def _extract_merchant(text: str) -> str:
    lines = [line.strip() for line in _clean_text(text).splitlines() if line.strip()]
    try:
        sale_index = next(i for i, line in enumerate(lines) if line.casefold() == "продажа")
    except StopIteration:
        return ""
    before = lines[:sale_index]
    ignored = (
        "фискальный чек",
        "оплата совершена",
        "платеж успешно совершен",
        "платёж успешно совершён",
    )
    candidates = [
        line
        for line in before
        if line.casefold() not in ignored
        and "₸" not in line
        and not line.isdigit()
    ]
    return candidates[-1] if candidates else ""


def parse_receipt_text(text: str) -> dict[str, Any]:
    clean = _clean_text(text)
    amount_match = _AMOUNT_AFTER_SUCCESS.search(clean)
    receipt_match = _RECEIPT_ID.search(clean)
    date_match = _DATE_TIME.search(clean)
    bin_match = _SELLER_BIN.search(clean)
    rnm_match = _RNM.search(clean)
    fp_match = _FP.search(clean)
    payer_match = _PAYER.search(clean)
    return {
        "readable": bool(clean.strip()),
        "looks_like_kaspi": "kaspi офд" in clean.casefold() and "фискальный чек" in clean.casefold(),
        "payment_successful": bool(_SUCCESS.search(clean)),
        "amount_kzt": _digits_amount(amount_match.group(1)) if amount_match else 0,
        "date_time": date_match.group(1).strip() if date_match else "",
        "merchant_or_recipient": _extract_merchant(clean),
        "payer": payer_match.group(1).strip() if payer_match else "",
        "receipt_or_transaction_id": receipt_match.group(1).strip() if receipt_match else "",
        "rnm": rnm_match.group(1).strip() if rnm_match else "",
        "fp": fp_match.group(1).strip() if fp_match else "",
        "seller_bin": bin_match.group(1).strip() if bin_match else "",
    }


def _decode_qr_from_image_bytes(data: bytes) -> str:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return ""
    detector = cv2.QRCodeDetector()
    try:
        ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
        if ok:
            for value in decoded:
                if value:
                    return str(value).strip()
    except Exception:
        pass
    try:
        value, _, _ = detector.detectAndDecode(image)
        return str(value or "").strip()
    except Exception:
        return ""


def extract_pdf_text_and_qr(data: bytes) -> tuple[str, str]:
    reader = PdfReader(io.BytesIO(data))
    texts: list[str] = []
    qr_url = ""
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
        if qr_url:
            continue
        try:
            for image in page.images:
                candidate = _decode_qr_from_image_bytes(image.data)
                if candidate:
                    qr_url = candidate
                    break
        except Exception:
            continue
    return "\n".join(texts), qr_url


def parse_kaspi_qr(url: str) -> dict[str, Any]:
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return {}
    if parsed.scheme != "https" or parsed.hostname != "receipt.kaspi.kz":
        return {}
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path.startswith("/web/fiscal"):
        try:
            amount = int(round(float((query.get("s") or ["0"])[0])))
        except (TypeError, ValueError):
            amount = 0
        return {
            "qr_url": url,
            "fp": str((query.get("i") or [""])[0]).strip(),
            "rnm": str((query.get("f") or [""])[0]).strip(),
            "amount_kzt": amount,
            "date_time": str((query.get("t") or [""])[0]).strip(),
        }
    if parsed.path.startswith("/web"):
        return {
            "qr_url": url,
            "receipt_or_transaction_id": str((query.get("extTranId") or [""])[0]).strip(),
            "date_time": str((query.get("sale_date") or [""])[0]).strip(),
        }
    return {}


def _strip_html(body: str) -> str:
    value = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
    value = re.sub(r"(?is)<style.*?>.*?</style>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return " ".join(value.split())


def _official_receipt_probe(url: str, expected: dict[str, Any], settings: Settings) -> tuple[bool, str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "receipt.kaspi.kz":
        return False, "", "QR ведёт не на официальный receipt.kaspi.kz"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "KORGAN-Receipt-Verifier/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            final_url = response.geturl()
            final_parsed = urllib.parse.urlparse(final_url)
            if final_parsed.hostname != "receipt.kaspi.kz":
                return False, final_url, "Kaspi перенаправил проверку на неожиданный домен"
            body = response.read(2_000_000).decode("utf-8", "ignore")
    except Exception as exc:
        return False, "", f"официальная проверка Kaspi ОФД временно недоступна: {type(exc).__name__}"

    text = _strip_html(body).casefold()
    markers = ("фискальный чек", "kaspi офд", "иин/бин продавца", "рнм", "фп")
    if not any(marker in text for marker in markers):
        return False, final_url, "официальная страница не вернула данные фискального чека"

    expected_bin = str(getattr(settings, "kaspi_seller_bin", "") or "").strip()
    expected_rnm = str(expected.get("rnm") or "").strip()
    expected_fp = str(expected.get("fp") or "").strip()
    expected_receipt = str(expected.get("receipt_or_transaction_id") or "").strip()

    strong_values = [value for value in (expected_rnm, expected_fp, expected_receipt) if value]
    if strong_values and not any(value.casefold() in text for value in strong_values):
        return False, final_url, "реквизиты QR не найдены на официальной странице Kaspi ОФД"
    if expected_bin and expected_bin not in text:
        if not any(value and value.casefold() in text for value in (expected_rnm, expected_fp)):
            return False, final_url, "БИН продавца не подтверждён официальной страницей Kaspi ОФД"
    return True, final_url, "официальная страница Kaspi ОФД подтвердила чек"


async def verify_official_receipt(url: str, expected: dict[str, Any], settings: Settings) -> tuple[bool, str, str]:
    return await asyncio.to_thread(_official_receipt_probe, url, expected, settings)


def _merge(primary: dict[str, Any], secondary: Any | None) -> dict[str, Any]:
    result = dict(primary)
    if secondary is None:
        return result
    for key in (
        "readable",
        "looks_like_kaspi",
        "payment_successful",
        "amount_kzt",
        "date_time",
        "merchant_or_recipient",
        "payer",
        "receipt_or_transaction_id",
        "rnm",
        "fp",
    ):
        if result.get(key) in ("", 0, False, None):
            result[key] = getattr(secondary, key, result.get(key))
    return result


class KaspiReceiptAnalyzer:
    """Deterministic Kaspi fiscal receipt verifier.

    PDF receipts are parsed without AI. QR is decoded locally and then checked
    against Kaspi's public receipt site. AI is only a fallback field reader for
    photos/screenshots; it never decides whether payment is approved.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.fallback = ReceiptAnalyzer(settings)

    async def analyze(self, data: bytes, filename: str, mime_type: str) -> KaspiReceiptCheck:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        is_pdf = suffix == "pdf" or mime_type == "application/pdf"

        parsed: dict[str, Any] = {}
        qr_url = ""
        fallback = None
        source = "deterministic"

        if is_pdf:
            try:
                text, qr_url = extract_pdf_text_and_qr(data)
                parsed = parse_receipt_text(text)
                source = "pdf-text+qr"
            except Exception:
                parsed = {}
        else:
            qr_url = _decode_qr_from_image_bytes(data)
            source = "image-qr"

        qr = parse_kaspi_qr(qr_url)
        if qr:
            for key, value in qr.items():
                if key == "qr_url":
                    continue
                if value not in ("", 0, None):
                    parsed[key] = value

        if not is_pdf or not parsed.get("readable"):
            try:
                fallback = await self.fallback.analyze(data, filename, mime_type)
            except Exception:
                fallback = None
            parsed = _merge(parsed, fallback)
            if fallback is not None:
                source += "+ai-read"

        official_verified = False
        official_final_url = ""
        official_note = "QR фискального чека не распознан"
        if qr:
            official_verified, official_final_url, official_note = await verify_official_receipt(
                qr_url, parsed, self.settings
            )
            source += "+ofd"

        suspicious = tuple(str(x) for x in getattr(fallback, "suspicious_signals", ()) or ())
        notes = [official_note]
        if is_pdf:
            notes.append("PDF реквизиты извлечены детерминированно; AI не принимал решение об оплате")
        elif fallback is not None:
            notes.append("AI использован только для чтения видимых полей; решение принимает детерминированный gate")

        return KaspiReceiptCheck(
            readable=bool(parsed.get("readable") or qr),
            looks_like_kaspi=bool(parsed.get("looks_like_kaspi") or qr),
            payment_successful=bool(parsed.get("payment_successful") or official_verified),
            amount_kzt=int(parsed.get("amount_kzt") or 0),
            date_time=str(parsed.get("date_time") or ""),
            merchant_or_recipient=str(parsed.get("merchant_or_recipient") or ""),
            payer=str(parsed.get("payer") or ""),
            receipt_or_transaction_id=str(parsed.get("receipt_or_transaction_id") or ""),
            rnm=str(parsed.get("rnm") or ""),
            fp=str(parsed.get("fp") or ""),
            seller_bin=str(parsed.get("seller_bin") or ""),
            qr_url=str(qr_url or ""),
            official_verified=bool(official_verified),
            official_final_url=str(official_final_url or ""),
            source=source,
            suspicious_signals=suspicious,
            notes=tuple(notes),
        )
