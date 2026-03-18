"""Simple JSON file store for Outlook account credentials."""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from outlook2api.config import get_config


class AccountStore:
    """Thread-safe store for address -> password mapping."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or get_config().get("accounts_file", "data/outlook_accounts.json")
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = {k: str(v) for k, v in data.items()}
                else:
                    self._data = {}
            except Exception:
                self._data = {}

    def _save(self) -> None:
        dn = os.path.dirname(self.path)
        if dn:
            os.makedirs(dn, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def add(self, address: str, password: str) -> None:
        with self._lock:
            self._data[address.lower()] = password
            self._save()

    def remove(self, address: str) -> None:
        with self._lock:
            self._data.pop(address.lower(), None)
            self._save()

    def has(self, address: str) -> bool:
        with self._lock:
            return address.lower() in self._data

    def get_password(self, address: str) -> Optional[str]:
        with self._lock:
            return self._data.get(address.lower())


_store: Optional[AccountStore] = None


def get_store() -> AccountStore:
    global _store
    if _store is None:
        _store = AccountStore()
    return _store
