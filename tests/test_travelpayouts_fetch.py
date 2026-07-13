from travelpayouts_fetch import airline_name, fetch_calendar


def test_airline_name_maps_known_and_passes_through():
    assert airline_name("EY") == "Etihad"
    assert airline_name("D7") == "AirAsia X"
    assert airline_name("ZZ") == "ZZ"          # unknown code passes through
    assert airline_name("") == "Unknown"


def test_fetch_calendar_parses_api_shape():
    fake = {
        "success": True,
        "data": {
            "2026-10-27": {"origin": "IST", "destination": "DPS", "airline": "G9",
                           "price": 39249, "flight_number": 501, "transfers": 2},
            "2026-10-30": {"origin": "IST", "destination": "DPS", "airline": "D7",
                           "price": 34255, "flight_number": 34, "transfers": 1},
        },
    }
    out = fetch_calendar("IST", "DPS", {"currency": "try"}, get=lambda path: fake)
    assert out["2026-10-27"]["price"] == 39249
    assert out["2026-10-27"]["airline"] == "Air Arabia"
    assert out["2026-10-27"]["airline_code"] == "G9"
    assert out["2026-10-30"]["stops"] == 1
    assert out["2026-10-30"]["airline"] == "AirAsia X"
