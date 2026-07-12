import textwrap
from backfill import csv_rows_to_records

def test_parses_csv_into_records(tmp_path):
    csv = tmp_path / "prices.csv"
    csv.write_text(textwrap.dedent("""\
        timestamp_utc,route_id,origin,destination,depart_date,return_date,trip,cheapest_price,currency,cheapest_airline,num_options
        2026-07-08T06:00:04Z,IST-DPS,IST,DPS,2026-10-26,,one-way,512,EUR,Qatar Airways,34
    """))
    recs = csv_rows_to_records(str(csv))
    assert len(recs) == 1
    r = recs[0]
    assert r.measurement == "flight_price"
    assert r.tags["route_id"] == "IST-DPS"
    assert r.tags["currency"] == "EUR"
    assert r.fields["price"] == 512
    assert r.fields["num_options"] == 34
    assert r.fields["cheapest_airline"] == "Qatar Airways"
    assert r.time.year == 2026 and r.time.month == 7 and r.time.day == 8
    assert r.fields["days_to_departure"] == 110

def test_skips_rows_without_price(tmp_path):
    csv = tmp_path / "prices.csv"
    csv.write_text(
        "timestamp_utc,route_id,origin,destination,depart_date,return_date,trip,cheapest_price,currency,cheapest_airline,num_options\n"
        "2026-07-08T06:00:04Z,IST-DPS,IST,DPS,2026-10-26,,one-way,,EUR,,0\n"
    )
    assert csv_rows_to_records(str(csv)) == []
