"""Fetch cheapest fare per airline for a route, in TRY.

Uses fast-flights 2.2 (returns the full itinerary list, not just "best flights").
Datacenter IPs need two things injected: the SOCS consent cookie (bypass Google's
EU consent wall) and curr=TRY&gl=TR (force Turkish Lira, since the egress IP would
otherwise geolocate to EUR). We install a patched `fast_flights.core.fetch` that adds
both, then group the results by airline and keep the cheapest price per airline.
"""
import os
import re
import sys
import time

import fast_flights.core as _core
from fast_flights.primp import Client
from fast_flights import FlightData, Passengers, get_flights as _ff_get_flights

URL = "https://www.google.com/travel/flights"
# Known-good SOCS consent cookie (rotatable via cfg/env). See the deployment memory.
DEFAULT_SOCS_COOKIE = "SOCS=CAISHAgBEhJnd3NfMjAyNDA5MTAtMF9SQzEaAmVuIAEaBgiAo7C3Bg"
# Google intermittently serves a JS-only "Loading results" shell (~50% of the time)
# with no flight data in the HTML, which raises "No flights found". Retry through it.
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RETRY_DELAY = 6
_PRICE_RE = re.compile(r"[\d.,]+")


def resolve_cookie(cfg: dict) -> str:
    return cfg.get("google_socs_cookie") or os.environ.get("GOOGLE_SOCS_COOKIE") or DEFAULT_SOCS_COOKIE


def install_fetch(cfg: dict) -> None:
    """Patch fast_flights.core.fetch to inject the consent cookie + forced currency."""
    cookie = resolve_cookie(cfg)
    curr = cfg.get("currency", "TRY")
    gl = cfg.get("gl", "TR")
    hl = cfg.get("hl", "en")

    def _fetch(params: dict):
        p = dict(params)
        p["curr"], p["hl"], p["gl"] = curr, hl, gl
        return Client(impersonate="chrome_126", verify=True).get(
            URL, params=p, headers={"cookie": cookie}
        )

    _core.fetch = _fetch


def parse_price(raw) -> int | None:
    """'TRY 34,002' / 'TRY\\xa034.002' -> 34002 ; 'Price unavailable' -> None."""
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


def cheapest_per_airline(result) -> dict:
    """From a fast-flights Result, return {airline_name: cheapest_price_int}."""
    out = {}
    for f in getattr(result, "flights", []):
        price = parse_price(getattr(f, "price", None))
        if price is None or price <= 0:
            continue
        name = (getattr(f, "name", None) or "").strip() or "Unknown"
        if name not in out or price < out[name]:
            out[name] = price
    return out


def _flight_data(route: dict):
    legs = [FlightData(date=route["depart_date"],
                       from_airport=route["origin"], to_airport=route["destination"])]
    if route.get("trip", "one-way") == "round-trip":
        if not route.get("return_date"):
            raise ValueError(f'route {route.get("id")} is round-trip but has no return_date')
        legs.append(FlightData(date=route["return_date"],
                               from_airport=route["destination"], to_airport=route["origin"]))
    return legs


def airline_prices(route: dict, cfg: dict, get_flights=None) -> dict:
    """Fetch and return {airline: cheapest_price} (in cfg currency, default TRY)."""
    get_flights = get_flights or _ff_get_flights
    install_fetch(cfg)
    legs = _flight_data(route)
    trip = route.get("trip", "one-way")
    max_attempts = int(cfg.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    delay = int(cfg.get("retry_delay", DEFAULT_RETRY_DELAY))
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = get_flights(
                flight_data=legs, trip=trip, seat=cfg.get("seat", "economy"),
                passengers=Passengers(adults=cfg.get("adults", 1)),
            )
            prices = cheapest_per_airline(result)
            if prices:
                return prices
            last_err = RuntimeError("no priced airlines in result")
        except Exception as e:  # transient "Loading results" shell raises "No flights found"
            last_err = e
        print(f"  attempt {attempt}/{max_attempts}: {str(last_err)[:60]}", file=sys.stderr)
        if attempt < max_attempts:
            time.sleep(delay)
    raise last_err
