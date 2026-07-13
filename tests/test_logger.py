from datetime import datetime, timezone
import logger

NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
CFG = {"currency": "TRY", "date_gap_seconds": 0,
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way",
                   "date_range": {"start": "2026-10-30", "end": "2026-10-31"}}]}


def test_route_dates_from_range():
    assert logger.route_dates({"date_range": {"start": "2026-10-30", "end": "2026-11-01"}}) == \
        ["2026-10-30", "2026-10-31", "2026-11-01"]


def test_collect_one_point_per_date_and_airline():
    def fetch(origin, destination, d, cfg):
        return {"THAI": {"price": 24518, "stops": 1}, "Etihad": {"price": 25582, "stops": 1}}
    records, attempted, succeeded = logger.collect(CFG, fetch=fetch, now=NOW)
    assert attempted == 2 and succeeded == 2
    assert len(records) == 4  # 2 dates x 2 airlines
    assert {(r.tags["depart_date"], r.tags["airline"]) for r in records} == {
        ("2026-10-30", "THAI"), ("2026-10-30", "Etihad"),
        ("2026-10-31", "THAI"), ("2026-10-31", "Etihad")}


def test_partial_failure_is_not_red_but_total_failure_is():
    calls = {"n": 0}
    def flaky(origin, destination, d, cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Loading results")   # first date fails
        return {"THAI": {"price": 24518, "stops": 0}}
    records, attempted, succeeded = logger.collect(CFG, fetch=flaky, now=NOW)
    assert attempted == 2 and succeeded == 1 and len(records) == 1   # partial ok

    def allfail(*a, **k):
        raise RuntimeError("rate limited")
    _, att, ok = logger.collect(CFG, fetch=allfail, now=NOW)
    assert att == 2 and ok == 0   # main() turns this into exit 2
