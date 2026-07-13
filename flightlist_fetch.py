"""Fetch flight fares from flightlist.io's JSON API (a thin proxy to Kiwi.com).

One HTTP GET returns the full carrier list (incl. budget carriers Google hides) for a
whole departure-date range, in TRY, with per-flight data. No browser, no auth, works
from any IP. We keep the cheapest fare per (departure date, airline).
"""
import gzip
import json
import os
import urllib.parse
import urllib.request
from datetime import date

API = "https://www.flightlist.io/api/search.php"

# Kiwi/IATA carrier code -> display name (extend as new carriers appear).
AIRLINES = {
    "TG": "THAI", "QR": "Qatar Airways", "EK": "Emirates", "EY": "Etihad",
    "TK": "Turkish Airlines", "SQ": "Singapore Airlines", "SV": "Saudia",
    "D7": "AirAsia X", "AK": "AirAsia", "JQ": "Jetstar", "G9": "Air Arabia",
    "GF": "Gulf Air", "VJ": "VietJet", "PC": "Pegasus", "AI": "Air India",
    "6E": "IndiGo", "FZ": "flydubai", "MH": "Malaysia Airlines", "CX": "Cathay Pacific",
    "CA": "Air China", "MU": "China Eastern", "CZ": "China Southern", "3U": "Sichuan Airlines",
    "TR": "Scoot", "ID": "Batik Air", "OD": "Batik Air Malaysia", "KU": "Kuwait Airways",
    "WY": "Oman Air", "GA": "Garuda Indonesia", "BR": "EVA Air", "PR": "Philippine Airlines",
    "VF": "AJet", "XQ": "SunExpress", "VN": "Vietnam Airlines", "OV": "Salam Air",
}
CABINS = {"economy": "M", "premium-economy": "W", "business": "C", "first": "F"}

# Kiwi's public airline-logo CDN (64x64 PNG per IATA carrier code).
LOGO_CDN = "https://images.kiwi.com/airlines/64x64/{}.png"


def airline_name(code: str) -> str:
    return AIRLINES.get(code, code)


def airlines_label(codes) -> str:
    return ", ".join(airline_name(c) for c in (codes or [])) or "Unknown"


def airline_logo(codes) -> str:
    """Logo URL for the itinerary's first (primary/first-leg) carrier, or '' if none."""
    codes = codes or []
    return LOGO_CDN.format(codes[0]) if codes else ""


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://www.flightlist.io/",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def _ddmmyyyy(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def search(route: dict, cfg: dict, get=None) -> list:
    """Return the raw flight list for a route over its date_range."""
    get = get or _get
    rng = route["date_range"]
    params = {
        "fly_from": route.get("fly_from", "city:" + route["origin"]),
        "fly_to": route.get("fly_to", "city:" + route["destination"]),
        "date_from": _ddmmyyyy(rng["start"]),
        "date_to": _ddmmyyyy(rng["end"]),
        "adults": cfg.get("adults", 2), "children": 0, "infants": 0,
        "selected_cabins": CABINS.get(cfg.get("cabin", "economy"), "M"),
        "curr": cfg.get("currency", "TRY"),
        "limit": route.get("limit", cfg.get("limit", 300)),
        "sort": "price",
        "max_stopovers": route.get("max_stopovers", cfg.get("max_stopovers", 10)),
        "flight_type": "oneway", "enable_vi": "true",
    }
    return (get(params) or {}).get("data", [])


def cheapest_per_date_airline(flights: list) -> dict:
    """{(depart_date, airline_label): {price, stops, origin, airline}} keeping the cheapest."""
    out = {}
    for f in flights:
        try:
            dep = f["local_departure"][:10]
            price = int(f["price"])
        except (KeyError, TypeError, ValueError):
            continue
        airline = airlines_label(f.get("airlines"))
        stops = max(len(f.get("route", [])) - 1, 0)
        key = (dep, airline)
        if key not in out or price < out[key]["price"]:
            out[key] = {"price": price, "stops": stops,
                        "origin": f.get("flyFrom", ""), "airline": airline,
                        "logo": airline_logo(f.get("airlines"))}
    return out
