from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

_INPUT_RE = re.compile(r"<handoff_input>\n(?P<body>.*)\n</handoff_input>", re.DOTALL)


def render_briefing(task: str, payload: BaseModel) -> str:
    body = json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False)
    return f"{task}\n\n<handoff_input>\n{body}\n</handoff_input>"


def parse_briefing(text: str) -> dict[str, Any]:
    match = _INPUT_RE.search(text)
    if match is None:
        return {}
    parsed = json.loads(match.group("body"))
    return parsed if isinstance(parsed, dict) else {}
