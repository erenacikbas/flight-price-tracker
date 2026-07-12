from datetime import datetime, timezone
from records import Record, airline_to_record, booking_url

CFG = {"cabin": "economy"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
INFO = {"airline": "Qatar Airways", "price": 512.3, "currency": "EUR",
        "stops": 1, "duration_min": 995, "offer_id": "off_1"}


def test_airline_record_tags_and_fields():
    r = airline_to_record(ROUTE, CFG, "2026-10-26", INFO, NOW)
    assert isinstance(r, Record)
    assert r.measurement == "flight_price"
    assert r.tags == {"route_id": "IST-DPS", "origin": "IST", "destination": "DPS",
                      "cabin": "economy", "depart_date": "2026-10-26",
                      "airline": "Qatar Airways", "currency": "EUR"}
    assert r.fields["price"] == 512.3
    assert r.fields["stops"] == 1
    assert r.fields["duration_min"] == 995
    assert r.fields["days_to_departure"] == 106  # 2026-07-12 -> 2026-10-26
    assert "IST" in r.fields["booking_url"] and "2026-10-26" in r.fields["booking_url"]


def test_booking_url_is_google_flights_deeplink():
    url = booking_url("IST", "DPS", "2026-10-26")
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "IST" in url and "DPS" in url
