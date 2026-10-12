"""Australian Treasury Tax Expenditures and Insights Statement (TEIS), pinned 2025-26 edition.

Revenue forgone per tax expenditure (A$m, accrual, 2021-22 to 2028-29) from the chart-data
workbook; tax category, functional category, type, reliability, previous code, commencement,
legislation and description from the DOCX Appendix A.1, joined on code and checked value by value.
CC BY 4.0, (c) Commonwealth of Australia. Revenue forgone assumes no behavioural response and is
not the revenue from abolition. Treasury publishes no total and cautions against adding items, so
the official aggregate is null; quantified sums are labelled derived. '-' nil, '..' rounded to
zero, '*' unquantifiable and 'nfp' not for publication stay null with their status.
"""
import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree as ET
import openpyxl
from .outlook import W, _text, fy, number

# New editions need review: update these and the catalogue (catalogue/au/budget.json).
PAGE = 'https://treasury.gov.au/publication/p2025-721342'
EDITION = '2025-26'
TITLE = '2025–26 Tax Expenditures and Insights Statement'
FIRST_PROJECTION = '2025-26'  # Forward estimates of the 2025-26 MYEFO on which the edition is based.
SHEET = 'Revenue forgone estimates'
LICENCE = 'CC BY 4.0'
ATTRIBUTION = 'Based on Commonwealth of Australia data (Treasury, Tax Expenditures and Insights Statement), CC BY 4.0.'
STATUS = {'-': 'nil', '..': 'negligible', '*': 'unquantifiable', 'nfp': 'withheld'}
MISSING = list(STATUS.values()) + ['included elsewhere']
MAGNITUDE = {'0': (0, 0), '1': (0, 10), '2': (10, 100), '3': (100, 1000), '4': (1000, None)}


def links(html):
    title = re.search(r'<title>([^<|]+)', html)
    date = re.search(r'datetime="(\d{4}-\d{2}-\d{2})T', html)
    xlsx = re.findall(r'href="(/sites/default/files/[^"]+-chart-data\.xlsx)"', html)
    docx = re.findall(r'href="(/sites/default/files/[^"]+\.docx)"', html)
    if not title or TITLE not in title[1].replace('&ndash;', '–') or not date or len(set(xlsx)) != 1 or len(set(docx)) != 1:
        raise ValueError('TEIS publication page changed: review the edition before importing')
    return date[1], 'https://treasury.gov.au' + xlsx[0], 'https://treasury.gov.au' + docx[0]


def parse_workbook(raw):
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    if SHEET not in wb.sheetnames:
        raise ValueError(f'TEIS sheet missing: {SHEET}')
    rows = [list(r) for r in wb[SHEET].values]
    header = rows[0]
    years = [fy(h) for h in header[2:] if h is not None]
    if header[:2] != ['Code', 'Title'] or not years or None in years or any(int(b[:4]) - int(a[:4]) != 1 for a, b in zip(years, years[1:])):
        raise ValueError('TEIS workbook header changed')
    out = {}
    for r in rows[1:]:
        if not r or r[0] is None:
            continue
        code = str(r[0]).strip()
        if not re.fullmatch(r'[A-Z]\d+', code) or code in out:
            raise ValueError(f'Invalid or duplicate TEIS code {code!r}')
        raw_values = ['' if v is None else str(v).strip() if isinstance(v, str) else v for v in r[2:2 + len(years)]]
        out[code] = {'title': str(r[1]).strip(), 'values': raw_values}
    return years, out


def cell(value):
    """Workbook cell -> (costMillion, status, rawValue)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), 'estimate', str(value)
    if value in STATUS:
        return None, STATUS[value], value
    raise ValueError(f'Unknown TEIS value code {value!r}')


def parse_appendix(raw):
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read('word/document.xml'))
    entries, sections, counts, current, section = {}, [], None, None, None
    in_appendix = False
    for el in root.find(W + 'body'):
        if el.tag == W + 'p':
            style = el.find(f'{W}pPr/{W}pStyle')
            style = style.get(W + 'val') if style is not None else ''
            text = _text(el)
            if style == 'Heading1':
                in_appendix = text.startswith('Appendix')
            if not in_appendix:
                continue
            if style == 'Heading3':
                section = text.lstrip('-').strip()
                sections.append(section)
                current = None
            elif style == 'Heading5':
                m = re.match(r'([A-Z]\d+)\s*(.+)$', text)
                if not m:
                    raise ValueError(f'Unparsed TEIS entry heading {text!r}')
                if m[1] in entries:
                    raise ValueError(f'Duplicate TEIS appendix code {m[1]}')
                current = entries[m[1]] = {'title': m[2].strip(), 'section': section, 'function': None, 'table': None, 'description': []}
            elif style == 'MeasureTableHeading' and current and text and current['function'] is None:
                current['function'] = re.sub(r'\s*\(\$m\)$', '', text)
            elif style.startswith('Heading'):
                current = None
            elif current and text and current['table'] is not None:
                current['description'].append(text)
        elif el.tag == W + 'tbl' and in_appendix:
            rows = [[_text(c) for c in tr.findall(W + 'tc')] for tr in el.findall(W + 'tr')]
            if current and current['table'] is None:
                current['table'] = rows
            elif rows and rows[0] and rows[0][0] == 'Tax expenditure category':
                counts = [(r[0], int(r[1])) for r in rows[1:] if len(r) == 2 and r[1].isdigit()]
    if counts is None:
        raise ValueError('TEIS Table A1.1 category counts missing')
    return entries, sections, counts


def metadata(rows, years):
    if len(rows) < 3 or [fy(y) for y in rows[0]] != years:
        raise ValueError('TEIS appendix estimate table changed')
    cells = [c.strip() for r in rows[2:] for c in r]
    label = re.compile(r'(Tax expenditure type|2024-25 code|Estimate Reliability|\* Category|Commencement date|Expiry date|Legislative reference)\s*:?\s*(.*)$')
    fields, i = {}, 0
    while i < len(cells):
        m = label.match(cells[i])
        if m:
            if m[1] in fields:
                raise ValueError(f'Duplicate TEIS metadata field {m[1]}')
            nxt = cells[i + 1] if i + 1 < len(cells) and not m[2] and not label.match(cells[i + 1]) else None
            fields[m[1]] = m[2] or nxt or None
            i += 2 if nxt is not None else 1
        elif cells[i]:
            raise ValueError(f'Unexpected TEIS metadata cell {cells[i]!r}')
        else:
            i += 1
    if not {'Tax expenditure type', 'Estimate Reliability'} <= set(fields):
        raise ValueError(f'TEIS appendix metadata fields changed: {sorted(fields)}')
    values = rows[1] * len(years) if len(rows[1]) == 1 else rows[1]  # one merged cell, e.g. 'Included in A43'
    if len(values) != len(years):
        raise ValueError('TEIS appendix estimate row has the wrong width')
    return values, fields


def magnitude(code):
    m = re.fullmatch(r'(\d|NA)\s*([+-])?', code or '')
    if not m:
        return None
    low, high = MAGNITUDE.get(m[1], (None, None))
    return {'code': code, 'sign': {'+': 'positive', '-': 'negative'}.get(m[2]), 'lowerMillion': low, 'upperMillion': high,
            'meaning': 'not available' if m[1] == 'NA' else f'{"negative " if m[2] == "-" else ""}order of magnitude ${low}m{"+" if high is None else f" to ${high}m"} a year on average'}


def same(docx_cell, value):
    if isinstance(value, float):
        return number(docx_cell) == value
    return docx_cell.strip() == value


def parse_reliefs(xlsx, docx, published, xlsx_url, docx_url, retrieved=None):
    years, workbook = parse_workbook(xlsx)
    entries, sections, counts = parse_appendix(docx)
    if set(entries) != set(workbook):
        raise ValueError(f'TEIS workbook and appendix codes differ: {sorted(set(entries) ^ set(workbook))[:10]}')
    by_section = [sum(1 for e in entries.values() if e['section'] == s) for s in sections]
    by_section = [n for n in by_section if n]
    if [n for _, n in counts if _ != 'Total'] != by_section or dict(counts).get('Total') != len(workbook):
        raise ValueError('TEIS appendix counts disagree with Table A1.1')
    heads = dict(zip([s for s in sections if any(e['section'] == s for e in entries.values())], [c for c, _ in counts if c != 'Total']))
    reliefs = []
    for code, row in sorted(workbook.items(), key=lambda kv: (kv[0][0], int(kv[0][1:]))):
        entry = entries[code]
        values, fields = metadata(entry['table'], years)
        reliability = re.sub(r'\s+-\s+', ' \u2013 ', fields['Estimate Reliability']) if fields['Estimate Reliability'] else None
        estimates = []
        for year, raw_value, docx_value in zip(years, row['values'], values):
            cost, status, raw_text = cell(raw_value)
            included = re.fullmatch(r'Included in ([A-Z]\d+)', docx_value.strip())
            if included and raw_text == '-':
                status = 'included elsewhere'
            elif not same(docx_value, cost if cost is not None else raw_text):
                raise ValueError(f'TEIS {code} {year}: workbook {raw_value!r} disagrees with appendix {docx_value!r}')
            forecast = year >= FIRST_PROJECTION
            if status == 'estimate' and forecast:
                status = 'forecast'
            estimates.append({'year': year, 'costMillion': cost, 'status': status, 'rawValue': raw_text, 'claimants': None,
                              'claimantStatus': 'unavailable', 'isForecast': forecast, **({'includedIn': included[1]} if status == 'included elsewhere' else {})})
        reliefs.append({'id': code, 'teisCode': code, 'name': row['title'], 'taxHead': heads[entry['section']], 'appendixSection': entry['section'],
            'classification': 'tax expenditure', 'estimateType': 'multi-year', 'objective': None,
            'description': ' '.join(entry['description']) or None, 'notes': None,
            'quality': f'Estimate reliability: {reliability}' if reliability else None, 'reliability': reliability,
            'functionalCategory': entry['function'], 'taxExpenditureType': fields['Tax expenditure type'],
            'previousCode': fields.get('2024-25 code'), 'commencementDate': fields.get('Commencement date'), 'expiryDate': fields.get('Expiry date'),
            'legislativeReference': fields.get('Legislative reference'), 'magnitudeCategory': magnitude(fields.get('* Category')),
            'sourceUrl': xlsx_url, 'publicationVintage': published, 'retrievalDate': retrieved, 'firstForecastYear': FIRST_PROJECTION,
            'aggregationRole': 'standalone', 'estimates': estimates})
    def totals(items):
        out = []
        for i, year in enumerate(years):
            values = [r['estimates'][i] for r in items]
            numeric = [e['costMillion'] for e in values if e['costMillion'] is not None]
            out.append({'year': year, 'quantifiedSumMillion': round(sum(numeric), 6), 'quantifiedCount': len(numeric),
                        'excluded': {s: sum(1 for e in values if e['status'] == s) for s in MISSING}, 'isForecast': year >= FIRST_PROJECTION})
        return out
    super_items = [r for r in reliefs if r['teisCode'].startswith('C')]
    if len({r['taxHead'] for r in super_items}) != 1:
        raise ValueError('TEIS C codes no longer form one superannuation category')
    data = {'schemaVersion': 1, 'asOf': published, 'publicationDate': published, 'country': 'au', 'edition': EDITION, 'unit': 'AUD million',
        'defaultYear': FIRST_PROJECTION, 'years': years,
        'sources': [{'id': 'au-teis-workbook', 'name': f'{TITLE}: chart data (revenue forgone estimates)', 'publisher': 'Australian Treasury', 'url': xlsx_url, 'publicationDate': published, 'licence': LICENCE, 'attribution': ATTRIBUTION},
                    {'id': 'au-teis-appendix', 'name': f'{TITLE}: Appendix A.1 (DOCX)', 'publisher': 'Australian Treasury', 'url': docx_url, 'publicationDate': published, 'licence': LICENCE, 'attribution': ATTRIBUTION},
                    {'id': 'au-teis-page', 'name': TITLE, 'publisher': 'Australian Treasury', 'url': PAGE, 'publicationDate': published, 'licence': LICENCE, 'attribution': ATTRIBUTION}],
        'aggregate': {'year': FIRST_PROJECTION, 'costMillion': None, 'count': None, 'label': 'No official total: Treasury does not publish an aggregate and cautions against adding tax expenditures (interactions).', 'source': PAGE,
                      'rounding': 'See derivedTotals for a labelled sum of quantified estimates only.'},
        'derivedTotals': {'basis': 'derived', 'method': 'Sum of numeric revenue-forgone estimates (positive and negative) for each year; nil, rounded-to-zero, unquantifiable and not-for-publication items are excluded and counted, never imputed.',
                          'caveat': 'Not an official total and not revenue available from abolition: items interact and coverage differs by year.', 'all': totals(reliefs), 'byTaxHead': {h: totals([r for r in reliefs if r['taxHead'] == h]) for h in dict.fromkeys(r['taxHead'] for r in reliefs)}},
        'superannuation': {'basis': 'TEIS codes C1-C12 (Appendix A.1 retirement savings / superannuation tax category)', 'codes': [r['teisCode'] for r in super_items], 'totals': totals(super_items),
                           'note': 'Derived sum of quantified superannuation tax expenditures. Treasury combines some items (e.g. C1 and C4 earnings concessions) in Chapter 2 estimates; those combined estimates are not imported.'},
        'reliefs': reliefs, 'isa': None, 'pensions': None,
        'notes': ['Revenue forgone is the difference between actual and benchmark tax treatment assuming unchanged behaviour. It is not the revenue gain from abolition and must not be added to payments or the budget balance.',
                  f'{years[0]} to {years[-1]}; years from {FIRST_PROJECTION} are forward-estimate projections (isForecast). Estimates are accrual and nominal; Treasury rounds them and reports reliability per item.',
                  'Status codes: nil (-; "included elsewhere" with includedIn where the appendix says the cost is included in another item), negligible (.. not zero but rounded to zero), unquantifiable (*; an order-of-magnitude category is kept in magnitudeCategory where published) and withheld (nfp, commercially sensitive). All are null, never zero.',
                  'classification is "tax expenditure" for every item: the TEIS does not split items into structural and non-structural. The tax category is from Appendix A.1 (Table A1.1); the functional category is the COFOG-style purpose.',
                  'Codes are renumbered between editions; previousCode gives the 2024-25 TEIS code. The edition is pinned; new editions need adapter review.',
                  'Superannuation concessions (codes C1 to C12) are summarised separately as a descriptive, non-official sum.']}
    validate_reliefs(data)
    return data


def validate_reliefs(data):
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported reliefs schema')
    rows = data.get('reliefs') or []
    years = data.get('years') or []
    if len(rows) < 250:
        raise ValueError('Incomplete TEIS dataset')
    if len({r['id'] for r in rows}) != len(rows) or len({(r['name'], r['taxHead']) for r in rows}) != len(rows):
        raise ValueError('Duplicate tax expenditure identity')
    for r in rows:
        if r['classification'] != 'tax expenditure' or not r.get('taxHead') or [e['year'] for e in r['estimates']] != years:
            raise ValueError(f'Malformed tax expenditure {r.get("id")}')
        for e in r['estimates']:
            if e['status'] not in MISSING + ['estimate', 'forecast']:
                raise ValueError(f'Unknown estimate status {e["status"]}')
            if e['status'] in MISSING and e['costMillion'] is not None:
                raise ValueError('Missing tax expenditure estimate converted to a value')
            if e['status'] in ('estimate', 'forecast') and e['costMillion'] is None:
                raise ValueError('Numeric estimate lost')
    if data.get('aggregate', {}).get('costMillion') is not None:
        raise ValueError('Treasury publishes no TEIS total')
    for i, total in enumerate(data['derivedTotals']['all']):
        values = [r['estimates'][i]['costMillion'] for r in rows if r['estimates'][i]['costMillion'] is not None]
        if abs(sum(values) - total['quantifiedSumMillion']) > 1e-6 or len(values) + sum(total['excluded'].values()) != len(rows):
            raise ValueError('Derived TEIS total inconsistent')
    if data.get('isa') or data.get('pensions'):
        raise ValueError('UK-only relief sections must be null')
    return data


def fetch_reliefs(fetcher):
    published, xlsx_url, docx_url = links(fetcher(PAGE).decode('utf-8', 'replace'))
    xlsx, docx = fetcher(xlsx_url), fetcher(docx_url)
    record = next((r for r in reversed(getattr(fetcher, 'records', [])) if r['url'] == xlsx_url), {})
    data = parse_reliefs(xlsx, docx, published, xlsx_url, docx_url, record.get('retrievedAt'))
    data['fileSha256'] = {'workbook': hashlib.sha256(xlsx).hexdigest(), 'appendix': hashlib.sha256(docx).hexdigest()}
    return data
