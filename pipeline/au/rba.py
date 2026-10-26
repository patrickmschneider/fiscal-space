"""RBA nominal zero-coupon curve (F17), bond-by-bond yields (F16) and benchmark yields (F2).

F17: fitted nominal Australian Government zero-coupon yields, continuously
compounded, 0.25-10 years, daily from 2017 (CSV of the f17hist workbook);
published monthly with data to the previous month-end. The 0-year column is
the cash rate anchor, not a fitted spot rate, and is dropped. The 1992-2016
archive is legacy .xls (no reader without a new dependency) and is skipped.
F2: interpolated yields to maturity (2/3/5/10y nominal, 10y indexed), weekly.
No official real zero-coupon curve exists. Real and breakeven curves come from
F16 (indicative mid yields to maturity of each Treasury Bond and Treasury Indexed
Bond, daily): on each F17 date, every indexed bond with at least a year to run is
a real-yield point at its time to maturity, and its breakeven is the nominal
yield interpolated linearly in time to maturity between the two Treasury Bonds
maturing either side of it, minus the real yield. Indexed bonds outside the
nominal range are not extrapolated. These are yields to maturity on different
coupon and indexation conventions, so breakevens are approximate.
breakeven10y (F2 nominal 10y minus indexed 10y) is kept for continuity.
"""
import csv
import io
import math
import re
from datetime import date, timedelta

PAGE_URL = 'https://www.rba.gov.au/statistics/tables/'
F17_URL = 'https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv'
F2_URL = 'https://www.rba.gov.au/statistics/tables/csv/f2-data.csv'
F16_URL = 'https://www.rba.gov.au/statistics/tables/csv/f16-data.csv'
MIN_INDEXED_YEARS = 1.0  # Shorter indexed bonds are dominated by the indexation lag.
LICENCE_URL = 'https://www.rba.gov.au/copyright/'
BENCHMARKS = {'FCMYGBAG2D': 'nominal2y', 'FCMYGBAG3D': 'nominal3y', 'FCMYGBAG5D': 'nominal5y', 'FCMYGBAG10D': 'nominal10y', 'FCMYGBAGID': 'indexed10y'}
MONTHS = {m: i for i, m in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
START = '2017-01-01'
DAILY_DAYS = 3 * 366  # F17 kept daily for ~3 years; earlier history thinned to month-end dates.
LOW, HIGH = -2.0, 25.0


def _date(text):
    match = re.fullmatch(r'(\d{2})-([A-Z][a-z]{2})-(\d{4})', text.strip())
    if not match or match[2] not in MONTHS:
        return None
    return date(int(match[3]), MONTHS[match[2]], int(match[1])).isoformat()


def _rate(text):
    text = text.strip()
    if not text:
        return None
    value = float(text)
    if not math.isfinite(value) or not LOW <= value <= HIGH:
        raise ValueError(f'RBA yield outside plausible range: {text}')
    return value


def parse_table(raw):
    """Return (series IDs, metadata rows by label, {date: [cells]}) from an RBA statistical CSV."""
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    meta, ids, data = {}, None, {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        if ids is None:
            if label == 'Series ID':
                ids = [c.strip() for c in row[1:]]
            else:
                meta[label] = [c.strip() for c in row[1:]]
            continue
        observed = _date(label)
        if observed is None:
            raise ValueError(f'Unrecognised RBA data row: {label[:40]}')
        if observed in data:
            raise ValueError(f'Duplicate RBA date {observed}')
        data[observed] = (row[1:] + [''] * len(ids))[:len(ids)]
    if not ids or not data:
        raise ValueError('RBA table lacks Series ID header or data')
    if any(u.lower() not in ('per cent per annum', 'per cent annum') for u in meta.get('Units', [])[:len(ids)] if u) or not meta.get('Units'):
        raise ValueError('RBA table units are not per cent per annum')
    return ids, meta, data


def _publication(meta):
    dates = {_date(d) for d in meta.get('Publication date', []) if d}
    return dates.pop() if len(dates) == 1 and None not in dates else None


def parse_f17(raw):
    ids, meta, data = parse_table(raw)
    tenors = []
    for i, sid in enumerate(ids):
        match = re.fullmatch(r'FZCY(\d+)D', sid)
        if not match:
            raise ValueError(f'Unexpected F17 series {sid}')
        if int(match[1]):  # FZCY0D is the cash-rate anchor, not a fitted spot rate.
            tenors.append((i, int(match[1]) / 100))
    if len(tenors) != 40 or any(b[1] <= a[1] for a, b in zip(tenors, tenors[1:])) or tenors[-1][1] != 10:
        raise ValueError('F17 maturities are not 0.25-10 years in 0.25-year steps')
    curves = {}
    for observed, cells in data.items():
        points = [{'tenor': t, 'rate': _rate(cells[i])} for i, t in tenors]
        if any(p['rate'] is not None for p in points):
            curves[observed] = points
    return curves, _publication(meta)


def parse_f2(raw):
    ids, meta, data = parse_table(raw)
    missing = set(BENCHMARKS) - set(ids)
    if missing:
        raise ValueError(f'F2 lacks series {sorted(missing)}')
    columns = {BENCHMARKS[sid]: i for i, sid in enumerate(ids) if sid in BENCHMARKS}
    rows = []
    for observed in sorted(data):
        row = {'date': observed, **{key: _rate(data[observed][i]) for key, i in columns.items()}}
        if any(row[k] is not None for k in columns):
            rows.append(row)
    return rows, _publication(meta)


def parse_f16(raw):
    """Return {date: {'nominal': [(maturity, yield)], 'indexed': [(maturity, yield)]}} from F16."""
    ids, meta, data = parse_table(raw)
    bonds = []
    for i, (title, description) in enumerate(zip(meta.get('Title', []), meta.get('Description', []))):
        match = re.search(r'(\d{2}-[A-Z][a-z]{2}-\d{4})$', description)
        kind = {'Treasury Bond': 'nominal', 'Treasury Indexed Bond': 'indexed'}.get(title)
        if kind is None or not match or not _date(match[1]):
            raise ValueError(f'Unexpected F16 security: {title} {description}')
        bonds.append((i, kind, _date(match[1])))
    if not any(k == 'indexed' for _, k, _ in bonds) or sum(k == 'nominal' for _, k, _ in bonds) < 10:
        raise ValueError('F16 lacks indexed or enough nominal bonds')
    out = {}
    for observed, cells in data.items():
        day = {'nominal': [], 'indexed': []}
        for i, kind, maturity in bonds:
            rate = _rate(cells[i]) if i < len(cells) else None
            if rate is not None and maturity > observed:
                day[kind].append((maturity, rate))
        if day['indexed'] and day['nominal']:
            out[observed] = day
    return out, _publication(meta)


def _years(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25


def indexed_curves(day, observed):
    """Real yields of indexed bonds (>= MIN_INDEXED_YEARS) and breakevens against bracketing nominal bonds."""
    nominal = sorted((_years(observed, m), r) for m, r in day['nominal'])
    real, breakeven = [], []
    for maturity, rate in sorted(day['indexed']):
        t = _years(observed, maturity)
        if t < MIN_INDEXED_YEARS:
            continue
        tenor = round(t, 4)
        real.append({'tenor': tenor, 'rate': rate})
        below = [n for n in nominal if n[0] <= t]
        above = [n for n in nominal if n[0] >= t]
        if below and above:
            (t0, y0), (t1, y1) = below[-1], above[0]
            interpolated = y0 if t1 == t0 else y0 + (y1 - y0) * (t - t0) / (t1 - t0)
            breakeven.append({'tenor': tenor, 'rate': round(interpolated - rate, 6)})
    return real, breakeven


def derive_breakeven(rows):
    return [{'date': r['date'], 'value': round(r['nominal10y'] - r['indexed10y'], 9)}
            for r in rows if r['nominal10y'] is not None and r['indexed10y'] is not None]


def thin(curves):
    """All dates in the latest ~3 years; before that the last observation of each month."""
    dates = sorted(d for d in curves if d >= START)
    cutoff = (date.fromisoformat(dates[-1]) - timedelta(days=DAILY_DAYS)).isoformat()
    month_end = {}
    for d in dates:
        month_end[d[:7]] = d
    keep = sorted({d for d in dates if d >= cutoff} | set(month_end.values()))
    return [{'date': d, 'points': curves[d]} for d in keep], cutoff


def fetch_curve(fetch):
    curves, f17_published = parse_f17(fetch(F17_URL))
    benchmarks, f2_published = parse_f2(fetch(F2_URL))
    f16, f16_published = parse_f16(fetch(F16_URL))
    benchmarks = [r for r in benchmarks if r['date'] >= START]
    rows, cutoff = thin(curves)
    if not rows or not benchmarks:
        raise ValueError('No RBA observations in retained range')
    latest = rows[-1]['date']
    real_rows, breakeven_rows = [], []
    for row in rows:
        if row['date'] in f16:
            real, breakeven = indexed_curves(f16[row['date']], row['date'])
            if real:
                real_rows.append({'date': row['date'], 'points': real})
            if breakeven:
                breakeven_rows.append({'date': row['date'], 'points': breakeven})
    if not real_rows or not breakeven_rows:
        raise ValueError('No F16 indexed-bond curves on F17 dates')
    attribution = 'Source: Reserve Bank of Australia (Statistical Tables F17, F16 and F2), CC BY 4.0. Month-end thinning, real-yield and breakeven curves are calculated by this dashboard; no RBA endorsement.'
    return {
        'schemaVersion': 1, 'status': 'available', 'units': '% per annum',
        'basis': 'RBA fitted nominal Australian Government zero-coupon yields (F17), continuously compounded; tenor in years (0.25-10). Real yields are F16 yields to maturity of individual Treasury Indexed Bonds; breakevens compare them with nominal Treasury Bond yields interpolated to the same maturity.',
        'asOf': latest, 'observationDate': latest, 'publicationDate': f17_published,
        'realAsOf': real_rows[-1]['date'], 'breakevenAsOf': breakeven_rows[-1]['date'], 'bondYieldsPublicationDate': f16_published,
        'benchmarksAsOf': benchmarks[-1]['date'], 'benchmarksPublicationDate': f2_published,
        'dailyFrom': cutoff,
        'sources': [
            {'id': 'rba-f17', 'publisher': 'Reserve Bank of Australia', 'name': 'Reserve Bank of Australia · F17 Zero-coupon interest rates', 'title': 'Zero-coupon interest rates – analytical series (yields)', 'url': PAGE_URL, 'downloadUrls': [F17_URL], 'licence': 'CC BY 4.0', 'licenceUrl': LICENCE_URL, 'attribution': attribution},
            {'id': 'rba-f16', 'publisher': 'Reserve Bank of Australia', 'name': 'Reserve Bank of Australia · F16 Indicative mid rates of Australian Government securities', 'title': 'Indicative mid rates of selected Australian Government securities (daily)', 'url': PAGE_URL, 'downloadUrls': [F16_URL], 'licence': 'CC BY 4.0', 'licenceUrl': LICENCE_URL, 'attribution': attribution},
            {'id': 'rba-f2', 'publisher': 'Reserve Bank of Australia', 'name': 'Reserve Bank of Australia · F2 Capital market yields – government bonds', 'title': 'Capital market yields – government bonds (daily)', 'url': PAGE_URL, 'downloadUrls': [F2_URL], 'licence': 'CC BY 4.0', 'licenceUrl': LICENCE_URL, 'attribution': attribution},
        ],
        'curves': rows, 'realCurves': real_rows, 'breakevenCurves': breakeven_rows,
        'benchmarkSeries': {
            'nominal2y': {'seriesId': 'FCMYGBAG2D', 'label': 'Australian Government 2-year bond yield (interpolated)'},
            'nominal3y': {'seriesId': 'FCMYGBAG3D', 'label': 'Australian Government 3-year bond yield (interpolated)'},
            'nominal5y': {'seriesId': 'FCMYGBAG5D', 'label': 'Australian Government 5-year bond yield (interpolated)'},
            'nominal10y': {'seriesId': 'FCMYGBAG10D', 'label': 'Australian Government 10-year bond yield (interpolated)'},
            'indexed10y': {'seriesId': 'FCMYGBAGID', 'label': 'Australian Government indexed (CPI-linked) bond real yield, 10 years (interpolated)'},
        },
        'benchmarks': benchmarks,
        'breakeven10y': derive_breakeven(benchmarks),
        'breakeven10yBasis': 'Derived: F2 nominal 10-year yield minus F2 indexed 10-year real yield on the same date. Both are interpolated yields to maturity, not zero-coupon rates.',
        'notes': [
            f'Curves are RBA F17 fitted nominal zero-coupon yields, continuously compounded, from 0.25 to 10 years (F17 does not extend beyond 10 years). The 0-year F17 column, which tracks the cash rate, is omitted. Every business day is kept from {cutoff}; earlier dates back to January 2017 are thinned to the last observation of each month. Missing values remain null; non-trading dates are excluded.',
            'Publication lags differ: F17 is published monthly with daily data to the previous month-end (up to about five weeks old), while F2 is published weekly with daily data to a few business days earlier. asOf refers to the F17 curve; benchmarksAsOf refers to F2.',
            f'The RBA does not publish a real (inflation-indexed) zero-coupon curve. The real-yield curve is the F16 indicative yield to maturity of each Treasury Indexed Bond with at least {MIN_INDEXED_YEARS:g} year to run, plotted at its time to maturity on the same dates as the nominal curve. Each breakeven is the nominal yield interpolated linearly between the two Treasury Bonds maturing either side of that indexed bond, minus its real yield; indexed bonds beyond the longest or before the shortest nominal bond have no breakeven. These are yields to maturity on bonds with different coupon, compounding and CPI-indexation conventions, so breakevens are approximate measures of CPI inflation compensation, including inflation risk and relative liquidity premia, not inflation forecasts. Shorter indexed bonds are omitted because the CPI indexation lag dominates their yields.',
            'breakeven10y is kept for continuity: it is a dashboard calculation: the F2 interpolated 10-year nominal bond yield minus the F2 interpolated 10-year indexed bond real yield, on matching dates only, with no interpolation. Because these are yields to maturity on bonds with different coupon, compounding and CPI-indexation conventions, it is not a zero-coupon breakeven; it reflects CPI-linked inflation compensation including inflation risk and relative liquidity premia, not an inflation forecast.',
            'The RBA describes these yields as its own assessments intended for research, which may be revised; they are not benchmarks for regulatory or commercial use. Observation dates are not publication or retrieval dates.',
        ],
    }


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and LOW <= value <= HIGH


def validate_curve(data):
    if data.get('schemaVersion') != 1 or data.get('status') != 'available':
        raise ValueError('Curve dataset not available')
    if not data.get('sources'):
        raise ValueError('Curve sources missing')
    curves = data.get('curves') or []
    if len(curves) < 200:
        raise ValueError('Fewer than 200 curve dates')
    dates = [c['date'] for c in curves]
    for key, as_of in (('realCurves', 'realAsOf'), ('breakevenCurves', 'breakevenAsOf')):
        series = data.get(key) or []
        series_dates = [c['date'] for c in series]
        if len(series) < 200 or series_dates != sorted(set(series_dates)) or not set(series_dates) <= set(dates):
            raise ValueError(f'{key} missing, unordered or on dates without a nominal curve')
        if data.get(as_of) != series_dates[-1]:
            raise ValueError(f'{as_of} does not match the latest {key}')
        for curve in series:
            tenors = [p['tenor'] for p in curve['points']]
            if not tenors or tenors[0] < MIN_INDEXED_YEARS or any(b <= a for a, b in zip(tenors, tenors[1:])):
                raise ValueError(f'{key} maturities invalid on {curve["date"]}')
            if any(not _finite(p['rate']) for p in curve['points']):
                raise ValueError(f'Implausible {key} value on {curve["date"]}')
    real_by = {c['date']: {p['tenor'] for p in c['points']} for c in data['realCurves']}
    if any(not {p['tenor'] for p in c['points']} <= real_by.get(c['date'], set()) for c in data['breakevenCurves']):
        raise ValueError('Breakeven points must sit at indexed-bond maturities')
    if dates != sorted(set(dates)):
        raise ValueError('Curve dates not sorted and unique')
    if data.get('asOf') != dates[-1] or data.get('observationDate') != dates[-1]:
        raise ValueError('Curve asOf does not match latest curve')
    for curve in curves:
        tenors = [p['tenor'] for p in curve['points']]
        if not tenors or any(b <= a for a, b in zip(tenors, tenors[1:])) or tenors[0] <= 0:
            raise ValueError(f'Tenors not strictly increasing on {curve["date"]}')
        rates = [p['rate'] for p in curve['points']]
        if any(r is not None and not _finite(r) for r in rates) or all(r is None for r in rates):
            raise ValueError(f'Implausible or empty curve on {curve["date"]}')
    rows = data.get('benchmarks') or []
    if not rows:
        raise ValueError('No benchmark yields')
    bdates = [r['date'] for r in rows]
    if bdates != sorted(set(bdates)):
        raise ValueError('Benchmark dates not sorted and unique')
    if data.get('benchmarksAsOf') != bdates[-1]:
        raise ValueError('benchmarksAsOf does not match latest benchmark')
    for row in rows:
        values = [row.get(k) for k in BENCHMARKS.values()]
        if any(v is not None and not _finite(v) for v in values) or all(v is None for v in values):
            raise ValueError(f'Implausible or empty benchmark row on {row["date"]}')
    expected = {r['date']: r['nominal10y'] - r['indexed10y'] for r in rows if r.get('nominal10y') is not None and r.get('indexed10y') is not None}
    breakeven = data.get('breakeven10y') or []
    if not breakeven or [b['date'] for b in breakeven] != sorted(expected):
        raise ValueError('breakeven10y dates must be exactly the matched nominal/indexed dates')
    for b in breakeven:
        if not isinstance(b['value'], (int, float)) or abs(b['value'] - expected[b['date']]) > 1e-9:
            raise ValueError(f'breakeven10y does not equal nominal minus indexed on {b["date"]}')
