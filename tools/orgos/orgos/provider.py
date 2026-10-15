"""Git providers. Only the fake exists today; it is labelled simulated everywhere it shows up.

A live GitHub provider needs a token for headless runs, which this project does not have yet
(see docs/ORG_OS.md "Blockers"). Until then, Claude sessions do the real GitHub calls through
their GitHub connector and feed the results in with `orgos sync-pr`.
"""

from typing import Protocol


class GitProvider(Protocol):
    simulated: bool

    def merge(self, number: int, head_sha: str, note: str) -> str: ...

    def comment(self, number: int, body: str) -> None: ...


class FakeProvider:
    simulated = True

    def __init__(self, fail_merge: str | None = None):
        self.merged: list[tuple[int, str, str]] = []
        self.comments: list[tuple[int, str]] = []
        self.fail_merge = fail_merge

    def merge(self, number: int, head_sha: str, note: str) -> str:
        if self.fail_merge:
            raise PermissionError(self.fail_merge)
        self.comments.append((number, note))
        self.merged.append((number, head_sha, note))
        return f"sim{number:04d}{head_sha[:8]}"

    def comment(self, number: int, body: str) -> None:
        self.comments.append((number, body))
