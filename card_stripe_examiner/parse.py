"""Split and interpret ISO magnetic-stripe tracks. Read only."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

INTERCHANGE = {
    "1": "International interchange OK",
    "2": "International interchange, integrated circuit where feasible",
    "5": "National interchange only",
    "6": "National interchange, integrated circuit where feasible",
    "7": "Private interchange, no general interchange except by agreement",
    "9": "Test",
}

AUTHORIZATION = {
    "0": "Normal authorization",
    "2": "Contact issuer by online means",
    "4": "Contact issuer by online means, except under a bilateral agreement",
}

PARSER_VERSION = 2

# Account lengths each network issues. Used only to flag an unusual length.
NETWORK_LENGTHS = {
    "Visa": {13, 16, 19},
    "Mastercard": {16},
    "American Express": {15},
    "Discover": {16, 17, 18, 19},
    "Diners Club": {14, 15, 16, 17, 18, 19},
    "JCB": {16, 17, 18, 19},
    "UnionPay": {16, 17, 18, 19},
    "Maestro": {12, 13, 14, 15, 16, 17, 18, 19},
    "Mir": {16, 17, 18, 19},
    "RuPay": {16},
    "Verve": {16, 18, 19},
}

SERVICES = {
    "0": "No restrictions, PIN required",
    "1": "No restrictions",
    "2": "Goods and services only",
    "3": "ATM only, PIN required",
    "4": "Cash only",
    "5": "Goods and services only, PIN required",
    "6": "No restrictions, PIN required where feasible",
    "7": "Goods and services only, PIN required where feasible",
}


@dataclass
class TrackParse:
    raw: str | None = None
    present: bool = False
    recognized: bool = False
    format_code: str | None = None
    pan: str | None = None
    name: str | None = None
    expiration: str | None = None
    service_code: str | None = None
    discretionary: str | None = None
    country: str | None = None
    currency: str | None = None
    additional: str | None = None
    unrecognized_reason: str | None = None
    read_error: bool = False
    luhn: str | None = None


@dataclass
class Comparison:
    pan: str = "Not comparable"
    expiration: str = "Not comparable"
    service_code: str = "Not comparable"
    track3_account: str = "Not comparable"
    tracks_differ: bool = False
    findings: list[str] = field(default_factory=list)


@dataclass
class ParsedCard:
    card_type: str
    brand: str
    pan: str | None
    name: str | None
    name_on_stripe: str | None
    expiration: str | None
    expiration_display: str | None
    expired: bool | None
    service_code: str | None
    service_lines: list[str]
    discretionary: str | None
    discretionary_source: str | None
    luhn: str
    tracks_present: list[str]
    track1: TrackParse
    track2: TrackParse
    track3: TrackParse
    comparison: Comparison
    tracks_read_error: list[str] = field(default_factory=list)
    length_ok: bool | None = None
    parser_version: int = 2


def luhn_ok(number: str) -> bool:
    digits = [int(character) for character in number if character.isdigit()]
    if len(digits) < 12 or any(not character.isdigit() for character in number):
        return False
    total = 0
    double = False
    for digit in reversed(digits):
        if double:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double = not double
    return total % 10 == 0


def luhn_status(pan: str | None) -> str:
    if not pan or not pan.isdigit() or len(pan) < 12:
        return "Not applicable"
    return "Pass" if luhn_ok(pan) else "Fail"


def luhn_label(status: str) -> str:
    return {
        "Pass": "Luhn pass",
        "Fail": "Luhn fail",
        "Not applicable": "Luhn not applicable",
    }.get(status, status)


def brand_from_pan(pan: str | None) -> str:
    """Network by prefix. A prefix suggests a network; it does not prove one."""
    if not pan or not pan.isdigit():
        return "Unknown"

    def starts(*prefixes: str) -> bool:
        return any(pan.startswith(prefix) for prefix in prefixes)

    def between(width: int, low: int, high: int) -> bool:
        return len(pan) >= width and low <= int(pan[:width]) <= high

    if between(6, 506099, 506198) or between(6, 507865, 507964) or between(6, 650002, 650027):
        return "Verve"
    if (
        between(6, 508500, 508999)
        or between(6, 606985, 607984)
        or between(6, 608001, 608500)
        or between(6, 652150, 653149)
    ):
        return "RuPay"
    if between(4, 2200, 2204):
        return "Mir"
    if starts("4"):
        return "Visa"
    if between(4, 2221, 2720) or between(2, 51, 55):
        return "Mastercard"
    if starts("34", "37"):
        return "American Express"
    if between(4, 3528, 3589):
        return "JCB"
    if starts("6011", "65") or between(3, 644, 649):
        return "Discover"
    if starts("36", "38", "39", "3095") or between(3, 300, 305):
        return "Diners Club"
    if starts("62"):
        return "UnionPay"
    if starts("50", "56", "57", "58", "6304", "639", "67"):
        return "Maestro"
    return "Unknown"


def pan_length_ok(brand: str, pan: str | None) -> bool | None:
    """True or False when the network's lengths are known, None otherwise."""
    lengths = NETWORK_LENGTHS.get(brand)
    if not lengths or not pan or not pan.isdigit():
        return None
    return len(pan) in lengths


def list_brand(parsed: ParsedCard) -> str:
    if parsed.card_type == "Non-standard / proprietary" and parsed.brand == "Unknown":
        return "Proprietary"
    if parsed.brand == "Unknown":
        return "Not recognized"
    return parsed.brand


def explain_service(code: str | None) -> list[str]:
    if not code or not re.fullmatch(r"\d{3}", code):
        return []
    return [
        f"Interchange: {INTERCHANGE.get(code[0], 'Not a standard value')}",
        f"Authorization: {AUTHORIZATION.get(code[1], 'Not a standard value')}",
        f"Services: {SERVICES.get(code[2], 'Not a standard value')}",
    ]


def plausible_yymm(value: str) -> bool:
    if not re.fullmatch(r"\d{4}", value or ""):
        return False
    month = int(value[2:])
    return 1 <= month <= 12


def expiration_display(yymm: str | None) -> str | None:
    if not yymm or not plausible_yymm(yymm):
        return None
    return f"{yymm[2:]}/20{yymm[:2]}"


def is_expired(yymm: str | None, today: date | None = None) -> bool | None:
    if not yymm or not plausible_yymm(yymm):
        return None
    today = today or date.today()
    year = 2000 + int(yymm[:2])
    month = int(yymm[2:])
    return today.year > year or (today.year == year and today.month > month)


def format_pan(pan: str | None) -> str:
    if not pan:
        return ""
    if len(pan) == 15 and pan[:2] in {"34", "37"}:
        return f"{pan[:4]} {pan[4:10]} {pan[10:]}"
    return " ".join(pan[index : index + 4] for index in range(0, len(pan), 4))


def last_four(pan: str | None) -> str:
    if not pan or len(pan) < 4:
        return "————"
    return pan[-4:]


def readable_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = " ".join(name.split())
    if "/" not in cleaned:
        return cleaned or None
    last, _, first = cleaned.partition("/")
    first = " ".join(first.replace(".", " ").split())
    last = " ".join(last.split())
    readable = " ".join(part for part in (first, last) if part)
    return readable or cleaned


def split_tracks(raw: str) -> dict[str, str | None]:
    """Pull each track out of a keyboard-wedge string, sentinels included."""
    source = raw or ""

    def grab(start: str, others: str) -> str | None:
        index = source.find(start)
        if index < 0:
            return None
        end = len(source)
        question = source.find("?", index + 1)
        if question >= 0:
            end = min(end, question + 1)
        for other in others:
            found = source.find(other, index + 1)
            if found >= 0:
                end = min(end, found)
        text = source[index:end]
        return text or None

    return {
        "track1": grab("%", ";+"),
        "track2": grab(";", "+"),
        "track3": grab("+", ""),
    }


def _strip(raw: str, start: str) -> str:
    text = raw.strip()
    if text.startswith(start):
        text = text[1:]
    if text.endswith("?"):
        text = text[:-1]
    return text


def _empty(raw: str | None) -> TrackParse:
    return TrackParse(raw=raw, present=bool(raw))


def is_read_error(data: str) -> bool:
    """A wedge reader sends E (for example %E? or ;E?) when it cannot read a track."""
    return bool(re.fullmatch(r"E+", (data or "").strip()))


def _mark_read_error(track: TrackParse, number: int) -> TrackParse:
    track.read_error = True
    track.unrecognized_reason = f"Track {number} read error. Swipe the card again."
    return track


def parse_track1(raw: str | None) -> TrackParse:
    track = _empty(raw)
    if not raw:
        return track
    data = _strip(raw, "%")
    if is_read_error(data):
        return _mark_read_error(track, 1)
    if not data.startswith("B"):
        run = re.search(r"\d{12,19}", data)
        track.pan = run.group(0) if run else None
        track.unrecognized_reason = "Track 1 is not format B."
        track.additional = data or None
        return track
    parts = data[1:].split("^")
    pan = parts[0] if parts else ""
    if not re.fullmatch(r"\d{12,19}", pan):
        run = re.search(r"\d{12,19}", data)
        track.pan = run.group(0) if run else None
        track.format_code = "B"
        track.unrecognized_reason = "Track 1 format B has no standard account number."
        track.additional = data or None
        return track
    track.format_code = "B"
    track.pan = pan
    track.name = parts[1] if len(parts) > 1 else None
    rest = parts[2] if len(parts) > 2 else ""
    _apply_expiry_block(track, rest, "Track 1 has no standard expiration.")
    return track


def parse_track2(raw: str | None) -> TrackParse:
    track = _empty(raw)
    if not raw:
        return track
    data = _strip(raw, ";")
    if is_read_error(data):
        return _mark_read_error(track, 2)
    match = re.fullmatch(r"(\d{12,19})([=D])(.*)", data)
    if not match:
        run = re.search(r"\d{12,19}", data)
        track.pan = run.group(0) if run else None
        track.unrecognized_reason = "Track 2 does not match the ABA layout."
        track.additional = data or None
        return track
    track.pan = match.group(1)
    _apply_expiry_block(track, match.group(3), "Track 2 has no standard expiration.")
    return track


def _apply_expiry_block(track: TrackParse, rest: str, invalid_message: str) -> None:
    if len(rest) >= 4 and plausible_yymm(rest[:4]):
        track.expiration = rest[:4]
        if len(rest) >= 7 and rest[4:7].isdigit():
            track.service_code = rest[4:7]
            track.discretionary = rest[7:] or None
            track.recognized = True
            return
        track.additional = rest[4:] or None
        track.unrecognized_reason = "Service code was not present."
        return
    track.additional = rest or None
    track.unrecognized_reason = invalid_message


def parse_track3(raw: str | None) -> TrackParse:
    track = _empty(raw)
    if not raw:
        return track
    data = _strip(raw, "+")
    if is_read_error(data):
        return _mark_read_error(track, 3)
    match = re.fullmatch(r"(\d{2})(\d{12,19})=(.*)", data)
    if not match:
        track.additional = data or None
        track.unrecognized_reason = "Track 3 does not match the ISO 4909 layout."
        return track
    track.recognized = True
    track.format_code = match.group(1)
    track.pan = match.group(2)
    rest = match.group(3)
    if len(rest) >= 6 and rest[:6].isdigit():
        track.country = rest[:3]
        track.currency = rest[3:6]
        track.additional = rest[6:] or None
    else:
        track.additional = rest or None
    return track


def _compare(left: str | None, right: str | None) -> str:
    if not left or not right:
        return "Not comparable"
    return "Match" if left == right else "Differs"


def _classify(track1: TrackParse, track2: TrackParse) -> str:
    if track1.recognized or track2.recognized:
        return "Bank format"
    structured_pan = (track1.format_code == "B" and track1.pan) or (
        track2.pan and track2.unrecognized_reason
    )
    dated = bool(track1.expiration or track2.expiration)
    if structured_pan and not dated:
        return "Non-standard / proprietary"
    if (track1.pan or track2.pan) and dated:
        return "Partial bank format"
    return "Non-standard / proprietary"


def _findings(
    luhn: str,
    comparison_pan: str,
    comparison_expiration: str,
    comparison_service: str,
    expired: bool | None,
    tracks_present: list[str],
    track3_account: str,
    read_errors: list[str] | None = None,
    brand: str = "Unknown",
    pan: str | None = None,
    length_ok: bool | None = None,
    other_luhn: list[tuple[str, str]] | None = None,
) -> list[str]:
    read_errors = read_errors or []
    items: list[str] = []
    for name in read_errors:
        items.append(f"{name} read error — swipe the card again")
    if luhn == "Pass":
        items.append("Luhn pass")
    elif luhn == "Fail":
        items.append("Luhn fail")
    else:
        items.append("Luhn not applicable")
    for name, status in other_luhn or []:
        items.append(f"{name} account number: {luhn_label(status)}")
    if length_ok is False and pan:
        items.append(f"Account length {len(pan)} is not standard for {brand}")
    sentences = {
        "Match": "match",
        "Differs": "differ",
    }
    if comparison_pan in sentences:
        items.append(f"Track 1 and track 2 account numbers {sentences[comparison_pan]}")
    if comparison_expiration in sentences:
        items.append(f"Track 1 and track 2 expirations {sentences[comparison_expiration]}")
    if comparison_service in sentences:
        items.append(f"Track 1 and track 2 service codes {sentences[comparison_service]}")
    if expired is True:
        items.append("Expiration is in the past")
    if "Track 1" not in tracks_present and "Track 1" not in read_errors:
        items.append("Track 1 was not read")
    if "Track 2" not in tracks_present and "Track 2" not in read_errors:
        items.append("Track 2 was not read")
    if "Track 3" in tracks_present:
        items.append("Track 3 is present")
    if track3_account == "Differs":
        items.append("Track 3 account number differs from the primary account")
    return items


def parse_swipe(raw: str, today: date | None = None) -> ParsedCard:
    tracks = split_tracks(raw or "")
    track1 = parse_track1(tracks["track1"])
    track2 = parse_track2(tracks["track2"])
    track3 = parse_track3(tracks["track3"])
    named = (("Track 1", track1), ("Track 2", track2), ("Track 3", track3))
    present = [name for name, track in named if track.present and not track.read_error]
    read_errors = [name for name, track in named if track.read_error]
    for _name, track in named:
        if track.pan:
            track.luhn = luhn_status(track.pan)
    pan = track2.pan or track1.pan or track3.pan
    if not pan:
        readable = "".join(track.raw or "" for _name, track in named if not track.read_error)
        source = readable if (track1.read_error or track2.read_error or track3.read_error) else (raw or "")
        run = re.search(r"\d{12,19}", source)
        pan = run.group(0) if run else None
    expiration = track2.expiration or track1.expiration
    service = track2.service_code or track1.service_code
    if track2.discretionary:
        discretionary = track2.discretionary
        discretionary_source = "Track 2"
    elif track1.discretionary:
        discretionary = track1.discretionary
        discretionary_source = "Track 1"
    else:
        discretionary = None
        discretionary_source = None
    name_on_stripe = track1.name
    pan_state = _compare(track1.pan, track2.pan)
    expiration_state = _compare(track1.expiration, track2.expiration)
    service_state = _compare(track1.service_code, track2.service_code)
    if track3.pan and pan:
        track3_account = "Match" if track3.pan == pan else "Differs"
    else:
        track3_account = "Not comparable"
    tracks_differ = "Differs" in {pan_state, expiration_state, service_state, track3_account}
    luhn = luhn_status(pan)
    other_luhn = [
        (name, track.luhn)
        for name, track in named
        if track.pan and track.pan != pan and track.luhn
    ]
    brand = brand_from_pan(pan)
    card_type = _classify(track1, track2)
    length_ok = pan_length_ok(brand, pan) if card_type != "Non-standard / proprietary" else None
    expired = is_expired(expiration, today)
    comparison = Comparison(
        pan=pan_state,
        expiration=expiration_state,
        service_code=service_state,
        track3_account=track3_account,
        tracks_differ=tracks_differ,
        findings=_findings(
            luhn,
            pan_state,
            expiration_state,
            service_state,
            expired,
            present,
            track3_account,
            read_errors=read_errors,
            brand=brand,
            pan=pan,
            length_ok=length_ok,
            other_luhn=other_luhn,
        ),
    )
    return ParsedCard(
        card_type=card_type,
        brand=brand,
        pan=pan,
        name=readable_name(name_on_stripe),
        name_on_stripe=name_on_stripe.strip() if name_on_stripe else None,
        expiration=expiration,
        expiration_display=expiration_display(expiration),
        expired=expired,
        service_code=service,
        service_lines=explain_service(service),
        discretionary=discretionary,
        discretionary_source=discretionary_source,
        luhn=luhn,
        tracks_present=present,
        track1=track1,
        track2=track2,
        track3=track3,
        comparison=comparison,
        tracks_read_error=read_errors,
        length_ok=length_ok,
        parser_version=PARSER_VERSION,
    )


def all_tracks_failed(parsed: ParsedCard) -> bool:
    return bool(parsed.tracks_read_error) and not parsed.tracks_present


def _expiry_text(yymm: str | None, expired: bool | None = None) -> str:
    shown = expiration_display(yymm) or "—"
    flag = expired if expired is not None else is_expired(yymm)
    if flag:
        return f"{shown}  ·  Expired"
    return shown


def account_fields(parsed: ParsedCard) -> list[tuple[str, str, bool]]:
    rows: list[tuple[str, str, bool]] = []
    track1 = parsed.track1.pan
    track2 = parsed.track2.pan
    if track1 and track2 and track1 != track2:
        rows.append(("Account (track 1)", format_pan(track1), True))
        rows.append(("Account (track 2)", format_pan(track2), True))
    else:
        rows.append(("Account", format_pan(parsed.pan) or "—", True))
    rows.append(("Name", parsed.name or "—", False))
    if parsed.name_on_stripe and parsed.name_on_stripe != parsed.name:
        rows.append(("Name on stripe", parsed.name_on_stripe, False))
    expiry_1 = parsed.track1.expiration
    expiry_2 = parsed.track2.expiration
    if expiry_1 and expiry_2 and expiry_1 != expiry_2:
        rows.append(("Expiration (track 1)", _expiry_text(expiry_1), True))
        rows.append(("Expiration (track 2)", _expiry_text(expiry_2), True))
    else:
        rows.append(("Expiration", _expiry_text(parsed.expiration, parsed.expired), True))
    return rows


def stripe_fields(parsed: ParsedCard) -> list[tuple[str, str, bool]]:
    rows: list[tuple[str, str, bool]] = []
    code_1 = parsed.track1.service_code
    code_2 = parsed.track2.service_code
    if code_1 and code_2 and code_1 != code_2:
        rows.append(("Service code (track 1)", code_1, True))
        rows.append(("Service code (track 2)", code_2, True))
    else:
        rows.append(("Service code", parsed.service_code or "—", True))
    if parsed.service_lines:
        rows.append(("Service code meaning", "\n".join(parsed.service_lines), False))
    rows.append(("Tracks present", ", ".join(parsed.tracks_present) or "None", False))
    if parsed.tracks_read_error:
        rows.append(("Read errors", ", ".join(parsed.tracks_read_error) + " — swipe again", False))
    source = f" ({parsed.discretionary_source}, issuer-defined)" if parsed.discretionary_source else ""
    rows.append((f"Discretionary data{source}", parsed.discretionary or "—", True))
    return rows


def parsed_to_dict(parsed: ParsedCard) -> dict:
    return asdict(parsed)


def _known(cls, data: dict) -> dict:
    return {key: value for key, value in data.items() if key in cls.__dataclass_fields__}


def parsed_from_dict(data: dict) -> ParsedCard:
    payload = _known(ParsedCard, dict(data))
    payload.setdefault("parser_version", 1)
    payload["track1"] = TrackParse(**_known(TrackParse, payload["track1"]))
    payload["track2"] = TrackParse(**_known(TrackParse, payload["track2"]))
    payload["track3"] = TrackParse(**_known(TrackParse, payload["track3"]))
    payload["comparison"] = Comparison(**_known(Comparison, payload["comparison"]))
    return ParsedCard(**payload)
