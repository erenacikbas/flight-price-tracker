"""Fetch cheapest fare per airline for a route+date from Google Flights (fast-flights 2.2).

Live prices (unlike Travelpayouts' cached data). Datacenter IPs need the SOCS consent
cookie + curr=TRY&gl=TR injected. Google intermittently serves a JS-only "Loading
results" shell (~50%), so we retry per date. Returns cheapest price per airline.
"""
import os
import re
import sys
import time

import fast_flights.core as _core
from fast_flights.primp import Client
from fast_flights import FlightData, Passengers, get_flights as _ff_get_flights

URL = "https://www.google.com/travel/flights"
DEFAULT_SOCS_COOKIE = "SOCS=CAISHAgBEhJnd3NfMjAyNDA5MTAtMF9SQzEaAmVuIAEaBgiAo7C3Bg"
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAY = 6
_PRICE_RE = re.compile(r"[\d.,]+")


def resolve_cookie(cfg: dict) -> str:
    return cfg.get("google_socs_cookie") or os.environ.get("GOOGLE_SOCS_COOKIE") or DEFAULT_SOCS_COOKIE


def install_fetch(cfg: dict) -> None:
    """Patch fast_flights.core.fetch to inject the consent cookie + forced TRY currency."""
    cookie = resolve_cookie(cfg)
    curr = cfg.get("currency", "TRY").upper()
    gl = cfg.get("gl", "TR")
    hl = cfg.get("hl", "en")

    def _fetch(params: dict):
        p = dict(params)
        p["curr"], p["hl"], p["gl"] = curr, hl, gl
        return Client(impersonate="chrome_126", verify=True).get(
            URL, params=p, headers={"cookie": cookie})

    _core.fetch = _fetch


def parse_price(raw) -> int | None:
    if raw is None:
        return None
    s = str(raw).replace("\xa0", " ")
    if "unavailable" in s.lower():
        return None
    m = _PRICE_RE.search(s)
    if not m:
        return None
    digits = m.group(0).replace(".", "").replace(",", "")
    return int(digits) if digits.isdigit() else None


def _stops(flight) -> int:
    s = getattr(flight, "stops", 0)
    if isinstance(s, int):
        return max(s, 0)
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 0


def cheapest_per_airline(result) -> dict:
    """{airline: {price, stops}} keeping each airline's cheapest itinerary."""
    out = {}
    for f in getattr(result, "flights", []):
        price = parse_price(getattr(f, "price", None))
        if price is None or price <= 0:
            continue
        name = (getattr(f, "name", None) or "").strip() or "Unknown"
        if name not in out or price < out[name]["price"]:
            out[name] = {"price": price, "stops": _stops(f)}
    return out


def airline_prices(origin: str, destination: str, date: str, cfg: dict, get_flights=None) -> dict:
    """Cheapest price per airline for one origin/destination/date, in cfg currency (TRY)."""
    get_flights = get_flights or _ff_get_flights
    install_fetch(cfg)
    legs = [FlightData(date=date, from_airport=origin, to_airport=destination)]
    max_attempts = int(cfg.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    delay = int(cfg.get("retry_delay", DEFAULT_RETRY_DELAY))
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = get_flights(flight_data=legs, trip="one-way", seat=cfg.get("cabin", "economy"),
                                 passengers=Passengers(adults=cfg.get("adults", 1)))
            prices = cheapest_per_airline(result)
            if prices:
                return prices
            last_err = RuntimeError("no priced airlines")
        except Exception as e:  # "Loading results" shell raises "No flights found"
            last_err = e
        if attempt < max_attempts:
            time.sleep(delay)
    raise last_err
