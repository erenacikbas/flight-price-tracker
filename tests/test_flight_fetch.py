from flight_fetch import parse_flight_row, rows_to_cheapest, flights_url, socs_value

THAI = "4:30 PM\n\xa0–\xa0\n2:15 PM+1\nTHAI\n16 hr 45 min\nIST–DPS\n1 stop\n3 hr 30 min BKK\n710 kg CO2e\nAvg emissions\nTRY\xa024,518"
TK = "1:55 AM\n\xa0–\xa0\n7:30 PM\nTurkish Airlines\n12 hr 35 min\nIST–DPS\nNonstop\n526 kg CO2e\n-27% emissions\nTRY\xa029,965"
SICHUAN = "3:40 PM\n\xa0–\xa0\n10:10 PM+1\nSichuan Airlines\n25 hr 30 min\nIST–DPS\n1 stop\n9 hr 40 min TFU\n1,484 kg CO2e\nAvg emissions\nTRY\xa022,829"


def test_parse_flight_row_stops_and_price():
    assert parse_flight_row(THAI) == ("THAI", 24518, 1)
    assert parse_flight_row(TK) == ("Turkish Airlines", 29965, 0)   # Nonstop -> 0
    assert parse_flight_row(SICHUAN) == ("Sichuan Airlines", 22829, 1)


def test_rows_to_cheapest_keeps_min_per_airline_and_skips_junk():
    rows = [THAI, TK, SICHUAN,
            "4:30 PM\n\xa0–\xa0\n2:15 PM+1\nTHAI\n16 hr 45 min\nIST–DPS\n1 stop\nTRY\xa026,000",  # dearer THAI
            "some unrelated li with no flight"]
    out = rows_to_cheapest(rows)
    assert out["THAI"] == {"price": 24518, "stops": 1}
    assert out["Sichuan Airlines"] == {"price": 22829, "stops": 1}
    assert "Turkish Airlines" in out


def test_flights_url_has_tfs_and_forced_try():
    url = flights_url("IST", "DPS", "2026-10-30", {"currency": "try", "adults": 1})
    assert url.startswith("https://www.google.com/travel/flights?tfs=")
    assert "curr=TRY" in url and "gl=TR" in url


def test_socs_value_strips_prefix():
    assert socs_value({"google_socs_cookie": "SOCS=ABC123"}) == "ABC123"
    assert socs_value({"google_socs_cookie": "XYZ"}) == "XYZ"
