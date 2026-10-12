"""ABS GFS expenses by purpose and ABS taxation revenue by type, with ABS nominal GDP.

Scope: general government. The default view is all levels of government
(consolidated, 55120DO021), the analogue of UK TES because Commonwealth grants
to states net out. The Commonwealth (55120DO002) is kept separately under
`levels` and is never mixed with all-levels figures. Receipts combine ABS
Taxation Revenue (55060DO002 all levels, 55060DO001 Commonwealth) with the GFS
operating statement non-tax revenue. One ABS vintage, about ten years; COFOG-A
divisions only (11, with transport separate from economic affairs).
GDP shares are derived here from ABS A2302467A (original, current prices),
summed July-June, and only when all four quarters exist.
"""
import csv
import io
import re
from datetime import datetime
import openpyxl

ABS = 'https://www.abs.gov.au'
GFS_PAGE = ABS + '/statistics/economy/government/government-finance-statistics-annual/latest-release'
TAX_PAGE = ABS + '/statistics/economy/government/taxation-revenue-australia/latest-release'
GDP_PAGE = ABS + '/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/latest-release'
GDP_URL = 'https://data.api.abs.gov.au/rest/data/ABS,ANA_AGG,1.0.0/M3.GPM.10.AUS.Q'
GDP_HEADERS = {'Accept': 'application/vnd.sdmx.data+csv'}
LICENCE = 'CC BY 4.0'
LICENCE_URL = 'https://www.abs.gov.au/website-privacy-copyright-and-disclaimer'
ATTRIBUTION = 'Source: Australian Bureau of Statistics, CC BY 4.0. GDP shares, groupings and residuals are calculated by this dashboard; no ABS endorsement.'
UNIT = 'AUD million'
ROUNDING = 'Rounding adjustment'
MIN_YEARS = 5

# Output names follow the UK dataset where the COFOG division is the same; Transport is COFOG-A only.
DIVISIONS = [('General public services', 'general public services'), ('Defence', 'defence'),
             ('Public order and safety', 'public order and safety'), ('Economic affairs', 'economic affairs'),
             ('Environment protection', 'environmental protection'),
             ('Housing and community amenities', 'housing and community amenities'), ('Health', 'health'),
             ('Recreation, culture and religion', 'recreation, culture and religion'), ('Education', 'education'),
             ('Social protection', 'social protection'), ('Transport', 'transport')]
NAMED_TAXES = [('Income tax on individuals', ['total income taxes levied on individuals', 'income taxes levied on individuals']),
               ('Company and other enterprise income tax', ['total income taxes levied on enterprises', 'income taxes levied on enterprises']),
               ('Goods and services tax (GST)', ['goods and services tax (gst)']),
               ('Payroll taxes', ['total taxes on employers payroll and labour force', 'taxes on employers payroll and labour force']),
               ('Property taxes (land tax and municipal rates)', ['total taxes on property', 'taxes on property']),
               ('Stamp duties and financial transaction taxes', ['taxes on financial and capital transactions']),
               ('Excises and levies', ['total excises and levies', 'excises and levies'])]
OTHER_TAXES = 'Other taxes'
TAX_TOTAL = ['total taxation revenue', 'total taxation on commonwealth government']
NON_TAX = [('Sales of goods and services', ['sales of goods and services']),
           ('Interest and dividend income', ['interest income', 'dividend income']),
           ('Royalty income', ['royalty income']),
           ('Other revenue (incl. grants received)', ['other revenue', 'current grants and subsidies'])]
LEVELS = {'all': ('DO021', 'DO002', 'General government, all levels of government (consolidated)'),
          'commonwealth': ('DO002', 'DO001', 'Commonwealth general government')}


def label(value):
    return ' '.join(str(value).split()).lower() if value is not None else ''


def number(value):
    if value is None or str(value).strip() in ('', '-', '..', 'np', 'na'):
        return None
    result = float(str(value).replace(',', '').strip())
    if not (-1e9 < result < 1e9):
        raise ValueError('Implausible number')
    return result


def links(html, pattern):
    """Latest-release page links, e.g. 55120DO021_YYYYYY.xlsx; one reference year only."""
    found = sorted(set(re.findall(r'href="(/statistics/[^"]*/(\d{4}-\d{2})/(%s)_(\d{6})\.xlsx)"' % pattern, html)))
    if not found or len({f[3] for f in found}) != 1:
        raise ValueError(f'Cannot identify a single latest ABS release for {pattern}')
    return {f[2]: ABS + f[0] for f in found}


def read_table(raw, sheet, title):
    """Return (release date, years, {label: values}) from an ABS formatted table."""
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    if sheet not in book.sheetnames:
        raise ValueError(f'Missing ABS {sheet}')
    rows = list(book[sheet].values)
    if title.lower() not in label(rows[3][0]):
        raise ValueError(f'Unexpected ABS table: {rows[3][0]}')
    match = re.search(r'Released at .* (\d{1,2} \w+ \d{4})', str(rows[2][0]))
    if not match:
        raise ValueError('Missing ABS release date')
    released = datetime.strptime(match[1], '%d %B %Y').date().isoformat()
    cols = [(i, str(v)) for i, v in enumerate(rows[4]) if re.fullmatch(r'\d{4}-\d{2}', str(v))]
    if any(str(rows[5][i]) != '$m' for i, _ in cols):
        raise ValueError('Expected ABS values in $m')
    if len(cols) < MIN_YEARS or any(int(b[:4]) != int(a[:4]) + 1 for (_, a), (_, b) in zip(cols, cols[1:])):
        raise ValueError('Insufficient or discontinuous ABS years')
    table = {}
    for row in rows[6:]:
        values = [number(row[i]) if i < len(row) else None for i, _ in cols]
        if label(row[0]) and all(v is not None for v in values):
            table.setdefault(label(row[0]), values)  # First valued row wins (headings carry no values).
    return released, [y for _, y in cols], table


def pick(table, names, what):
    for name in names:
        if name in table:
            return table[name]
    raise ValueError(f'Missing ABS row: {what}')


def reconcile(items, total, year, what, tolerance):
    residual = round(total - sum(x['value'] for x in items), 6)
    if abs(residual) > tolerance:
        raise ValueError(f'{what} fails reconciliation in {year} ({residual})')
    if residual:
        items.append({'name': ROUNDING, 'value': residual})
    return items


def parse_expenses(raw, title):
    released, years, table = read_table(raw, 'Table_4', title)
    rows = {name: pick(table, ['total ' + key, key], name) for name, key in DIVISIONS}
    totals = pick(table, ['total expenses'], 'total expenses')
    debt = table.get('public debt transactions')
    out = []
    for c, year in enumerate(years):
        items = [{'name': name, 'value': rows[name][c]} for name, _ in DIVISIONS]
        row = {'year': year, 'total': totals[c], 'items': reconcile(items, totals[c], year, 'COFOG-A expenses', len(DIVISIONS))}
        if debt is not None:
            row['debtInterest'] = debt[c]
        out.append(row)
    return released, out


def parse_receipts(gfs_raw, gfs_title, tax_raw, tax_sheet, tax_title):
    released, years, ops = read_table(gfs_raw, 'Table_1', gfs_title)
    tax_released, tax_years, tax = read_table(tax_raw, tax_sheet, tax_title)
    if tax_years != years:
        raise ValueError('ABS taxation and GFS years differ')
    revenue = pick(ops, ['total gfs revenue'], 'total GFS revenue')
    gfs_tax = pick(ops, ['taxation revenue'], 'GFS taxation revenue')
    tax_total = pick(tax, TAX_TOTAL, 'total taxation revenue')
    named = [(name, pick(tax, keys, name)) for name, keys in NAMED_TAXES]
    non_tax = [(name, [pick(ops, [k], k) for k in keys]) for name, keys in NON_TAX]
    out = []
    for c, year in enumerate(years):
        if abs(tax_total[c] - gfs_tax[c]) > 2:
            raise ValueError(f'ABS taxation revenue differs from GFS taxation in {year}')
        items = [{'name': name, 'value': v[c]} for name, v in named]
        other = round(tax_total[c] - sum(x['value'] for x in items), 6)
        items.append({'name': OTHER_TAXES, 'value': other})
        items += [{'name': name, 'value': sum(v[c] for v in vs)} for name, vs in non_tax]
        out.append({'year': year, 'total': revenue[c], 'taxTotal': tax_total[c],
                    'items': reconcile(items, revenue[c], year, 'GFS revenue', len(NON_TAX) + 2)})
    return released, tax_released, out


def parse_gdp(raw):
    """Financial-year (July-June) sums of original quarterly nominal GDP; incomplete years are null."""
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    quarters = {}
    for r in rows:
        if (r.get('MEASURE'), r.get('DATA_ITEM'), r.get('TSEST'), r.get('REGION'), r.get('FREQ')) != ('M3', 'GPM', '10', 'AUS', 'Q'):
            raise ValueError('Expected ABS ANA_AGG M3.GPM.10.AUS.Q (A2302467A)')
        if r.get('UNIT_MEASURE') != 'AUD' or r.get('UNIT_MULT') != '6':
            raise ValueError('Expected GDP in AUD million')
        match = re.fullmatch(r'(\d{4})-Q([1-4])', r['TIME_PERIOD'])
        value = number(r['OBS_VALUE'])
        if not match or (value is not None and value <= 0) or r['TIME_PERIOD'] in quarters:
            raise ValueError('Invalid GDP quarter')
        quarters[r['TIME_PERIOD']] = value
    if len(quarters) < 8:
        raise ValueError('Insufficient GDP quarters')
    def year(fy):
        start = int(fy[:4])
        parts = [quarters.get(q) for q in (f'{start}-Q3', f'{start}-Q4', f'{start + 1}-Q1', f'{start + 1}-Q2')]
        return sum(parts) if all(v is not None for v in parts) else None
    return year, max(quarters)


def with_gdp(rows, gdp_year):
    def pct(v, gdp):
        return round(v / gdp * 100, 4) if gdp else None
    out = []
    for r in rows:
        gdp = gdp_year(r['year'])
        row = {**r, 'totalPctGdp': pct(r['total'], gdp),
               'items': [{**i, 'pctGdp': pct(i['value'], gdp)} for i in r['items']], 'gdpMillion': gdp}
        if 'debtInterest' in r:
            row['debtInterestPctGdp'] = pct(r['debtInterest'], gdp)
        out.append(row)
    return out


def source(id_, title, page, url, released, observed):
    return {'id': id_, 'name': f'Australian Bureau of Statistics · {title}', 'title': title,
            'publisher': 'Australian Bureau of Statistics', 'url': page, 'downloadUrl': url,
            'publicationDate': released, 'observationDate': observed, 'licence': LICENCE,
            'licenceUrl': LICENCE_URL, 'attribution': ATTRIBUTION}


def build(level, gfs_raw, tax_raw, gfs_url, tax_url, gdp_year, gdp_source):
    gfs_code, tax_code, scope = LEVELS[level]
    gfs_title = 'Total all levels of Government, General Government' if level == 'all' else 'Commonwealth General Government'
    tax_sheet, tax_title = ('Table_2', 'Total taxation revenue by sub-category') if level == 'all' else ('Table_1', 'Taxation, Commonwealth Government')
    released, expenses = parse_expenses(gfs_raw, gfs_title + ' Expenses by Purpose')
    _, tax_released, receipts = parse_receipts(gfs_raw, gfs_title + ' Operating Statement', tax_raw, tax_sheet, tax_title)
    if [r['year'] for r in expenses] != [r['year'] for r in receipts]:
        raise ValueError('Expense and revenue years differ')
    last = expenses[-1]['year']
    gfs_src = source(f'abs-gfs-{gfs_code.lower()}', f'Government Finance Statistics, Annual ({gfs_code}: {scope}), Tables 1 and 4',
                     GFS_PAGE, gfs_url, released, last)
    tax_src = source(f'abs-tax-{tax_code.lower()}', f'Taxation Revenue, Australia (55060{tax_code})', TAX_PAGE, tax_url, tax_released, last)
    debt_note = ['Public debt transactions are published within general public services for this level and are carried as debtInterest.'] \
        if level == 'commonwealth' else ['The all-levels table does not publish public debt transactions within general public services, so debtInterest is omitted rather than derived from unconsolidated level tables.']
    return {
        'level': level, 'label': scope, 'publicationDate': released,
        'years': expenses,
        'history': {'years': with_gdp(expenses, gdp_year), 'unit': UNIT,
                    'basis': f'{scope}: ABS GFS expenses by purpose (COFOG-A divisions), accrual, current prices. Total is total GFS expenses.',
                    'sources': [gfs_src, gdp_source],
                    'notes': ['GDP shares are derived by this dashboard (value / July-June sum of quarterly nominal GDP), not published ABS ratios.'] + debt_note},
        'receipts': {'years': with_gdp(receipts, gdp_year), 'unit': UNIT, 'totalLabel': 'Total GFS revenue',
                     'basis': f'{scope}: ABS taxation revenue by type plus GFS non-tax revenue, reconciling to total GFS revenue (accrual, current prices).',
                     'sources': [tax_src, gfs_src, gdp_source],
                     'notes': ['Income tax on individuals includes the Medicare levy and fringe benefits tax. Company and other enterprise income tax includes tax paid by superannuation funds.',
                               'GST is a Commonwealth tax in ABS statistics although its proceeds are paid to the states.',
                               'Other taxes is derived as total taxation less the named taxes (sales, international trade, gambling, insurance, motor vehicle, non-resident and other taxes). taxTotal is ABS total taxation revenue.',
                               'Rounding adjustment reconciles independently rounded ABS items to total GFS revenue.']},
    }


def fetch_composition(fetch):
    gfs_links = links(fetch(GFS_PAGE).decode('utf-8', 'replace'), r'55120DO0(?:21|02)')
    tax_links = links(fetch(TAX_PAGE).decode('utf-8', 'replace'), r'55060DO00[12]')
    if set(gfs_links) != {'55120DO021', '55120DO002'} or set(tax_links) != {'55060DO001', '55060DO002'}:
        raise ValueError('ABS latest-release pages lack the expected workbooks')
    gdp_year, gdp_last = parse_gdp(fetch(GDP_URL, headers=GDP_HEADERS))
    gdp_src = {'id': 'abs-gdp-a2302467a', 'name': 'Australian Bureau of Statistics · GDP, current prices, original (A2302467A)',
               'title': 'Australian National Accounts: GDP, current prices, original (ANA_AGG M3.GPM.10.AUS.Q)',
               'publisher': 'Australian Bureau of Statistics', 'url': GDP_PAGE, 'downloadUrl': GDP_URL,
               'observationDate': gdp_last, 'licence': LICENCE, 'licenceUrl': LICENCE_URL, 'attribution': ATTRIBUTION}
    levels = {}
    for level, (gfs_code, tax_code, _) in LEVELS.items():
        g, t = gfs_links['55120' + gfs_code], tax_links['55060' + tax_code]
        levels[level] = build(level, fetch(g), fetch(t), g, t, gdp_year, gdp_src)
    main, cth = levels['all'], levels['commonwealth']
    years = [r['year'] for r in main['years']]
    gdp_rows = [{'year': y, 'nominalMillion': gdp_year(y)} for y in years]
    sources = [s for s in main['history']['sources'] + main['receipts']['sources'] + cth['receipts']['sources']]
    sources = list({s['id']: s for s in sources}.values())
    return {
        'schemaVersion': 1, 'asOf': years[-1], 'publicationDate': main['publicationDate'], 'level': 'all',
        'unit': UNIT, 'basis': main['history']['basis'],
        'years': main['years'], 'history': main['history'], 'receipts': main['receipts'],
        'levels': {'commonwealth': {k: cth[k] for k in ('label', 'publicationDate', 'years', 'history', 'receipts')}},
        'gdp': {'code': 'A2302467A', 'unit': UNIT, 'asOf': gdp_last, 'years': gdp_rows,
                'basis': 'Derived: July-June sum of four published quarters of nominal GDP (current prices, original). Null when any quarter is missing.'},
        'sources': sources,
        'notes': [
            f'Default view is general government, all levels of government, consolidated: transfers between levels (such as Commonwealth grants to the states) net out, so spending is counted once by the level that finally spends it.',
            'The Commonwealth general government view (levels.commonwealth) is an alternative, not a component: its expenses include grants to the states, classified by purpose, and must not be added to or mixed with all-levels figures.',
            f'History covers {years[0]} to {years[-1]} only ({len(years)} years): each ABS release publishes a rolling ten-year window. Earlier releases are a different vintage with later revisions and are not spliced in.',
            'Expenses by purpose are top-level COFOG-A divisions only (11 divisions; Transport is a separate division, unlike international COFOG). Groups (e.g. pensions within social protection) are not published at all-levels level, so no social protection breakdown is provided.',
            'Totals are total GFS expenses (accrual), not cash payments, and differ from the Commonwealth budget aggregates. Covid support in 2019-20 and 2020-21 (JobKeeper) is in Economic affairs.',
            'GDP shares are derived by this dashboard from ABS quarterly nominal GDP summed July-June; they are not published ABS ratios and use the latest GDP vintage.',
            'Rounding adjustment items reconcile independently rounded ABS items to the published total.',
        ],
    }


def _check_year_rows(rows, what, expense):
    if len(rows) < MIN_YEARS:
        raise ValueError(f'{what}: fewer than {MIN_YEARS} years')
    years = [r.get('year') for r in rows]
    if any(not re.fullmatch(r'\d{4}-\d{2}', str(y)) for y in years) or any(int(b[:4]) != int(a[:4]) + 1 for a, b in zip(years, years[1:])):
        raise ValueError(f'{what}: invalid or discontinuous years')
    for r in rows:
        total, items = r.get('total'), r.get('items') or []
        if not isinstance(total, (int, float)) or total <= 0:
            raise ValueError(f'{what}: non-positive total in {r["year"]}')
        names = [i.get('name') for i in items]
        if len(names) != len(set(names)) or len(items) < 5:
            raise ValueError(f'{what}: incomplete or duplicated items in {r["year"]}')
        if any(not isinstance(i.get('value'), (int, float)) for i in items):
            raise ValueError(f'{what}: missing value in {r["year"]}')
        rounding = sum(i['value'] for i in items if i['name'] == ROUNDING)
        if abs(rounding) > len(items):
            raise ValueError(f'{what}: rounding adjustment too large in {r["year"]}')
        if any(i['value'] < 0 for i in items if i['name'] != ROUNDING):
            raise ValueError(f'{what}: negative item in {r["year"]}')
        if abs(sum(i['value'] for i in items) - total) > 0.5:
            raise ValueError(f'{what}: items do not sum to total in {r["year"]}')
        if expense and [n for n in names if n != ROUNDING] != [n for n, _ in DIVISIONS]:
            raise ValueError(f'{what}: unexpected COFOG-A divisions in {r["year"]}')
        if 'debtInterest' in r:
            gps = next(i['value'] for i in items if i['name'] == 'General public services')
            if not 0 <= r['debtInterest'] <= gps:
                raise ValueError(f'{what}: debt transactions outside general public services in {r["year"]}')
        gdp = r.get('gdpMillion', 'absent')
        if gdp != 'absent':
            if gdp is None:
                if r.get('totalPctGdp') is not None or any(i.get('pctGdp') is not None for i in items):
                    raise ValueError(f'{what}: GDP share without complete GDP in {r["year"]}')
            elif gdp <= 0 or abs(r['totalPctGdp'] - total / gdp * 100) > 1e-3 or \
                    any(abs(i['pctGdp'] - i['value'] / gdp * 100) > 1e-3 for i in items):
                raise ValueError(f'{what}: GDP shares inconsistent in {r["year"]}')
    return years


def _check_view(view, what):
    years = _check_year_rows(view.get('years', []), what + ' expenses', True)
    hist = _check_year_rows(view.get('history', {}).get('years', []), what + ' history', True)
    rec = _check_year_rows(view.get('receipts', {}).get('years', []), what + ' receipts', False)
    if not (years == hist == rec):
        raise ValueError(f'{what}: years differ across views')
    for r in view['receipts']['years']:
        named = sum(i['value'] for i in r['items'] if i['name'] in [n for n, _ in NAMED_TAXES] + [OTHER_TAXES])
        if abs(named - r.get('taxTotal', -1)) > 0.5 or r['taxTotal'] > r['total']:
            raise ValueError(f'{what}: taxes do not reconcile to total taxation in {r["year"]}')
    for part in (view['history'], view['receipts']):
        if not part.get('sources') or not part.get('basis'):
            raise ValueError(f'{what}: missing basis or sources')
    return years


def validate_composition(data):
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported schemaVersion')
    years = _check_view(data, 'All levels')
    if data.get('asOf') != years[-1] or data.get('level') != 'all':
        raise ValueError('asOf or level mismatch')
    cth = data.get('levels', {}).get('commonwealth')
    if not cth:
        raise ValueError('Missing Commonwealth level')
    _check_view(cth, 'Commonwealth')
    for s in data.get('sources', []):
        if not all(s.get(k) for k in ('id', 'name', 'publisher', 'url', 'licence', 'attribution')):
            raise ValueError('Incomplete source metadata')
    if not data.get('sources') or not data.get('notes'):
        raise ValueError('Missing sources or notes')
