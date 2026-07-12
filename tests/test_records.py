from datetime import datetime, timezone
from records import CheapestResult, Record, route_to_record

CFG = {"currency": "EUR"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
         "depart_date": "2026-10-26", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)

def test_maps_tags_and_fields():
    c = CheapestResult(price=468, airline="Qatar Airways", num_options=35, price_level="typical")
    r = route_to_record(ROUTE, CFG, c, NOW)
    assert r.measurement == "flight_price"
    assert r.tags == {"route_id": "IST-DPS", "origin": "IST", "destination": "DPS",
                      "trip": "one-way", "currency": "EUR", "price_level": "typical"}
    assert r.fields["price"] == 468
    assert r.fields["num_options"] == 35
    assert r.fields["cheapest_airline"] == "Qatar Airways"
    assert r.fields["days_to_departure"] == 106  # 2026-07-12 -> 2026-10-26
    assert r.time == NOW

def test_missing_price_level_defaults_unknown():
    c = CheapestResult(price=500, airline="X", num_options=1, price_level="")
    r = route_to_record(ROUTE, CFG, c, NOW)
    assert r.tags["price_level"] == "unknown"
