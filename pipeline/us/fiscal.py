"""US federal receipts, outlays and deficit (Monthly Treasury Statement), debt held by the public (MSPD) and GDP.

Scope is the federal government unified budget (on-budget plus off-budget: Social Security trust funds and
the Postal Service), cash basis, as published in the Monthly Treasury Statement (MTS) through the Treasury
Fiscal Data API. The US fiscal year runs October to September; fiscal-year labels use the 'YYYY-YY' form
named by the calendar year in which the year starts (FY2026, October 2025 to September 2026, is '2025-26').

Totals come from MTS Table 1, which repeats every month of the current and prior fiscal year in each
statement: each month takes its value from the newest statement that carries it, so prior-year months are
revised. Receipts by source and outlays by function come from MTS Table 9, which has only current-month and
year-to-date columns: a month is the difference of the "prior fiscal year to date" columns of the statements
twelve and eleven months later (the revised basis, which reconciles with Table 1), or the current-month
column of its own statement where no later statement exists yet (first published).

Debt held by the public is the month-end Monthly Statement of the Public Debt (MSPD) total. Nominal GDP is
BEA's not seasonally adjusted quarterly level (NA000334Q, $ million) downloaded from FRED; quarters BEA has
not yet published are filled with CBO's projected year-on-year growth (US-CBO/cbo-data), as the UK edition
does with the OBR forecast.
"""
import csv
import io
import json
import math
import re
from datetime import date
from pathlib import Path

from ..obr_gdp import forecast_quarters
from .text import long_date, month_year

API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/'
PAGE_SIZE = 10000
T1_URL = API + 'v1/accounting/mts/mts_table_1?sort=record_date,src_line_nbr&page[size]={size}&page[number]={page}'
T9_URL = API + 'v1/accounting/mts/mts_table_9?sort=record_date,src_line_nbr&page[size]={size}&page[number]={page}'
MSPD_URL = API + 'v1/debt/mspd/mspd_table_1?filter=record_date:gte:{start}-01&sort=record_date,src_line_nbr&page[size]={size}&page[number]={page}'
LATEST_T1_URL = API + 'v1/accounting/mts/mts_table_1?sort=-record_date,src_line_nbr&page[size]=1&page[number]=1'
MTS_DATASET = '015-BFS-2014Q1-13'
META_URL = f'https://api.fiscaldata.treasury.gov/services/dtg/metadata/{MTS_DATASET}'
CALENDAR_URL = 'https://api.fiscaldata.treasury.gov/services/calendar/release'
MTS_PAGE = 'https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/'
MSPD_PAGE = 'https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/'
GDP_NSA_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=NA000334Q'
GDP_SAAR_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP'
GDP_NSA_PAGE = 'https://fred.stlouisfed.org/series/NA000334Q'
BEA_PAGE = 'https://www.bea.gov/data/gdp/gross-domestic-product'
CBO_RAW = 'https://raw.githubusercontent.com/US-CBO/cbo-data/main/'
CBO_CATALOG_URL = CBO_RAW + 'catalog.json'
CBO_REPO = 'https://github.com/US-CBO/cbo-data'
CBO_PAGE = 'https://www.cbo.gov/data/budget-economic-data'
SAVED = Path(__file__).resolve().parents[2] / 'public-us/data/fiscal.json'

FIRST_MONTH = '2014-10'  # FY2015: the API's statements start March 2015; FY2015 detail comes from FY2016 prior-year columns.
SCOPE = 'US federal government, unified budget (on-budget and off-budget); cash basis; excludes state and local governments'
UNIT_M, UNIT_B = 'USD million', 'USD billion'
LICENCE = 'Public domain (U.S. Government work, 17 U.S.C. 105)'
MTS_ATTRIBUTION = 'Source: U.S. Department of the Treasury, Bureau of the Fiscal Service, Monthly Treasury Statement, via Fiscal Data.'
MONTHS = ['October', 'November', 'December', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September']
NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
SEASONAL = 'not seasonally adjusted'

# Output key -> MTS Table 9 lines (summed). Receipt lines must be exactly these; together they are total receipts.
RECEIPTS = {
    'individualIncomeTax': ('Individual income taxes', ['Individual Income Taxes']),
    'payrollTaxes': ('Social insurance and retirement receipts (payroll taxes)', ['Employment and General Retirement', 'Unemployment Insurance', 'Other Retirement']),
    'corporationTax': ('Corporation income taxes', ['Corporation Income Taxes']),
    'customsDuties': ('Customs duties', ['Customs Duties']),
    'exciseTaxes': ('Excise taxes', ['Excise Taxes']),
    'estateGiftTaxes': ('Estate and gift taxes', ['Estate and Gift Taxes']),
    'miscellaneousReceipts': ('Miscellaneous receipts (incl. Federal Reserve deposits of earnings)', ['Miscellaneous Receipts']),
}
OUTLAYS = {
    'socialSecurity': ('Social Security', ['Social Security']),
    'medicare': ('Medicare', ['Medicare']),
    'health': ('Health (Medicaid and other health)', ['Health']),
    'defense': ('National defense', ['National Defense']),
    'netInterest': ('Net interest', ['Net Interest']),
    'incomeSecurity': ('Income security', ['Income Security']),
    'veterans': ('Veterans benefits and services', ['Veterans Benefits and Services']),
}
OTHER_OUTLAYS = 'otherOutlays'  # Total net outlays less the named functions (incl. undistributed offsetting receipts).
RECEIPT_LINES = {line for _, lines in RECEIPTS.values() for line in lines}
FUNCTIONS = {'National Defense', 'International Affairs', 'General Science, Space, and Technology', 'Energy',
             'Natural Resources and Environment', 'Agriculture', 'Commerce and Housing Credit', 'Transportation',
             'Community and Regional Development', 'Education, Training, Employment, and Social Services', 'Health',
             'Medicare', 'Income Security', 'Social Security', 'Veterans Benefits and Services', 'Administration of Justice',
             'General Government', 'Net Interest', 'Undistributed Offsetting Receipts'}
DETAIL_KEYS = [*RECEIPTS, *OUTLAYS, OTHER_OUTLAYS]


# ---- helpers ----

def number(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '')
    if text in ('', 'null', '.', 'NA'):
        return None
    result = float(text)
    if not math.isfinite(result) or abs(result) > 1e15:
        raise ValueError(f'Non-finite or implausible number {value!r}')
    return result


def shift(month, n):
    y, m = map(int, month.split('-'))
    y, m0 = divmod(y * 12 + m - 1 + n, 12)
    return f'{y:04d}-{m0 + 1:02d}'


def fy_start_of(month):
    """Calendar year in which the October-September fiscal year containing `month` starts."""
    y, m = map(int, month.split('-'))
    return y if m >= 10 else y - 1


def fy_label(start):
    return f'{start}-{str(start + 1)[2:]}'


def millions(dollars):
    return None if dollars is None else round(dollars / 1e6, 3) + 0.0


def month_end(record_date):
    y, m, d = map(int, record_date.split('-'))
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - date(y, m, d)).days == 1


def fetch_pages(fetch, template, **params):
    """All rows of a Fiscal Data endpoint; every page goes through `fetch` so each is archived."""
    rows, page, pages, total = [], 1, None, None
    while pages is None or page <= pages:
        body = json.loads(fetch(template.format(size=PAGE_SIZE, page=page, **params)).decode('utf-8'))
        meta = body.get('meta') or {}
        if 'data' not in body or 'total-pages' not in meta or 'total-count' not in meta:
            raise ValueError('Unexpected Fiscal Data API response')
        pages, total = meta['total-pages'], meta['total-count']
        if pages > 20:
            raise ValueError('Implausibly many Fiscal Data API pages')
        rows.extend(body['data'])
        page += 1
    if len(rows) != total:
        raise ValueError(f'Fiscal Data API returned {len(rows)} of {total} rows')
    return rows


# ---- MTS Table 1: monthly totals ----

def parse_table1(rows):
    """{month: {'receipts','outlays','deficit' (dollars), 'record': newest record_date, 'first': first-published tuple}}."""
    if not rows:
        raise ValueError('MTS Table 1 is empty')
    by_record = {}
    for r in rows:
        if r.get('table_nbr') != '1':
            raise ValueError('Unexpected MTS table number in Table 1')
        by_record.setdefault(r['record_date'], []).append(r)
    months = {}
    for record, items in sorted(by_record.items()):
        if not month_end(record):
            raise ValueError(f'MTS Table 1 record date {record} is not a month end')
        years = {}
        for r in items:
            match = re.fullmatch(r'FY (\d{4})', r['classification_desc'].strip())
            if r['parent_id'] in ('null', None, '') and match:
                years[r['classification_id']] = int(match[1])
        if not years:
            raise ValueError(f'MTS Table 1 {record} has no fiscal-year headers')
        sums = {}
        for r in items:
            if r['parent_id'] in ('null', None, ''):
                continue
            if r['parent_id'] not in years:
                raise ValueError(f'MTS Table 1 {record} row has an unknown parent')
            fy, desc = years[r['parent_id']], r['classification_desc'].strip()
            values = tuple(number(r[k]) for k in ('current_month_gross_rcpt_amt', 'current_month_gross_outly_amt', 'current_month_dfct_sur_amt'))
            if None in values:
                raise ValueError(f'MTS Table 1 {record} {desc} FY{fy} has missing values')
            receipts, outlays, deficit = values
            if abs(outlays - receipts - deficit) > 100:  # dollars
                raise ValueError(f'MTS Table 1 identity failed in {record} {desc} FY{fy}')
            if desc == 'Year-to-Date':
                sums.setdefault(fy, [None, None])[1] = values
                continue
            if desc not in MONTHS or r.get('record_type_cd') != 'MTH':
                raise ValueError(f'Unexpected MTS Table 1 line {desc!r}')
            month = f'{fy - 1 if MONTHS.index(desc) < 3 else fy}-{(MONTHS.index(desc) + 9) % 12 + 1:02d}'
            if month > record[:7]:
                raise ValueError(f'MTS Table 1 {record} reports a future month {month}')
            acc = sums.setdefault(fy, [[0.0, 0.0, 0.0], None])
            acc[0] = [a + b for a, b in zip(acc[0] or [0.0] * 3, values)]
            entry = months.setdefault(month, {})
            if record[:7] == month:
                entry['first'] = values
            if entry.get('record', '') < record:
                entry.update(receipts=receipts, outlays=outlays, deficit=deficit, record=record)
        for fy, (total, ytd) in sums.items():
            if ytd is None or total is None or max(abs(a - b) for a, b in zip(total, ytd)) > 1000:
                raise ValueError(f'MTS Table 1 {record} FY{fy} months do not sum to year to date')
    return months


# ---- MTS Table 9: receipts by source, outlays by function ----

def parse_table9(rows):
    """{statement month: {(section, line): (current month, current FYTD, prior FYTD) in dollars}}."""
    statements = {}
    for r in rows:
        if r.get('table_nbr') != '9':
            raise ValueError('Unexpected MTS table number in Table 9')
        statements.setdefault(r['record_date'], []).append(r)
    out = {}
    for record, items in statements.items():
        if not month_end(record):
            raise ValueError(f'MTS Table 9 record date {record} is not a month end')
        items.sort(key=lambda r: int(r['src_line_nbr']))
        section, lines = None, {}
        for r in items:
            desc, kind = r['classification_desc'].strip(), r['data_type_cd']
            if r['sequence_level_nbr'] == '1':
                section = {'Receipts': 'receipts', 'Net Outlays': 'outlays'}.get(desc)
                if section is None:
                    raise ValueError(f'Unexpected MTS Table 9 section {desc!r} in {record}')
                continue
            if kind == 'S':
                continue  # subheading without values (social insurance and retirement receipts)
            if section is None or kind not in ('D', 'T'):
                raise ValueError(f'Unexpected MTS Table 9 row {desc!r} in {record}')
            values = tuple(number(r[k]) for k in ('current_month_rcpt_outly_amt', 'current_fytd_rcpt_outly_amt', 'prior_fytd_rcpt_outly_amt'))
            if None in values:
                raise ValueError(f'MTS Table 9 {record} {desc} has missing values')
            key = (section, 'Total' if kind == 'T' else desc)
            if key in lines:
                raise ValueError(f'Duplicate MTS Table 9 line {desc!r} in {record}')
            lines[key] = values
        receipts = {d for s, d in lines if s == 'receipts' and d != 'Total'}
        outlays = {d for s, d in lines if s == 'outlays' and d != 'Total'}
        if receipts != RECEIPT_LINES:
            raise ValueError(f'MTS Table 9 receipt lines changed in {record}: {sorted(receipts ^ RECEIPT_LINES)}')
        if not outlays <= FUNCTIONS or not {l for _, ls in OUTLAYS.values() for l in ls} <= outlays:
            raise ValueError(f'MTS Table 9 outlay functions changed in {record}: {sorted(outlays ^ FUNCTIONS)}')
        for section in ('receipts', 'outlays'):
            if (section, 'Total') not in lines:
                raise ValueError(f'MTS Table 9 {record} has no {section} total')
            for col in range(3):
                parts = sum(v[col] for (s, d), v in lines.items() if s == section and d != 'Total')
                if abs(parts - lines[(section, 'Total')][col]) > 1000:
                    raise ValueError(f'MTS Table 9 {section} lines do not sum to the total in {record}')
        out[record[:7]] = lines
    if not out:
        raise ValueError('MTS Table 9 is empty')
    return out


def detail_month(statements, month):
    """({line: dollars}, method) for one month, preferring revised prior-year YTD differences."""
    later, before = statements.get(shift(month, 12)), statements.get(shift(month, 11))
    if later and (month.endswith('-10') or before):
        return {k: v[2] - (0 if month.endswith('-10') else before[k][2]) for k, v in later.items()}, 'revised'
    own = statements.get(month)
    if own:
        return {k: v[0] for k, v in own.items()}, 'first-published'
    return None, None


def details(lines):
    out = {key: sum(lines[('receipts', l)] for l in names) for key, (_, names) in RECEIPTS.items()}
    named = 0.0
    for key, (_, names) in OUTLAYS.items():
        out[key] = sum(lines[('outlays', l)] for l in names)
        named += out[key]
    out[OTHER_OUTLAYS] = lines[('outlays', 'Total')] - named
    return out


# ---- MSPD: debt held by the public ----

def parse_mspd(rows):
    """{month: (debt held by the public, total public debt outstanding)} in $ million at month end."""
    by_record = {}
    for r in rows:
        by_record.setdefault(r['record_date'], {})[(r['security_type_desc'].strip(), r['security_class_desc'].strip())] = r
    out = {}
    for record, lines in by_record.items():
        if not month_end(record):
            raise ValueError(f'MSPD record date {record} is not a month end')
        total = lines.get(('Total Public Debt Outstanding', '_'))
        parts = [lines.get(('Total Marketable', '_')), lines.get(('Total Nonmarketable', '_'))]
        if total is None or None in parts:
            raise ValueError(f'MSPD Table 1 totals missing in {record}')
        for col in ('debt_held_public_mil_amt', 'total_mil_amt'):
            if abs(sum(number(p[col]) for p in parts) - number(total[col])) > 3:  # source rounds lines independently ($1-2m)
                raise ValueError(f'MSPD Table 1 totals do not reconcile in {record}')
        public, gross = number(total['debt_held_public_mil_amt']), number(total['total_mil_amt'])
        if not 0 < public <= gross:
            raise ValueError(f'Implausible MSPD debt in {record}')
        out[record[:7]] = (public, gross)
    return out


# ---- GDP: BEA via FRED, CBO projection for the publication gap ----

def parse_fred(raw, code):
    """Quarter index (year*4 + quarter-1) -> value from a FRED graph CSV."""
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    if not rows or [c.strip() for c in rows[0]] != ['observation_date', code]:
        raise ValueError(f'Unexpected FRED CSV header for {code}')
    quarters = {}
    for row in rows[1:]:
        if not row:
            continue
        match = re.fullmatch(r'(\d{4})-(01|04|07|10)-01', row[0].strip())
        if not match or len(row) != 2:
            raise ValueError(f'Unexpected FRED {code} row {row!r}')
        index = int(match[1]) * 4 + (int(match[2]) - 1) // 3
        value = number(row[1])
        if index in quarters or (value is not None and value <= 0):
            raise ValueError(f'Duplicate or non-positive FRED {code} quarter')
        quarters[index] = value
    if len(quarters) < 40:
        raise ValueError(f'Insufficient FRED {code} quarters')
    return quarters


def check_gdp_units(nsa, saar):
    """NA000334Q must be quarterly $ million: four NSA quarters equal the annual average of SAAR $ billion x 1000."""
    last = max(i for i, v in nsa.items() if v is not None)
    years = [y for y in range(last // 4 - 4, last // 4 + 1) if all(nsa.get(y * 4 + q) and saar.get(y * 4 + q) for q in range(4))]
    if len(years) < 2:
        raise ValueError('Too few complete years to check GDP units')
    for y in years[-3:]:
        ratio = sum(nsa[y * 4 + q] for q in range(4)) / (sum(saar[y * 4 + q] for q in range(4)) / 4 * 1000)
        if not 0.99 < ratio < 1.01:
            raise ValueError(f'BEA NSA GDP does not match SAAR GDP in {y} (ratio {ratio:.4f}); check units')


def cbo_vintage(catalog_raw, dataset='economic_projections', file_type='quarterly'):
    catalog = json.loads(catalog_raw.decode('utf-8'))
    entry = next((d for d in catalog.get('datasets', []) if d.get('identifier') == dataset), None)
    if not entry:
        raise ValueError(f'CBO catalogue has no {dataset} dataset')
    files = {d['vintage']: d['downloadURL'] for d in entry.get('distribution', []) if d.get('file_type') == file_type}
    if not files or not all(re.fullmatch(r'\d{4}-\d{2}', v) for v in files):
        raise ValueError(f'CBO {dataset} has no {file_type} vintages')
    vintage = max(files)
    path = files[vintage]
    if not re.fullmatch(r'data/[a-z_/]+_\d{4}-\d{2}\.csv', path):
        raise ValueError('Unexpected CBO download path')
    return {'vintage': vintage, 'url': CBO_RAW + path, 'schemaUrl': CBO_RAW + entry['schema_path'],
            'landingPage': entry.get('landingPage') or CBO_PAGE, 'title': entry.get('title', dataset)}


def parse_cbo_gdp(raw, schema_raw):
    schema = json.loads(schema_raw.decode('utf-8'))
    unit = ((schema.get('fields') or {}).get('gdp') or {}).get('unit', '')
    if unit != 'SAAR, billions_of_dollars':
        raise ValueError(f'CBO gdp unit changed: {unit!r}')
    quarters = {}
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        if row.get('variable') != 'gdp':
            continue
        match = re.fullmatch(r'(\d{4})q([1-4])', row.get('date', ''))
        value = number(row.get('value'))
        if not match or value is None or value <= 0:
            raise ValueError(f'Unexpected CBO gdp row {row!r}')
        index = int(match[1]) * 4 + int(match[2]) - 1
        if index in quarters:
            raise ValueError('Duplicate CBO gdp quarter')
        quarters[index] = value
    if not quarters or sorted(quarters) != list(range(min(quarters), max(quarters) + 1)):
        raise ValueError('CBO gdp quarters missing or not contiguous')
    return quarters


def build_gdp(nsa, through=None, cbo=None):
    """Four-quarter sums of BEA NSA GDP ($ million); with `cbo`, unpublished quarters up to `through` are projected."""
    quarters = {i: v for i, v in nsa.items() if v is not None}
    bea_end = max(quarters)
    added = forecast_quarters(quarters, cbo['quarters'], through) if cbo and through else {}
    quarters.update(added)
    observations = []
    for index in range(max(min(quarters), 1999 * 4), max(quarters) + 1):
        y, q0 = divmod(index, 4)
        values = [quarters.get(i) for i in range(index - 3, index + 1)]
        row = {'date': f'{y:04d}-{(q0 + 1) * 3:02d}',
               'rollingAnnualMillion': round(sum(values), 1) if all(v is not None for v in values) else None}
        forecast = [f'{i // 4}Q{i % 4 + 1}' for i in range(index - 3, index + 1) if i in added]
        if forecast:
            row['forecastQuarters'] = forecast
        observations.append(row)
    as_of = f'{bea_end // 4:04d}-{(bea_end % 4 + 1) * 3:02d}'
    gdp = {
        'code': 'NA000334Q', 'asOf': as_of, 'releaseDate': None, 'nextRelease': None, 'unit': UNIT_M,
        'basis': 'Four-quarter sum of nominal GDP, current dollars, not seasonally adjusted (BEA). Dashboard scaling, not an official Treasury, OMB or CBO ratio.',
        'methodologyUrl': BEA_PAGE,
        'notes': [
            'Sum of four consecutive quarters of BEA nominal GDP, not seasonally adjusted (FRED series NA000334Q, $ million at quarterly rates). Units are checked against seasonally adjusted GDP at annual rates (FRED GDP).',
            'Where BEA has not yet published the quarter ending at the latest fiscal month, that quarter is the BEA value a year earlier grown by CBO\'s projected year-on-year growth in nominal GDP for the quarter. Projected quarters are flagged and replaced when BEA publishes.' if cbo else 'No CBO projection was available, so quarters BEA has not yet published are missing and later ratios are not shown.',
            'Flows and debt are scaled by the latest four-quarter GDP total ending at or before the month, carried forward by at most two months; otherwise no ratio is shown.',
            'FRED (Federal Reserve Bank of St. Louis) redistributes the BEA series; BEA is the producer. The FRED download carries no release date, so none is shown.',
            'Historical GDP is the latest BEA vintage and may differ from the GDP behind ratios published by CBO or OMB.'],
        'sources': [{'id': 'bea-gdp-nsa', 'name': 'BEA · Gross domestic product, not seasonally adjusted (NA000334Q), via FRED', 'publisher': 'U.S. Bureau of Economic Analysis',
                     'url': GDP_NSA_PAGE, 'downloadUrl': GDP_NSA_URL, 'observationDate': as_of, 'licence': 'Public domain (U.S. Government work); retrieved from FRED, Federal Reserve Bank of St. Louis',
                     'attribution': 'Source: U.S. Bureau of Economic Analysis, Gross Domestic Product [NA000334Q], retrieved from FRED, Federal Reserve Bank of St. Louis.'}],
        'observations': observations,
    }
    if added:
        gdp['sources'].append({'id': 'cbo-economic-projections', 'name': f'CBO · Economic projections, quarterly nominal GDP ({month_year(cbo["vintage"])} vintage)', 'publisher': 'Congressional Budget Office',
                               'url': cbo['landingPage'], 'downloadUrl': cbo['url'], 'publicationDate': cbo['vintage'], 'licence': 'Public domain (U.S. Government work)',
                               'attribution': 'Source: Congressional Budget Office, Economic Projections, via the CBO open data repository (US-CBO/cbo-data).'})
        gdp['forecastExtension'] = {'vintage': f'CBO economic projections, {NAMES[int(cbo["vintage"][5:]) - 1]} {cbo["vintage"][:4]}',
                                    'publicationDate': cbo['vintage'], 'quarters': [f'{i // 4}Q{i % 4 + 1}' for i in sorted(added)],
                                    'fileName': cbo['url'].rsplit('/', 1)[-1]}
    return gdp


def gdp_at(gdp, month, max_lag=2):
    rows = [r for r in gdp['observations'] if r['date'] <= month]
    if not rows or not rows[-1]['rollingAnnualMillion']:
        return None
    y, m = map(int, rows[-1]['date'].split('-'))
    dy, dm = map(int, month.split('-'))
    return rows[-1]['rollingAnnualMillion'] if (dy - y) * 12 + dm - m <= max_lag else None


# ---- release dates ----

def release_dates(meta_raw, calendar_raw):
    meta = json.loads(meta_raw.decode('utf-8'))
    if isinstance(meta, list):
        meta = next((m for m in meta if m.get('dataset_id') == MTS_DATASET), {})
    if meta.get('dataset_id') != MTS_DATASET or 'Monthly Treasury Statement' not in meta.get('title', ''):
        raise ValueError('Fiscal Data metadata is not the Monthly Treasury Statement')
    api = next((a for a in meta.get('apis', []) if a.get('endpoint_txt', '').endswith('/mts/mts_table_1')), None)
    if not api or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', api.get('last_updated') or ''):
        raise ValueError('MTS Table 1 last-updated date missing from Fiscal Data metadata')
    upcoming = sorted(r['date'] for r in json.loads(calendar_raw.decode('utf-8'))
                      if r.get('datasetId') == MTS_DATASET and str(r.get('released')).lower() == 'false'
                      and re.fullmatch(r'\d{4}-\d{2}-\d{2}', r.get('date') or '') and r['date'] > api['last_updated'])
    if upcoming:
        nxt = long_date(upcoming[0])
    else:
        nxt = 'Not in the Fiscal Data release calendar; the MTS is normally published on the eighth business day after month end.'
    return api['last_updated'], nxt, api.get('latest_date')


def month_span(months):
    """['2025-10', ..., '2026-09'] -> 'October 2025 to September 2026' (or one month)."""
    first, last = month_year(months[0]), month_year(months[-1])
    return first if first == last else f'{first} to {last}'


# ---- assembly ----

SERIES_META = {
    'borrowing': ('MTS Table 1: total deficit (-) / surplus (+), sign reversed', 'Unified budget deficit (outlays less receipts)', UNIT_M, SCOPE),
    'receipts': ('MTS Table 1: total receipts', 'Total receipts', UNIT_M, SCOPE),
    'spending': ('MTS Table 1: total outlays', 'Total outlays (net)', UNIT_M, SCOPE),
    'debtBillion': ('MSPD Table 1: total public debt outstanding, debt held by the public', 'Debt held by the public (Treasury securities, end of month)', UNIT_B, 'Treasury securities held outside federal government accounts (federal debt, not general government)'),
    'grossDebtBillion': ('MSPD Table 1: total public debt outstanding', 'Gross federal debt (incl. intragovernmental holdings, end of month)', UNIT_B, 'All Treasury securities outstanding, including those held by federal trust funds'),
    'debtPct': ('Derived', 'Debt held by the public as % of four-quarter nominal GDP (dashboard-derived)', '% of GDP', SCOPE),
}


def assemble(t1, statements, debt, gdp, first_month=FIRST_MONTH):
    last = max(t1)
    observations, month = [], first_month
    while month <= last:
        if month not in t1:
            raise ValueError(f'MTS Table 1 has no value for {month}')
        total = t1[month]
        lines, method = detail_month(statements, month)
        if lines is None:
            raise ValueError(f'MTS Table 9 cannot supply {month}')
        detail = details(lines)
        # Table 9 totals must agree with Table 1: exactly as first published, closely once revised.
        if method == 'first-published':
            if 'first' not in total:
                raise ValueError(f'MTS Table 1 has no first-published value for {month}')
            ref, tolerance = total['first'][:2], 1e4  # same statement: must agree to the dollar
        else:
            ref, tolerance = (total['receipts'], total['outlays']), 2e9  # prior-year columns vs Table 1 revisions
        if max(abs(lines[('receipts', 'Total')] - ref[0]), abs(lines[('outlays', 'Total')] - ref[1])) > tolerance:
            raise ValueError(f'MTS Tables 1 and 9 disagree for {month}')
        public, gross = debt.get(month, (None, None))
        row = {'date': month, 'borrowing': millions(total['deficit']), 'receipts': millions(total['receipts']), 'spending': millions(total['outlays']),
               'debtBillion': None if public is None else round(public / 1000, 3), 'grossDebtBillion': None if gross is None else round(gross / 1000, 3), 'debtPct': None,
               **{k: millions(v) for k, v in detail.items()}, 'detailMethod': method}
        denominator = gdp_at(gdp, month) if row['debtBillion'] is not None else None
        if denominator:
            row['debtPct'] = round(row['debtBillion'] * 1000 / denominator * 100, 2)
        observations.append(row)
        month = shift(month, 1)
    return observations


def series_dict():
    series = {k: {'code': code, 'label': label, 'unit': unit, 'scope': scope, 'sourceTitle': 'Monthly Treasury Statement' if k in ('borrowing', 'receipts', 'spending') else 'Monthly Statement of the Public Debt' if k in ('debtBillion', 'grossDebtBillion') else 'Derived by this dashboard',
                  'derived': k == 'debtPct', 'seasonalAdjustment': SEASONAL} for k, (code, label, unit, scope) in SERIES_META.items()}
    for key, (label, lines) in RECEIPTS.items():
        series[key] = {'code': 'MTS Table 9: ' + ' + '.join(lines), 'label': label, 'unit': UNIT_M, 'scope': SCOPE, 'group': 'receipts',
                       'sourceTitle': 'Monthly Treasury Statement, Table 9 (receipts by source)', 'derived': False, 'seasonalAdjustment': SEASONAL}
    for key, (label, lines) in OUTLAYS.items():
        series[key] = {'code': 'MTS Table 9: ' + ' + '.join(lines), 'label': label, 'unit': UNIT_M, 'scope': SCOPE, 'group': 'spending',
                       'sourceTitle': 'Monthly Treasury Statement, Table 9 (outlays by function)', 'derived': False, 'seasonalAdjustment': SEASONAL}
    series[OTHER_OUTLAYS] = {'code': 'MTS Table 9: total net outlays less the named functions', 'label': 'Other outlays (all other functions, net of undistributed offsetting receipts)',
                             'unit': UNIT_M, 'scope': SCOPE, 'group': 'spending', 'sourceTitle': 'Monthly Treasury Statement, Table 9; residual derived by this dashboard',
                             'derived': True, 'seasonalAdjustment': SEASONAL}
    return series


def load_cbo_gdp(fetch):
    info = cbo_vintage(fetch(CBO_CATALOG_URL))
    info['quarters'] = parse_cbo_gdp(fetch(info['url']), fetch(info['schemaUrl']))
    return info


def fetch_fiscal(fetch, first_month=FIRST_MONTH):
    t1 = parse_table1(fetch_pages(fetch, T1_URL))
    statements = parse_table9(fetch_pages(fetch, T9_URL))
    debt = parse_mspd(fetch_pages(fetch, MSPD_URL, start=first_month))
    release, next_release, latest = release_dates(fetch(META_URL), fetch(CALENDAR_URL))
    as_of = max(t1)
    if latest and latest[:7] != as_of:
        raise ValueError(f'MTS metadata latest date {latest} does not match Table 1 ({as_of})')
    nsa = parse_fred(fetch(GDP_NSA_URL), 'NA000334Q')
    check_gdp_units(nsa, parse_fred(fetch(GDP_SAAR_URL), 'GDP'))
    try:
        cbo = load_cbo_gdp(fetch)
    except RuntimeError:  # download failure only; a malformed CBO file still fails loudly
        cbo = None
    gdp = build_gdp(nsa, as_of, cbo)
    observations = assemble(t1, statements, debt, gdp, first_month)
    revised_to = max((o['date'] for o in observations if o['detailMethod'] == 'revised'), default=None)
    first_published = [o['date'] for o in observations if o['detailMethod'] == 'first-published']
    return {
        'schemaVersion': 1, 'asOf': as_of, 'releaseDate': release, 'nextRelease': next_release,
        'scope': SCOPE,
        'basis': 'Current dollars, cash basis, not seasonally adjusted; monthly flows as published in the Monthly Treasury Statement',
        'fiscalYearStartMonth': 10,
        'sources': [
            {'id': 'treasury-mts', 'name': 'U.S. Treasury · Monthly Treasury Statement (Tables 1 and 9)', 'publisher': 'U.S. Department of the Treasury, Bureau of the Fiscal Service',
             'url': MTS_PAGE, 'downloadUrl': T1_URL.format(size=PAGE_SIZE, page=1), 'publicationDate': release, 'observationDate': as_of, 'licence': LICENCE, 'attribution': MTS_ATTRIBUTION},
            {'id': 'treasury-mspd', 'name': 'U.S. Treasury · Monthly Statement of the Public Debt (Table 1)', 'publisher': 'U.S. Department of the Treasury, Bureau of the Fiscal Service',
             'url': MSPD_PAGE, 'downloadUrl': MSPD_URL.format(start=first_month, size=PAGE_SIZE, page=1), 'observationDate': max(debt), 'licence': LICENCE,
             'attribution': 'Source: U.S. Department of the Treasury, Bureau of the Fiscal Service, Monthly Statement of the Public Debt, via Fiscal Data.'},
            *gdp['sources']],
        'series': series_dict(),
        'observations': observations,
        'gdp': gdp,
        'notes': [
            'Scope: US federal government, unified budget (on-budget plus off-budget Social Security trust funds and the Postal Service). State and local governments are excluded, so this is not general government.',
            'Borrowing is outlays minus receipts: a positive value is a deficit and a negative value a surplus. It equals the Monthly Treasury Statement deficit with the sign reversed (the statement shows deficits as negative numbers).',
            'The fiscal year runs October to September and is named by the year in which it ends (FY2026 is October 2025 to September 2026); charts label it by both calendar years, e.g. "2025-26" for FY2026.',
            f'Coverage starts in {month_year(first_month)} (FY{fy_start_of(first_month) + 1}). Treasury Fiscal Data carries MTS statements from March 2015; FY2015 is the first fiscal year with complete receipts-by-source and outlays-by-function detail (from the FY2016 prior-year columns). Earlier MTS history is published only as PDF and text statements and is not used.',
            'Totals (receipts, outlays, deficit) are MTS Table 1 monthly values from the newest statement that reports each month; Table 1 repeats the current and prior fiscal year, so a month is revised for up to two years and then fixed.',
            f'Receipts by source and outlays by function come from MTS Table 9. Detail through {month_year(revised_to)} is revised: it is taken from the "prior fiscal year to date" columns of the statements a year later and reconciles with the Table 1 totals. ' +
            (f'Detail for {month_span(first_published)} is as first published in each month\'s own statement and has not yet been revised.' if first_published else 'No month uses first-published detail.'),
            'Receipt detail is exhaustive: the seven receipt series sum to total receipts. Payroll taxes are social insurance and retirement receipts (employment and general retirement, unemployment insurance, other retirement). Outlays are by budget function; other outlays are total net outlays less the seven named functions and include undistributed offsetting receipts (which are negative), so the outlay series sum to total outlays.',
            'Health is mostly Medicaid; Medicare outlays are net of premiums and other offsetting receipts. Net interest is net of interest received by trust funds and other interest income.',
            'Debt held by the public is from the Monthly Statement of the Public Debt (Treasury securities held outside federal government accounts, end of month). It excludes agency debt and does not match CBO\'s "debt held by the public" to the last billion. Gross federal debt adds intragovernmental holdings (mainly trust funds).',
            'Debt as a share of GDP is calculated by this dashboard: debt held by the public divided by the latest four-quarter BEA nominal GDP (not seasonally adjusted) ending at most two months earlier, with quarters BEA has not yet published projected from CBO growth (see the GDP notes). It is not an official Treasury, OMB or CBO ratio.',
            f'Treasury Fiscal Data last updated MTS Table 1 on {long_date(release)}; the next release date comes from the Fiscal Data release calendar. Values are in millions of dollars (debt in billions), converted from dollars and cents and rounded to the nearest $1,000.'],
    }


# ---- forecast ----

def fetch_forecast(fetch):
    """CBO publishes no monthly deficit profile, so the forecast group is explicitly unavailable."""
    body = json.loads(fetch(LATEST_T1_URL).decode('utf-8'))
    record = ((body.get('data') or [{}])[0]).get('record_date', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', record):
        raise ValueError('Could not determine the latest MTS month')
    budget = cbo_vintage(fetch(CBO_CATALOG_URL), 'ten_year_budget', 'annual_fy')
    fy = fy_label(fy_start_of(record[:7]))
    month = f'{NAMES[int(budget["vintage"][5:]) - 1]} {budget["vintage"][:4]}'
    return {
        'schemaVersion': 1, 'status': 'unavailable', 'fiscalYear': fy,
        'vintage': f'CBO baseline budget projections, {month} (annual only)', 'publicationDate': budget['vintage'],
        'units': UNIT_B,
        'basis': 'Cumulative unified federal deficit, fiscal year to date; positive is a deficit',
        'sources': [{'id': 'cbo-ten-year-budget', 'publisher': 'Congressional Budget Office', 'title': f'{budget["title"]} ({month} vintage)',
                     'url': budget['landingPage'], 'downloadUrl': budget['url'], 'publicationDate': budget['vintage'], 'licence': 'Public domain (U.S. Government work)',
                     'attribution': 'Source: Congressional Budget Office, via the CBO open data repository (US-CBO/cbo-data).'}],
        'cumulative': [],
        'notes': [
            'No monthly profile is available. CBO and OMB publish only annual (fiscal-year) deficit projections, with no month-by-month path, so there is no official benchmark for year-to-date results.',
            'CBO\'s Monthly Budget Review compares year-to-date results with the prior year, not with a projection. This dashboard does not divide an annual projection across months.',
            f'The fiscal year shown is the one containing the latest Monthly Treasury Statement month ({month_year(record)}); "2025-26" is FY2026. CBO\'s open-data repository gives the month of each baseline but not the day.'],
    }


# ---- validators ----

def _months_contiguous(dates):
    for left, right in zip(dates, dates[1:]):
        if right != shift(left, 1):
            raise ValueError(f'Missing or unordered month after {left}')


def validate_fiscal(data, previous=None):
    if data.get('schemaVersion') != 1 or not data.get('sources') or not data.get('notes'):
        raise ValueError('Fiscal dataset missing schema, sources or notes')
    if 'federal' not in data.get('scope', '') or 'unified budget' not in data.get('scope', ''):
        raise ValueError('Fiscal scope must state the federal unified budget')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data.get('releaseDate') or '') or not data.get('nextRelease'):
        raise ValueError('Release dates missing')
    rows = data.get('observations', [])
    _months_contiguous([r['date'] for r in rows])
    if len(rows) < 24 or not rows[0]['date'].endswith('-10'):
        raise ValueError('Fewer than 24 months or history does not start in October')
    if rows[-1]['date'] != data.get('asOf'):
        raise ValueError('asOf must be the latest month')
    series = data.get('series') or {}
    for key in ('borrowing', 'receipts', 'spending', 'debtBillion', 'debtPct', *DETAIL_KEYS):
        if key not in series:
            raise ValueError(f'Series metadata missing for {key}')
    for r in rows:
        when = r['date']
        if any(not isinstance(r.get(k), (int, float)) for k in ('borrowing', 'receipts', 'spending', *DETAIL_KEYS)):
            raise ValueError(f'Missing flow values in {when}')
        if abs(r['spending'] - r['receipts'] - r['borrowing']) > 0.01:
            raise ValueError(f'Borrowing identity failed in {when}')
        if not 100_000 < r['receipts'] < 2_000_000 or not 100_000 < r['spending'] < 2_000_000 or abs(r['borrowing']) > 1_000_000:
            raise ValueError(f'Implausible monthly magnitude in {when} (expected USD million)')
        if r.get('detailMethod') not in ('revised', 'first-published'):
            raise ValueError(f'Unknown detail method in {when}')
        receipts = sum(r[k] for k in RECEIPTS)
        outlays = sum(r[k] for k in (*OUTLAYS, OTHER_OUTLAYS))
        tolerance = 2000 if r['detailMethod'] == 'revised' else 25000
        if abs(receipts - r['receipts']) > tolerance or abs(outlays - r['spending']) > tolerance:
            raise ValueError(f'Receipt or outlay detail does not reconcile with totals in {when}')
        if r['individualIncomeTax'] <= 0 or r['payrollTaxes'] <= 0 or r['socialSecurity'] <= 0:  # net interest can be negative (e.g. September trust-fund interest credits)
            raise ValueError(f'Implausible sign in detail series for {when}')
        if r.get('debtBillion') is not None:
            if not 5_000 < r['debtBillion'] < 100_000 or (r.get('grossDebtBillion') is not None and r['grossDebtBillion'] < r['debtBillion']):
                raise ValueError(f'Implausible debt in {when} (expected USD billion)')
        if r.get('debtPct') is not None and (r.get('debtBillion') is None or not 30 < r['debtPct'] < 200):
            raise ValueError(f'Implausible debt ratio in {when}')
    if sum(r.get('debtBillion') is None for r in rows[-3:]) > 1:
        raise ValueError('Debt held by the public missing for recent months')
    detail = [r['detailMethod'] for r in rows]
    if detail != sorted(detail, key=('revised', 'first-published').index):
        raise ValueError('Revised detail months must precede first-published months')
    gdp = data.get('gdp') or {}
    obs = gdp.get('observations') or []
    if not obs or not any(o.get('rollingAnnualMillion') for o in obs):
        raise ValueError('Missing GDP denominator')
    for left, right in zip(obs, obs[1:]):
        if right['date'] != shift(left['date'], 3):
            raise ValueError('GDP quarters are not contiguous')
    for o in obs:
        value = o.get('rollingAnnualMillion')
        if value is not None and not 5e6 < value < 1e8:
            raise ValueError(f'Implausible four-quarter GDP in {o["date"]} (expected USD million)')
    flagged = sorted({q for o in obs for q in o.get('forecastQuarters', [])})
    extension = gdp.get('forecastExtension')
    if flagged and (not extension or extension.get('quarters') != flagged or not extension.get('vintage')):
        raise ValueError('GDP forecast quarters are not disclosed in forecastExtension')
    if extension and not flagged:
        raise ValueError('forecastExtension without forecast quarters')
    if len(flagged) > 2:
        raise ValueError('More than two projected GDP quarters')
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
    if status != 'unavailable':
        raise ValueError('No official US monthly deficit profile exists; status must be "unavailable"')
    if data.get('cumulative'):
        raise ValueError('Unavailable forecast carries values')
    match = re.fullmatch(r'(\d{4})-(\d{2})', data.get('fiscalYear') or '')
    if not match or (int(match[1]) + 1) % 100 != int(match[2]):
        raise ValueError('Invalid fiscal year label')
    if not data.get('vintage') or not re.fullmatch(r'\d{4}-\d{2}(-\d{2})?', data.get('publicationDate') or ''):
        raise ValueError('Forecast vintage or publication date missing')
