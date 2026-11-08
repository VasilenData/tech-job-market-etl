import csv
import json
from datetime import date
from unittest.mock import MagicMock, Mock

import pytest

from pipeline import run


@pytest.mark.parametrize("failed_sources", [[], ["arbeitnow"], ["remotive"], ["arbeitnow", "remotive"]])
def test_only_complete_source_coverage_publishes_daily_outputs(tmp_path, monkeypatch, failed_sources):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql/schema.sql").write_text("-- test schema")
    conn = MagicMock()
    monkeypatch.setattr(run, "ROOT", str(tmp_path))
    monkeypatch.setattr(run, "connect", lambda: conn)
    for name in ("arbeitnow", "remotive"):
        monkeypatch.setattr(run.extract, "fetch_" + name,
                            Mock(side_effect=ValueError("source failure")) if name in failed_sources else Mock(return_value=[{}]))
    monkeypatch.setattr(run.transform, "normalize_batch", lambda rows, norm: ([{"job_id": "test"}], []))
    load = Mock(return_value={"fetched": 1, "valid": 1, "rejected": 0, "inserted": 1, "updated": 0})
    export, history = Mock(), Mock()
    monkeypatch.setattr(run.load, "load", load)
    monkeypatch.setattr(run, "export_reports", export)
    monkeypatch.setattr(run, "append_history", history)
    assert run.main() == bool(failed_sources)
    assert load.call_count == 2 - len(failed_sources)  # successful source work is retained
    assert export.call_count == history.call_count == (0 if failed_sources else 1)
    status = json.loads((tmp_path / "data/run_status.json").read_text())
    assert status["publication"] == ("withheld" if failed_sources else "complete")
    assert {name for name, result in status["sources"].items() if result["status"] == "failed"} == set(failed_sources)
    conn.close.assert_called_once()
    for call in load.call_args_list:
        assert call.kwargs["today"].isoformat() == status["day"]
    if not failed_sources:
        assert history.call_args.kwargs["today"].isoformat() == status["day"]


def test_failed_csv_serialization_preserves_previous_complete_file(tmp_path):
    target = tmp_path / "history.csv"
    target.write_text("previous complete history\n", encoding="utf-8")

    def broken_writer(stream):
        stream.write("partial")
        raise OSError("disk failure")

    with pytest.raises(OSError, match="disk failure"):
        run.atomic_text(str(target), broken_writer)
    assert target.read_text() == "previous complete history\n"
    assert list(tmp_path.iterdir()) == [target]


def test_connection_failure_replaces_old_status_with_current_failure(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/run_status.json").write_text('{"publication":"complete"}')
    monkeypatch.setattr(run, "ROOT", str(tmp_path))
    monkeypatch.setattr(run, "connect", Mock(side_effect=ConnectionError("database unavailable")))
    with pytest.raises(ConnectionError):
        run.main()
    status = json.loads((tmp_path / "data/run_status.json").read_text())
    assert status["publication"] == "withheld"
    assert status["error_type"] == "ConnectionError"


def test_same_day_history_refresh_is_idempotent_and_preserves_other_days(tmp_path):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [("data_engineering", 4, 2)]
    path = tmp_path / "history.csv"
    path.write_text("day,role_family,active_jobs,remote_jobs\n2026-11-07,other,7,3\n", encoding="utf-8")
    run.append_history(conn, str(path), today=date(2026, 11, 8))
    first = path.read_bytes()
    run.append_history(conn, str(path), today=date(2026, 11, 8))
    assert path.read_bytes() == first
    with path.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream))[1:] == [["2026-11-07", "other", "7", "3"],
                                               ["2026-11-08", "data_engineering", "4", "2"]]
