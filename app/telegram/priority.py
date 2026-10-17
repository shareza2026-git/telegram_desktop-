"""Chats whose messages must reach the window first (quote rooms, price feeds).

A chat is a priority chat when its title contains one of the quote keywords,
unless the user switched it off; the user can also switch any other chat on.
Choices are saved in the client data folder, so they move with the app.
"""

import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

# Titles of quote rooms and price channels usually contain one of these.
QUOTE_KEYWORDS = (
    "اتاق",
    "لفظ",
    "مظنه",
    "قیمت",
    "نقدی",
    "آبشده",
    "آب شده",
    "سکه",
    "طلا",
    "دلار",
)


class PriorityChats:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._on: set[int] = set()
        self._off: set[int] = set()
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("Priority chat settings could not be read; using defaults")
            return
        if isinstance(payload, dict):
            self._on = {int(value) for value in payload.get("on", []) if isinstance(value, int)}
            self._off = {int(value) for value in payload.get("off", []) if isinstance(value, int)}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps({"on": sorted(self._on), "off": sorted(self._off)}),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def matches_keywords(title: str) -> bool:
        return any(keyword in title for keyword in QUOTE_KEYWORDS)

    def is_priority(self, chat_id: int, title: str) -> bool:
        if chat_id in self._on:
            return True
        if chat_id in self._off:
            return False
        return self.matches_keywords(title)

    def set(self, chat_id: int, title: str, enabled: bool) -> None:
        self._on.discard(chat_id)
        self._off.discard(chat_id)
        # Store only choices that differ from the keyword rule.
        if enabled != self.matches_keywords(title):
            (self._on if enabled else self._off).add(chat_id)
        self._save()
