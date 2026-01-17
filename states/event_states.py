"""
Event-only map state (no pose). Use RaspiState for telemetry/heartbeat.
"""
from dataclasses import dataclass, field
from typing import List
import time


@dataclass
class Event:
    ts: float
    kind: str
    data: dict


@dataclass
class EventState:
    events: List[Event] = field(default_factory=list)

    def log_event(self, kind: str, **data):
        self.events.append(Event(time.time(), kind, data))

    def snapshot(self):
        # Return a shallow copy
        return EventState(events=list(self.events))

    def snapshot_dict(self) -> dict:
        return {"events": [e.__dict__ for e in self.events]}
