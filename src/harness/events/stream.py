"""Append-only EventStream with pub/sub subscribers and JSONL trajectory logging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from harness.events.schema import Event

EventSubscriber = Callable[[Event], None]


class EventStream:
    """Single source of truth for all events emitted during an agent run."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, callback: EventSubscriber) -> None:
        self._subscribers.append(callback)

    def publish(self, event: Event) -> None:
        self._events.append(event)
        for callback in self._subscribers:
            callback(event)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)


class JsonlTrajectoryLogger:
    """Sidecar subscriber that persists every Event as one JSON line."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: Event) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self.output_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    @staticmethod
    def load(path: Path) -> list[dict]:
        records: list[dict] = []
        with Path(path).open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
