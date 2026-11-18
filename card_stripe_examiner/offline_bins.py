"""Offline issuing-bank directory imported from a CSV file. Lookups never leave this computer."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from card_stripe_examiner.bin_lookup import BinResult

OFFLINE_NOTE = (
    "Offline BIN directory imported on this computer. This is not a verification by the issuing bank."
)

# Header names seen in common BIN lists, in order of preference.
COLUMNS = {
    "bin": ("bin", "iin", "bin/iin", "bin_iin", "prefix", "bin_number", "iin_start", "number"),
    "bank": ("issuer", "bank", "bank_name", "issuer_name", "issuing_bank", "issuing_organization", "issuer_bank"),
    "country": ("country_name", "country", "issuer_country", "iso_country_name", "country_iso_name", "alpha_2", "country_code", "iso_code_2"),
    "scheme": ("scheme", "brand", "card_brand", "network", "vendor", "card_scheme"),
    "kind": ("type", "card_type", "funding", "funding_source"),
    "level": ("category", "level", "card_level", "product", "card_category"),
    "prepaid": ("prepaid", "is_prepaid"),
    "phone": ("bank_phone", "phone", "issuer_phone", "issuer_phone_number"),
    "url": ("bank_url", "url", "website", "issuer_url", "issuer_website"),
    "city": ("bank_city", "city", "issuer_city"),
}


def default_database_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home()
    return base / "CardStripeExaminer" / "bin_offline.sqlite"


def _key(header: str) -> str:
    return "_".join(header.strip().lower().replace("-", " ").split())


def _pick(headers: list[str]) -> dict[str, int]:
    keys = [_key(header) for header in headers]
    found: dict[str, int] = {}
    for field, names in COLUMNS.items():
        for name in names:
            if name in keys:
                found[field] = keys.index(name)
                break
    return found


def _prepaid(value: str | None, *others: str | None) -> int | None:
    text = (value or "").strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return 1
    if text in {"false", "no", "n", "0"}:
        return 0
    if any("prepaid" in (other or "").lower() for other in others):
        return 1
    return None


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


class OfflineBinDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_database_path()

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        return sqlite3.connect(str(path or self.path))

    def exists(self) -> bool:
        return self.path.exists()

    def info(self) -> dict | None:
        if not self.exists():
            return None
        try:
            with closing(self._connect()) as connection:
                rows = dict(connection.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error:
            return None
        return rows or None

    def import_csv(self, csv_path: str | Path) -> int:
        """Replace the offline directory with the rows in a CSV file. Returns the number of BINs kept."""
        source = Path(csv_path)
        text = _read_text(source)
        sample = text[:20000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError("The file is empty.") from exc
        columns = _pick(headers)
        if "bin" not in columns:
            raise ValueError("No BIN column was found. The first row must name the columns, for example bin, issuer, country.")
        if "bank" not in columns and "scheme" not in columns:
            raise ValueError("No issuer or brand column was found in the file.")

        def cell(row: list[str], field: str) -> str | None:
            index = columns.get(field)
            if index is None or index >= len(row):
                return None
            value = row[index].strip()
            return value or None

        records = []
        for row in reader:
            digits = "".join(character for character in (cell(row, "bin") or "") if character.isdigit())
            if not 6 <= len(digits) <= 11:
                continue
            kind = cell(row, "kind")
            level = cell(row, "level")
            records.append(
                (
                    digits,
                    cell(row, "bank"),
                    cell(row, "country"),
                    cell(row, "scheme"),
                    kind,
                    level,
                    _prepaid(cell(row, "prepaid"), kind, level),
                    cell(row, "phone"),
                    cell(row, "url"),
                    cell(row, "city"),
                )
            )
        if not records:
            raise ValueError("No usable BIN rows were found in the file.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".importing")
        if temporary.exists():
            temporary.unlink()
        with self._connect(temporary) as connection:
            connection.execute(
                "CREATE TABLE bins (bin TEXT PRIMARY KEY, bank TEXT, country TEXT, scheme TEXT, kind TEXT,"
                " level TEXT, prepaid INTEGER, phone TEXT, url TEXT, city TEXT)"
            )
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT OR REPLACE INTO bins VALUES (?,?,?,?,?,?,?,?,?,?)", records)
            count = connection.execute("SELECT COUNT(*) FROM bins").fetchone()[0]
            meta = {
                "source_name": source.name,
                "imported_at": datetime.now().isoformat(timespec="seconds"),
                "rows": str(count),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            connection.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
        connection.close()
        os.replace(temporary, self.path)
        return count

    def clear(self) -> None:
        if self.exists():
            self.path.unlink()

    def lookup(self, account: str | None) -> BinResult | None:
        digits = "".join(character for character in (account or "") if character.isdigit())
        if len(digits) < 6 or not self.exists():
            return None
        candidates = [digits[:length] for length in range(min(11, len(digits)), 5, -1)]
        try:
            with closing(self._connect()) as connection:
                for prefix in candidates:
                    row = connection.execute(
                        "SELECT bin, bank, country, scheme, kind, level, prepaid, phone, url, city FROM bins WHERE bin = ?",
                        (prefix,),
                    ).fetchone()
                    if row:
                        meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
                        return self._result(row, meta)
        except sqlite3.Error:
            return None
        return None

    @staticmethod
    def _result(row, meta: dict) -> BinResult:
        prefix, bank, country, scheme, kind, level, prepaid, phone, url, city = row
        name = meta.get("source_name", "imported list")
        imported = (meta.get("imported_at") or "")[:10]
        return BinResult(
            queried_digits=prefix,
            looked_up_at=datetime.now().isoformat(timespec="seconds"),
            bank_name=bank,
            bank_city=city,
            bank_phone=phone,
            bank_url=url,
            country=country,
            scheme=scheme.title() if scheme else None,
            brand=level,
            card_kind=kind.title() if kind else None,
            prepaid=None if prepaid is None else bool(prepaid),
            source_note=OFFLINE_NOTE,
            source=f"Offline BIN list {name} (imported {imported})",
        )
