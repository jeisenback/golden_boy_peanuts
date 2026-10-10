"""
Unit tests for scripts/write_candidate_snapshot.py and scripts/publish_candidate_snapshot.sh
(issue #218). No network; the price lookup runs on in-memory SQLite and the publish
script runs against a local bare git repository.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
import json
import pathlib as _pathlib
from pathlib import Path
import shutil
import subprocess
import sys as _sys

from sqlalchemy import create_engine, text

from src.agents.ingestion.models import OptionStructure
from src.agents.strategy_evaluation.models import StrategyCandidate

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
from scripts.write_candidate_snapshot import (  # type: ignore[import]
    fetch_latest_prices,
    serialize_snapshot,
    write_snapshot,
)

_REPO_ROOT = _pathlib.Path(__file__).resolve().parents[2]
_PUBLISH = _REPO_ROOT / "scripts" / "publish_candidate_snapshot.sh"
_RUN_TIME = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


def _candidate(instrument: str = "USO", edge: float = 0.61) -> StrategyCandidate:
    return StrategyCandidate(
        instrument=instrument,
        structure=OptionStructure.LONG_STRADDLE,
        expiration=30,
        edge_score=edge,
        signals={"volatility_gap": "positive"},
        generated_at=_RUN_TIME,
    )


def _engine_with_prices(rows: list[tuple[str, float, datetime]]):  # type: ignore[no-untyped-def]
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE market_prices (instrument TEXT, price REAL, timestamp TIMESTAMP)")
        )
        for instrument, price, ts in rows:
            conn.execute(
                text("INSERT INTO market_prices VALUES (:i, :p, :t)"),
                {"i": instrument, "p": price, "t": ts},
            )
    return engine


def test_serialize_round_trips_every_issue_field() -> None:
    snapshot = serialize_snapshot([_candidate()], {"USO": 78.7}, date(2026, 10, 12))
    restored = json.loads(json.dumps(snapshot))
    assert restored["run_date"] == "2026-10-12"
    assert restored["candidates"] == [
        {
            "instrument": "USO",
            "structure": "long_straddle",
            "expiration": 30,
            "edge_score": 0.61,
            "signals": {"volatility_gap": "positive"},
            "generated_at": "2026-10-12T20:00:00+00:00",
            "price_at_generation": 78.7,
        }
    ]


def test_serialize_empty_list_keeps_an_empty_candidates_list() -> None:
    snapshot = serialize_snapshot([], {}, date(2026, 10, 12))
    assert snapshot == {"run_date": "2026-10-12", "candidates": []}


def test_serialize_converts_other_timezones_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    candidate = _candidate().model_copy(
        update={"generated_at": datetime(2026, 10, 12, 16, 0, tzinfo=eastern)}
    )
    snapshot = serialize_snapshot([candidate], {}, date(2026, 10, 12))
    assert snapshot["candidates"][0]["generated_at"] == "2026-10-12T20:00:00+00:00"


def test_serialize_writes_null_price_for_instrument_without_one() -> None:
    snapshot = serialize_snapshot([_candidate("XOM")], {"USO": 78.7}, date(2026, 10, 12))
    assert snapshot["candidates"][0]["price_at_generation"] is None


def test_fetch_latest_prices_returns_most_recent_row_per_instrument() -> None:
    engine = _engine_with_prices(
        [
            ("USO", 70.0, datetime(2026, 10, 9, 20, 0)),
            ("USO", 78.7, datetime(2026, 10, 12, 20, 0)),
            ("XLE", 90.0, datetime(2026, 10, 12, 20, 0)),
            ("CVX", 150.0, datetime(2026, 10, 12, 20, 0)),
        ]
    )
    assert fetch_latest_prices(engine, ["USO", "XLE"]) == {"USO": 78.7, "XLE": 90.0}
    assert fetch_latest_prices(engine, []) == {}


def test_write_snapshot_overwrites_same_date_and_writes_empty_run(tmp_path: Path) -> None:
    engine = _engine_with_prices([("USO", 78.7, datetime(2026, 10, 12, 19, 0))])
    out = tmp_path / "candidates"

    first = write_snapshot([_candidate(edge=0.5)], engine=engine, out_dir=out, now=_RUN_TIME)
    second = write_snapshot([_candidate(edge=0.7)], engine=engine, out_dir=out, now=_RUN_TIME)
    assert first == second == out / "2026-10-12.json"
    assert json.loads(second.read_text())["candidates"][0]["edge_score"] == 0.7
    assert len(list(out.iterdir())) == 1

    empty = write_snapshot([], engine=engine, out_dir=out, now=_RUN_TIME + timedelta(days=1))
    assert empty.name == "2026-10-13.json"
    assert json.loads(empty.read_text())["candidates"] == []


def _run(
    command: str, *args: str, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a fixed git/bash command with its full path; arguments are all test-controlled."""
    executable = shutil.which(command)
    assert executable is not None
    return subprocess.run(  # noqa: S603
        [executable, *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def _git(cwd: Path, *args: str) -> str:
    return _run("git", *args, cwd=cwd).stdout.strip()


def test_publish_script_creates_orphan_data_branch_then_updates_it(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "--initial-branch=develop", str(remote))
    _git(tmp_path, "clone", "--quiet", str(remote), str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    (work / "README.md").write_text("code\n")
    _git(work, "add", ".")
    _git(work, "commit", "--quiet", "-m", "init")
    _git(work, "push", "--quiet", "origin", "HEAD:develop")

    snapshots = work / "data" / "candidates"
    snapshots.mkdir(parents=True)
    (snapshots / "2026-10-12.json").write_text('{"run_date": "2026-10-12", "candidates": []}\n')

    def publish() -> None:
        _run("bash", str(_PUBLISH), cwd=work)

    publish()
    assert _git(remote, "branch", "--list").replace("*", "").split() == ["data", "develop"]
    assert _git(remote, "ls-tree", "-r", "--name-only", "data") == "data/candidates/2026-10-12.json"
    assert _git(remote, "rev-list", "--count", "data") == "1"

    (snapshots / "2026-10-12.json").write_text('{"run_date": "2026-10-12", "candidates": [1]}\n')
    (snapshots / "2026-10-13.json").write_text('{"run_date": "2026-10-13", "candidates": []}\n')
    publish()
    assert _git(remote, "ls-tree", "-r", "--name-only", "data").split() == [
        "data/candidates/2026-10-12.json",
        "data/candidates/2026-10-13.json",
    ]
    assert _git(remote, "rev-list", "--count", "data") == "2"
    assert _git(remote, "rev-parse", "develop") == _git(work, "rev-parse", "HEAD")
    assert _git(work, "branch", "--show-current") == "develop"


def test_publish_script_fails_loudly_without_snapshots(tmp_path: Path) -> None:
    result = _run("bash", str(_PUBLISH), str(tmp_path / "empty"), check=False)
    assert result.returncode != 0
    assert "nothing to publish" in result.stderr
