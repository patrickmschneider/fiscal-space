"""Australian Government general government cash aggregates (Finance MFS), FBO history, ABS GDP and Budget profile.

Scope is the Commonwealth general government sector, not the whole public sector. Finance publishes
year-to-date (YTD) cumulative figures with no June statement: monthly values are differences of YTD
columns, and June is derived as the Final Budget Outcome (FBO) annual total less May YTD. Rows are
original (not seasonally adjusted). Sheet units switch from $m to $b in 2020-21 and labels and row order
change by year, so rows are mapped by label and units by header. Net Future Fund earnings are deducted
from the underlying cash balance (UCB) in 2005-06 to 2019-20 only; MFS shows them separately from 2013-14.
"""
import csv
import io
import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl

PACKAGE_URL = 'https://data.gov.au/data/api/3/action/package_show?id=australian-government-general-government-sector-monthly-financial-statements-tables-and-data'
PACKAGE_PAGE = 'https://data.gov.au/data/dataset/australian-government-general-government-sector-monthly-financial-statements-tables-and-data'
FBO_TEMPLATE = 'https://archive.budget.gov.au/{fy}/fbo/download/06_appendix_b.docx'
FBO_PAGE = 'https://archive.budget.gov.au/{fy}/index.htm#fbo'
GDP_URL = 'https://data.api.abs.gov.au/rest/data/ABS,ANA_AGG,1.0.0/M3.GPM.10.AUS.Q'
GDP_HEADERS = {'Accept': 'application/vnd.sdmx.data+csv'}
GDP_PAGE = 'https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/latest-release'
CATALOGUE = Path(__file__).resolve().parents[2] / 'catalogue/au/fiscal.json'
SAVED = Path(__file__).resolve().parents[2] / 'public-au/data/fiscal.json'
SCOPE = 'Australian Government (Commonwealth) general government sector; cash basis; excludes public corporations, states and local government'
FINANCE_LICENCE = 'Creative Commons Attribution 3.0 Australia'
FINANCE_ATTRIBUTION = 'Source: Department of Finance, Monthly Financial Statements, via data.gov.au. Licensed under CC BY 3.0 AU.'
CCBY4 = 'Creative Commons Attribution 4.0 International'
MONTHS = ['july', 'august', 'september', 'october', 'november', 'december', 'january', 'february', 'march', 'april', 'may', 'june']
FF_DEDUCTED = range(2005, 2020)  # FY start years where UCB = receipts - payments - net Future Fund earnings
ROWS = {'receipts': {'receipts', 'underlying cash receipts'}, 'payments': {'payments', 'underlying cash payments'},
        'ff': {'net future fund earnings'}, 'ucb': {'underlying cash balance'},
        'fiscal': {'fiscal balance'}, 'netDebt': {'net debt'}}
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def number(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '').replace('−', '-').replace('–', '-')
    if text in ('', '-', '..', 'na', 'n/a', 'NA'):
        return None
    result = float(text)
    if not math.isfinite(result) or abs(result) > 1e12:
        raise ValueError('Non-finite or implausible number')
    return result


def fy_label(start):
    return f'{start}-{str(start + 1)[2:]}'


def fy_start(label):
    match = re.fullmatch(r'(\d{4})-(\d{2})', label or '')
    if not match or (int(match[1]) + 1) % 100 != int(match[2]):
        raise ValueError(f'Invalid financial year {label!r}')
    return int(match[1])


def period(start, index):
    """Month index 0..11 of a July-June financial year starting in `start`."""
    month = (index + 6) % 12 + 1
    return f'{start + (month < 7)}-{month:02d}'


def label_key(text):
    text = re.sub(r'\([a-z]\)', '', str(text or ''), flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return re.sub(r'^less ', '', text)


# ---- data.gov.au discovery ----

def discover(raw):
    package = json.loads(raw.decode('utf-8'))
    if not package.get('success'):
        raise ValueError('data.gov.au package_show failed')
    found = {}
    for resource in package['result']['resources']:
        name = re.sub(r'\s+', ' ', resource.get('name', '')).strip().lower()
        for key, prefix in (('aggregates', 'aggregates - '), ('profiles', 'aggregates monthly profiles - ')):
            if name.startswith(prefix):
                if key in found:
                    raise ValueError(f'Ambiguous MFS {key} resource')
                url = resource.get('url', '')
                if not url.startswith('https://') or not url.lower().endswith('.xlsx'):
                    raise ValueError(f'Unexpected MFS {key} resource URL')
                found[key] = {'url': url, 'modified': (resource.get('last_modified') or resource.get('metadata_modified') or '')[:10]}
    if set(found) != {'aggregates', 'profiles'}:
        raise ValueError('MFS aggregates resources not found in data.gov.au package')
    return found


# ---- MFS workbooks ----

def read_sheet(rows, title):
    """Return (fy start, unit multiplier to $m, columns[{month index, kind, ytd}], {label: [values]}, raw labels)."""
    start = fy_start(title)
    header_index = next((i for i, r in enumerate(rows[:6]) if r and str(r[0] or '').strip().upper().startswith('AGGREGATES')), None)
    if header_index is None:
        raise ValueError(f'MFS sheet {title} has no AGGREGATES header')
    columns, units = [], set()
    for col, cell in enumerate(rows[header_index][1:], 1):
        if cell is None or not str(cell).strip():
            continue
        text = re.sub(r'\s+', ' ', str(cell)).strip()
        months = [i for i, m in enumerate(MONTHS) if re.search(rf'\b{m}\b', text, re.I)]
        unit = re.search(r'\$([mb])\b', text)
        if len(months) != 1 or not unit or not re.search(rf'{start}\s*-\s*{start + 1}', text):
            raise ValueError(f'Unrecognised MFS column header in {title}: {text!r}')
        units.add(unit[1])
        kind = 'actual' if text.upper().startswith('ACTUAL') else re.sub(r'\s*profile.*$', '', text, flags=re.I).strip().lower() + ' profile'
        columns.append({'col': col, 'month': months[0], 'kind': kind, 'ytd': 'YTD' in text.upper() or months[0] == 0})
    if len(units) != 1 or [c['month'] for c in columns] != list(range(len(columns))) or not 1 <= len(columns) <= 11:
        raise ValueError(f'MFS sheet {title} must have consistent units and July to May columns in order')
    scale = 1000 if units == {'b'} else 1
    values, labels, decimals = {}, {}, 0
    for row in rows[header_index + 1:]:
        if not row or row[0] is None or str(row[0]).strip().startswith(('(', '*')) or not str(row[0]).strip():
            continue
        for key, names in ROWS.items():
            if label_key(row[0]) in names:
                if key in values:
                    raise ValueError(f'Duplicate {key} row in MFS sheet {title}')
                cells = [row[c['col']] if c['col'] < len(row) else None for c in columns]
                decimals = max([decimals] + [len(str(v).strip().split('.')[1]) for v in cells if v is not None and '.' in str(v).strip()])
                values[key] = [None if (v := number(row[c['col']] if c['col'] < len(row) else None)) is None else round(v * scale, 3) for c in columns]
                labels[key] = str(row[0]).strip()
    # Rounding unit of the published figures in $m: $0.1b in 2020-21 to 2022-23, otherwise $1m or finer.
    rounding = 100 if scale == 1000 and decimals <= 1 else 1
    return start, columns, values, labels, rounding


def ytd_series(columns, raw):
    """Convert published columns to YTD values; a non-YTD (single-month) column after July is added to the prior YTD."""
    out = []
    for column, value in zip(columns, raw):
        if value is not None and not column['ytd']:
            value = None if not out or out[-1] is None else round(out[-1] + value, 3)
        out.append(value)
    return out


def parse_aggregates(raw):
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    years = {}
    for title in book.sheetnames:
        if not re.fullmatch(r'\d{4}-\d{2}', title):
            continue
        start, columns, values, labels, rounding = read_sheet(list(book[title].iter_rows(values_only=True)), title)
        if 'ucb' not in values:
            raise ValueError(f'MFS sheet {title} has no underlying cash balance')
        if any(c['kind'] != 'actual' for c in columns):
            raise ValueError(f'MFS aggregates sheet {title} contains non-actual columns')
        ytd = {k: ytd_series(columns, v) for k, v in values.items()}
        if 'ff' in ytd:  # blank Future Fund cells before the first deduction in a year are zero, if the identity confirms it
            ytd['ff'] = [0 if f is None and u is not None else f for f, u in zip(ytd['ff'], ytd['ucb'])]
        # Published YTD identity: UCB = receipts - payments (- net Future Fund earnings where shown).
        for i in range(len(columns)):
            r, p, u = ytd.get('receipts', [None] * 12)[i], ytd.get('payments', [None] * 12)[i], ytd['ucb'][i]
            if None not in (r, p, u):
                ff = (ytd.get('ff') or [None] * 12)[i] or 0
                if abs(r - p - ff - u) > 2 * rounding + 1:
                    raise ValueError(f'MFS YTD cash identity failed in {title} column {i + 1}')
        years[start] = {'ytd': ytd, 'labels': labels, 'months': len(columns), 'rounding': rounding,
                        'underlyingReceipts': label_key(labels.get('receipts', '')) == 'underlying cash receipts'}
    if not years or sorted(years) != list(range(min(years), max(years) + 1)):
        raise ValueError('MFS aggregates must contain consecutive financial-year sheets')
    return years


# ---- FBO Appendix B ----

def docx_tables(raw):
    """Tables keyed by caption ('B.1'); continuation tables under the same caption are concatenated."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo('word/document.xml')
        if info.file_size > 50_000_000:
            raise ValueError('FBO document too large')
        body = ET.fromstring(archive.read(info)).find(W + 'body')
    text = lambda e: ''.join(t.text or '' for t in e.iter(W + 't')).strip()
    tables, caption = {}, None
    for element in body:
        if element.tag == W + 'p':
            match = re.match(r'Table\s*(B\.\d+):', text(element))
            if match:
                caption = match[1]
        elif element.tag == W + 'tbl' and caption:
            tables.setdefault(caption, []).extend([text(c) for c in r.findall(W + 'tc')] for r in element.findall(W + 'tr'))
    return tables


def table_years(rows, columns, table):
    """Year rows only; `columns` maps field -> cell index, checked against the expected cell count."""
    out = {}
    for row in rows:
        if not row or not re.fullmatch(r'\d{4}-\d{2}', row[0]):
            continue
        if any(i >= len(row) for i in columns.values()):
            raise ValueError(f'FBO table {table} row {row[0]} has too few cells')
        if row[0] in out:
            raise ValueError(f'Duplicate FBO year {row[0]} in {table}')
        out[row[0]] = {k: number(row[i]) for k, i in columns.items()}
    return out


def parse_fbo(raw):
    tables = docx_tables(raw)
    head = lambda t: ' '.join(' '.join(r) for r in tables.get(t, [])[:6])
    expected = {'B.1': ('Receipts', 'Payments', 'Fund'), 'B.2': ('Headline',), 'B.4': ('Net debt',),
                'B.5': ('Face value', 'Total AGS on issue'), 'B.6': ('Revenue', 'Expenses', 'Net capital investment')}
    for table, words in expected.items():
        if not all(w in head(table) for w in words):
            raise ValueError(f'FBO Appendix B table {table} missing or relabelled')
    b1 = table_years(tables['B.1'], {'receipts': 1, 'receiptsPct': 2, 'payments': 4, 'paymentsPct': 6, 'ff': 8, 'ucb': 10, 'ucbPct': 11}, 'B.1')
    b2 = table_years(tables['B.2'], {'receipts': 1, 'headline': 8, 'headlinePct': 9}, 'B.2')
    b4 = table_years(tables['B.4'], {'netDebt': 1, 'netDebtPct': 2, 'netInterest': 4}, 'B.4')
    b5 = table_years(tables['B.5'], {'ags': 1, 'agsPct': 2}, 'B.5')
    b6 = table_years(tables['B.6'], {'revenue': 1, 'expenses': 4, 'fiscal': 13, 'fiscalPct': 14}, 'B.6')
    years = sorted(b1)
    if not years or years[0] != '1970-71' or [fy_start(y) for y in years] != list(range(1970, fy_start(years[-1]) + 1)):
        raise ValueError('FBO Table B.1 must run continuously from 1970-71')
    rows = []
    for year in years:
        a = b1[year]
        start = fy_start(year)
        if None in (a['receipts'], a['payments'], a['ucb']):
            raise ValueError(f'FBO cash aggregates missing for {year}')
        ff = a['ff'] if start in FF_DEDUCTED else 0
        if abs(a['receipts'] - a['payments'] - (ff or 0) - a['ucb']) > 2:
            raise ValueError(f'FBO Table B.1 identity failed in {year}')
        if year in b2 and b2[year]['receipts'] != a['receipts']:
            raise ValueError(f'FBO Tables B.1 and B.2 disagree in {year}')
        d, g, f = b4.get(year, {}), b5.get(year, {}), b6.get(year, {})
        rows.append({'year': year, 'receiptsMillion': a['receipts'], 'paymentsMillion': a['payments'],
                     'futureFundEarningsMillion': a['ff'], 'futureFundDeducted': start in FF_DEDUCTED,
                     'underlyingCashBalanceMillion': a['ucb'], 'borrowingMillion': -a['ucb'],
                     'receiptsPctGdp': a['receiptsPct'], 'paymentsPctGdp': a['paymentsPct'], 'underlyingCashBalancePctGdp': a['ucbPct'],
                     'headlineCashBalanceMillion': b2.get(year, {}).get('headline'),
                     'netDebtMillion': d.get('netDebt'), 'netDebtPctGdp': d.get('netDebtPct'), 'netInterestPaymentsMillion': d.get('netInterest'),
                     'grossDebtFaceValueMillion': g.get('ags'), 'grossDebtPctGdp': g.get('agsPct'),
                     'fiscalBalanceMillion': f.get('fiscal'), 'fiscalBalancePctGdp': f.get('fiscalPct')})
    return rows


def fbo_candidates(latest_fy_start, catalogue=CATALOGUE):
    """Newest first: catalogue overrides by year, else the archive.budget.gov.au path pattern."""
    overrides, template = {}, FBO_TEMPLATE
    if catalogue.exists():
        source = next((s for s in json.loads(catalogue.read_text()).get('sources', []) if s.get('id') == 'fbo-historical'), {})
        overrides, template = source.get('appendixBUrls', {}), source.get('appendixBUrlTemplate', FBO_TEMPLATE)
    out = []
    for start in range(latest_fy_start, latest_fy_start - 3, -1):
        fy = fy_label(start)
        out.append((fy, overrides.get(fy) or template.format(fy=fy)))
    return out


# ---- ABS GDP ----

def parse_gdp(raw):
    """ABS 5206.0 A2302467A: GDP, current prices, original, quarterly, $m; four-quarter rolling sums."""
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    code = lambda v: str(v or '').split(':')[0].strip()
    quarters = {}
    for row in rows:
        if (code(row.get('MEASURE')), code(row.get('DATA_ITEM')), code(row.get('TSEST')), code(row.get('REGION')), code(row.get('FREQ'))) != ('M3', 'GPM', '10', 'AUS', 'Q'):
            raise ValueError('Unexpected ABS series; expected ANA_AGG M3.GPM.10.AUS.Q')
        if code(row.get('UNIT_MEASURE')) != 'AUD' or code(row.get('UNIT_MULT')) != '6':
            raise ValueError('ABS GDP must be AUD millions')
        match = re.fullmatch(r'(\d{4})-Q([1-4])', row.get('TIME_PERIOD', ''))
        if not match:
            raise ValueError('Unexpected ABS time period')
        index = int(match[1]) * 4 + int(match[2]) - 1
        value = number(row.get('OBS_VALUE'))
        if index in quarters or (value is not None and value <= 0):
            raise ValueError('Duplicate or non-positive GDP quarter')
        quarters[index] = value
    if len(quarters) < 8:
        raise ValueError('Insufficient GDP quarters')
    observations = []
    for index in range(min(quarters), max(quarters) + 1):
        y, q0 = divmod(index, 4)
        if y < 1999:
            continue
        values = [quarters.get(i) for i in range(index - 3, index + 1)]
        observations.append({'date': f'{y:04d}-{(q0 + 1) * 3:02d}',
                             'rollingAnnualMillion': round(sum(values), 1) if all(v is not None for v in values) else None})
    if not any(r['rollingAnnualMillion'] for r in observations):
        raise ValueError('No complete four-quarter GDP totals')
    return {'code': 'A2302467A', 'asOf': observations[-1]['date'], 'releaseDate': None, 'nextRelease': None, 'unit': 'A$ million',
            'basis': 'Four-quarter sum of nominal GDP, current prices, original (not seasonally adjusted). Dashboard scaling, not an official Finance or Treasury ratio.',
            'methodologyUrl': GDP_PAGE,
            'notes': ['Sum of four consecutive published quarters of ABS series A2302467A (5206.0 Table 3). No interpolation or forecast.',
                      'The ABS Data API response carries no release date, so releaseDate is null; the latest quarter is given by asOf.',
                      'Historical GDP is the latest ABS vintage and may differ from the GDP behind ratios published in Budget papers.'],
            'sources': [{'id': 'abs-gdp-a2302467a', 'name': 'ABS · Australian National Accounts, GDP current prices (A2302467A)', 'publisher': 'Australian Bureau of Statistics',
                         'url': GDP_PAGE, 'downloadUrl': GDP_URL, 'observationDate': observations[-1]['date'], 'licence': CCBY4,
                         'attribution': 'Source: Australian Bureau of Statistics, Australian National Accounts. Licensed under CC BY 4.0.'}],
            'observations': observations}


def gdp_at(gdp, date, max_lag=2):
    rows = [r for r in gdp['observations'] if r['date'] <= date]
    if not rows or not rows[-1]['rollingAnnualMillion']:
        return None
    y, m = map(int, rows[-1]['date'].split('-'))
    dy, dm = map(int, date.split('-'))
    return rows[-1]['rollingAnnualMillion'] if (dy - y) * 12 + dm - m <= max_lag else None


# ---- monthly assembly ----

def monthly(years, fbo, gdp):
    annual = {r['year']: r for r in fbo or []}
    observations = []
    for start in sorted(years):
        year, fy = years[start], fy_label(start)
        ytd = year['ytd']
        full = {k: v + [None] * (11 - len(v)) for k, v in ytd.items()}
        june = annual.get(fy) if year['months'] == 11 else None
        for i in range(12):
            if i == 11:
                obs = {'date': period(start, 11), 'borrowing': None, 'receipts': None, 'spending': None, 'futureFundEarnings': None,
                       'fiscalBalance': None, 'debtBillion': None, 'debtPct': None, 'method': 'fbo-residual' if june else 'unavailable',
                       'roundingMillion': year['rounding']}
                if june:
                    may = lambda k: full[k][10] if k in full else None
                    diff = lambda total, k: None if total is None or may(k) is None else round(total - may(k), 3)
                    obs['borrowing'] = None if may('ucb') is None else round(may('ucb') - june['underlyingCashBalanceMillion'], 3)
                    receipts_total = june['receiptsMillion']
                    if 'ff' in full:
                        obs['futureFundEarnings'] = diff(june['futureFundEarningsMillion'], 'ff')
                    elif year['underlyingReceipts'] and start in FF_DEDUCTED:
                        receipts_total -= june['futureFundEarningsMillion'] or 0  # MFS receipts already exclude net Future Fund earnings
                    obs['receipts'] = diff(receipts_total, 'receipts')
                    obs['spending'] = diff(june['paymentsMillion'], 'payments')
                    obs['fiscalBalance'] = diff(june['fiscalBalanceMillion'], 'fiscal')
                    if 'netDebt' in full and june['netDebtMillion'] is not None:
                        obs['debtBillion'] = round(june['netDebtMillion'] / 1000, 3)
                observations.append(obs)
                continue
            def flow(key):
                values = full.get(key)
                if not values or values[i] is None:
                    return None
                if i == 0:
                    return values[0]
                return None if values[i - 1] is None else round(values[i] - values[i - 1], 3)
            ucb = flow('ucb')
            nd = full.get('netDebt', [None] * 11)[i]
            observations.append({'date': period(start, i), 'borrowing': None if ucb is None else -ucb,
                                 'receipts': flow('receipts'), 'spending': flow('payments'),
                                 'futureFundEarnings': flow('ff') if 'ff' in full else None, 'fiscalBalance': flow('fiscal'),
                                 'debtBillion': None if nd is None else round(nd / 1000, 3), 'debtPct': None,
                                 'method': 'published-month' if i == 0 else 'ytd-difference', 'roundingMillion': year['rounding']})
    for obs in observations:
        for k in ('borrowing', 'receipts', 'spending', 'futureFundEarnings', 'fiscalBalance'):
            if obs[k] is not None:
                obs[k] = round(obs[k], 3) + 0.0
        if obs['debtBillion'] is not None and gdp:
            denominator = gdp_at(gdp, obs['date'])
            obs['debtPct'] = round(obs['debtBillion'] * 1000 / denominator * 100, 2) if denominator else None
    while observations and observations[-1]['borrowing'] is None:
        observations.pop()
    return observations


SERIES = {
    'borrowing': ('Underlying cash balance', 'Underlying cash deficit (minus the underlying cash balance)', 'A$ million'),
    'receipts': ('Receipts', 'Cash receipts', 'A$ million'),
    'spending': ('Payments', 'Cash payments', 'A$ million'),
    'futureFundEarnings': ('Net Future Fund earnings', 'Net Future Fund earnings deducted from the underlying cash balance', 'A$ million'),
    'fiscalBalance': ('Fiscal balance', 'Fiscal balance (accrual net lending; positive is surplus)', 'A$ million'),
    'debtBillion': ('Net debt', 'Net debt (end of month)', 'A$ billion'),
    'debtPct': ('Derived', 'Net debt as % of four-quarter nominal GDP (dashboard-derived)', '% of GDP'),
}


def fetch_fiscal(fetch):
    resources = discover(fetch(PACKAGE_URL))
    url = resources['aggregates']['url']
    years = parse_aggregates(fetch(url))
    fbo, fbo_year, fbo_url = None, None, None
    for fy, candidate in fbo_candidates(max(years)):
        try:
            raw = fetch(candidate)
        except (RuntimeError, ValueError):
            continue  # not yet published (or not archived offline); try the previous edition
        fbo, fbo_year, fbo_url = parse_fbo(raw), fy, candidate
        break
    if fbo is None:
        raise ValueError('No Final Budget Outcome Appendix B could be retrieved')
    if fbo[-1]['year'] != fbo_year:
        raise ValueError(f'FBO {fbo_year} Appendix B does not end in {fbo_year}')
    gdp = parse_gdp(fetch(GDP_URL, headers=GDP_HEADERS))
    observations = monthly(years, fbo, gdp)
    asof = observations[-1]['date']
    labels = {}
    for start in sorted(years):
        for key, label in years[start]['labels'].items():
            labels.setdefault(key, []).append(label)
    code = {'borrowing': 'ucb', 'receipts': 'receipts', 'spending': 'payments', 'futureFundEarnings': 'ff', 'fiscalBalance': 'fiscal', 'debtBillion': 'netDebt'}
    series = {}
    for key, (default, label, unit) in SERIES.items():
        seen = list(dict.fromkeys(labels.get(code.get(key), [])))
        series[key] = {'code': labels[code[key]][-1] if seen else default, 'label': label, 'unit': unit, 'scope': SCOPE,
                       'sourceTitle': 'Finance MFS aggregates' + (f'; row labels used: {", ".join(seen)}' if seen else '; derived by this dashboard'),
                       'derived': key == 'debtPct', 'seasonalAdjustment': 'original (not seasonally adjusted)'}
    release = resources['aggregates']['modified']
    june_years = sorted({o['date'][:4] for o in observations if o['method'] == 'fbo-residual'})
    return {
        'schemaVersion': 1, 'asOf': asof, 'releaseDate': release,
        'nextRelease': 'Not announced in the source data; Finance publishes monthly statements about five to six weeks after month end (none for June).',
        'scope': SCOPE, 'basis': 'Current prices, cash basis (fiscal balance accrual), original (not seasonally adjusted); monthly flows derived from year-to-date statements',
        'sources': [
            {'id': 'finance-mfs', 'name': 'Department of Finance · Monthly Financial Statements, aggregates', 'publisher': 'Department of Finance',
             'url': PACKAGE_PAGE, 'downloadUrl': url, 'publicationDate': release, 'observationDate': asof, 'licence': FINANCE_LICENCE, 'attribution': FINANCE_ATTRIBUTION},
            {'id': 'fbo-appendix-b', 'name': f'Australian Government · Final Budget Outcome {fbo_year}, Appendix B', 'publisher': 'Australian Government (Treasury and Finance)',
             'url': FBO_PAGE.format(fy=fbo_year), 'downloadUrl': fbo_url, 'observationDate': fbo_year, 'licence': CCBY4,
             'attribution': f'Source: Final Budget Outcome {fbo_year}, Appendix B, Commonwealth of Australia. Licensed under CC BY 4.0.'},
            *gdp['sources']],
        'series': series,
        'observations': observations,
        'gdp': gdp,
        'annual': {'source': 'fbo-appendix-b', 'edition': fbo_year, 'unit': 'A$ million; % of GDP as published (Treasury GDP)', 'rows': fbo},
        'notes': [
            'Scope: Australian Government (Commonwealth) general government sector only, not the whole public sector; state and local governments and public corporations are excluded.',
            'Positive borrowing is an underlying cash deficit; negative borrowing is a surplus. borrowing = minus the published underlying cash balance.',
            'Identity: spending - receipts + futureFundEarnings = borrowing. Net Future Fund earnings are deducted from the underlying cash balance only from 2005-06 to 2019-20; the MFS shows them separately from 2013-14 (futureFundEarnings), while in 2011-12 and 2012-13 the published "underlying cash receipts" already exclude them. Elsewhere futureFundEarnings is null.',
            'Finance publishes year-to-date figures. July is the published month; August to May are differences of consecutive year-to-date columns (2000-01 August is published as a single month). Receipts and payments start in October 2011 because the 2011-12 July and August columns are blank; earlier months carry only the underlying cash balance and fiscal balance.',
            f'There is no June statement. June values (method "fbo-residual") are derived as the Final Budget Outcome annual total less May year-to-date, so they also absorb any revisions to earlier months; June net debt is the FBO end-of-year figure. Derived for {june_years[0]}-{june_years[-1]}; a June without a published FBO is null.' if june_years else 'No Final Budget Outcome matched; June values are null.',
            'fiscalBalance is the accrual fiscal balance (net operating balance less net capital investment): positive is a surplus (net lending), the opposite sign to borrowing. Pre-2005-06 values follow the AAS-based statements then published and are less comparable.',
            'Missing values: blank source cells (e.g. 2000-01 March) leave that month and the following month null; nothing is interpolated.',
            'debtBillion is published Finance net debt (MFS from 2007-08; June from the FBO). debtPct is derived by this dashboard as net debt divided by the latest four-quarter ABS nominal GDP ending at most two months earlier; Finance does not publish a monthly ratio, and it is null when no such GDP total exists yet.',
            'Units: Finance publishes $m to 2019-20 and $b from 2020-21 (rounded to $0.1b in 2020-21 to 2022-23); all flows here are A$ million. roundingMillion gives the source rounding unit per month, and the identity tolerance is three times it.',
            'All months use the current Finance file, which keeps each month as published at the time; the FBO June residual reconciles each year to the final outcome.',
            '"annual" is FBO Appendix B history (Tables B.1, B.2, B.4, B.5, B.6) from 1970-71, with published % of GDP; grossDebtFaceValueMillion is the face value of Australian Government Securities on issue. Cash data before 1999-2000 are ABS-based and before 1998-99 on a cash accounting framework (structural breaks per the FBO).'],
    }


# ---- Budget monthly profile (forecast) ----

def parse_profile(raw, publication_date, source_url):
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    titles = [t for t in book.sheetnames if re.fullmatch(r'\d{4}-\d{2}', t)]
    if not titles:
        raise ValueError('No financial-year sheets in MFS monthly profiles')
    title = max(titles, key=fy_start)
    rows = list(book[title].iter_rows(values_only=True))
    start, columns, values, labels, _ = read_sheet(rows, title)
    if 'ucb' not in values:
        raise ValueError('Monthly profile has no underlying cash balance row')
    budget = 'budget profile'
    coverage, cumulative = [], []
    for column, value in zip(columns, values['ucb']):
        when = period(start, column['month'])
        coverage.append({'period': when, 'kind': column['kind'], 'published': value is not None})
        if column['kind'] == budget and value is not None:
            if not column['ytd']:
                raise ValueError('Budget profile columns must be year-to-date')
            cumulative.append({'period': when, 'value': round(-value / 1000, 3)})
    complete = len(cumulative) == 12
    missing = [c['period'] for c in coverage if not (c['kind'] == budget and c['published'])] + [period(start, 11)] * (len(columns) == 11)
    status = 'available' if complete else 'partial' if cumulative else 'unavailable'
    return {
        'schemaVersion': 1, 'status': status, 'fiscalYear': title, 'vintage': f'{title} Budget',
        'publicationDate': publication_date, 'units': 'A$ billion',
        'basis': 'Cumulative underlying cash deficit (minus the underlying cash balance), Australian Government general government sector; positive is a deficit',
        'sources': [{'id': 'finance-mfs-profile', 'publisher': 'Department of Finance', 'title': 'Monthly Financial Statements, aggregates monthly profiles',
                     'url': PACKAGE_PAGE, 'downloadUrl': source_url, 'publicationDate': publication_date, 'licence': FINANCE_LICENCE, 'attribution': FINANCE_ATTRIBUTION}],
        'cumulative': cumulative,
        'profileColumns': coverage,
        'notes': [
            f'Only months whose column is the {title} Budget profile are included; actuals substituted by Finance ("Where there was no Budget profile published for the month, the actuals figure is used"), MYEFO and revised Budget profiles are excluded so one vintage is shown.',
            'Status is "available" only when all twelve months (July to June) of the same Budget profile are published. Finance adds each month\'s profile with that month\'s statement, never publishes a June profile, and substitutes actuals where no profile exists, so this file is normally "partial".' if not complete else 'All twelve months of the Budget profile are published.',
            f'Months not covered by the Budget profile: {", ".join(missing)}.' if missing else 'No months missing.',
            'Values are Finance year-to-date underlying cash balances with the sign reversed and converted to A$ billion; no interpolation or division of an annual forecast. Publication date is the Finance data release; the forecast vintage is the Budget.'],
    }


def fetch_forecast(fetch):
    resource = discover(fetch(PACKAGE_URL))['profiles']
    return parse_profile(fetch(resource['url']), resource['modified'], resource['url'])


# ---- validators ----

def validate_fiscal(data, previous=None):
    if data.get('schemaVersion') != 1 or not data.get('sources') or not data.get('notes'):
        raise ValueError('Fiscal dataset missing schema, sources or notes')
    if 'general government' not in data.get('scope', '') or 'cash' not in data.get('scope', ''):
        raise ValueError('Fiscal scope must state Commonwealth general government, cash basis')
    rows = data.get('observations', [])
    dates = [r['date'] for r in rows]
    for left, right in zip(dates, dates[1:]):
        y, m = map(int, left.split('-'))
        if right != f'{y + (m == 12):04d}-{m % 12 + 1:02d}':
            raise ValueError(f'Missing or unordered month after {left}')
    complete = [r for r in rows if None not in (r.get('borrowing'), r.get('receipts'), r.get('spending'))]
    if len(complete) < 24:
        raise ValueError('Fewer than 24 months with borrowing, receipts and spending')
    if not rows or rows[-1]['date'] != data.get('asOf') or rows[-1].get('borrowing') is None:
        raise ValueError('asOf must be the latest month with borrowing')
    for r in rows:
        if r.get('method') not in ('published-month', 'ytd-difference', 'fbo-residual', 'unavailable'):
            raise ValueError(f'Unknown method in {r["date"]}')
        if r['method'] == 'unavailable' and any(r.get(k) is not None for k in ('borrowing', 'receipts', 'spending')):
            raise ValueError(f'Unavailable month {r["date"]} carries values')
        if r['method'] == 'fbo-residual' and not r['date'].endswith('-06'):
            raise ValueError('Only June may be an FBO residual')
        if r.get('roundingMillion') not in (1, 100):
            raise ValueError(f'Unknown source rounding in {r["date"]}')
        if r in complete and abs(r['spending'] - r['receipts'] + (r.get('futureFundEarnings') or 0) - r['borrowing']) > 3 * r['roundingMillion']:
            raise ValueError(f'Borrowing identity failed in {r["date"]}')
        if r.get('debtPct') is not None and (r.get('debtBillion') is None or not -50 < r['debtPct'] < 200):
            raise ValueError(f'Implausible net debt ratio in {r["date"]}')
    gdp = data.get('gdp') or {}
    if not gdp.get('observations') or not any(o.get('rollingAnnualMillion') for o in gdp['observations']):
        raise ValueError('Missing GDP denominator')
    annual = (data.get('annual') or {}).get('rows') or []
    if not annual or annual[0]['year'] != '1970-71':
        raise ValueError('Missing FBO annual history')
    by_year = {a['year']: a for a in annual}
    for r in rows:
        if r['method'] == 'fbo-residual':
            start = int(r['date'][:4]) - 1
            fy, span = fy_label(start), {period(start, i) for i in range(12)}
            months = [x for x in rows if x['date'] in span]
            if fy in by_year and len(months) == 12 and all(x['borrowing'] is not None for x in months):
                if abs(sum(x['borrowing'] for x in months) + by_year[fy]['underlyingCashBalanceMillion']) > 0.01:
                    raise ValueError(f'Monthly borrowing does not sum to the FBO outcome for {fy}')
    if previous is None and SAVED.exists():
        previous = json.loads(SAVED.read_text())
    if previous:
        if data['asOf'] < previous.get('asOf', ''):
            raise ValueError(f'Latest month regressed from {previous["asOf"]} to {data["asOf"]}')
        had = {o['date'] for o in previous.get('observations', []) if o.get('borrowing') is not None}
        has = {o['date'] for o in rows if o.get('borrowing') is not None}
        if had - has:
            raise ValueError(f'Previously published months lost: {sorted(had - has)[:5]}')


def validate_forecast(data):
    if data.get('schemaVersion') != 1 or not data.get('sources') or not data.get('notes'):
        raise ValueError('Forecast missing schema, sources or notes')
    status = data.get('status')
    if status not in ('available', 'partial', 'unavailable'):
        raise ValueError('Unknown forecast status')
    start = fy_start(data.get('fiscalYear'))
    cumulative = data.get('cumulative') or []
    allowed = [period(start, i) for i in range(12)]
    periods = [r.get('period') for r in cumulative]
    if any(p not in allowed for p in periods) or periods != sorted(periods, key=allowed.index) or len(set(periods)) != len(periods):
        raise ValueError('Forecast periods must be unique months of the financial year in order')
    for r in cumulative:
        if not isinstance(r.get('value'), (int, float)) or not math.isfinite(r['value']) or abs(r['value']) > 1000:
            raise ValueError('Invalid forecast value')
    if status == 'available' and periods != allowed:
        raise ValueError('Available forecast must have 12 cumulative months July to June')
    if status == 'partial' and not cumulative:
        raise ValueError('Partial forecast has no months')
    if status == 'unavailable' and cumulative:
        raise ValueError('Unavailable forecast carries values')
    if not data.get('vintage') or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data.get('publicationDate') or ''):
        raise ValueError('Forecast vintage or publication date missing')
