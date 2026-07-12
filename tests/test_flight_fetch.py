from flight_fetch import select_cheapest, fetch_cheapest

class FakeFlight:
    def __init__(self, price, airlines):
        self.price = price
        self.airlines = airlines

class FakeResult(list):
    current_price = "typical"

def test_select_cheapest_picks_min_valid():
    res = FakeResult([FakeFlight(600, ["A"]), FakeFlight(468, ["Qatar Airways"]), FakeFlight(None, ["B"])])
    c = select_cheapest(res)
    assert c.price == 468
    assert c.airline == "Qatar Airways"
    assert c.num_options == 3
    assert c.price_level == "typical"

def test_select_cheapest_no_valid_returns_none_price():
    res = FakeResult([FakeFlight(None, ["B"]), FakeFlight(0, ["C"])])
    c = select_cheapest(res)
    assert c.price is None
    assert c.num_options == 2

def test_fetch_cheapest_uses_injected_get_flights():
    res = FakeResult([FakeFlight(500, ["Emirates"])])
    route = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
             "depart_date": "2026-10-26", "trip": "one-way"}
    cfg = {"currency": "EUR", "seat": "economy", "adults": 1}
    captured = {}
    def fake_get_flights(q, integration=None):
        captured["integration"] = integration
        return res
    c = fetch_cheapest(route, cfg, get_flights=fake_get_flights)
    assert c.price == 500
    assert c.airline == "Emirates"
    # a cookie-injecting integration must be passed through
    assert captured["integration"] is not None

def test_cookiefetch_sets_socs_header(monkeypatch):
    from flight_fetch import CookieFetch, DEFAULT_SOCS_COOKIE
    seen = {}
    class FakeClient:
        def __init__(self, **kw): pass
        def get(self, url, params=None, headers=None):
            seen["headers"] = headers
            class R: text = "<html></html>"
            return R()
    import flight_fetch
    monkeypatch.setattr(flight_fetch, "Client", FakeClient)
    class Q:
        def params(self): return {"tfs": "x"}
    CookieFetch(DEFAULT_SOCS_COOKIE).fetch_html(Q())
    assert "SOCS=" in seen["headers"]["cookie"]
