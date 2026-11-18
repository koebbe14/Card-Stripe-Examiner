"""Issuing-bank directory lookup. The request body is never used, and the URL carries only a BIN."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

HOST = "lookup.binlist.net"
USER_AGENT = "CardStripeExaminer/1.4"
SOURCE_NOTE = (
    "Directory lookup from binlist.net. This is not a verification by the issuing bank."
)
ONLINE_SOURCE = "binlist.net"

# How long a saved online answer is reused before the BIN is checked again.
FOUND_TTL = timedelta(days=180)
NOT_FOUND_TTL = timedelta(days=7)


@dataclass
class BinResult:
    queried_digits: str
    looked_up_at: str
    bank_name: str | None = None
    bank_city: str | None = None
    bank_phone: str | None = None
    bank_url: str | None = None
    country: str | None = None
    scheme: str | None = None
    brand: str | None = None
    card_kind: str | None = None
    prepaid: bool | None = None
    error: str | None = None
    source_note: str = SOURCE_NOTE
    source: str | None = None
    from_cache: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BinResult":
        known = {field: data.get(field) for field in cls.__dataclass_fields__}
        if not known.get("source_note"):
            known["source_note"] = SOURCE_NOTE
        known["from_cache"] = bool(known.get("from_cache"))
        return cls(**known)

    def source_text(self) -> str:
        return self.source or ONLINE_SOURCE


_COUNTRY_NAMES = {
    "United States of America": "United States",
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
    "Russian Federation": "Russia",
    "Korea, Republic of": "South Korea",
    "Korea (the Republic of)": "South Korea",
    "Viet Nam": "Vietnam",
    "Iran, Islamic Republic of": "Iran",
    "Taiwan, Province of China": "Taiwan",
}


def clean_country(name: str | None) -> str | None:
    """Everyday country name: drops ISO-style suffixes such as "(the)"."""
    if not name:
        return name
    text = " ".join(str(name).split())
    for suffix in (" (the)", " (The)", ", the"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return _COUNTRY_NAMES.get(text, text)


def cache_expired(result: BinResult, now: datetime | None = None) -> bool:
    """Not-found answers are rechecked after a week, found answers after six months."""
    try:
        stamp = datetime.fromisoformat(result.looked_up_at)
    except (TypeError, ValueError):
        return True
    age = (now or datetime.now()) - stamp
    limit = NOT_FOUND_TTL if result.error else FOUND_TTL
    return age > limit


def _from_cache(item: dict | None, now: datetime | None = None) -> BinResult | None:
    if not item:
        return None
    result = BinResult.from_dict(item)
    if cache_expired(result, now):
        return None
    result.from_cache = True
    return result


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def get(self, key: str, now: datetime | None = None) -> BinResult | None:
        return _from_cache(self.data.get(key), now)

    def put(self, key: str, result: BinResult) -> None:
        stored = result.to_dict()
        stored["from_cache"] = False
        self.data[key] = stored


class DiskCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_cache_path()
        self.data: dict[str, dict] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = {str(key): value for key, value in loaded.items() if isinstance(value, dict)}
            except (OSError, json.JSONDecodeError):
                self.data = {}

    def get(self, key: str, now: datetime | None = None) -> BinResult | None:
        return _from_cache(self.data.get(key), now)

    def put(self, key: str, result: BinResult) -> None:
        stored = result.to_dict()
        stored["from_cache"] = False
        self.data[key] = stored
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def default_cache_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home()
    return base / "CardStripeExaminer" / "bin_cache.json"


def bin_candidates(account: str | None) -> list[str]:
    digits = "".join(character for character in (account or "") if character.isdigit())
    found: list[str] = []
    if len(digits) >= 8:
        found.append(digits[:8])
    if len(digits) >= 6:
        short = digits[:6]
        if short not in found:
            found.append(short)
    return found


def prompt_digits(account: str | None) -> str | None:
    found = bin_candidates(account)
    return found[0] if found else None


def build_request(bin_code: str, token: str | None = None) -> tuple[str, dict[str, str]]:
    if not re.fullmatch(r"\d{6}|\d{8}", bin_code or ""):
        raise ValueError("Refusing to send anything other than a 6- or 8-digit BIN")
    url = f"https://{HOST}/{bin_code}"
    headers = {
        "Accept-Version": "3",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"token {token}"
    return url, headers


def fetch_bin(bin_code: str, token: str | None = None, opener=None) -> tuple[int, dict | None]:
    """Perform the lookup. `bin_code` is the only card-related value this function accepts."""
    url, headers = build_request(bin_code, token)
    request = urllib.request.Request(url, headers=headers, method="GET")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=12) as response:
            status = int(getattr(response, "status", 200))
            body = response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    if not body:
        return status, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return status, None
    return status, payload if isinstance(payload, dict) else None


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _title(value) -> str | None:
    text = _text(value)
    return text.title() if text else None


def result_from_payload(queried_digits: str, payload: dict) -> BinResult:
    bank = payload.get("bank") if isinstance(payload.get("bank"), dict) else {}
    country = payload.get("country") if isinstance(payload.get("country"), dict) else {}
    prepaid = payload.get("prepaid")
    return BinResult(
        queried_digits=queried_digits,
        looked_up_at=datetime.now().isoformat(timespec="seconds"),
        bank_name=_text(bank.get("name")),
        bank_city=_text(bank.get("city")),
        bank_phone=_text(bank.get("phone")),
        bank_url=_text(bank.get("url")),
        country=_text(country.get("name")),
        scheme=_title(payload.get("scheme")),
        brand=_text(payload.get("brand")),
        card_kind=_title(payload.get("type")),
        prepaid=prepaid if isinstance(prepaid, bool) else None,
        source=ONLINE_SOURCE,
    )


def _stamp(digits: str, error: str) -> BinResult:
    return BinResult(
        queried_digits=digits,
        looked_up_at=datetime.now().isoformat(timespec="seconds"),
        error=error,
        source=ONLINE_SOURCE,
    )


def lookup_account(account: str, token: str | None = None, opener=None, cache=None) -> BinResult:
    """Look up an issuing bank. Only 6- or 8-digit prefixes from `account` are transmitted."""
    candidates = bin_candidates(account)
    if not candidates:
        return _stamp("", "No BIN could be read from this account number.")
    primary = candidates[0]
    if cache is not None:
        cached = cache.get(primary)
        if cached is not None:
            return cached
    for code in candidates:
        try:
            status, payload = fetch_bin(code, token=token, opener=opener)
        except urllib.error.URLError:
            return _stamp(code, "The lookup did not complete. Check the network connection.")
        if status == 200 and payload:
            result = result_from_payload(code, payload)
            if cache is not None:
                cache.put(primary, result)
                cache.put(code, result)
            return result
        if status == 404:
            continue
        if status == 429:
            return _stamp(code, "The lookup service is limiting requests. Try again later.")
        return _stamp(code, "The lookup did not complete. Check the network connection.")
    missing = _stamp(candidates[-1], "No issuing bank is listed for this BIN.")
    if cache is not None:
        cache.put(primary, missing)
    return missing
