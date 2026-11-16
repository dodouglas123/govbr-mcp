from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from govbr.models import cnpj

# Redige CPF explícito em textos públicos. Sequências nuas também podem ser códigos
# administrativos, por isso são removidas somente nos valores de texto expostos.
CPF_TEXT = re.compile(r"(?<![0-9])(?:[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|[0-9]{11})(?![0-9])")
CONTROL = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
OPEN_TAG = re.compile(r"<[^>]{0,300}>")
PNCP_PATTERN = re.compile(r"([A-Z0-9]{12}[0-9]{2})-([12])-([0-9]{6,9})/(20[0-9]{2})", re.ASCII)


def clean_text(value: Any, size: int = 420) -> str | None:
    if not isinstance(value, (str, int)):
        return None
    text = OPEN_TAG.sub(" ", str(value)[: size * 3])
    text = CPF_TEXT.sub("[CPF omitido]", text)
    text = CONTROL.sub(" ", text)
    return " ".join(text.split())[:size] or None


def search_key(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def corporate_id(value: Any) -> str | None:
    if not isinstance(value, (str, int)):
        return None
    try:
        return cnpj(str(value))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value[:10])
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def epoch_iso(value: Any) -> str | None:
    return clean_text(value, 40) if parse_date(value) else None


def money(value: Any, *, locale: str = "json") -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if len(text) > 40:
        return None
    if locale == "pt-BR":
        if not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,4})?", text):
            return None
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
        if amount.is_finite() and abs(amount) < Decimal("1e18"):
            return amount
    except InvalidOperation:
        pass
    return None


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(data: Any) -> str:
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return digest(serialized.encode())


def integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) <= 12 and value.isascii() and value.isdecimal():
        return int(value)
    return None


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def selected(row: dict, keys: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, (bool, int, float)):
            values[key] = value
        elif isinstance(value, Decimal) and value.is_finite():
            values[key] = str(value)
        elif isinstance(value, str):
            values[key] = clean_text(value)
    return values


def pncp_parts(identifier: str) -> tuple[str, str, int, int]:
    match = PNCP_PATTERN.fullmatch(identifier.upper())
    if not match:
        raise ValueError("Formato PNCP esperado CNPJ-1-000001/2025 ou CNPJ-2-000001/2025")
    company, kind, sequence, year = match.groups()
    return cnpj(company), kind, int(year), int(sequence)
