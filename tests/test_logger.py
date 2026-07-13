from datetime import datetime, timezone
import logger

NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
CFG = {"currency": "TRY",
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way",
                   "fly_from": "city:IST", "fly_to": "city:DPS",
                   "date_range": {"start": "2026-10-24", "end": "2026-11-01"}}]}


def test_route_window():
    w = logger.route_window({"date_range": {"start": "2026-10-30", "end": "2026-11-01"}})
    assert w == {"2026-10-30", "2026-10-31", "2026-11-01"}


def test_collect_keeps_in_window_and_makes_records():
    def fetch(route):
        return {
            ("2026-10-26", "AirAsia X"): {"price": 34833, "stops": 2, "origin": "SAW", "airline": "AirAsia X"},
            ("2026-10-30", "THAI"): {"price": 49842, "stops": 1, "origin": "IST", "airline": "THAI"},
            ("2026-12-25", "THAI"): {"price": 1, "stops": 0, "origin": "IST", "airline": "THAI"},  # out of window
        }
    records, attempted, succeeded = logger.collect(CFG, fetch=fetch, now=NOW)
    assert attempted == 1 and succeeded == 1
    assert {(r.tags["depart_date"], r.tags["airline"]) for r in records} == {
        ("2026-10-26", "AirAsia X"), ("2026-10-30", "THAI")}


def test_collect_error_and_empty_flagged():
    def boom(route):
        raise RuntimeError("api down")
    _, att, ok = logger.collect(CFG, fetch=boom, now=NOW)
    assert att == 1 and ok == 0        # main() -> exit 2

    _, att2, ok2 = logger.collect(CFG, fetch=lambda r: {}, now=NOW)
    assert att2 == 1 and ok2 == 0
