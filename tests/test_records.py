from datetime import datetime, timezone
from records import Record, airline_to_record

CFG = {"currency": "TRY"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
         "depart_date": "2026-10-26", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)


def test_airline_record_tags_and_fields():
    r = airline_to_record(ROUTE, CFG, "Qatar Airways", 25432, NOW)
    assert isinstance(r, Record)
    assert r.measurement == "flight_price"
    assert r.tags == {"route_id": "IST-DPS", "origin": "IST", "destination": "DPS",
                      "trip": "one-way", "currency": "TRY", "airline": "Qatar Airways"}
    assert r.fields["price"] == 25432
    assert r.fields["days_to_departure"] == 106  # 2026-07-12 -> 2026-10-26
    assert r.time == NOW


def test_currency_defaults_to_try():
    r = airline_to_record(ROUTE, {}, "THAI", 24518, NOW)
    assert r.tags["currency"] == "TRY"
