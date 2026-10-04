"""Shared decision log (written by the twin core and traffic management, read by storage/UI)."""
import json
from .config import fmt


class DecisionLog:
    def __init__(self, echo: bool = False):
        self.entries = []
        self.echo = echo

    def add(self, t: int, tag: str, text: str, metadata: dict = None):
        meta_str = json.dumps(metadata) if metadata else None
        self.entries.append((t, tag, text, meta_str))
        if self.echo:
            print(f"{fmt(t):>5}  {tag:<7} {text}")
