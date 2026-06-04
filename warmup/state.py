from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class State:
    last_warmup: datetime | None
    last_result: str
    next_warmup: datetime | None


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def load_state(path: Path) -> State:
    if not path.exists():
        return State(last_warmup=None, last_result="", next_warmup=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    return State(
        last_warmup=_parse(data.get("last_warmup")),
        last_result=data.get("last_result", ""),
        next_warmup=_parse(data.get("next_warmup")),
    )


def save_state(path: Path, state: State) -> None:
    path.write_text(
        json.dumps(
            {
                "last_warmup": _iso(state.last_warmup),
                "last_result": state.last_result,
                "next_warmup": _iso(state.next_warmup),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
