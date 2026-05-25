"""Persistent store for user-defined session title overrides.

Maps session_id -> custom title. Stored as JSON in the data directory
(NOT cache) so custom titles survive cache clears and index rebuilds.
"""

import logging
import os
from pathlib import Path

import orjson

from .config import TITLE_OVERRIDES_FILE

logger = logging.getLogger(__name__)


class TitleOverrides:
    """Read/write store of session title overrides backed by a JSON file."""

    def __init__(self, path: Path = TITLE_OVERRIDES_FILE) -> None:
        self._path = path
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = orjson.loads(self._path.read_bytes())
        except (orjson.JSONDecodeError, OSError) as e:
            logger.warning("Could not read title overrides at %s: %s", self._path, e)
            return {}
        if not isinstance(raw, dict):
            return {}
        # Keep only str -> str entries
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}

    def _save(self) -> None:
        # Persist atomically. A disk error must not crash callers (e.g. the TUI
        # rename action); the in-memory state stands and the index still reflects
        # the new title until the next rebuild.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_bytes(orjson.dumps(self._data))
            os.replace(tmp, self._path)
        except OSError as e:
            logger.warning("Could not save title overrides to %s: %s", self._path, e)

    def get(self, session_id: str) -> str | None:
        return self._data.get(session_id)

    def set(self, session_id: str, title: str) -> None:
        self._data[session_id] = title
        self._save()

    def clear(self, session_id: str) -> None:
        if session_id in self._data:
            del self._data[session_id]
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._data)
