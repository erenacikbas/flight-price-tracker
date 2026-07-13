from datetime import datetime, timezone
from records import Record, date_airline_record, booking_url

CFG = {"currency": "TRY"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
INFO = {"price": 34833, "stops": 2, "origin": "SAW", "airline": "AirAsia X, AirAsia, Jetstar",
        "logo": "https://images.kiwi.com/airlines/64x64/D7.png",
        "depart_time": "06:05", "duration_min": 1320, "bag_price": 6284}


def test_date_airline_record():
    r = date_airline_record(ROUTE, CFG, "2026-10-26", INFO, NOW)
    assert isinstance(r, Record)
    assert r.tags["depart_date"] == "2026-10-26"
    assert r.tags["airline"] == "AirAsia X, AirAsia, Jetstar"
    assert r.tags["airline_logo"] == "https://images.kiwi.com/airlines/64x64/D7.png"
    assert r.tags["depart_time"] == "06:05"
    assert r.tags["origin"] == "SAW"                      # actual departure airport
    assert r.tags["currency"] == "TRY"
    assert r.tags["booking_url"] == booking_url("SAW", "DPS", "2026-10-26")
    assert r.fields["price"] == 34833
    assert r.fields["stops"] == 2
    assert r.fields["days_to_departure"] == 106           # 2026-07-12 -> 2026-10-26
    assert r.fields["duration_min"] == 1320
    assert r.fields["bag_price"] == 6284


def test_booking_url_is_kiwi_deeplink():
    url = booking_url("SAW", "DPS", "2026-10-26")
    assert url.startswith("https://www.kiwi.com/deep?affilid=flightlistflightlistio")
    assert "from=SAW" in url and "to=DPS" in url and "departure=2026-10-26" in url
