import pytest

from pipeline import extract


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": "unavailable"}, []])
def test_arbeitnow_schema_failure_is_not_silently_empty(monkeypatch, payload):
    monkeypatch.setattr(extract, "get_json", lambda *args: payload)
    with pytest.raises(ValueError, match="list"):
        extract.fetch_arbeitnow()


def test_arbeitnow_stops_after_valid_empty_page(monkeypatch):
    responses = iter([{"data": [{"slug": "one"}]}, {"data": []}])
    monkeypatch.setattr(extract, "get_json", lambda *args: next(responses))
    assert extract.fetch_arbeitnow() == [{"slug": "one"}]


def test_remotive_schema_failure_is_not_silently_empty(monkeypatch):
    monkeypatch.setattr(extract, "get_json", lambda *args: {"error": "unavailable"})
    with pytest.raises(ValueError, match="jobs"):
        extract.fetch_remotive()
