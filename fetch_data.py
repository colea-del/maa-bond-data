"""
Builds data.json for the MAA Bond Worksheet.

  Bonds: FINRA TRACE end-of-day last-sale price and yield, via the open-source
         OpenBB FINRA provider (pip install openbb openbb-finra). Free, no key.
  UST:   U.S. Treasury daily par yield curve XML (official, no key).
         Fallback: FRED constant-maturity series (same Treasury data, ~1 day lag).

If a source fails, the previous values in data.json are kept and the failure is
written to "errors" so the worksheet can show it. Nothing fails silently.
"""
import csv
import datetime as dt
import io
import json
import os
import urllib.request
import xml.etree.ElementTree as ET

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# CUSIP = characters 3-11 of the ISIN
CUSIPS = [
    "59523UAN7", "59523UAY3", "59523UAX5", "59523UAW7", "59523UAV9",
    "59523UAU1", "59523UAS6", "59523UAR8", "59523UAQ0", "59523UAP2",
]

TREASURY_TAGS = {
    "BC_1MONTH": 0.083, "BC_1_5MONTH": 0.125, "BC_2MONTH": 0.167, "BC_3MONTH": 0.25,
    "BC_4MONTH": 0.333, "BC_6MONTH": 0.5, "BC_1YEAR": 1, "BC_2YEAR": 2, "BC_3YEAR": 3,
    "BC_5YEAR": 5, "BC_7YEAR": 7, "BC_10YEAR": 10, "BC_20YEAR": 20, "BC_30YEAR": 30,
}
FRED_IDS = {
    "DGS1MO": 0.083, "DGS3MO": 0.25, "DGS6MO": 0.5, "DGS1": 1, "DGS2": 2, "DGS3": 3,
    "DGS5": 5, "DGS7": 7, "DGS10": 10, "DGS20": 20, "DGS30": 30,
}


def http_get(url, timeout=60):
    # Default urllib user agent on purpose: FRED's bot filter rejected custom ones in testing.
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return r.read().decode("utf-8")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def curve_from_treasury(year):
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}")
    root = ET.fromstring(http_get(url))
    best_date, best = None, None
    for el in root.iter():
        if local(el.tag) != "properties":
            continue
        date, pts = None, {}
        for child in el:
            name = local(child.tag)
            if name == "NEW_DATE" and child.text:
                date = child.text[:10]
            elif name in TREASURY_TAGS and child.text:
                try:
                    pts[str(TREASURY_TAGS[name])] = float(child.text)
                except ValueError:
                    pass
        if date and pts and (best_date is None or date > best_date):
            best_date, best = date, pts
    if not best:
        raise RuntimeError(f"Treasury XML for {year} had no curve entries")
    return {"date": best_date, "source": "U.S. Treasury par yield curve", "points": best}


def curve_from_fred():
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + ",".join(FRED_IDS)
    rows = list(csv.DictReader(io.StringIO(http_get(url))))
    for row in reversed(rows):  # latest row with a full set of values
        pts = {}
        for sid, tenor in FRED_IDS.items():
            v = row.get(sid, "")
            if v not in ("", "."):
                pts[str(tenor)] = float(v)
        if len(pts) == len(FRED_IDS):
            return {"date": row["observation_date"], "source": "FRED (Treasury constant maturity)", "points": pts}
    raise RuntimeError("FRED CSV had no complete row")


def fetch_curve(errors):
    year = dt.date.today().year
    for attempt in (lambda: curve_from_treasury(year),
                    lambda: curve_from_treasury(year - 1),  # early January: new year's feed may be empty
                    curve_from_fred):
        try:
            return attempt()
        except Exception as e:  # noqa: BLE001
            errors.append(f"UST source failed: {type(e).__name__}: {e}")
    return None


def rows_to_dicts(res):
    out = []
    for r in getattr(res, "results", None) or []:
        d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        out.append(d)
    return out


def fetch_trace(errors):
    try:
        from openbb import obb
    except Exception as e:  # noqa: BLE001
        errors.append(f"OpenBB import failed: {e}")
        return {}
    start = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    rows = []
    try:
        rows = rows_to_dicts(obb.finra.fixedincome.bond_historical(cusip=CUSIPS, start_date=start))
    except Exception as e:  # noqa: BLE001 - retry one CUSIP at a time so one bad bond can't sink all
        errors.append(f"TRACE batch request failed, retrying per bond: {e}")
        for c in CUSIPS:
            try:
                rows += rows_to_dicts(obb.finra.fixedincome.bond_historical(cusip=c, start_date=start))
            except Exception as e2:  # noqa: BLE001
                errors.append(f"TRACE {c}: {e2}")
    latest = {}
    for r in rows:
        c = (r.get("cusip") or "").upper()
        if c not in CUSIPS or r.get("price") is None:
            continue
        d = str(r.get("date"))[:10]
        if c not in latest or d > latest[c]["trade_date"]:
            latest[c] = {
                "price": float(r["price"]),
                "ytm": float(r["last_sale_yield"]) if r.get("last_sale_yield") is not None else None,
                "trade_date": d,
            }
    missing = [c for c in CUSIPS if c not in latest]
    if missing:
        errors.append("No TRACE trade in the last 30 days for: " + ", ".join(missing))
    return latest


def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                prev = json.load(f)
        except Exception:  # noqa: BLE001
            prev = {}
    errors = []
    curve = fetch_curve(errors) or prev.get("curve")
    bonds = dict(prev.get("bonds", {}))
    bonds.update(fetch_trace(errors))  # keep last good value for any bond that failed
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "curve": curve,
        "bonds": bonds,
        "errors": errors,
    }
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
