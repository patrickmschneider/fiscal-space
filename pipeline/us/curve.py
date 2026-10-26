"""US Treasury daily par yield curves: nominal (CMT) and real (TIPS), with derived breakevens.

Source: US Department of the Treasury, "Daily Treasury Par Yield Curve Rates" and
"Daily Treasury Par Real Yield Curve Rates", one CSV per calendar year. These are
PAR yields (bond-equivalent, semiannual compounding) read from Treasury's
monotone convex spline fitted to on-the-run securities; they are NOT zero-coupon
spot rates like the Bank of England and RBA fitted curves.

Nominal tenors vary over time (2-month from Oct 2018, 4-month from Oct 2022,
1.5-month from Feb 2025); columns absent from a year's file are omitted for
that date; blank cells (including a new maturity's pre-introduction rows) stay null; nothing is
interpolated. Breakeven = nominal par minus real par at matched tenors (5, 7,
10, 20, 30 years) on matched dates: an approximation of inflation
compensation including inflation risk and relative liquidity premia.

Overlay: the Federal Reserve Board staff TIPS curve (Gurkaynak, Sack and Wright,
FEDS 2008-05) gives par real yields and par inflation compensation for every year
from 2 to 20, filling the short end Treasury does not publish. It is a different
fitted model, published with about a week's lag, so it is kept as separate series
on the Treasury dates and is never mixed into the Treasury curves. If its download
fails the Treasury curves still publish, with the failure recorded.
"""
import csv
import io
import math
import re
from datetime import date, timedelta

from .text import long_date

PAGE_URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve'
REAL_PAGE_URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve'
METHOD_URL = 'https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology'
CSV_URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv'
KINDS = {'nominal': 'daily_treasury_yield_curve', 'real': 'daily_treasury_real_yield_curve'}
START = '2017-01-01'
DAILY_DAYS = 3 * 366  # every business day for ~3 years; earlier history thinned to month-ends (as the AU edition).
LOW, HIGH = -5.0, 25.0
MIN_CURVE_DATES, MIN_BENCHMARKS = 200, 1000  # a live run has ~830 curve dates and ~2,450 benchmark days
NOMINAL_MONTHS = (1, 1.5, 2, 3, 4, 6)
NOMINAL_YEARS = (1, 2, 3, 5, 7, 10, 20, 30)
REAL_YEARS = (5, 7, 10, 20, 30)
BREAKEVEN_TENORS = (5.0, 7.0, 10.0, 20.0, 30.0)
FRB_URL = 'https://www.federalreserve.gov/data/yield-curve-tables/feds200805.csv'
FRB_PAGE = 'https://www.federalreserve.gov/data/tips-yield-curve-and-inflation-compensation.htm'
FRB_TENORS = tuple(float(n) for n in range(2, 21))
BENCHMARKS = {'nominal2y': ('nominal', 2.0), 'nominal5y': ('nominal', 5.0), 'nominal10y': ('nominal', 10.0), 'nominal30y': ('nominal', 30.0), 'indexed10y': ('real', 10.0)}


def _tenor_years(months=None, years=None):
    return round(months / 12, 6) if months is not None else float(years)


EXPECTED = {
    'nominal': {_tenor_years(months=m) for m in NOMINAL_MONTHS} | {_tenor_years(years=y) for y in NOMINAL_YEARS},
    'real': {_tenor_years(years=y) for y in REAL_YEARS},
}


def csv_url(year, kind):
    return CSV_URL.format(year=int(year), kind=KINDS[kind])


def _header_tenor(label):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(mo|mos|month|months|yr|yrs|year|years)', label.strip().lower())
    if not match:
        raise ValueError(f'Unrecognised Treasury tenor column: {label!r}')
    value = float(match[1])
    return _tenor_years(months=value) if match[2].startswith('mo') else _tenor_years(years=value)


def _date(text):
    match = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', text.strip())
    if not match:
        raise ValueError(f'Unrecognised Treasury date: {text[:20]!r}')
    return date(int(match[3]), int(match[1]), int(match[2])).isoformat()


def _rate(text):
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f'Non-numeric Treasury yield: {text[:20]!r}') from None
    if not math.isfinite(value) or not LOW <= value <= HIGH:
        raise ValueError(f'Treasury yield outside plausible range: {text}')
    return value


def parse_csv(raw, kind='nominal', year=None):
    """Return {iso date: [{tenor, rate}]} for one Treasury yearly CSV (tenors ascending, in years)."""
    if kind not in KINDS:
        raise ValueError('Unsupported Treasury curve kind')
    text = raw.decode('utf-8-sig')
    if text.lstrip().startswith('<'):
        raise ValueError('Treasury returned HTML instead of CSV')
    rows = [r for r in csv.reader(io.StringIO(text)) if r and any(c.strip() for c in r)]
    if not rows or rows[0][0].strip() != 'Date':
        raise ValueError('Treasury CSV lacks a Date header')
    tenors = [_header_tenor(c) for c in rows[0][1:]]
    if len(tenors) < 3 or len(set(tenors)) != len(tenors) or not set(tenors) <= EXPECTED[kind]:
        raise ValueError(f'Unexpected {kind} Treasury tenors: {tenors}')
    order = sorted(range(len(tenors)), key=lambda i: tenors[i])
    curves = {}
    for row in rows[1:]:
        if len(row) != len(tenors) + 1:
            raise ValueError(f'Treasury CSV row has {len(row)} cells, expected {len(tenors) + 1}')
        observed = _date(row[0])
        if year is not None and int(observed[:4]) != int(year):
            raise ValueError(f'Treasury {year} CSV contains {observed}')
        if observed in curves:
            raise ValueError(f'Duplicate Treasury date {observed}')
        points = [{'tenor': tenors[i], 'rate': _rate(row[i + 1])} for i in order]
        if any(p['rate'] is not None for p in points):
            curves[observed] = points
    return curves


def derive_breakevens(nominal, real):
    """Nominal minus real par yield at the five matched tenors on matched dates; null where either is missing."""
    result = {}
    for observed in sorted(nominal.keys() & real.keys()):
        n = {p['tenor']: p['rate'] for p in nominal[observed]}
        r = {p['tenor']: p['rate'] for p in real[observed]}
        points = [{'tenor': t, 'rate': round(n[t] - r[t], 6) if n.get(t) is not None and r.get(t) is not None else None}
                  for t in BREAKEVEN_TENORS if t in r]
        if any(p['rate'] is not None for p in points):
            result[observed] = points
    return result


def benchmark_rows(nominal, real):
    rows = []
    for observed in sorted(nominal.keys() | real.keys()):
        curves = {'nominal': {p['tenor']: p['rate'] for p in nominal.get(observed, [])},
                  'real': {p['tenor']: p['rate'] for p in real.get(observed, [])}}
        row = {'date': observed, **{key: curves[kind].get(tenor) for key, (kind, tenor) in BENCHMARKS.items()}}
        if any(row[k] is not None for k in BENCHMARKS):
            rows.append(row)
    return rows


def parse_frb(raw):
    """Fed TIPS file -> ({date: real par points}, {date: breakeven par points}), tenors 2-20 years."""
    lines = raw.decode('utf-8-sig').splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith('Date,')), None)
    if start is None:
        raise ValueError('Fed TIPS file has no Date header')
    rows = csv.DictReader(lines[start:])
    columns = {f'{prefix}{int(t):02d}' for prefix in ('TIPSPY', 'BKEVENPY') for t in FRB_TENORS}
    if not columns <= set(rows.fieldnames or []):
        raise ValueError('Fed TIPS file lacks par real yield or par inflation compensation columns')
    real, breakeven = {}, {}
    for row in rows:
        day = date.fromisoformat(row['Date']).isoformat()
        if day < START:
            continue
        for prefix, store in (('TIPSPY', real), ('BKEVENPY', breakeven)):
            points = []
            for t in FRB_TENORS:
                text = row[f'{prefix}{int(t):02d}'].strip()
                rate = None if text in ('', 'NA') else round(float(text), 4)
                if rate is not None and not (LOW <= rate <= HIGH):
                    raise ValueError(f'Implausible Fed TIPS {prefix} rate {rate} on {day}')
                points.append({'tenor': t, 'rate': rate})
            if any(p['rate'] is not None for p in points):
                if day in store:
                    raise ValueError(f'Duplicate Fed TIPS date {day}')
                store[day] = points
    if not real or not breakeven:
        raise ValueError('Fed TIPS file has no observations in the retained range')
    return real, breakeven


def thin_dates(dates):
    """All dates in the latest ~3 years; before that the last observation of each month."""
    dates = sorted(dates)
    cutoff = (date.fromisoformat(dates[-1]) - timedelta(days=DAILY_DAYS)).isoformat()
    month_end = {}
    for d in dates:
        month_end[d[:7]] = d
    return sorted({d for d in dates if d >= cutoff} | set(month_end.values())), cutoff


def fetch_curve(fetch, today=None):
    today = today or date.today()
    first = int(START[:4])
    nominal, real, urls = {}, {}, {'nominal': [], 'real': []}
    for year in range(first, today.year + 1):
        for kind, store in (('nominal', nominal), ('real', real)):
            url = csv_url(year, kind)
            parsed = parse_csv(fetch(url), kind, year)
            if not parsed and year != today.year:
                raise ValueError(f'Treasury {kind} CSV for {year} has no observations')
            store.update(parsed)
            urls[kind].append(url)
    nominal = {d: v for d, v in nominal.items() if d >= START}
    real = {d: v for d, v in real.items() if d >= START}
    if not nominal or not real:
        raise ValueError('No Treasury observations in retained range')
    breakevens = derive_breakevens(nominal, real)
    keep, cutoff = thin_dates(nominal)
    def rows(curves):
        return [{'date': d, 'points': curves[d]} for d in keep if d in curves]
    try:
        frb_real, frb_breakeven = parse_frb(fetch(FRB_URL))
        frb_error = None
    except Exception as exc:  # The overlay is supplementary; the Treasury curves still publish.
        frb_real, frb_breakeven, frb_error = {}, {}, str(exc)
    benchmarks = benchmark_rows(nominal, real)
    breakeven10y = [{'date': r['date'], 'value': round(r['nominal10y'] - r['indexed10y'], 6)}
                    for r in benchmarks if r['nominal10y'] is not None and r['indexed10y'] is not None]
    latest = keep[-1]
    attribution = 'Source: U.S. Department of the Treasury, Daily Treasury Par Yield Curve Rates and Daily Treasury Par Real Yield Curve Rates (public domain U.S. Government data). Breakevens, month-end thinning and date comparisons are calculated by this dashboard; no Treasury endorsement.'
    return {
        'schemaVersion': 1, 'status': 'available', 'units': '% per annum',
        'basis': 'US Treasury daily par yield curves (nominal CMT and real TIPS), bond-equivalent yields with semiannual compounding; tenor in years. These are par yields, not zero-coupon spot rates. Breakeven = nominal par yield minus real par yield at the same maturity on the same date.',
        'asOf': latest, 'observationDate': latest, 'publicationDate': None,
        'realAsOf': max(real), 'breakevenAsOf': max(breakevens) if breakevens else None,
        'benchmarksAsOf': benchmarks[-1]['date'], 'dailyFrom': cutoff,
        'sources': [
            {'id': 'ust-par-nominal', 'publisher': 'U.S. Department of the Treasury', 'name': 'U.S. Treasury · Daily Treasury Par Yield Curve Rates', 'title': 'Daily Treasury par yield curve rates (nominal, 1 month to 30 years)', 'url': PAGE_URL, 'downloadUrls': urls['nominal'], 'licence': 'Public domain (U.S. Government work)', 'methodologyUrl': METHOD_URL, 'attribution': attribution},
            {'id': 'ust-par-real', 'publisher': 'U.S. Department of the Treasury', 'name': 'U.S. Treasury · Daily Treasury Par Real Yield Curve Rates', 'title': 'Daily Treasury par real yield curve rates (TIPS, 5 to 30 years)', 'url': REAL_PAGE_URL, 'downloadUrls': urls['real'], 'licence': 'Public domain (U.S. Government work)', 'methodologyUrl': METHOD_URL, 'attribution': attribution},
            *([] if frb_error else [{'id': 'frb-tips', 'publisher': 'Federal Reserve Board', 'name': 'Federal Reserve Board · The TIPS Yield Curve and Inflation Compensation (staff estimates)', 'title': 'Gurkaynak, Sack and Wright TIPS yield curve: par real yields and par inflation compensation, 2 to 20 years', 'url': FRB_PAGE, 'downloadUrls': [FRB_URL], 'licence': 'Public domain (U.S. Government work); staff research product, not an official statistical release', 'attribution': 'Source: Federal Reserve Board, The TIPS Yield Curve and Inflation Compensation (Gurkaynak, Sack and Wright, FEDS 2008-05). Staff estimates, subject to delay and revision.'}]),
        ],
        'curves': rows(nominal), 'realCurves': rows(real), 'breakevenCurves': rows(breakevens),
        'frbRealCurves': rows(frb_real), 'frbBreakevenCurves': rows(frb_breakeven),
        'frbAsOf': max(d for d in keep if d in frb_breakeven) if frb_breakeven and any(d in frb_breakeven for d in keep) else None,
        **({'frbError': frb_error} if frb_error else {}),
        'benchmarkSeries': {
            'nominal2y': {'seriesId': '2 Yr', 'label': 'US Treasury 2-year par yield (nominal)'},
            'nominal5y': {'seriesId': '5 Yr', 'label': 'US Treasury 5-year par yield (nominal)'},
            'nominal10y': {'seriesId': '10 Yr', 'label': 'US Treasury 10-year par yield (nominal)'},
            'nominal30y': {'seriesId': '30 Yr', 'label': 'US Treasury 30-year par yield (nominal)'},
            'indexed10y': {'seriesId': '10 YR (real)', 'label': 'US Treasury 10-year par real yield (TIPS)'},
        },
        'benchmarks': benchmarks,
        'breakeven10y': breakeven10y,
        'breakeven10yBasis': 'Derived: Treasury 10-year nominal par yield minus 10-year TIPS par real yield on the same date. Both are par (bond-equivalent, semiannual) yields read from Treasury fitted curves, not zero-coupon rates.',
        'notes': [
            'Curves are US Treasury par yield curves: the yield at which a hypothetical Treasury security priced at par would trade, read from Treasury\'s monotone convex spline fitted to bid-side prices of the most recently auctioned securities. Yields are bond-equivalent with semiannual compounding. They are par yields, not zero-coupon spot rates. Maturities under one year are shown in years (for example, 6 months = 0.5).',
            f'Every business day is shown from {long_date(cutoff)}; earlier dates back to January 2017 are thinned to the last observation of each month. Daily benchmark yields and the 10-year breakeven are kept for every business day since January 2017. Missing values are left blank, not interpolated; non-trading dates are excluded. Nominal maturities vary over time: 2-month from October 2018, 4-month from October 2022 and 1.5-month from February 2025. Before a maturity was introduced it is left blank, as in the Treasury files.',
            'Breakevens are a dashboard calculation: nominal par yield minus TIPS real par yield at matched 5, 7, 10, 20 and 30-year maturities on matching dates only. Because both are par yields on coupon-bearing securities rather than zero-coupon rates, this is an approximation of CPI-U inflation compensation; it includes inflation risk premia and relative liquidity premia (TIPS are less liquid) and is not an inflation forecast.',
            'The dashed overlay on the real-yield and breakeven charts is the Federal Reserve Board staff TIPS curve (Gurkaynak, Sack and Wright): par real yields and par inflation compensation for each maturity from 2 to 20 years. It is a separately fitted model, not an official Federal Reserve statistic, and is published with about a week\'s lag, so each chart shows its latest date on or before the selected date. Its values differ from Treasury\'s at matching maturities because the two curves are fitted differently.' if not frb_error else f'The Federal Reserve Board staff TIPS curve overlay could not be refreshed ({frb_error}).',
            'Treasury publishes the curves each business day after market close; observation dates are not publication or retrieval dates. Treasury may revise past values.',
        ],
    }


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and LOW <= value <= HIGH


def _check_curves(curves, kind, label):
    dates = [c['date'] for c in curves]
    if dates != sorted(set(dates)):
        raise ValueError(f'{label} dates not sorted and unique')
    for curve in curves:
        tenors = [p['tenor'] for p in curve['points']]
        if not tenors or any(b <= a for a, b in zip(tenors, tenors[1:])) or not set(tenors) <= kind:
            raise ValueError(f'{label} tenors unexpected or not increasing on {curve["date"]}')
        rates = [p['rate'] for p in curve['points']]
        if any(r is not None and not _finite(r) for r in rates) or all(r is None for r in rates):
            raise ValueError(f'Implausible or empty {label} on {curve["date"]}')
    return dates


def validate_curve(data):
    if data.get('schemaVersion') != 1 or data.get('status') != 'available':
        raise ValueError('Curve dataset not available')
    if not data.get('sources') or any(not s.get('url', '').startswith('https://') for s in data['sources']):
        raise ValueError('Curve sources missing or not HTTPS')
    curves, real, breakeven = data.get('curves') or [], data.get('realCurves') or [], data.get('breakevenCurves') or []
    if min(len(curves), len(real), len(breakeven)) < MIN_CURVE_DATES:
        raise ValueError(f'Fewer than {MIN_CURVE_DATES} nominal, real or breakeven curve dates')
    dates = _check_curves(curves, EXPECTED['nominal'], 'nominal curve')
    real_dates = _check_curves(real, EXPECTED['real'], 'real curve')
    breakeven_dates = _check_curves(breakeven, set(BREAKEVEN_TENORS), 'breakeven curve')
    if data.get('asOf') != dates[-1] or data.get('observationDate') != dates[-1]:
        raise ValueError('Curve asOf does not match latest curve')
    if data.get('realAsOf') != real_dates[-1] or data.get('breakevenAsOf') != breakeven_dates[-1]:
        raise ValueError('realAsOf/breakevenAsOf do not match latest curves')
    if not set(real_dates) <= set(dates) or len(set(dates) - set(real_dates)) > max(5, len(dates) // 50):
        raise ValueError('Real and nominal curves are not matched by date')
    if dates[-1] != real_dates[-1]:
        raise ValueError('Latest nominal and real curve dates differ')
    nominal_by, real_by = {c['date']: c['points'] for c in curves}, {c['date']: c['points'] for c in real}
    matched = [d for d in real_dates if any(
        p['rate'] is not None and next((q['rate'] for q in nominal_by[d] if q['tenor'] == p['tenor']), None) is not None
        for p in real_by[d])]
    if breakeven_dates != matched:
        raise ValueError('Breakeven dates are not exactly the matched nominal/real dates')
    for curve in breakeven:
        n = {p['tenor']: p['rate'] for p in nominal_by[curve['date']]}
        r = {p['tenor']: p['rate'] for p in real_by[curve['date']]}
        for p in curve['points']:
            expected = n[p['tenor']] - r[p['tenor']] if n.get(p['tenor']) is not None and r.get(p['tenor']) is not None else None
            if (expected is None) != (p['rate'] is None) or (expected is not None and abs(p['rate'] - expected) > 1e-6):
                raise ValueError(f'Breakeven is not nominal minus real on {curve["date"]} at {p["tenor"]}y')
    frb_real, frb_breakeven = data.get('frbRealCurves') or [], data.get('frbBreakevenCurves') or []
    if frb_real or frb_breakeven:
        frb_dates = _check_curves(frb_breakeven, set(FRB_TENORS), 'Fed TIPS breakeven curve')
        if not set(_check_curves(frb_real, set(FRB_TENORS), 'Fed TIPS real curve')) <= set(dates) or not set(frb_dates) <= set(dates):
            raise ValueError('Fed TIPS curves fall on dates without a Treasury curve')
        if data.get('frbAsOf') != frb_dates[-1] or not any(s.get('id') == 'frb-tips' for s in data['sources']):
            raise ValueError('Fed TIPS overlay lacks a matching frbAsOf or source')
    elif not data.get('frbError'):
        raise ValueError('Fed TIPS overlay missing without a recorded download failure')
    latest = nominal_by[dates[-1]]
    if {p['tenor'] for p in latest if p['rate'] is not None} < {2.0, 10.0, 30.0}:
        raise ValueError('Latest nominal curve lacks 2, 10 or 30-year yields')
    rows = data.get('benchmarks') or []
    if len(rows) < MIN_BENCHMARKS:
        raise ValueError('Too few benchmark yields')
    bdates = [r['date'] for r in rows]
    if bdates != sorted(set(bdates)):
        raise ValueError('Benchmark dates not sorted and unique')
    if data.get('benchmarksAsOf') != bdates[-1]:
        raise ValueError('benchmarksAsOf does not match latest benchmark')
    for row in rows:
        values = [row.get(k) for k in BENCHMARKS]
        if any(v is not None and not _finite(v) for v in values) or all(v is None for v in values):
            raise ValueError(f'Implausible or empty benchmark row on {row["date"]}')
        for key, (kind, tenor) in BENCHMARKS.items():
            source = (nominal_by if kind == 'nominal' else real_by).get(row['date'])
            if source is not None and next((p['rate'] for p in source if p['tenor'] == tenor), None) != row.get(key):
                raise ValueError(f'Benchmark {key} disagrees with curve on {row["date"]}')
    expected = {r['date']: r['nominal10y'] - r['indexed10y'] for r in rows if r.get('nominal10y') is not None and r.get('indexed10y') is not None}
    series = data.get('breakeven10y') or []
    if not series or [b['date'] for b in series] != sorted(expected):
        raise ValueError('breakeven10y dates must be exactly the matched nominal/real dates')
    for b in series:
        if not isinstance(b['value'], (int, float)) or abs(b['value'] - expected[b['date']]) > 1e-6:
            raise ValueError(f'breakeven10y does not equal nominal minus real on {b["date"]}')
