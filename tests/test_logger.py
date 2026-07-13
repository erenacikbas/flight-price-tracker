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
    def fetch(origin, destination, d):
        return {"THAI": {"price": 24518, "stops": 1}, "Sichuan Airlines": {"price": 22829, "stops": 1}}
    records, attempted, succeeded = logger.collect(CFG, fetch=fetch, now=NOW)
    assert attempted == 2 and succeeded == 2
    assert len(records) == 4
    assert {(r.tags["depart_date"], r.tags["airline"]) for r in records} == {
        ("2026-10-30", "THAI"), ("2026-10-30", "Sichuan Airlines"),
        ("2026-10-31", "THAI"), ("2026-10-31", "Sichuan Airlines")}


def test_partial_ok_total_failure_flagged():
    calls = {"n": 0}
    def flaky(o, d, day):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("timeout")
        return {"THAI": {"price": 24518, "stops": 1}}
    recs, att, ok = logger.collect(CFG, fetch=flaky, now=NOW)
    assert att == 2 and ok == 1 and len(recs) == 1

    _, att2, ok2 = logger.collect(CFG, fetch=lambda *a: {}, now=NOW)
    assert att2 == 2 and ok2 == 0   # main() turns this into exit 2
