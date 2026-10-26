"""OMB Historical Tables: federal outlays by function and receipts by source, with OMB fiscal-year GDP.

Scope: the federal government, unified budget (on- plus off-budget), cash-basis
outlays and receipts as published in the Historical Tables volume of the
Budget of the U.S. Government. One edition is used throughout: the landing page
is scraped for the current histNNzN_fyYYYY.xlsx links and every table must
come from the same budget year.

Only actual years are kept. OMB columns labelled "estimate" (the
administration's projections) are dropped, and the last actual year must equal
the last year of Table 1.1, which contains actuals only. The 1976 transition
quarter (TQ) is not a fiscal year and is excluded.

Years are labelled 'YYYY-YY' by the calendar year in which the fiscal year
starts: FY2025 (October 2024 to September 2025) is '2024-25'. Fiscal years to
FY1976 ran July to June. GDP shares use the fiscal-year GDP published by OMB in
Table 1.2 of the same edition, so ratios are internally consistent.
"""
import io
import re
import warnings
import openpyxl

PAGE = 'https://www.whitehouse.gov/omb/information-resources/budget/historical-tables/'
LICENCE = 'Public domain (U.S. Government work, 17 U.S.C. 105)'
LICENCE_URL = 'https://www.whitehouse.gov/copyright/'
ATTRIBUTION = ('Source: Office of Management and Budget, Historical Tables, Budget of the U.S. Government. '
               'Groupings and GDP shares are calculated by this dashboard; no OMB endorsement.')
PUBLISHER = 'Office of Management and Budget'
UNIT = 'USD million'
FIRST_YEAR = 1940
MIN_YEARS = 5
MAX_ROUNDING = 5  # US$ million; OMB lines are rounded independently.
TABLES = {'1.1': 'hist01z1', '1.2': 'hist01z2', '2.1': 'hist02z1', '2.4': 'hist02z4', '2.5': 'hist02z5', '3.1': 'hist03z1'}
EMPTY = '..........'

# Output category -> OMB Table 3.1 functions (budget function codes in brackets in the notes).
FUNCTIONS = [
    ('National defense', ['national defense']),
    ('Social Security', ['social security']),
    ('Medicare', ['medicare']),
    ('Health (Medicaid and other)', ['health']),
    ('Income security', ['income security']),
    ('Veterans benefits and services', ['veterans benefits and services']),
    ('Education, training, employment and social services', ['education, training, employment, and social services']),
    ('Transportation', ['transportation']),
    ('Commerce and housing credit', ['commerce and housing credit']),
    ('Other functions', ['energy', 'natural resources and environment', 'community and regional development',
                         'international affairs', 'general science, space, and technology', 'agriculture',
                         'administration of justice', 'general government', 'allowances']),
    ('Net interest', ['net interest']),
    ('Undistributed offsetting receipts', ['undistributed offsetting receipts']),
]
SUPERFUNCTIONS = {'human resources': ['education, training, employment, and social services', 'health', 'medicare',
                                      'income security', 'social security', 'veterans benefits and services'],
                  'physical resources': ['energy', 'natural resources and environment', 'commerce and housing credit',
                                         'transportation', 'community and regional development'],
                  'other functions': ['international affairs', 'general science, space, and technology', 'agriculture',
                                      'administration of justice', 'general government', 'allowances']}
# Categories that OMB can legitimately publish as net negative outlays (loan reestimates, asset sales, offsets).
MAY_BE_NEGATIVE = {'Education, training, employment and social services', 'Commerce and housing credit', 'Veterans benefits and services',
                   'Other functions', 'Undistributed offsetting receipts'}
RECEIPTS = ['Individual income taxes', 'Corporation income taxes', 'Social Security payroll taxes (OASDI)',
            'Medicare payroll taxes (hospital insurance)', 'Other social insurance and retirement receipts',
            'Excise taxes', 'Customs duties and fees', 'Estate and gift taxes',
            'Federal Reserve deposits of earnings', 'Other miscellaneous receipts']
ROUNDING = 'Rounding adjustment'
NON_TAX = {'Federal Reserve deposits of earnings', 'Other miscellaneous receipts'}


def label(value):
    return re.sub(r'\s*\(\d\)$', '', ' '.join(str(value).split())).lower() if value is not None else ''


def number(value):
    """OMB cells: numbers, '..........' (nil), '*' / '-*' (under $500 thousand)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not (-1e9 < value < 1e9):
            raise ValueError('Implausible OMB number')
        return float(value)
    text = str(value).strip() if value is not None else ''
    if text == EMPTY or text in ('*', '-*'):
        return 0.0
    raise ValueError(f'Unexpected OMB cell: {value!r}')


def year_label(fy):
    return f'{fy - 1}-{str(fy)[2:]}'


def links(html):
    """Current edition xlsx links from the landing page; all must share one budget year."""
    found = {}
    for url, code, fy in re.findall(r'href="(https://www\.whitehouse\.gov/wp-content/uploads/\d{4}/\d{2}/(hist\d{2}z\d)_fy(\d{4})\.xlsx)"', html):
        found.setdefault(code, set()).add((url, int(fy)))
    years = {fy for urls in found.values() for _, fy in urls}
    if len(years) != 1 or any(len(v) != 1 for v in found.values()):
        raise ValueError('Cannot identify a single OMB Historical Tables edition')
    missing = [t for t, code in TABLES.items() if code not in found]
    if missing:
        raise ValueError(f'OMB landing page lacks tables {missing}')
    match = re.search(r'"dateModified":"(\d{4}-\d{2}-\d{2})', html) or re.search(r'article:modified_time" content="(\d{4}-\d{2}-\d{2})', html)
    return {t: next(iter(found[code]))[0] for t, code in TABLES.items()}, years.pop(), match[1] if match else None


def sheet(raw, title):
    with warnings.catch_warnings():  # OMB workbooks have no default style; openpyxl warns harmlessly.
        warnings.simplefilter('ignore', UserWarning)
        book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)  # Not read_only: OMB files lack dimension records.
    rows = [tuple(r) for r in book.worksheets[0].values]
    if not rows or not str(rows[0][0] or '').upper().startswith(title.upper()):
        raise ValueError(f'Unexpected OMB table: {rows[0][0] if rows else None}')
    return rows


def fy_of(value):
    """Return (fiscal year, is_estimate) or None for TQ and non-year cells."""
    text = ' '.join(str(value).split()).lower() if value is not None else ''
    match = re.fullmatch(r'(\d{4})( estimate)?', text)
    return (int(match[1]), bool(match[2])) if match else None


def check_estimates_last(cols, what):
    flags = [fy[1] for _, fy in cols]
    if True in flags and not all(flags[flags.index(True):]):
        raise ValueError(f'{what}: actual year after an estimate')


def contiguous(years, what):
    if len(years) < MIN_YEARS or years != list(range(years[0], years[0] + len(years))):
        raise ValueError(f'{what}: insufficient or discontinuous years')


def parse_rows_by_year(rows, header_rows, columns, what):
    """Year-per-row tables (1.1, 1.2, 2.1, 2.5): {fy: {name: value}} for actual years >= FIRST_YEAR."""
    out = {}
    for r in rows[header_rows:]:
        fy = fy_of(r[0])
        if fy is None:
            continue  # Ranges such as 1789-1849, TQ and footnotes.
        year, estimate = fy
        if estimate or year < FIRST_YEAR:
            continue
        if year in out:
            raise ValueError(f'{what}: duplicate year {year}')
        out[year] = {name: number(r[i]) for name, i in columns.items()}
    contiguous(sorted(out), what)
    return out


def expect_header(rows, cells, what):
    for (r, c), text in cells.items():
        if text.lower() not in ' '.join(str(rows[r][c] or '').split()).lower():
            raise ValueError(f'{what}: unexpected column {rows[r][c]!r}, expected {text!r}')


def parse_totals(raw11, raw12):
    t11 = sheet(raw11, 'Table 1.1')
    expect_header(t11, {(2, 1): 'Total', (3, 1): 'Receipts', (3, 2): 'Outlays'}, 'Table 1.1')
    t12 = sheet(raw12, 'Table 1.2')
    expect_header(t12, {(1, 1): 'GDP (in billions of dollars)', (2, 2): 'Receipts', (2, 3): 'Outlays'}, 'Table 1.2')
    totals = parse_rows_by_year(t11, 4, {'receipts': 1, 'outlays': 2}, 'Table 1.1')
    ratios = parse_rows_by_year(t12, 3, {'gdp': 1, 'receipts': 2, 'outlays': 3}, 'Table 1.2')
    if sorted(totals) != sorted(ratios):
        raise ValueError('Tables 1.1 and 1.2 years differ')
    if any(str(r[0]).strip().lower().endswith('estimate') for r in t11 + t12 if r[0]):
        raise ValueError('Tables 1.1/1.2 unexpectedly contain estimates')
    for year, r in ratios.items():
        if r['gdp'] <= 0:
            raise ValueError(f'Non-positive OMB GDP in {year}')
    return totals, ratios


def parse_outlays(raw):
    rows = sheet(raw, 'Table 3.1')
    if label(rows[1][0]) != 'superfunction and function' or label(rows[2][0]) != 'in millions of dollars:':
        raise ValueError('Table 3.1: unexpected layout')
    cols = [(i, fy_of(v)) for i, v in enumerate(rows[1]) if i and fy_of(v)]
    actual = [(i, fy[0]) for i, fy in cols if not fy[1] and fy[0] >= FIRST_YEAR]
    check_estimates_last(cols, 'Table 3.1')
    contiguous([y for _, y in actual], 'Table 3.1')
    end = next(n for n, r in enumerate(rows) if label(r[0]).startswith('as percentages of outlays'))
    table = {}
    for r in rows[3:end]:
        name = label(r[0])
        if name and not name.startswith('('):
            if name in table:
                raise ValueError(f'Table 3.1: duplicate row {name}')
            table[name] = {y: number(r[i]) for i, y in actual}
    needed = [k for _, keys in FUNCTIONS for k in keys] + list(SUPERFUNCTIONS) + ['total, federal outlays']
    missing = [k for k in needed if k not in table]
    if missing:
        raise ValueError(f'Table 3.1: missing rows {missing}')
    out = {}
    for _, y in actual:
        total = table['total, federal outlays'][y]
        for sup, parts in SUPERFUNCTIONS.items():
            if abs(sum(table[p][y] for p in parts) - table[sup][y]) > 2:
                raise ValueError(f'Table 3.1: {sup} does not reconcile in {y}')
        items = [{'name': name, 'value': sum(table[k][y] for k in keys)} for name, keys in FUNCTIONS]
        out[y] = {'total': total, 'items': reconcile(items, total, y, 'Table 3.1 functions')}
    return out


def parse_social_insurance(raw):
    """Table 2.4 (years in columns): OASDI, hospital insurance and the total of social insurance receipts."""
    rows = sheet(raw, 'Table 2.4')
    cols = [(i, fy_of(v)) for i, v in enumerate(rows[2]) if i and fy_of(v)]
    check_estimates_last(cols, 'Table 2.4')
    actual = [(i, fy[0]) for i, fy in cols if not fy[1] and fy[0] >= FIRST_YEAR]
    contiguous([y for _, y in actual], 'Table 2.4')
    names = [label(r[0]) for r in rows]
    try:
        oasi = names.index('old-age and survivors insurance:')
        di = names.index('disability insurance (off-budget)')
        hi = names.index('hospital insurance')
        total = names.index('total, social insurance and retirement receipts')
    except ValueError as exc:
        raise ValueError('Table 2.4: missing social insurance rows') from exc
    if not (oasi < di < hi < total) or names[oasi + 1] != 'federal funds' or names[oasi + 2] != 'trust funds (off-budget)' or di != oasi + 3:
        raise ValueError('Table 2.4: unexpected OASI layout')
    value = lambda row, i: number(rows[row][i])
    return {y: {'oasdi': value(oasi + 1, i) + value(oasi + 2, i) + value(di, i), 'hi': value(hi, i), 'total': value(total, i)}
            for i, y in actual}


def parse_receipts(raw21, raw24, raw25):
    t21 = sheet(raw21, 'Table 2.1')
    expect_header(t21, {(2, 1): 'Individual Income Taxes', (2, 2): 'Corporation Income Taxes', (2, 3): 'Social Insurance',
                        (3, 3): 'Total', (2, 6): 'Excise Taxes', (2, 7): 'Other', (2, 8): 'Total Receipts', (3, 8): 'Total'}, 'Table 2.1')
    t25 = sheet(raw25, 'Table 2.5')
    expect_header(t25, {(2, 1): 'Total "Other Receipts"', (2, 2): 'Estate and Gift Taxes', (2, 3): 'Customs Duties',
                        (2, 4): 'Miscellaneous Receipts', (3, 5): 'Federal Reserve Deposits', (3, 6): 'All Other'}, 'Table 2.5')
    by_source = parse_rows_by_year(t21, 4, {'individual': 1, 'corporation': 2, 'social': 3, 'excise': 6, 'other': 7, 'total': 8}, 'Table 2.1')
    other = parse_rows_by_year(t25, 4, {'total': 1, 'estate': 2, 'customs': 3, 'misc': 4, 'fed': 5, 'misc_other': 6}, 'Table 2.5')
    social = parse_social_insurance(raw24)
    out = {}
    for y, r in by_source.items():
        o, s = other.get(y), social.get(y)
        if o is None or s is None:
            raise ValueError(f'Receipts detail missing for {y}')
        checks = [(r['individual'] + r['corporation'] + r['social'] + r['excise'] + r['other'], r['total'], 'Table 2.1 sources'),
                  (o['total'], r['other'], 'Table 2.5 total'), (o['estate'] + o['customs'] + o['misc'], o['total'], 'Table 2.5 items'),
                  (o['fed'] + o['misc_other'], o['misc'], 'Table 2.5 miscellaneous'), (s['total'], r['social'], 'Table 2.4 social insurance')]
        for a, b, what in checks:
            if abs(a - b) > 2:
                raise ValueError(f'{what} fails reconciliation in {y} ({a - b})')
        values = [r['individual'], r['corporation'], s['oasdi'], s['hi'], r['social'] - s['oasdi'] - s['hi'], r['excise'],
                  o['customs'], o['estate'], o['fed'], o['misc_other']]
        items = reconcile([{'name': n, 'value': v} for n, v in zip(RECEIPTS, values)], r['total'], y, 'Receipts by source')
        out[y] = {'total': r['total'], 'taxTotal': r['total'] - o['fed'] - o['misc_other'], 'items': items}
    return out


def reconcile(items, total, year, what):
    """OMB rounds each line independently; residuals of a few $ million become an explicit rounding item."""
    residual = round(total - sum(i['value'] for i in items), 6)
    if abs(residual) > MAX_ROUNDING:
        raise ValueError(f'{what} fail reconciliation in {year} ({residual})')
    return items + ([{'name': ROUNDING, 'value': residual}] if residual else [])


def pct(value, gdp):
    return round(value / gdp * 100, 4)


def with_gdp(rows, gdp):
    return [{**r, 'totalPctGdp': pct(r['total'], gdp[r['year']]), 'gdpMillion': gdp[r['year']],
             'items': [{**i, 'pctGdp': pct(i['value'], gdp[r['year']])} for i in r['items']]} for r in rows]


def source(id_, table, title, url, released, observed):
    return {'id': id_, 'name': f'OMB Historical Tables · Table {table}', 'title': f'Table {table}—{title}',
            'publisher': PUBLISHER, 'url': PAGE, 'downloadUrl': url, 'publicationDate': released,
            'observationDate': observed, 'licence': LICENCE, 'licenceUrl': LICENCE_URL, 'attribution': ATTRIBUTION}


def build(raw, urls, edition, released):
    totals, ratios = parse_totals(raw['1.1'], raw['1.2'])
    outlays = parse_outlays(raw['3.1'])
    receipts = parse_receipts(raw['2.1'], raw['2.4'], raw['2.5'])
    years = sorted(totals)
    if sorted(outlays) != years or sorted(receipts) != years:
        raise ValueError('OMB tables cover different actual years (estimate columns may have been mislabelled)')
    gdp = {}
    for y in years:
        if abs(outlays[y]['total'] - totals[y]['outlays']) > 2 or abs(receipts[y]['total'] - totals[y]['receipts']) > 2:
            raise ValueError(f'Table 3.1/2.1 totals differ from Table 1.1 in {y}')
        gdp[year_label(y)] = round(ratios[y]['gdp'] * 1000, 3)
        for key, rows in (('outlays', outlays), ('receipts', receipts)):
            if abs(rows[y]['total'] / gdp[year_label(y)] * 100 - ratios[y][key]) > 0.051:
                raise ValueError(f'{key} share of GDP differs from OMB Table 1.2 in {y}')
    spend = [{'year': year_label(y), **outlays[y]} for y in years]
    rec = [{'year': year_label(y), **receipts[y]} for y in years]
    first, last = spend[0]['year'], spend[-1]['year']
    src = {t: source(f'omb-hist-{t.replace(".", "-")}-fy{edition}', t, title, urls[t], released, last) for t, title in [
        ('1.1', 'Summary of Receipts, Outlays, and Surpluses or Deficits'),
        ('1.2', 'Summary of Receipts, Outlays, and Surpluses or Deficits as Percentages of GDP'),
        ('2.1', 'Receipts by Source'), ('2.4', 'Composition of Social Insurance and Retirement Receipts and of Excise Taxes'),
        ('2.5', 'Composition of "Other Receipts"'), ('3.1', 'Outlays by Superfunction and Function')]}
    scope = 'Federal government, unified budget (on- and off-budget)'
    gdp_note = 'GDP shares are calculated by this dashboard by dividing each value by OMB fiscal-year GDP (Table 1.2 of the same edition); they are not the rounded OMB percentages.'
    return {
        'schemaVersion': 1, 'asOf': last, 'publicationDate': released, 'level': 'federal', 'label': scope,
        'edition': {'budgetYear': edition, 'title': f'Historical Tables, Budget of the U.S. Government, Fiscal Year {edition}',
                    'lastActualYear': last, 'estimatesExcluded': True},
        'unit': UNIT,
        'basis': f'{scope}: OMB outlays by budget function (Table 3.1), cash basis, current dollars. Total is total federal outlays.',
        'years': [{k: r[k] for k in ('year', 'total', 'items')} for r in spend],
        'history': {'years': with_gdp(spend, gdp), 'unit': UNIT,
                    'basis': f'{scope}: OMB Historical Tables, outlays by budget function (Table 3.1), grouped into {len(FUNCTIONS)} categories. Total is total federal outlays.',
                    'sources': [src['3.1'], src['1.2'], src['1.1']],
                    'notes': [gdp_note,
                              'Other functions groups energy, natural resources and environment, community and regional development, international affairs, general science, space and technology, agriculture, administration of justice and general government.',
                              'Undistributed offsetting receipts (employer agency retirement contributions, outer continental shelf rents and royalties, spectrum auctions and similar) are negative outlays; OMB does not allocate them to functions.',
                              'Education, training, employment and social services and Commerce and housing credit can be net negative, e.g. student-loan subsidy reestimates and modifications (FY2023) or credit-program receipts.']},
        'receipts': {'years': with_gdp(rec, gdp), 'unit': UNIT, 'totalLabel': 'Total federal receipts',
                     'basis': f'{scope}: OMB receipts by source (Tables 2.1, 2.4 and 2.5), cash basis, reconciling to total federal receipts.',
                     'sources': [src['2.1'], src['2.4'], src['2.5'], src['1.2']],
                     'notes': [gdp_note,
                               'Social Security payroll taxes are OASI and DI receipts; Medicare payroll taxes are hospital insurance (HI) receipts. Other social insurance covers unemployment insurance, railroad retirement and federal employee retirement contributions.',
                               'Federal taxes are total receipts less Federal Reserve deposits of earnings and other miscellaneous receipts (fees, fines, and similar). Customs duties include customs fees.']},
        'gdp': {'unit': UNIT, 'asOf': last, 'years': [{'year': year_label(y), 'nominalMillion': gdp[year_label(y)]} for y in years],
                'basis': 'OMB fiscal-year GDP, Historical Tables Table 1.2 (same edition), converted from billions to millions of dollars.'},
        'sources': list(src.values()),
        'notes': [
            f'Federal government only: state and local spending and revenue are excluded. Federal grants to states (e.g. Medicaid, highway grants) are counted in the federal function that pays them.',
            f'History covers FY{int(first[:4]) + 1} to FY{int(last[:4]) + 1} ({len(years)} years), actual results from the FY{edition} Budget Historical Tables. OMB administration estimates for later years are excluded.',
            'Fiscal years are named by the calendar year in which they end: FY2025 is October 2024 to September 2025. Until FY1976 fiscal years ran July to June; the 1976 transition quarter (July to September 1976) is excluded.',
            'Outlays and receipts are on a cash (budget) basis including off-budget Social Security and the Postal Service; they are not national-accounts measures.',
            'Medicare outlays are net of beneficiary premiums and other offsetting receipts that OMB records within the function; Medicare begins in FY1966. Health is mainly Medicaid, ACA premium tax credits, CHIP and public health.',
            gdp_note,
        ],
    }


def fetch_composition(fetch):
    urls, edition, released = links(fetch(PAGE).decode('utf-8', 'replace'))
    if released is None:
        raise ValueError('OMB landing page lacks a modification date')
    raw = {t: fetch(url) for t, url in urls.items()}
    return build(raw, urls, edition, released)


def _check_rows(rows, what, names, gdp):
    if len(rows) < MIN_YEARS:
        raise ValueError(f'{what}: fewer than {MIN_YEARS} years')
    years = [r.get('year') for r in rows]
    if any(not re.fullmatch(r'\d{4}-\d{2}', str(y)) or str(int(y[:4]) + 1)[2:] != y[5:] for y in years) or \
            any(int(b[:4]) != int(a[:4]) + 1 for a, b in zip(years, years[1:])):
        raise ValueError(f'{what}: invalid or discontinuous years')
    for r in rows:
        total, items = r.get('total'), r.get('items') or []
        if not isinstance(total, (int, float)) or total <= 0:
            raise ValueError(f'{what}: non-positive total in {r["year"]}')
        if [i.get('name') for i in items if i.get('name') != ROUNDING] != names or len(items) - len(names) not in (0, 1) or \
                (len(items) > len(names) and items[-1].get('name') != ROUNDING):
            raise ValueError(f'{what}: unexpected categories in {r["year"]}')
        if any(not isinstance(i.get('value'), (int, float)) for i in items):
            raise ValueError(f'{what}: missing value in {r["year"]}')
        for i in items:
            if i['name'] == 'Undistributed offsetting receipts':
                if i['value'] > 0:
                    raise ValueError(f'{what}: positive offsetting receipts in {r["year"]}')
            elif i['name'] == ROUNDING:
                if abs(i['value']) > MAX_ROUNDING or not i['value']:
                    raise ValueError(f'{what}: rounding adjustment out of range in {r["year"]}')
            elif i['value'] < 0 and i['name'] not in MAY_BE_NEGATIVE and abs(i['value']) > 0.5:
                raise ValueError(f'{what}: negative {i["name"]} in {r["year"]}')
        if abs(sum(i['value'] for i in items) - total) > 0.5:
            raise ValueError(f'{what}: items do not sum to total in {r["year"]}')
        if 'taxTotal' in r and not (0 < r['taxTotal'] <= total and abs(total - r['taxTotal'] - sum(i['value'] for i in items if i['name'] in NON_TAX)) <= 2):
            raise ValueError(f'{what}: taxTotal inconsistent in {r["year"]}')
        if gdp is not None:
            g = r.get('gdpMillion')
            if not isinstance(g, (int, float)) or g <= 0 or g != gdp.get(r['year']):
                raise ValueError(f'{what}: missing or inconsistent GDP in {r["year"]}')
            if abs(r['totalPctGdp'] - total / g * 100) > 1e-3 or any(abs(i['pctGdp'] - i['value'] / g * 100) > 1e-3 for i in items):
                raise ValueError(f'{what}: GDP shares inconsistent in {r["year"]}')
            if not 3 < r['totalPctGdp'] < 60:
                raise ValueError(f'{what}: implausible share of GDP in {r["year"]}')
    return years


def validate_composition(data):
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported schemaVersion')
    if data.get('unit') != UNIT or data.get('level') != 'federal':
        raise ValueError('Unexpected unit or level')
    gdp = {r.get('year'): r.get('nominalMillion') for r in data.get('gdp', {}).get('years', [])}
    if not gdp or any(not isinstance(v, (int, float)) or v <= 0 for v in gdp.values()):
        raise ValueError('Missing or invalid GDP')
    fn = [n for n, _ in FUNCTIONS]
    years = _check_rows(data.get('years', []), 'Outlays', fn, None)
    hist = _check_rows(data.get('history', {}).get('years', []), 'Outlay history', fn, gdp)
    rec = _check_rows(data.get('receipts', {}).get('years', []), 'Receipts', RECEIPTS, gdp)
    if not (years == hist == rec == list(gdp)):
        raise ValueError('Years differ across views')
    if any('taxTotal' not in r for r in data['receipts']['years']):
        raise ValueError('Receipts lack taxTotal')
    if [(r['total'], r['items']) for r in data['years']] != [(r['total'], [{'name': i['name'], 'value': i['value']} for i in r['items']]) for r in data['history']['years']]:
        raise ValueError('years and history disagree')
    edition = data.get('edition') or {}
    if data.get('asOf') != years[-1] or edition.get('lastActualYear') != years[-1] or not edition.get('estimatesExcluded'):
        raise ValueError('asOf or edition mismatch')
    if int(years[-1][:4]) + 1 >= int(edition.get('budgetYear', 0)):
        raise ValueError('Latest year is not an actual year for this budget edition')
    for part in (data['history'], data['receipts']):
        if part.get('unit') != UNIT or not part.get('sources') or not part.get('basis'):
            raise ValueError('Missing unit, basis or sources')
    for s in data.get('sources', []):
        if not all(s.get(k) for k in ('id', 'name', 'publisher', 'url', 'licence', 'attribution')) or not str(s.get('downloadUrl', '')).startswith('https://'):
            raise ValueError('Incomplete source metadata')
    if not data.get('sources') or not data.get('notes'):
        raise ValueError('Missing sources or notes')
