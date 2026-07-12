from datetime import datetime, timezone
from records import CheapestResult
import logger

CFG = {"currency": "EUR", "seat": "economy", "adults": 1,
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS",
                   "depart_date": "2026-10-26", "trip": "one-way"}]}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)

def test_collect_builds_record_for_priced_route():
    fetch = lambda route, cfg: CheapestResult(468, "Qatar Airways", 35, "typical")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert len(records) == 1
    assert records[0].fields["price"] == 468
    assert hard_failures == 0

def test_collect_counts_hard_failure_when_options_exist_but_unpriced():
    # options were returned (num_options>0) but none had a price -> data broke, not "sold out"
    fetch = lambda route, cfg: CheapestResult(None, "", 30, "typical")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert records == []
    assert hard_failures == 1

def test_collect_no_hard_failure_when_zero_options():
    # genuinely no itineraries (sold out / too far out) -> skip, not a failure
    fetch = lambda route, cfg: CheapestResult(None, "", 0, "")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert records == []
    assert hard_failures == 0
