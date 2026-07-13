"""Fetch cheapest fare per departure date from the Travelpayouts (Aviasales) data API.

Free, no-KYC flight price data. One /v1/prices/calendar call returns the cheapest
fare per day (with airline + stops), in the requested currency (TRY). Data is
cached (fares Aviasales users found recently), so coverage varies by date.
"""
import os
import json
import time
import urllib.request

HOST = "https://api.travelpayouts.com"

# IATA airline code -> display name (common carriers on this and similar routes).
AIRLINES = {
    "QR": "Qatar Airways", "EK": "Emirates", "EY": "Etihad", "TK": "Turkish Airlines",
    "TG": "THAI", "SQ": "Singapore Airlines", "SV": "Saudia", "D7": "AirAsia X",
    "G9": "Air Arabia", "6E": "IndiGo", "GF": "Gulf Air", "WY": "Oman Air",
    "KU": "Kuwait Airways", "MH": "Malaysia Airlines", "CX": "Cathay Pacific",
    "FZ": "flydubai", "PC": "Pegasus", "AK": "AirAsia", "CA": "Air China",
    "MU": "China Eastern", "CZ": "China Southern", "SU": "Aeroflot",
}


def airline_name(code: str) -> str:
    return AIRLINES.get(code, code or "Unknown")


def _token() -> str:
    return os.environ["TRAVELPAYOUTS_TOKEN"]


def _get(path: str) -> dict:
    req = urllib.request.Request(HOST + path, headers={"X-Access-Token": _token(),
                                                       "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read())


def fetch_calendar(origin: str, destination: str, cfg: dict, get=None) -> dict:
    """Return {depart_date: {price, airline, airline_code, stops, flight_number}}.

    One call returns the full cached calendar (~a year of days that have data).
    """
    get = get or _get
    currency = cfg.get("currency", "try").lower()
    one_way = "true" if cfg.get("trip", "one-way") == "one-way" else "false"
    # depart_date month is required by the API but it returns the whole cached range.
    path = (f"/v1/prices/calendar?origin={origin}&destination={destination}"
            f"&depart_date=2026-10&calendar_type=departure_date"
            f"&currency={currency}&one_way={one_way}")
    for attempt in range(1, 4):
        try:
            data = get(path).get("data") or {}
            out = {}
            for day, r in data.items():
                code = r.get("airline", "")
                out[day] = {
                    "price": int(r["price"]),
                    "airline": airline_name(code),
                    "airline_code": code,
                    "stops": int(r.get("transfers", 0)),
                    "flight_number": r.get("flight_number", 0),
                }
            return out
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * attempt)
