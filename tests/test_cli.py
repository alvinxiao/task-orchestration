
import json
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample.json"


def run_cli(args, stdin_text=None):
    return subprocess.run(
        [sys.executable, "-m", "task_orchestration.cli", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_solves_example():
    process = run_cli([str(EXAMPLE)])
    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout)
    assert payload["status"] == "OPTIMAL"
    assigned_ids = [task["task_id"] for schedule in payload["assignments"] for task in schedule["tasks"]]
    assert sorted(assigned_ids) == ["task1", "task2", "task3", "task4"]
    assert [item["task_id"] for item in payload["unassigned"]] == ["task5"]


def test_cli_rejects_malformed_json():
    process = run_cli([], stdin_text="{not json")
    assert process.returncode == 2
    assert "invalid planning request" in process.stderr


def test_cli_rejects_invalid_reference():
    request = {
        "employees": [],
        "customers": [{"id": "c1", "name": "Alpha"}],
        "task_types": [],
        "tasks": [
            {"id": "t1", "task_type_id": "ghost", "customer_id": "c1", "earliest_start": 0, "priority": "MINOR"}
        ],
        "options": {"time_limit_seconds": 1},
    }
    process = run_cli([], stdin_text=json.dumps(request))
    assert process.returncode == 2
    assert "unknown task type" in process.stderr


def test_cli_rejects_unsafe_horizon_without_traceback():
    request = json.loads(EXAMPLE.read_text())
    request["tasks"][0]["earliest_start"] = 10**12
    process = run_cli([], stdin_text=json.dumps(request))
    assert process.returncode == 2
    assert "planning horizon" in process.stderr
    assert "Traceback" not in process.stderr
    assert process.stdout == ""
