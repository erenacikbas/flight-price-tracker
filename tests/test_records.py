from datetime import datetime, timezone
from records import Record, date_to_record, booking_url

CFG = {"currency": "try", "marker": "750309", "adults": 1}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
INFO = {"price": 39249, "airline": "Air Arabia", "airline_code": "G9", "stops": 2}


def test_date_record_tags_and_fields():
    r = date_to_record(ROUTE, CFG, "2026-10-27", INFO, NOW)
    assert isinstance(r, Record)
    assert r.measurement == "flight_price"
    assert r.tags == {"route_id": "IST-DPS", "origin": "IST", "destination": "DPS",
                      "depart_date": "2026-10-27", "airline": "Air Arabia", "currency": "TRY"}
    assert r.fields["price"] == 39249
    assert r.fields["stops"] == 2
    assert r.fields["days_to_departure"] == 107  # 2026-07-12 -> 2026-10-27
    assert r.fields["booking_url"] == "https://www.aviasales.com/search/IST2710DPS1?marker=750309"


def test_booking_url_format():
    url = booking_url("IST", "DPS", "2026-10-26", "750309", 1)
    assert url == "https://www.aviasales.com/search/IST2610DPS1?marker=750309"
