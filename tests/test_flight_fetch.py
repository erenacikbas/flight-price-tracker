from flight_fetch import parse_price, cheapest_per_airline, airline_prices, _stops


class FakeFlight:
    def __init__(self, name, price, stops=0):
        self.name = name
        self.price = price
        self.stops = stops


class FakeResult:
    def __init__(self, flights):
        self.flights = flights


def test_parse_price_variants():
    assert parse_price("TRY 24,518") == 24518
    assert parse_price("TRY\xa034.255") == 34255
    assert parse_price("Price unavailable") is None
    assert parse_price(None) is None


def test_stops_coercion():
    assert _stops(FakeFlight("x", "1", 2)) == 2
    assert _stops(FakeFlight("x", "1", "1 stop")) == 1
    assert _stops(FakeFlight("x", "1", "Nonstop")) == 0


def test_cheapest_per_airline_keeps_min_with_stops():
    res = FakeResult([
        FakeFlight("THAI", "TRY 26,000", 1),
        FakeFlight("THAI", "TRY 24,518", 1),   # cheaper same airline
        FakeFlight("Etihad", "TRY 25,582", 1),
        FakeFlight("Singapore", "Price unavailable"),
    ])
    out = cheapest_per_airline(res)
    assert out == {"THAI": {"price": 24518, "stops": 1}, "Etihad": {"price": 25582, "stops": 1}}


def test_airline_prices_uses_injected_get_flights():
    res = FakeResult([FakeFlight("Qatar Airways", "TRY 26,524", 1)])
    got = airline_prices("IST", "DPS", "2026-10-30", {"currency": "TRY"}, get_flights=lambda **kw: res)
    assert got == {"Qatar Airways": {"price": 26524, "stops": 1}}
