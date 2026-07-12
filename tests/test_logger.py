from datetime import datetime, timezone
import logger

NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)


def test_route_dates_from_range():
    dates = logger.route_dates({"date_range": {"start": "2026-10-24", "end": "2026-10-27"}})
    assert dates == ["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27"]


def test_route_dates_explicit_list_and_single():
    assert logger.route_dates({"depart_dates": ["2026-10-26"]}) == ["2026-10-26"]
    assert logger.route_dates({"depart_date": "2026-10-26"}) == ["2026-10-26"]


CFG = {"cabin": "economy",
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS",
                   "date_range": {"start": "2026-10-24", "end": "2026-10-25"}}]}


def test_collect_records_per_date_and_airline():
    def fetch(origin, destination, d, cfg):
        return {"Qatar Airways": {"airline": "Qatar Airways", "price": 500.0, "currency": "EUR"},
                "THAI": {"airline": "THAI", "price": 480.0, "currency": "EUR"}}
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert hard_failures == 0
    assert len(records) == 4  # 2 dates x 2 airlines
    assert {r.tags["depart_date"] for r in records} == {"2026-10-24", "2026-10-25"}


def test_collect_hard_failure_on_empty_and_error():
    records, hf = logger.collect(CFG, fetch=lambda *a, **k: {}, now=NOW)
    assert records == [] and hf == 2  # both dates empty

    def boom(*a, **k):
        raise RuntimeError("duffel down")
    records2, hf2 = logger.collect(CFG, fetch=boom, now=NOW)
    assert records2 == [] and hf2 == 2
