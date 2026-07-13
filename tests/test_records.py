from datetime import datetime, timezone
from records import Record, airline_date_record, booking_url

CFG = {"currency": "TRY"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)


def test_airline_date_record():
    r = airline_date_record(ROUTE, CFG, "2026-10-30", "THAI", {"price": 24518, "stops": 1}, NOW)
    assert isinstance(r, Record)
    assert r.measurement == "flight_price"
    assert r.tags["depart_date"] == "2026-10-30"
    assert r.tags["airline"] == "THAI"
    assert r.tags["currency"] == "TRY"
    assert r.tags["booking_url"].startswith("https://www.google.com/travel/flights?q=")
    assert r.fields["price"] == 24518
    assert r.fields["stops"] == 1
    assert r.fields["days_to_departure"] == 110  # 2026-07-12 -> 2026-10-30


def test_booking_url_is_google_flights():
    url = booking_url("IST", "DPS", "2026-10-30")
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "IST" in url and "DPS" in url and "2026-10-30" in url
