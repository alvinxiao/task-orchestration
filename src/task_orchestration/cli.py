
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .domain import PlanningRequest
from .solver import solve

_EXIT_INPUT_ERROR = 2
_EXIT_UNSOLVED = 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: task-assign [request.json]", file=sys.stderr)
        return _EXIT_INPUT_ERROR
    try:
        raw = Path(args[0]).read_text(encoding="utf-8") if args else sys.stdin.read()
        request = PlanningRequest.model_validate_json(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
        print(f"invalid planning request: {error}", file=sys.stderr)
        return _EXIT_INPUT_ERROR
    try:
        result = solve(request)
    except ValueError as error:
        print(f"invalid planning request: {error}", file=sys.stderr)
        return _EXIT_INPUT_ERROR
    print(result.model_dump_json(indent=2))
    return 0 if result.status in ("OPTIMAL", "FEASIBLE") else _EXIT_UNSOLVED


if __name__ == "__main__":
    raise SystemExit(main())
