"""Recovery copies of the open case, written while you work so a crash does not lose swipes."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from card_stripe_examiner.session import CaseSession, session_from_payload

INTERVAL_MS = 30_000


def default_folder() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home()
    return base / "CardStripeExaminer" / "autosave"


def recovery_path(session: CaseSession, folder: Path | None = None) -> Path:
    folder = folder or default_folder()
    case = re.sub(r"[^A-Za-z0-9._-]+", "-", session.case_number).strip("-.") or "case"
    stamp = re.sub(r"\D", "", session.started_at) or "unsaved"
    return folder / f"{case}-{stamp}.json"


def write_recovery(session: CaseSession, folder: Path | None = None) -> Path:
    path = recovery_path(session, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = session.to_dict()
    payload["recovery"] = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "path": session.path,
    }
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path


def clear_recovery(session: CaseSession | None, folder: Path | None = None) -> None:
    if session is None:
        return
    path = recovery_path(session, folder)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def find_recoveries(folder: Path | None = None) -> list[dict]:
    folder = folder or default_folder()
    if not folder.exists():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            details = payload.get("recovery") or {}
            found.append(
                {
                    "file": path,
                    "case_number": str(payload.get("case_number") or ""),
                    "cards": len(payload.get("cards") or []),
                    "saved_at": str(details.get("saved_at") or ""),
                    "path": details.get("path"),
                }
            )
        except (OSError, ValueError, AttributeError):
            continue
    return found


def load_recovery(file: Path) -> CaseSession:
    payload = json.loads(Path(file).read_text(encoding="utf-8"))
    details = payload.get("recovery") or {}
    return session_from_payload(payload, details.get("path"))


def discard_recovery(file: Path) -> None:
    try:
        Path(file).unlink()
    except FileNotFoundError:
        pass
