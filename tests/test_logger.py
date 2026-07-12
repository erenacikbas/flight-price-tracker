from datetime import datetime, timezone
import logger

CFG = {"currency": "TRY", "seat": "economy", "adults": 1,
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS",
                   "depart_date": "2026-10-26", "trip": "one-way"}]}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)


def test_collect_one_record_per_airline():
    fetch = lambda route, cfg: {"Qatar Airways": 25432, "THAI": 24518, "Emirates": 34002}
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert hard_failures == 0
    assert len(records) == 3
    airlines = {r.tags["airline"] for r in records}
    assert airlines == {"Qatar Airways", "THAI", "Emirates"}
    assert all(r.tags["currency"] == "TRY" for r in records)


def test_collect_hard_failure_when_no_airlines():
    fetch = lambda route, cfg: {}
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert records == []
    assert hard_failures == 1


def test_collect_hard_failure_on_fetch_exception():
    def boom(route, cfg):
        raise RuntimeError("consent page / scrape broke")
    records, hard_failures = logger.collect(CFG, fetch=boom, now=NOW)
    assert records == []
    assert hard_failures == 1
