"""Background work that must not block the window."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from card_stripe_examiner.bin_lookup import BinResult, lookup_account, prompt_digits


class LookupThread(QThread):
    finished_ok = Signal(list)

    def __init__(self, jobs: list[tuple[str, str]], token: str | None, cache) -> None:
        super().__init__()
        self.jobs = jobs
        self.token = token
        self.cache = cache

    def run(self) -> None:
        try:
            grouped: dict[str, list[tuple[str, str]]] = {}
            order: list[str] = []
            for card_id, account in self.jobs:
                key = prompt_digits(account) or ""
                if key not in grouped:
                    order.append(key)
                    grouped[key] = []
                grouped[key].append((card_id, account))
            results = []
            for key in order:
                group = grouped[key]
                result = lookup_account(group[0][1], token=self.token, cache=self.cache)
                for card_id, _account in group:
                    results.append((card_id, result.to_dict()))
            self.finished_ok.emit(results)
        except Exception:
            message = "The lookup did not complete. Check the network connection."
            self.finished_ok.emit(
                [
                    (
                        card_id,
                        BinResult(queried_digits="", looked_up_at="", error=message).to_dict(),
                    )
                    for card_id, _account in self.jobs
                ]
            )
