from flight_fetch import parse_price, cheapest_per_airline, airline_prices


class FakeFlight:
    def __init__(self, name, price):
        self.name = name
        self.price = price


class FakeResult:
    def __init__(self, flights):
        self.flights = flights


def test_parse_price_variants():
    assert parse_price("TRY 34,002") == 34002
    assert parse_price("TRY\xa034.002") == 34002
    assert parse_price("Price unavailable") is None
    assert parse_price(None) is None


def test_cheapest_per_airline_keeps_min_and_skips_unpriced():
    res = FakeResult([
        FakeFlight("Qatar Airways", "TRY 25,432"),
        FakeFlight("Qatar Airways", "TRY 37,133"),   # more expensive same airline
        FakeFlight("THAI", "TRY 24,518"),
        FakeFlight("Singapore Airlines", "Price unavailable"),
    ])
    prices = cheapest_per_airline(res)
    assert prices == {"Qatar Airways": 25432, "THAI": 24518}


def test_airline_prices_uses_injected_get_flights():
    res = FakeResult([FakeFlight("Emirates", "TRY 34,002")])
    route = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
             "depart_date": "2026-10-26", "trip": "one-way"}
    cfg = {"currency": "TRY", "seat": "economy", "adults": 1}
    prices = airline_prices(route, cfg, get_flights=lambda **kw: res)
    assert prices == {"Emirates": 34002}
