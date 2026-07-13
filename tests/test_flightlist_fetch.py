from flightlist_fetch import (airline_name, airlines_label, airline_logo, _ddmmyyyy,
                              cheapest_per_date_airline, search)


def _flight(dep, price, airlines, legs, flyfrom="SAW"):
    return {"local_departure": dep + "T06:05:00.000Z", "price": price,
            "airlines": airlines, "route": [{}] * legs, "flyFrom": flyfrom, "flyTo": "DPS"}


def test_airline_name_and_label():
    assert airline_name("D7") == "AirAsia X"
    assert airline_name("ZZ") == "ZZ"
    assert airlines_label(["D7", "AK", "JQ"]) == "AirAsia X, AirAsia, Jetstar"
    assert airlines_label([]) == "Unknown"


def test_airline_logo():
    assert airline_logo(["D7", "AK"]) == "https://images.kiwi.com/airlines/64x64/D7.png"
    assert airline_logo([]) == ""


def test_ddmmyyyy():
    assert _ddmmyyyy("2026-10-24") == "24/10/2026"


def test_cheapest_per_date_airline_groups_and_computes_stops():
    flights = [
        _flight("2026-10-26", 40000, ["D7", "AK", "JQ"], 3),   # 3 legs -> 2 stops
        _flight("2026-10-26", 34833, ["D7", "AK", "JQ"], 3),   # cheaper same combo
        _flight("2026-10-26", 49842, ["TG"], 2, flyfrom="IST"),
    ]
    out = cheapest_per_date_airline(flights)
    assert out[("2026-10-26", "AirAsia X, AirAsia, Jetstar")]["price"] == 34833
    assert out[("2026-10-26", "AirAsia X, AirAsia, Jetstar")]["stops"] == 2
    assert out[("2026-10-26", "AirAsia X, AirAsia, Jetstar")]["origin"] == "SAW"
    assert out[("2026-10-26", "AirAsia X, AirAsia, Jetstar")]["logo"] == "https://images.kiwi.com/airlines/64x64/D7.png"
    assert out[("2026-10-26", "THAI")]["origin"] == "IST"


def test_search_builds_params_and_reads_data():
    captured = {}
    def fake_get(params):
        captured.update(params)
        return {"data": [_flight("2026-10-24", 43379, ["GF", "VJ"], 2)]}
    route = {"origin": "IST", "destination": "DPS", "fly_from": "city:IST", "fly_to": "city:DPS",
             "date_range": {"start": "2026-10-24", "end": "2026-11-01"}}
    data = search(route, {"adults": 2, "currency": "TRY"}, get=fake_get)
    assert len(data) == 1
    assert captured["fly_from"] == "city:IST" and captured["fly_to"] == "city:DPS"
    assert captured["date_from"] == "24/10/2026" and captured["date_to"] == "01/11/2026"
    assert captured["adults"] == 2 and captured["curr"] == "TRY" and captured["flight_type"] == "oneway"
