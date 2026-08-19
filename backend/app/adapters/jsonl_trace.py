from __future__ import annotations

import json

from ..domain.models import SimulationEvent


class JsonlTraceWriter:
    """Pure serializer: SimulationEvent sequence -> JSONL text.

    No filesystem I/O — SimulationService owns writing and atomic publication (D-002/§17).
    """

    def serialize(self, events: tuple[SimulationEvent, ...]) -> str:
        if not events:
            return ""
        lines = []
        for ev in events:
            obj = {"t": ev.t, "event": ev.event.value, "request_id": ev.request_id}
            if ev.server_id is not None:
                obj["server_id"] = ev.server_id
            lines.append(json.dumps(obj, separators=(",", ":")))
        return "\n".join(lines) + "\n"
