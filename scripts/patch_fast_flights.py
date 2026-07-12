# scripts/patch_fast_flights.py
"""Apply a guard to fast-flights 3.0.2's parser so itineraries with no price
in the expected slot are skipped instead of raising IndexError.

Temporary: remove once fixed upstream. Idempotent.
"""
import os
import fast_flights

TARGET = "        flight = k[0]\n        price = k[1][0][1]"
GUARDED = ("        flight = k[0]\n"
           "        if not k[1] or not k[1][0]:  # guard: no price in this slot\n"
           "            continue\n"
           "        price = k[1][0][1]")


def main() -> int:
    path = os.path.join(os.path.dirname(fast_flights.__file__), "parser.py")
    src = open(path, encoding="utf-8").read()
    if "no price in this slot" in src:
        print("already patched")
        return 0
    if TARGET not in src:
        raise SystemExit(f"patch anchor not found in {path} — fast-flights version changed?")
    open(path, "w", encoding="utf-8").write(src.replace(TARGET, GUARDED))
    print("patched", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
