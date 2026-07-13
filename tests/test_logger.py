from datetime import datetime, timezone
import logger

NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
CFG = {"currency": "try", "marker": "750309",
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way",
                   "date_range": {"start": "2026-10-24", "end": "2026-11-01"}}]}


def test_dates_in_window():
    w = logger.dates_in_window({"date_range": {"start": "2026-10-30", "end": "2026-11-01"}})
    assert w == {"2026-10-30", "2026-10-31", "2026-11-01"}


def test_collect_keeps_only_in_window_dates():
    def fetch(origin, destination, cfg):
        return {
            "2026-07-13": {"price": 41005, "airline": "IndiGo", "stops": 2},   # out of window
            "2026-10-27": {"price": 39249, "airline": "Air Arabia", "stops": 2},
            "2026-10-30": {"price": 34255, "airline": "AirAsia X", "stops": 1},
        }
    records, hard = logger.collect(CFG, fetch=fetch, now=NOW)
    assert hard == 0
    assert {r.tags["depart_date"] for r in records} == {"2026-10-27", "2026-10-30"}


def test_collect_hard_failure_on_error_but_not_on_empty_window():
    # fetch error -> hard failure
    def boom(*a, **k):
        raise RuntimeError("travelpayouts down")
    _, hf = logger.collect(CFG, fetch=boom, now=NOW)
    assert hf == 1
    # no dates in window is NOT a hard failure (just sparse cache)
    recs, hf2 = logger.collect(CFG, fetch=lambda *a, **k: {"2026-07-13": {"price": 1, "airline": "X", "stops": 0}}, now=NOW)
    assert recs == [] and hf2 == 0
