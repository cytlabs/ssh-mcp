"""Bounded replayable character buffers with explicit loss reporting."""

from collections import deque

from .errors import InputError


class OutputBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.parts: deque[str] = deque()
        self.start = 0
        self.end = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self.parts.append(text)
        self.end += len(text)
        excess = self.end - self.start - self.capacity
        while excess > 0:
            part = self.parts.popleft()
            count = min(excess, len(part))
            self.start += count
            excess -= count
            if count < len(part):
                self.parts.appendleft(part[count:])

    def read(self, cursor: int, limit: int) -> dict:
        if type(cursor) is not int or cursor < 0 or cursor > self.end:
            raise InputError("Invalid output cursor")
        position = max(cursor, self.start)
        text = "".join(self.parts)[position - self.start:position - self.start + limit]
        return {"text": text, "cursor": position + len(text),
                "dropped_chars": max(0, self.start - cursor),
                "has_more": position + len(text) < self.end}
