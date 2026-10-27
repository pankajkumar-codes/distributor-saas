"""The jobs queue port (LLD-0 §3.7, TD-3).

The outbox hands each message to a `Queue` after commit. In AWS that is SqsQueue
(`platform_common.aws`, the only module that imports boto3); tests use FakeQueue and a
local server uses InlineQueue, which runs the worker's handler straight away. The app
picks one at start-up with `set_queue`; nothing here reads the environment.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class Queue(Protocol):
    def send(self, body: dict) -> None: ...


@dataclass
class FakeQueue:
    """Records messages; a test delivers them with `drain`, as many times as it likes."""

    sent: list[dict] = field(default_factory=list)

    def send(self, body: dict) -> None:
        self.sent.append(dict(body))

    def drain(self, handle: Callable[[dict], object]) -> list[object]:
        messages, self.sent = self.sent, []
        return [handle(m) for m in messages]


@dataclass
class InlineQueue:
    """Local runs only: handles each message as soon as it is sent (after commit)."""

    handle: Callable[[dict], object]

    def send(self, body: dict) -> None:
        self.handle(dict(body))


_queue: Queue | None = None


def set_queue(queue: Queue | None) -> None:
    global _queue
    _queue = queue


def get_queue() -> Queue:
    if _queue is None:
        raise RuntimeError("no jobs queue configured; the app sets one at start-up (set_queue)")
    return _queue
