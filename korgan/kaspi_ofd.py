from __future__ import annotations

import asyncio
import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


_KASPI_RECEIPT_HOST = "receipt.kaspi.kz"
_KASPI_RECEIPT_PATH = "/api/v3/receipt/download"
_MAX_RECEIPT_BYTES = 512_000
_KZ_TZ = timezone(timedelta(hours=5))
_DATE_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


class KaspiOFDVerificationError(RuntimeError):
    """Raised when an official Kaspi OFD receipt cannot be verified safely."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "svg"}:
            self._skip_depth += 1
        elif tag in {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


@dataclass(frozen=True)
class KaspiFiscalReceipt:
    canonical_url: str
    body_sha256: str
    ext_transaction_id: str
    receipt_number: str
    successful: bool
    amount_kzt: int
    sale_datetime: str
    seller_name: str
    seller_bin: str
    rnm: str
    fp: str
    ofd_name: str
    raw_text: str

    @property
    def transaction_id(self) -> str:
        strong = ":".join(part for part in (self.rnm, self.receipt_number, self.fp) if part)
        return strong or self.ext_transaction_id

    @property
    def receipt_fingerprint(self) -> str:
        payload = f"{self.canonical_url}\n{self.body_sha256}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def canonicalize_kaspi_receipt_url(value: str) -> str:
    """Validate a fiscal QR target and return a stable official Kaspi URL.

    Only the exact HTTPS Kaspi OFD receipt endpoint is accepted. This prevents
    user-controlled URLs from turning the verifier into a generic HTTP fetcher.
    """
    text = str(value or "").strip()
    if len(text) > 2048:
        raise KaspiOFDVerificationError("Ссылка фискального чека слишком длинная")
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        raise KaspiOFDVerificationError("QR должен вести на защищённый HTTPS-чек Kaspi ОФД")
    if parsed.username or parsed.password:
        raise KaspiOFDVerificationError("Некорректная ссылка фискального чека")
    if (parsed.hostname or "").lower() != _KASPI_RECEIPT_HOST:
        raise KaspiOFDVerificationError("QR не ведёт на официальный receipt.kaspi.kz")
    if parsed.port not in (None, 443):
        raise KaspiOFDVerificationError("Некорректный порт ссылки Kaspi ОФД")
    if parsed.path.rstrip("/") != _KASPI_RECEIPT_PATH:
        raise KaspiOFDVerificationError("QR ведёт не на страницу фискального чека Kaspi ОФД")
    if parsed.fragment:
        raise KaspiOFDVerificationError("Некорректный фрагмент ссылки фискального чека")

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    params: dict[str, str] = {}
    allowed = {"extTranId", "hash", "locale", "sale_date"}
    for key, val in pairs:
        if key not in allowed or key in params:
            raise KaspiOFDVerificationError("Некорректные параметры ссылки фискального чека")
        params[key] = val.strip()
    if not params.get("extTranId") or not params.get("sale_date"):
        raise KaspiOFDVerificationError("В QR отсутствуют обязательные данные Kaspi ОФД")
    if "hash" in params and not re.fullmatch(r"[0-9a-fA-F]{32,128}", params["hash"]):
        raise KaspiOFDVerificationError("Некорректная подпись ссылки Kaspi ОФД")

    ordered = [(key, params[key]) for key in ("extTranId", "hash", "locale", "sale_date") if key in params]
    return urlunparse(("https", _KASPI_RECEIPT_HOST, _KASPI_RECEIPT_PATH, "", urlencode(ordered), ""))


def _fetch_sync(url: str, timeout: float) -> tuple[bytes, str]:
    opener = build_opener(_NoRedirect())
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "KORGAN-PaymentVerifier/1.0",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            length = response.headers.get("Content-Length")
            if length and int(length) > _MAX_RECEIPT_BYTES:
                raise KaspiOFDVerificationError("Ответ Kaspi ОФД превышает допустимый размер")
            body = response.read(_MAX_RECEIPT_BYTES + 1)
            if len(body) > _MAX_RECEIPT_BYTES:
                raise KaspiOFDVerificationError("Ответ Kaspi ОФД превышает допустимый размер")
            content_type = str(response.headers.get("Content-Type") or "").lower()
    except HTTPError as exc:
        raise KaspiOFDVerificationError(f"Kaspi ОФД вернул HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise KaspiOFDVerificationError("Не удалось получить фискальный чек с Kaspi ОФД") from exc

    if canonicalize_kaspi_receipt_url(final_url) != url:
        raise KaspiOFDVerificationError("Kaspi ОФД перенаправил запрос на неожиданный адрес")
    if not body:
        raise KaspiOFDVerificationError("Kaspi ОФД вернул пустой чек")
    if not any(kind in content_type for kind in ("text/html", "application/xhtml", "text/plain")):
        raise KaspiOFDVerificationError("Kaspi ОФД вернул неподдерживаемый формат ответа")
    return body, content_type


def _visible_lines(body: bytes) -> tuple[list[str], str]:
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError:
        source = body.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(source)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return lines, "\n".join(lines)


def _value_after_label(lines: list[str], labels: tuple[str, ...]) -> str:
    folded_labels = tuple(label.casefold() for label in labels)
    for index, line in enumerate(lines):
        folded = line.casefold()
        for label, label_folded in zip(labels, folded_labels):
            pos = folded.find(label_folded)
            if pos < 0:
                continue
            rest = line[pos + len(label):].lstrip(" :№-—")
            if rest:
                return rest.strip()
            if index + 1 < len(lines):
                return lines[index + 1].strip()
    return ""


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _amount(value: str) -> int:
    match = re.search(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*|\d+)(?:[,.](\d{1,2}))?\s*(?:₸|тг|KZT)?", value, re.I)
    if not match:
        return 0
    integer = re.sub(r"\D", "", match.group(1))
    cents = (match.group(2) or "").ljust(2, "0")
    if cents and int(cents) != 0:
        return 0
    return int(integer or 0)


def parse_kaspi_ofd_receipt(url: str, body: bytes) -> KaspiFiscalReceipt:
    canonical = canonicalize_kaspi_receipt_url(url)
    parsed_url = urlparse(canonical)
    query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    lines, text = _visible_lines(body)
    folded = text.casefold()

    status_markers = (
        "платеж успешно совершен",
        "платёж успешно совершен",
        "оплата успешно произведена",
        "оплата успешно совершена",
        "оплата совершена",
        "успешно оплачено",
    )
    successful = any(marker in folded for marker in status_markers)

    amount_raw = _value_after_label(lines, ("Итого", "К оплате", "Сумма оплаты", "Сумма покупки", "Сумма"))
    amount_kzt = _amount(amount_raw)
    if not amount_kzt:
        candidates = re.findall(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*|\d+)\s*₸", text)
        amounts = [_amount(item) for item in candidates]
        amounts = [item for item in amounts if item > 0]
        amount_kzt = amounts[-1] if amounts else 0

    receipt_number = _value_after_label(lines, ("№ чека", "Номер чека", "Чек №"))
    sale_datetime = _value_after_label(lines, ("Дата и время", "Дата/время", "Время продажи"))
    seller_name = _value_after_label(lines, ("Наименование продавца", "Продавец", "Организация"))
    seller_bin = _digits(_value_after_label(lines, ("ИИН/БИН продавца", "БИН продавца", "ИИН/БИН", "БИН")))
    rnm = re.sub(r"\s+", "", _value_after_label(lines, ("РНМ",)))
    fp = re.sub(r"\s+", "", _value_after_label(lines, ("ФП", "Фискальный признак")))
    ofd_name = _value_after_label(lines, ("ОФД", "Оператор фискальных данных"))

    if not sale_datetime:
        sale_datetime = query.get("sale_date", "")

    return KaspiFiscalReceipt(
        canonical_url=canonical,
        body_sha256=hashlib.sha256(body).hexdigest(),
        ext_transaction_id=query.get("extTranId", "").strip(),
        receipt_number=receipt_number[:120],
        successful=successful,
        amount_kzt=amount_kzt,
        sale_datetime=sale_datetime[:120],
        seller_name=seller_name[:200],
        seller_bin=seller_bin[:12],
        rnm=rnm[:120],
        fp=fp[:160],
        ofd_name=ofd_name[:120],
        raw_text=text[:20_000],
    )


async def fetch_kaspi_ofd_receipt(url: str, *, timeout: float = 8.0) -> KaspiFiscalReceipt:
    canonical = canonicalize_kaspi_receipt_url(url)
    body, _content_type = await asyncio.to_thread(_fetch_sync, canonical, timeout)
    return parse_kaspi_ofd_receipt(canonical, body)


def _parse_datetime(value: str | datetime) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            for fmt in _DATE_FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KZ_TZ)
    return parsed.astimezone(timezone.utc)


def _normalize(value: str) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def fiscal_receipt_issues(
    receipt: KaspiFiscalReceipt,
    expected_amount: int,
    *,
    expected_recipient: str = "",
    expected_bin: str = "",
    offered_at: str | datetime | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return deterministic blockers. Any issue keeps the paid result locked."""
    issues: list[str] = []
    if not receipt.successful:
        issues.append("Kaspi ОФД не подтвердил успешную оплату")
    if receipt.amount_kzt != int(expected_amount):
        issues.append(f"сумма фискального чека {receipt.amount_kzt} ₸ вместо {expected_amount} ₸")
    if not receipt.transaction_id.strip():
        issues.append("в фискальном чеке не найден уникальный идентификатор")
    if not receipt.rnm:
        issues.append("в фискальном чеке не найден РНМ")
    if not receipt.fp:
        issues.append("в фискальном чеке не найден ФП")
    if "kaspi" not in _normalize(receipt.ofd_name) or "офд" not in receipt.ofd_name.casefold():
        issues.append("оператор фискальных данных не подтверждён как Kaspi ОФД")

    configured_bin = _digits(expected_bin)
    if configured_bin:
        if len(configured_bin) != 12:
            issues.append("в настройках KORGAN указан некорректный БИН получателя")
        elif receipt.seller_bin != configured_bin:
            issues.append("БИН продавца в фискальном чеке не соответствует KORGAN")
    elif expected_recipient.strip():
        haystack = _normalize(receipt.seller_name or receipt.raw_text)
        tokens = [_normalize(token) for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", expected_recipient)]
        tokens = [token for token in tokens if len(token) >= 5]
        if not tokens or not any(token in haystack for token in tokens):
            issues.append("продавец в фискальном чеке не соответствует получателю KORGAN")

    receipt_time = _parse_datetime(receipt.sale_datetime)
    if receipt_time is None:
        issues.append("не удалось подтвердить дату/время фискального чека")
    elif offered_at is not None:
        offer_time = _parse_datetime(offered_at)
        if offer_time is None:
            issues.append("не удалось подтвердить время открытия текущей оплаты")
        else:
            if receipt_time < offer_time - timedelta(minutes=2):
                issues.append("фискальный чек создан до открытия текущей заявки на оплату")
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if receipt_time > current + timedelta(minutes=10):
                issues.append("дата/время фискального чека находятся недопустимо в будущем")
    return issues
