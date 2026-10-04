"""Container: Message broker.

InMemoryBroker mimics MQTT topics (with + and # wildcards) so the demo needs no server.
No external server is required.
"""
import json
from collections import deque


def topic_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


class InMemoryBroker:
    def __init__(self, keep: int = 200):
        self.subscribers = []
        self.log = deque(maxlen=keep)

    def subscribe(self, pattern: str, callback):
        self.subscribers.append((pattern, callback))

    def publish(self, topic: str, payload: dict):
        wire = json.dumps(payload)          # serialize like a real broker would
        self.log.append((topic, wire))
        for pattern, cb in list(self.subscribers):
            if topic_matches(pattern, topic):
                cb(topic, json.loads(wire))
