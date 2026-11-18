"""Case sessions. Saved locally as JSON. Nothing is uploaded."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from card_stripe_examiner.parse import PARSER_VERSION, parse_swipe, parsed_from_dict, parsed_to_dict

SCHEMA = 1

PRINTED_FIELDS = ("account", "name", "expiration")
PRINTED_NAMES = {"account": "Account number", "name": "Name", "expiration": "Expiration"}
PRINTED_FINDINGS = {
    "account": "Printed account number differs from the stripe",
    "name": "Printed name differs from the stripe",
    "expiration": "Printed expiration differs from the stripe",
}
# Result of comparing one typed field with the stripe.
PRINTED_STATES = {
    "match": "Matches the stripe",
    "differs": "Differs from the stripe",
    "blank": "Not entered",
    "no_stripe": "Not on the stripe",
    "unreadable": "Enter the date as MM/YY",
}
_TITLES = {"MR", "MRS", "MS", "MISS", "DR"}


FACE_TYPES = {
    "unknown": "Not recorded",
    "bank": "Bank card (credit or debit)",
    "gift": "Gift card",
    "hotel": "Hotel key or access card",
    "id": "ID or membership card",
    "blank": "Blank or white plastic",
    "other": "Other",
}
FACE_WORDS = {
    "gift": "a gift card",
    "hotel": "a hotel key or access card",
    "id": "an ID or membership card",
    "blank": "blank or white plastic",
    "other": "a non-bank card",
}
BANK_STRIPES = {"Bank format", "Partial bank format"}
PHOTO_SIDES = {"front": "Front", "back": "Back"}
PHOTO_TYPES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")


def normalize_face(value) -> str:
    text = str(value or "unknown").lower()
    return text if text in FACE_TYPES else "unknown"


def empty_printed() -> dict:
    return {
        "matches": False,
        "account_text": "",
        "name_text": "",
        "expiration_text": "",
        "earlier_differs": [],
    }


def normalize_printed(payload) -> dict:
    """Current printed-card record. Records saved by version 1.1 or earlier, which marked each field
    separately, are converted: three matches become the tick box, and a field marked as different
    with nothing typed is kept as an earlier mark so the finding is not lost."""
    data = empty_printed()
    if not isinstance(payload, dict):
        return data
    for name in PRINTED_FIELDS:
        data[f"{name}_text"] = str(payload.get(f"{name}_text") or "")
    if "matches" in payload:
        data["matches"] = bool(payload.get("matches"))
        earlier = payload.get("earlier_differs") or []
        data["earlier_differs"] = [name for name in PRINTED_FIELDS if name in earlier]
        return data
    marks = {name: str(payload.get(name) or "unknown").lower() for name in PRINTED_FIELDS}
    if all(mark == "match" for mark in marks.values()):
        data["matches"] = True
        return data
    for name, mark in marks.items():
        if mark == "match":
            data[f"{name}_text"] = ""
        elif mark == "differs" and not data[f"{name}_text"].strip():
            data["earlier_differs"].append(name)
    return data


def _account_digits(text: str) -> str:
    return "".join(character for character in text if character.isdigit())


def _name_tokens(text: str, drop_initials: bool = False) -> set[str]:
    words = "".join(character if character.isalpha() else " " for character in text.upper()).split()
    tokens = {word for word in words if word not in _TITLES}
    if drop_initials:
        tokens = {word for word in tokens if len(word) > 1}
    return tokens


def printed_expiry_yymm(text: str) -> str | None:
    """Read a printed expiration such as 12/28, 12/2028, 1228 or 2028-12 as YYMM."""
    parts = [part for part in "".join(c if c.isdigit() else " " for c in text).split() if part]
    month = year = None
    if len(parts) == 1:
        run = parts[0]
        if len(run) == 4:
            month, year = run[:2], run[2:]
        elif len(run) == 6:
            month, year = run[:2], run[2:]
    elif len(parts) == 2:
        first, second = parts
        if len(first) == 4:
            year, month = first, second
        else:
            month, year = first, second
    if month is None or year is None or not (1 <= len(month) <= 2) or len(year) not in (2, 4):
        return None
    if not 1 <= int(month) <= 12:
        return None
    return f"{year[-2:]}{int(month):02d}"


def compare_printed_field(parsed, name: str, text: str) -> str:
    """One of the PRINTED_STATES keys for a typed value against the parsed stripe."""
    typed = (text or "").strip()
    if not typed:
        return "blank"
    if name == "account":
        stripe = {pan for pan in (parsed.pan, parsed.track1.pan, parsed.track2.pan, parsed.track3.pan) if pan}
        if not stripe:
            return "no_stripe"
        return "match" if _account_digits(typed) in stripe else "differs"
    if name == "expiration":
        stripe = {value for value in (parsed.expiration, parsed.track1.expiration, parsed.track2.expiration) if value}
        if not stripe:
            return "no_stripe"
        yymm = printed_expiry_yymm(typed)
        if yymm is None:
            return "unreadable"
        return "match" if yymm in stripe else "differs"
    stripe_name = parsed.name_on_stripe
    if not stripe_name:
        return "no_stripe"
    if _name_tokens(typed) == _name_tokens(stripe_name):
        return "match"
    short_typed = _name_tokens(typed, drop_initials=True)
    if short_typed and short_typed == _name_tokens(stripe_name, drop_initials=True):
        return "match"
    return "differs"


def printed_states(card: "CardRecord") -> dict[str, str]:
    data = normalize_printed(card.printed)
    parsed = card.view()
    states = {}
    for name in PRINTED_FIELDS:
        if data["matches"]:
            states[name] = "match"
        else:
            states[name] = compare_printed_field(parsed, name, data[f"{name}_text"])
            if states[name] == "blank" and name in data["earlier_differs"]:
                states[name] = "differs"
    return states


def printed_differs(card: "CardRecord") -> bool:
    return any(state == "differs" for state in printed_states(card).values())


def printed_findings(card: "CardRecord") -> list[str]:
    data = normalize_printed(card.printed)
    states = printed_states(card)
    items = []
    for name in PRINTED_FIELDS:
        if states[name] != "differs":
            continue
        finding = PRINTED_FINDINGS[name]
        if not data["matches"] and not data[f"{name}_text"].strip() and name in data["earlier_differs"]:
            finding += " (marked in an earlier version)"
        items.append(finding)
    return items


def printed_summary(card: "CardRecord", mask_account=None) -> list[tuple[str, str]]:
    """(label, text) rows describing the printed card, for reports and exports."""
    data = normalize_printed(card.printed)
    if data["matches"]:
        return [("Printed card", "Account number, name and expiration match the stripe")]
    states = printed_states(card)
    rows = []
    for name in PRINTED_FIELDS:
        typed = data[f"{name}_text"].strip()
        state = states[name]
        if state == "differs" and not typed and name in data["earlier_differs"]:
            rows.append((PRINTED_NAMES[name], "Differs from the stripe (marked in an earlier version)"))
            continue
        if not typed:
            rows.append((PRINTED_NAMES[name], "Not entered"))
            continue
        shown = mask_account(typed) if (mask_account and name == "account") else typed
        rows.append((PRINTED_NAMES[name], f"{shown}  ·  {PRINTED_STATES[state]}"))
    return rows


def face_findings(card: "CardRecord") -> list[str]:
    face = normalize_face(card.face_type)
    stripe = card.view().card_type
    if face in FACE_WORDS and stripe in BANK_STRIPES:
        return [f"Bank-format stripe on a card printed as {FACE_WORDS[face]}"]
    if face == "bank" and stripe not in BANK_STRIPES:
        return ["Card printed as a bank card does not carry a bank-format stripe"]
    return []


def card_label(session: "CaseSession | None", card: "CardRecord") -> str:
    if card.exhibit.strip():
        return card.exhibit.strip()
    if session is not None:
        for index, other in enumerate(session.cards, start=1):
            if other.id == card.id:
                return f"Card {index}"
    return "Card"


def card_accounts(card: "CardRecord") -> set[str]:
    parsed = card.view()
    found = {parsed.pan} if parsed.pan else set()
    for track in (parsed.track1, parsed.track2, parsed.track3):
        if track.pan:
            found.add(track.pan)
    return found


def duplicates_for(session: "CaseSession | None", card: "CardRecord") -> list[str]:
    """Findings that tie this card to other cards in the case by account number or identical swipe."""
    if session is None:
        return []
    mine = card_accounts(card)
    same_swipe: list[str] = []
    same_account: list[str] = []
    for other in session.cards:
        if other.id == card.id:
            continue
        if other.raw == card.raw:
            same_swipe.append(card_label(session, other))
        elif mine and mine & card_accounts(other):
            same_account.append(card_label(session, other))
    items = []
    if same_swipe:
        items.append(
            "Identical stripe data to " + ", ".join(same_swipe) + " (the same card may have been swiped twice)"
        )
    if same_account:
        items.append("Account number also on " + ", ".join(same_account))
    return items


def has_duplicates(session: "CaseSession | None", card: "CardRecord") -> bool:
    return bool(duplicates_for(session, card))


def card_findings(card: "CardRecord", session: "CaseSession | None" = None) -> list[str]:
    items = list(card.view().comparison.findings)
    items.extend(printed_findings(card))
    items.extend(face_findings(card))
    items.extend(duplicates_for(session, card))
    return items


@dataclass
class CardRecord:
    id: str
    swiped_at: str
    raw: str
    note: str = ""
    parsed: dict = field(default_factory=dict)
    bin_lookup: dict | None = None
    printed: dict = field(default_factory=empty_printed)
    exhibit: str = ""
    face_type: str = "unknown"
    photos: list[dict] = field(default_factory=list)

    def view(self):
        return parsed_from_dict(self.parsed)


@dataclass
class CaseSession:
    case_number: str
    examiner: str = ""
    unit: str = ""
    notes: str = ""
    started_at: str = ""
    cards: list[CardRecord] = field(default_factory=list)
    path: str | None = None
    # Photo files to delete from the case folder at the next save (absolute paths). Not saved.
    pending_deletions: list[str] = field(default_factory=list)
    exhibit_prefix: str = ""
    next_exhibit: int = 1
    first_exhibit: int = 1

    def next_exhibit_label(self) -> str:
        return f"{self.exhibit_prefix}{self.next_exhibit}"

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "case_number": self.case_number,
            "examiner": self.examiner,
            "unit": self.unit,
            "notes": self.notes,
            "started_at": self.started_at,
            "exhibit_prefix": self.exhibit_prefix,
            "first_exhibit": self.first_exhibit,
            "next_exhibit": self.next_exhibit,
            "cards": [
                {
                    "id": card.id,
                    "swiped_at": card.swiped_at,
                    "raw": card.raw,
                    "note": card.note,
                    "parsed": card.parsed,
                    "bin_lookup": card.bin_lookup,
                    "printed": normalize_printed(card.printed),
                    "exhibit": card.exhibit,
                    "face_type": normalize_face(card.face_type),
                    "photos": list(card.photos),
                }
                for card in self.cards
            ],
        }


def new_session(
    case_number: str,
    examiner: str = "",
    unit: str = "",
    notes: str = "",
    started_at: datetime | None = None,
    exhibit_prefix: str = "",
    first_exhibit: int = 1,
) -> CaseSession:
    number = case_number.strip()
    if not number:
        raise ValueError("Enter a case number.")
    moment = started_at or datetime.now()
    return CaseSession(
        case_number=number,
        examiner=examiner.strip(),
        unit=unit.strip(),
        notes=notes.strip(),
        started_at=moment.isoformat(timespec="seconds"),
        exhibit_prefix=exhibit_prefix,
        next_exhibit=max(0, int(first_exhibit)),
        first_exhibit=max(0, int(first_exhibit)),
    )


def add_card(session: CaseSession, raw: str, when: datetime | None = None) -> CardRecord:
    text = (raw or "").strip()
    if not text:
        raise ValueError("The swipe was empty.")
    moment = when or datetime.now()
    card = CardRecord(
        id=uuid.uuid4().hex,
        swiped_at=moment.isoformat(timespec="seconds"),
        raw=text,
        parsed=parsed_to_dict(parse_swipe(text)),
        exhibit=session.next_exhibit_label(),
    )
    session.next_exhibit += 1
    session.cards.append(card)
    return card


def automatic_exhibit_number(session: CaseSession, label: str) -> int | None:
    """The number in an exhibit label that still has the automatic form (prefix and number).
    None for a label the examiner typed in some other form, such as "Item 7A"."""
    prefix = session.exhibit_prefix.strip()
    pattern = (re.escape(prefix) + r"\s*(\d+)") if prefix else r"(\d+)"
    match = re.fullmatch(pattern, (label or "").strip())
    return int(match.group(1)) if match else None


def renumber_exhibits(session: CaseSession) -> list[tuple[str, str]]:
    """Number the automatic exhibit labels in swipe order with no gaps, starting at the case's first
    exhibit number. Labels the examiner typed in another form are left as they are.
    Returns the (old, new) labels that changed."""
    changes: list[tuple[str, str]] = []
    number = session.first_exhibit
    for card in session.cards:
        if automatic_exhibit_number(session, card.exhibit) is None:
            continue
        label = f"{session.exhibit_prefix}{number}"
        if card.exhibit != label:
            changes.append((card.exhibit, label))
            card.exhibit = label
        number += 1
    session.next_exhibit = number
    return changes


def remove_card_and_renumber(session: CaseSession, card_id: str) -> tuple[int, list[tuple[str, str]]]:
    """Remove a card and close the gap in the exhibit numbers. Returns its position (-1 if not found)
    and the exhibit labels that changed."""
    for index, card in enumerate(session.cards):
        if card.id == card_id:
            for photo in card.photos:
                _queue_photo_deletion(session, photo)
            del session.cards[index]
            return index, renumber_exhibits(session)
    return -1, []


def remove_card(session: CaseSession, card_id: str) -> int:
    return remove_card_and_renumber(session, card_id)[0]


def cards_for_report(session: CaseSession, differs_only: bool = False) -> list[CardRecord]:
    if not differs_only:
        return list(session.cards)
    return [card for card in session.cards if printed_differs(card)]


PHOTO_FOLDER = "Photos"


def photo_folder_name(_session_path: str | Path | None = None) -> str:
    """New photos go in a Photos folder beside the case file. Photos saved by earlier versions keep the
    folder recorded with each photo, so older cases still find them."""
    return PHOTO_FOLDER


def case_store(root: str | Path | None = None) -> Path:
    """Where cases are saved: %LOCALAPPDATA%\\CardStripeExaminer\\Cases, one folder per case number."""
    if root is not None:
        return Path(root)
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home()) / "CardStripeExaminer" / "Cases"


def case_folder_name(case_number: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", case_number).strip(" .")
    return cleaned or "case"


def store_path(case_number: str, root: str | Path | None = None, copy: int = 1) -> Path:
    """The case file's path in the store. copy 2, 3, ... gives "<case> (2)" and so on."""
    name = case_folder_name(case_number)
    if copy > 1:
        name = f"{name} ({copy})"
    return case_store(root) / name / f"{name}.json"


def in_store(path: str | Path | None, root: str | Path | None = None) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(case_store(root).resolve())
        return True
    except ValueError:
        return False


def _queue_photo_deletion(session: CaseSession, photo: dict) -> None:
    path = photo_path(session, photo)
    if path is not None:
        session.pending_deletions.append(str(path))


def _delete_pending(session: CaseSession, case_folder: Path) -> list[str]:
    """Delete queued photo files that are inside this case's folder and no longer used by any card."""
    in_use = {
        str(Path(session.path).parent / photo["file"]) if session.path else ""
        for card in session.cards
        for photo in card.photos
        if photo.get("file")
    }
    in_use = {str(Path(item).resolve()) for item in in_use if item}
    deleted = []
    folder = case_folder.resolve()
    for item in session.pending_deletions:
        target = Path(item)
        try:
            resolved = target.resolve()
            resolved.relative_to(folder)
        except (OSError, ValueError):
            continue
        if str(resolved) in in_use or not target.exists():
            continue
        try:
            target.unlink()
            deleted.append(str(target))
        except OSError:
            continue
    session.pending_deletions.clear()
    return deleted


def photo_path(session: CaseSession, photo: dict) -> Path | None:
    if not session.path or not photo.get("file"):
        return None
    return Path(session.path).parent / photo["file"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def add_photo(
    session: CaseSession,
    card: CardRecord,
    source: str | Path,
    side: str,
    origin: str = "file",
    original_name: str | None = None,
) -> dict:
    """Copy a photo into the case's photo folder beside the saved case file.

    origin is "file" for an imported photo or "camera" for one captured in the program."""
    if not session.path:
        raise ValueError("Save the case before adding photos. Photos are kept in a folder beside the case file.")
    if side not in PHOTO_SIDES:
        raise ValueError("Choose the front or the back of the card.")
    original = Path(source)
    if original.suffix.lower() not in PHOTO_TYPES:
        raise ValueError("Choose a photo file (JPG, PNG, BMP, GIF, TIFF or WebP).")
    folder_name = photo_folder_name(session.path)
    folder = Path(session.path).parent / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", card_label(session, card)).strip("-.") or card.id[:8]
    number = 1
    while True:
        name = f"{label}-{side}-{number}{original.suffix.lower()}"
        if not (folder / name).exists():
            break
        number += 1
    destination = folder / name
    shutil.copy2(original, destination)
    photo = {
        "side": side,
        "file": f"{folder_name}/{name}",
        "original_name": original_name or original.name,
        "origin": "camera" if origin == "camera" else "file",
        "sha256": _sha256(destination),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    card.photos.append(photo)
    return photo


def remove_photo(card: CardRecord, file: str, session: CaseSession | None = None) -> bool:
    """Take a photo off the card. With the session given, the case's copy of the photo is deleted
    from the case folder at the next save."""
    for index, photo in enumerate(card.photos):
        if photo.get("file") == file:
            if session is not None:
                _queue_photo_deletion(session, photo)
            del card.photos[index]
            return True
    return False


def _carry_photos(session: CaseSession, destination: Path) -> None:
    """When a case is saved somewhere new, copy its photos to a folder beside the new file."""
    if not session.path:
        return
    old = Path(session.path)
    if old.resolve() == destination.resolve():
        return
    new_folder_name = photo_folder_name(destination)
    for card in session.cards:
        for photo in card.photos:
            source = old.parent / photo.get("file", "")
            if not photo.get("file") or not source.exists():
                continue
            target = destination.parent / new_folder_name / Path(photo["file"]).name
            if source.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            photo["file"] = f"{new_folder_name}/{target.name}"


def session_json(session: CaseSession) -> str:
    return json.dumps(session.to_dict(), indent=2, ensure_ascii=False)


def save_session(session: CaseSession, path: str | Path) -> list[str]:
    """Write the case file. Photos of removed cards and removed photos are deleted from the case
    folder only now, after the case file no longer refers to them. Returns the deleted files."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _carry_photos(session, destination)
    temporary = destination.with_name(destination.name + ".saving")
    temporary.write_text(session_json(session), encoding="utf-8")
    temporary.replace(destination)
    session.path = str(destination)
    return _delete_pending(session, destination.parent)


def session_from_payload(payload, path: str | None = None) -> CaseSession:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("This file is not a card session.")
    number = payload.get("case_number")
    if not isinstance(number, str) or not number.strip():
        raise ValueError("This file is not a card session.")
    cards: list[CardRecord] = []
    for item in payload.get("cards") or []:
        if not isinstance(item, dict) or "parsed" not in item or "raw" not in item:
            raise ValueError("This file is not a card session.")
        raw = str(item.get("raw") or "")
        parsed = item["parsed"]
        if isinstance(parsed, dict) and int(parsed.get("parser_version") or 1) < PARSER_VERSION and raw:
            swiped = str(item.get("swiped_at") or "")
            try:
                swiped_day = datetime.fromisoformat(swiped).date()
            except ValueError:
                swiped_day = None
            parsed = parsed_to_dict(parse_swipe(raw, today=swiped_day))
        photos = [dict(photo) for photo in item.get("photos") or [] if isinstance(photo, dict)]
        cards.append(
            CardRecord(
                id=str(item.get("id") or uuid.uuid4().hex),
                swiped_at=str(item.get("swiped_at") or ""),
                raw=raw,
                note=str(item.get("note") or ""),
                parsed=parsed,
                bin_lookup=item.get("bin_lookup"),
                printed=normalize_printed(item.get("printed")),
                exhibit=str(item.get("exhibit") or ""),
                face_type=normalize_face(item.get("face_type")),
                photos=photos,
            )
        )
    try:
        next_exhibit = int(payload.get("next_exhibit"))
    except (TypeError, ValueError):
        next_exhibit = len(cards) + 1
    automatic = [
        int(match.group(1))
        for card in cards
        for match in [
            re.fullmatch(
                (re.escape(str(payload.get("exhibit_prefix") or "").strip()) + r"\s*(\d+)")
                if str(payload.get("exhibit_prefix") or "").strip()
                else r"(\d+)",
                card.exhibit.strip(),
            )
        ]
        if match
    ]
    try:
        first_exhibit = int(payload.get("first_exhibit"))
    except (TypeError, ValueError):
        first_exhibit = min(automatic) if automatic else next_exhibit
    session = CaseSession(
        case_number=number.strip(),
        examiner=str(payload.get("examiner") or ""),
        unit=str(payload.get("unit") or ""),
        notes=str(payload.get("notes") or ""),
        started_at=str(payload.get("started_at") or ""),
        cards=cards,
        path=path,
        exhibit_prefix=str(payload.get("exhibit_prefix") or ""),
        next_exhibit=next_exhibit,
        first_exhibit=first_exhibit,
    )
    for card in session.cards:
        card.view()
    return session


def load_session(path: str | Path) -> CaseSession:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("This file is not a card session.") from exc
    try:
        return session_from_payload(payload, str(source))
    except (TypeError, KeyError) as exc:
        raise ValueError("This file is not a card session.") from exc
