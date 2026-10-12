"""Australian Government budget outlook: pinned Budget and MYEFO vintages plus Budget Paper 1 history.

Sources (CC BY 4.0, (c) Commonwealth of Australia): 2026-27 Budget Paper No. 1 (Statement 2
Table 2.2, Statement 3 Table 3.1, Box 3.1 and chart data, Statement 11 historical tables,
nominal GDP workbook) and MYEFO 2025-26 (Part 2 Table 2.3, Part 3 Table 3.1 and chart data).
General government sector, cash basis, July-June financial years. borrowing = minus the
underlying cash balance (UCB), which excludes net Future Fund earnings; debtPct/debtBn are net
debt (gross debt is kept separately). Treasury publishes no output gap and no numerical fiscal
rules. Vintages are pinned: a new Budget/MYEFO needs adapter review and is added, never
substituted. Chart sheets are found by their caption in the statement, never by number.
Derived values (primary balances, structural $b, implied GDP) are flagged in seriesMetadata.
"""
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET
import openpyxl

BUDGET_BASE = 'https://budget.gov.au/content'
MYEFO_BASE = 'https://archive.budget.gov.au/2025-26/myefo'
GDP_URL = f'{BUDGET_BASE}/bp1/download/bp1_s2-data-nominal-GDP.xlsx'
HISTORY_URL = f'{BUDGET_BASE}/bp1/download/bp1_bs-11.docx'
LICENCE = 'CC BY 4.0'
ATTRIBUTION = 'Based on Commonwealth of Australia data (Australian Government Budget papers), CC BY 4.0.'
VINTAGES = [
    {'id': '2025-12', 'label': '2025-26 MYEFO', 'publicationDate': '2025-12-17', 'forecastStart': '2025-26',
     'page': f'{MYEFO_BASE}/index.htm', 'dateText': r'released on \w+ 17\s+December\s+2025',
     'fiscal': f'{MYEFO_BASE}/download/03_Part_3.docx', 'economy': f'{MYEFO_BASE}/download/02_Part_2.docx',
     'chart': f'{MYEFO_BASE}/download/myefo-2025-26-chart-data.zip', 'chartBook': 'part-3',
     'chartLabel': '2025-26 MYEFO', 'tableRow': 'MYEFO', 'economyTable': r'Table\s*2\.3', 'tables': 'MYEFO Part 3 Table 3.1, Part 2 Table 2.3'},
    {'id': '2026-05', 'label': '2026-27 Budget', 'publicationDate': '2026-05-12', 'forecastStart': '2025-26',
     'page': f'{BUDGET_BASE}/bp1/download/bp1_prelims.docx', 'dateText': r'12 May 2026',
     'fiscal': f'{BUDGET_BASE}/bp1/download/bp1_bs-3.docx', 'economy': f'{BUDGET_BASE}/bp1/download/bp1_bs-2.docx',
     'chart': f'{BUDGET_BASE}/download/chart-data-final.zip', 'chartBook': 'bp1-bs3',
     'chartLabel': '2026-27 Budget', 'tableRow': None, 'economyTable': r'Table\s*2\.2', 'tables': 'BP1 Statement 3 Table 3.1, Statement 2 Table 2.2'},
]
LATEST = '2026-05'
MEASURES = {'underlying cash balance': 'ucb', 'receipts': 'receipts', 'tax receipts': 'taxReceipts', 'non-tax receipts': 'nonTaxReceipts',
            'payments': 'spending', 'gross debt': 'grossDebt', 'net debt': 'debt', 'net interest payments': 'interest'}
ECONOMY = {'real gross domestic product': 'realGdpGrowth', 'nominal gross domestic product': 'nominalGdpGrowth', 'consumer price index': 'inflation',
           'wage price index': 'wagePriceIndexGrowth', 'gdp deflator': 'gdpDeflatorGrowth', 'unemployment rate (per cent)': 'unemploymentRate'}
CHARTS = {'ucbPct': ('Underlying cash balance', None), 'grossDebtPct': ('Gross debt', None), 'debtPct': ('Net debt', None),
          'receiptsPct': ('Total receipts', 'total'), 'spendingPct': ('Total payments', None)}
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
YEAR = re.compile(r'(\d{4})[-–](\d{2})')


def fy(text):
    m = YEAR.fullmatch(str(text).strip())
    return f'{m[1]}-{m[2]}' if m and int(m[2]) == (int(m[1]) + 1) % 100 else None


def number(text):
    """'1,051.0', '-0.4', '2 1/4', '- 1/4', '3/4' -> float; '' and dashes -> None."""
    t = str(text).strip().replace(',', '').replace('−', '-').replace('–', '-').replace('\xa0', ' ')
    if t in ('', '-', '..', 'na', 'nfp', '*'):
        return None
    m = re.fullmatch(r'(-)?\s*(\d+(?:\.\d+)?)?\s*(?:(\d)/(\d))?', t)
    if not m or (m[2] is None and m[3] is None):
        raise ValueError(f'Unparseable official number: {text!r}')
    value = float(m[2] or 0) + (int(m[3]) / int(m[4]) if m[3] else 0)
    return -value if m[1] else value


def _text(el):
    out = []
    for node in el.iter():
        if node.tag == W + 't':
            out.append(node.text or '')
        elif node.tag == W + 'noBreakHyphen':
            out.append('-')
        elif node.tag == W + 'tab':
            out.append(' ')
    return re.sub(r'\s+', ' ', ''.join(out).replace('‍', '')).strip()


def docx_blocks(raw):
    """Body-level blocks in order: ('p', text) or ('t', rows); merged cells repeated across their grid span."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read('word/document.xml'))
    blocks = []
    for el in root.find(W + 'body'):
        if el.tag == W + 'p':
            blocks.append(('p', _text(el)))
        elif el.tag == W + 'tbl':
            rows = []
            for tr in el.findall(W + 'tr'):
                row = []
                for tc in tr.findall(W + 'tc'):
                    span = tc.find(f'{W}tcPr/{W}gridSpan')
                    row += [_text(tc)] * int(span.get(W + 'val') if span is not None else 1)
                rows.append(row)
            blocks.append(('t', rows))
    return blocks


def paragraphs(raw):
    """All paragraph texts in document order, including those inside tables and text boxes."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read('word/document.xml'))
    return [_text(p) for p in root.iter(W + 'p')]


def tables_after(blocks, pattern, first_only=True):
    """Rows of the table(s) following headings matching pattern (continued tables are concatenated)."""
    rows, found, active = [], False, False
    for kind, value in blocks:
        if kind == 'p' and value:
            active = bool(re.match(pattern, value))
            found |= active
        elif kind == 't' and active:
            rows += value
            active = False
            if first_only:
                return rows
    if not found or not rows:
        raise ValueError(f'Official table missing: {pattern}')
    return rows


def label(cell):
    return re.sub(r'(\([a-z]\))+$', '', cell.strip()).strip().lower().replace('nontax', 'non-tax')


def parse_aggregates(rows, sub_row=None):
    """Table 3.1 in either layout: Budget (value row + 'Per cent of GDP' row) or MYEFO (rows per vintage)."""
    header = next((i for i, r in enumerate(rows) if sum(bool(fy(c)) for c in r) >= 3), None)
    if header is None or header + 1 >= len(rows):
        raise ValueError('Table 3.1 year header missing')
    years, units = rows[header], rows[header + 1]
    groups, group = [], ''
    for i in range(len(years)):
        cell = rows[header - 1][i] if header and i < len(rows[header - 1]) else ''
        group = cell or group
        groups.append(group)
    cols = []
    for i, (y, u) in enumerate(zip(years, units)):
        if fy(y):
            unit = 'Bn' if u.strip() == '$b' else 'Pct' if '%' in u else None
            if unit is None:
                raise ValueError(f'Table 3.1 unit header changed: {u!r}')
            cols.append((i, fy(y), unit, groups[i]))
    if len({(y, u) for _, y, u, _ in cols}) != len(cols):
        raise ValueError('Duplicate Table 3.1 year columns')
    out, current = {}, None
    for row in rows[header + 2:]:
        name = label(row[0]) if row else ''
        if name in MEASURES:
            current = MEASURES[name]
            if sub_row:
                continue
            mode = 'value'
        elif name == 'per cent of gdp' and current and not sub_row:
            mode = 'pct'
        elif sub_row and current and name == sub_row.lower():
            mode = 'value'
        elif not name or (sub_row and current):
            continue
        else:
            raise ValueError(f'Unexpected Table 3.1 row: {row[0]!r}')
        for i, year, unit, _ in cols:
            value = number(row[i]) if i < len(row) else None
            key = f'{current}{"Pct" if mode == "pct" else unit}'
            if value is not None:
                if key in out.setdefault(year, {}):
                    raise ValueError(f'Duplicate Table 3.1 value {key} {year}')
                out[year][key] = value
    missing = [m for m in MEASURES.values() if not any(f'{m}Bn' in v for v in out.values())]
    if missing:
        raise ValueError(f'Table 3.1 measures missing: {missing}')
    actual = sorted({y for _, y, _, g in cols if g.strip().lower() in ('actual', 'actuals')})
    projected = sorted({y for _, y, _, g in cols if g.strip().lower().startswith('projection')})
    return out, actual, projected


def captions(raw):
    found = {}
    for text in paragraphs(raw):
        m = re.match(r'Chart\s*(\d+\.\d+):?\s*(.+)$', text)
        if m:
            found.setdefault(m[2].strip().lower(), []).append(m[1])
    return found


def chart_sheets(raw, book):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in archive.namelist() if n.lower().endswith('.xlsx') and book in n.lower()]
    if len(names) != 1:
        raise ValueError(f'Chart workbook {book} missing or ambiguous')
    wb = openpyxl.load_workbook(io.BytesIO(archive.read(names[0])), data_only=True, read_only=True)
    return {ws.title: [list(r) for r in ws.values] for ws in wb.worksheets}


def sheet_series(rows):
    """Flatten chart headers (group headers forward-filled) and return {header: {year: value}}."""
    first = next((i for i, r in enumerate(rows) if r and fy(r[0] or '')), None)
    if first is None or first < 2:
        raise ValueError('Chart sheet has no year rows')
    head = rows[1:first]
    width = max(len(r) for r in rows)
    labels = []
    for c in range(1, width):
        parts = []
        for r in head:
            filled = next((r[k] for k in range(c, 0, -1) if k < len(r) and r[k] not in (None, '')), None) if r is not head[-1] else (r[c] if c < len(r) else None)
            if filled not in (None, ''):
                parts.append(str(filled).strip())
        labels.append(' - '.join(parts))
    out = {}
    for c, name in enumerate(labels, 1):
        if not name:
            continue
        values = {}
        for r in rows[first:]:
            year = fy(r[0] or '') if r and r[0] else None
            if year and c < len(r) and r[c] not in (None, ''):
                if not isinstance(r[c], (int, float)) or not math.isfinite(r[c]):
                    raise ValueError(f'Non-numeric chart value {r[c]!r}')
                values[year] = round(float(r[c]), 6)
        out[name] = values
    return out


def chart(sheets, caps, title, column, require=None):
    """Series for one column of the uniquely captioned sheet that carries this column (and require)."""
    hits = []
    for number_ in caps.get(title.lower(), []):
        for name in (number_, f'C{number_}'):
            if name in sheets:
                series = sheet_series(sheets[name])
                match = [k for k in series if column.lower() in k.lower()]
                if len(match) > 1 and require:
                    match = [k for k in match if require in k.lower()]
                if len(match) == 1 and any('historical' in k.lower() for k in series):
                    hits.append(series[match[0]])
    if len(hits) != 1:
        raise ValueError(f'Chart "{title}" with column "{column}" not found exactly once ({len(hits)})')
    return hits[0]


def structural(sheets, caps):
    hits = []
    for number_ in caps.get('structural budget balance', []):
        for name in (number_, f'C{number_}'):
            if name in sheets:
                series = {k.lower(): v for k, v in sheet_series(sheets[name]).items()}
                keys = {'underlying cash balance': 'ucb', 'structural budget balance': 'structural', 'cyclical factors': 'cyclical', 'temporary fiscal measures': 'temporary'}
                if set(keys) <= set(series):
                    hits.append({v: series[k] for k, v in keys.items()})
    if len(hits) != 1:
        raise ValueError('Structural budget balance chart not found exactly once')
    return hits[0]


def parse_economy(rows, column=None):
    header = next((i for i, r in enumerate(rows) if sum(bool(fy(c)) for c in r) >= 3), None)
    if header is None:
        raise ValueError('Economic forecast table header missing')
    years = rows[header]
    sub = rows[header + 1] if column and header + 1 < len(rows) else None
    cols = [(i, fy(y)) for i, y in enumerate(years) if fy(y) and (sub is None or not sub[i] or sub[i] == column)]
    if len({y for _, y in cols}) != len(cols):
        raise ValueError('Economic forecast columns ambiguous')
    out = {}
    for row in rows[header + 1:]:
        key = ECONOMY.get(label(row[0])) if row else None
        if key:
            for i, year in cols:
                out.setdefault(year, {})[key] = number(row[i])
    if any(k not in out.get(cols[-1][1], {}) for k in ECONOMY.values()):
        raise ValueError('Economic forecast rows missing')
    return out


def parse_gdp(raw, column):
    rows = [list(r) for r in openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True).worksheets[0].values]
    head = next((r for r in rows if r and any(isinstance(c, str) and 'Nominal GDP' in c for c in r)), None)
    if head is None or head.count(column) != 1:
        raise ValueError(f'Nominal GDP column missing: {column}')
    i = head.index(column)
    return {fy(r[0]): r[i] / 1000 for r in rows if r and r[0] and fy(r[0]) and i < len(r) and isinstance(r[i], (int, float))}


def parse_history(raw, gdp):
    blocks = docx_blocks(raw)
    estimates = {}
    def table(n, width):
        out = {}
        for r in tables_after(blocks, rf'Table\s*11\.{n}:', first_only=False):
            m = re.fullmatch(r'(\d{4}-\d{2})\s*(\(e\))?', r[0].strip()) if r else None
            year = fy(m[1]) if m else None
            if not year:
                continue
            if m[2]:
                estimates.setdefault(n, {})[year] = [number(c) for c in r[1:] if c]
                continue
            cells = [c for c in r[1:] if c]
            if len(cells) != width:
                raise ValueError(f'Table 11.{n} row shape changed for {year}')
            out[year] = [number(c) for c in cells]
        return out
    t1, t3, t4, t5 = table(1, 8), table(3, 6), table(4, 4), table(5, 6)
    rows = []
    for year in sorted(t1):
        if year not in t3 or year not in t4 or year not in t5:
            raise ValueError(f'Statement 11 tables disagree on years: {year}')
        rec, rec_pct, pay, real, pay_pct, ff, ucb, ucb_pct = t1[year]
        tax, tax_pct, nontax, nontax_pct, total, _ = t3[year]
        debt, debt_pct, interest, interest_pct = t4[year]
        gross, gross_pct = t5[year][:2]
        if total != rec:
            raise ValueError(f'Statement 11 receipts disagree in {year}')
        if abs(pay - rec + ucb) <= 2.5:
            includes_ff = False
        elif ff is not None and abs(pay - rec + ff + ucb) <= 2.5:
            includes_ff = True
        else:
            raise ValueError(f'Statement 11 UCB identity failed in {year}')
        implied = gdp.get(year) is None
        g = rec / rec_pct * 100 / 1000 if implied else gdp[year]
        rows.append({'year': year, 'status': 'outturn', 'borrowingBn': -ucb / 1000, 'borrowingPct': -ucb_pct,
            'receiptsBn': rec / 1000, 'receiptsPct': rec_pct, 'taxReceiptsBn': tax / 1000, 'nonTaxReceiptsBn': nontax / 1000,
            'spendingBn': pay / 1000, 'spendingPct': pay_pct, 'spendingRealGrowth': real,
            'futureFundEarningsBn': ff / 1000 if ff is not None else None, 'receiptsIncludeFutureFundEarnings': includes_ff,
            'interestBn': interest / 1000, 'deficitInterestBn': interest / 1000, 'interestPct': interest_pct,
            'debtBn': debt / 1000, 'debtPct': debt_pct, 'grossDebtBn': gross / 1000, 'grossDebtPct': gross_pct,
            'gdpBn': round(g, 3), 'gdpBasis': 'implied from receipts ratio' if implied else 'published',
            'primaryBalancePct': round((ucb + interest) / 1000 / g * 100, 6),
            'structuralBorrowingBn': None, 'structuralBorrowingPct': None, 'structuralPrimaryBalancePct': None, 'outputGapPct': None})
    real_growth = {year: cells[3] for year, cells in estimates.get(1, {}).items() if len(cells) == 8}
    return rows, real_growth


def parse_strategy(raw):
    texts = paragraphs(raw)
    start = next((i for i, t in enumerate(texts) if re.match(r'Box\s*3\.1:.*Fiscal Strategy', t)), None)
    if start is None:
        raise ValueError('Box 3.1 fiscal strategy missing')
    box = texts[start:start + 40]
    goal = next((t for t in box if re.search(r'overarching goal.*reduce gross debt as a share of the economy over time', t, re.I)), None)
    if goal is None:
        raise ValueError('Fiscal strategy overarching goal changed: review Box 3.1 before importing')
    i = box.index(goal) + 1
    objectives = []
    while i < len(box) and box[i] and not box[i].startswith('Delivering on') and box[i] != '|':
        objectives.append(box[i])
        i += 1
    if not 3 <= len(objectives) <= 10:
        raise ValueError('Fiscal strategy objectives not found')
    return goal, objectives


def fetch_text(fetch, url):
    raw = fetch(url)
    return raw.decode('utf-8', 'replace') if url.endswith('.htm') else '\n'.join(paragraphs(raw))


def build_vintage(spec, fetch, gdp_raw):
    if not re.search(spec['dateText'], re.sub(r'&nbsp;|\xa0', ' ', fetch_text(fetch, spec['page']))):
        raise ValueError(f'{spec["label"]} publication date not confirmed: review new vintage before importing')
    fiscal_raw = fetch(spec['fiscal'])
    values, actual, projected = parse_aggregates(tables_after(docx_blocks(fiscal_raw), r'Table\s*3\.1:'), spec['tableRow'])
    caps, sheets = captions(fiscal_raw), chart_sheets(fetch(spec['chart']), spec['chartBook'])
    charts = {key: chart(sheets, caps, title, spec['chartLabel'], require) for key, (title, require) in CHARTS.items()}
    sbb = structural(sheets, caps)
    economy = parse_economy(tables_after(docx_blocks(fetch(spec['economy'])), rf'{spec["economyTable"]}:\s*Domestic economy'), spec['tableRow'])
    gdp = parse_gdp(gdp_raw, f'Nominal GDP - {spec["chartLabel"]}')
    years = sorted(y for y in values if y not in projected)
    rows, projections = [], []
    for year in years:
        v = values[year]
        if year not in gdp:
            raise ValueError(f'No nominal GDP for {year}')
        g = gdp[year]
        row = {'year': year, 'status': 'outturn' if year < spec['forecastStart'] else 'forecast',
               'borrowingBn': -v['ucbBn'], 'borrowingPct': -v['ucbPct'], 'underlyingCashBalanceBn': v['ucbBn'], 'underlyingCashBalancePct': v['ucbPct'],
               'receiptsBn': v['receiptsBn'], 'receiptsPct': v['receiptsPct'], 'taxReceiptsBn': v['taxReceiptsBn'], 'taxReceiptsPct': v['taxReceiptsPct'],
               'nonTaxReceiptsBn': v['nonTaxReceiptsBn'], 'nonTaxReceiptsPct': v['nonTaxReceiptsPct'], 'spendingBn': v['spendingBn'], 'spendingPct': v['spendingPct'],
               'grossDebtBn': v['grossDebtBn'], 'grossDebtPct': v['grossDebtPct'], 'debtBn': v['debtBn'], 'debtPct': v['debtPct'],
               'interestBn': v['interestBn'], 'interestPct': v['interestPct'], 'gdpBn': g,
               'primaryBalancePct': round((v['interestBn'] - (-v['ucbBn'])) / g * 100, 6), 'outputGapPct': None,
               'earningsGrowth': None, 'bankRate': None, 'giltYield': None, 'netInvestmentBn': None}
        s = {k: sbb[k].get(year) for k in sbb}
        row.update({'structuralBalancePct': s['structural'], 'cyclicalFactorsPct': s['cyclical'], 'temporaryMeasuresPct': s['temporary'],
                    'structuralBorrowingPct': -s['structural'] if s['structural'] is not None else None,
                    'structuralBorrowingBn': round(-s['structural'] * g / 100, 6) if s['structural'] is not None else None,
                    'structuralPrimaryBalancePct': round(s['structural'] + v['interestBn'] / g * 100, 6) if s['structural'] is not None else None})
        for key in ECONOMY.values():
            row[key] = economy.get(year, {}).get(key)
        rows.append(row)
    last = years[-1]
    for year in sorted(y for y in charts['ucbPct'] if y > last):
        s = {k: sbb[k].get(year) for k in sbb}
        projections.append({'year': year, 'status': 'projection', 'gdpBn': gdp.get(year),
            'borrowingPct': -charts['ucbPct'][year], 'underlyingCashBalancePct': charts['ucbPct'][year],
            'grossDebtPct': charts['grossDebtPct'].get(year), 'debtPct': charts['debtPct'].get(year),
            'receiptsPct': charts['receiptsPct'].get(year), 'spendingPct': charts['spendingPct'].get(year),
            'structuralBalancePct': s['structural'], 'cyclicalFactorsPct': s['cyclical'], 'temporaryMeasuresPct': s['temporary']})
    for year in projected:
        target = next((p for p in projections if p['year'] == year), None)
        for key in ('ucbPct', 'grossDebtPct', 'debtPct', 'receiptsPct', 'spendingPct'):
            published = values[year].get(key)
            field = 'underlyingCashBalancePct' if key == 'ucbPct' else key
            if published is not None and (target is None or target.get(field) is None or abs(target[field] - published) > .051):
                raise ValueError(f'Table 3.1 projection {key} {year} disagrees with chart data')
        if target is not None:
            target.update({'taxReceiptsPct': values[year].get('taxReceiptsPct'), 'nonTaxReceiptsPct': values[year].get('nonTaxReceiptsPct'), 'interestPct': values[year].get('interestPct')})
    chart_check = {}
    for row in rows:
        for key, field in (('ucbPct', 'underlyingCashBalancePct'), ('grossDebtPct', 'grossDebtPct'), ('debtPct', 'debtPct'), ('receiptsPct', 'receiptsPct'), ('spendingPct', 'spendingPct')):
            if row['year'] in charts[key]:
                chart_check[f'{key}:{row["year"]}'] = round(charts[key][row['year']] - row[field], 6)
    if any(abs(d) > .051 for d in chart_check.values()):
        raise ValueError(f'Table 3.1 and chart data disagree: {chart_check}')
    fiscal_source = spec['fiscal']
    notes = [f'{spec["label"]} ({spec["tables"]}). Years are July-June. {", ".join(actual) or "No year"} is published actual; later years are estimates (forward estimates).',
             'borrowingBn/Pct = minus the underlying cash balance (excludes net Future Fund earnings). debtBn/debtPct = net debt (market value, net of financial assets); grossDebtBn/Pct = face value of Australian Government Securities on issue.',
             'interestBn = net interest payments (cash). primaryBalancePct is derived: (net interest - borrowing) / nominal GDP. Structural $b and structural primary balance are derived from Treasury\'s published structural budget balance (% GDP).',
             'Structural budget balance (Treasury Working Paper 2013-01): UCB = structural balance + cyclical factors + temporary fiscal measures. Treasury publishes no output gap; outputGapPct is null. A borrowing-minus-structural "cyclical" residual includes temporary fiscal measures.',
             'CPI and wage price index are through-the-year growth to the June quarter; real/nominal GDP and GDP deflator are year-average growth; unemployment rate is the June-quarter rate. Earnings, cash rate and bond-yield assumptions are not published in these tables and are null.',
             'Projection rows beyond the forward estimates are Treasury medium-term projections (chart data, % of GDP, rounded to 0.1), not forecasts.']
    return {'id': spec['id'], 'label': spec['label'], 'publicationDate': spec['publicationDate'], 'forecastStart': spec['forecastStart'],
            'rows': rows, 'projections': projections, 'rules': [], 'reconstructed': False, 'sourceUrl': fiscal_source, 'tables': spec['tables'],
            'chartCrossCheck': {'maxAbsDifferencePct': max((abs(d) for d in chart_check.values()), default=None), 'comparisons': len(chart_check)},
            'sources': [{'id': f'au-outlook-{spec["id"]}-fiscal', 'name': f'{spec["label"]}: fiscal outlook (Table 3.1)', 'publisher': 'Australian Government (Treasury and Finance)', 'url': fiscal_source, 'publicationDate': spec['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION},
                        {'id': f'au-outlook-{spec["id"]}-charts', 'name': f'{spec["label"]}: chart data', 'publisher': 'Australian Treasury', 'url': spec['chart'], 'publicationDate': spec['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION},
                        {'id': f'au-outlook-{spec["id"]}-economy', 'name': f'{spec["label"]}: domestic economy forecasts', 'publisher': 'Australian Treasury', 'url': spec['economy'], 'publicationDate': spec['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION}],
            'notes': notes}


def strategy_paths(goal, objectives, vintage):
    path = vintage['rows'] + vintage['projections']
    def series(key):
        return [{'year': r['year'], 'value': r.get(key), 'status': r['status']} for r in path if r.get(key) is not None]
    def peak(key):
        future = [r for r in series(key) if r['status'] != 'outturn']
        return max(future, key=lambda r: r['value']) if future else None
    debt = series('grossDebtPct')
    ucb = series('underlyingCashBalancePct')
    first_balance = next((r for r in ucb if r['status'] != 'outturn' and r['value'] >= 0), None)
    indicators = {
        'limiting growth in spending': {'measure': 'Payments real growth (%, Statement 11 Table 11.1) and payments, % of GDP', 'path': series('spendingRealGrowth'), 'paymentsPct': series('spendingPct')},
        'payments-to-gdp': {'measure': 'Payments, % of GDP', 'path': series('spendingPct'), 'peak': peak('spendingPct'), 'end': series('spendingPct')[-1] if series('spendingPct') else None},
        'gross debt': {'measure': 'Gross debt, % of GDP (face value of AGS on issue)', 'path': debt, 'peak': peak('grossDebtPct'), 'end': debt[-1] if debt else None},
        'balance': {'measure': 'Underlying cash balance, % of GDP', 'path': ucb, 'firstYearAtOrAboveZero': first_balance, 'end': ucb[-1] if ucb else None},
    }
    items = []
    for i, text in enumerate(objectives, 1):
        key = next((k for k in indicators if k in text.lower().replace('payments‑to‑gdp', 'payments-to-gdp')), None)
        items.append({'id': f'objective-{i}', 'text': text, 'indicator': indicators.get(key),
                      'indicatorNote': None if key else 'No forecast series in the imported tables corresponds to this objective; Treasury reports progress in the Statement 3 narrative, which is not imported.'})
    return {'name': 'Economic and Fiscal Strategy', 'legalBasis': 'Charter of Budget Honesty Act 1998', 'vintage': vintage['id'],
            'publicationDate': vintage['publicationDate'], 'sourceUrl': vintage['sourceUrl'], 'location': 'Budget Paper No. 1, Statement 3, Box 3.1',
            'numericTargets': False, 'assessment': None, 'overarchingGoal': {'text': goal, 'indicator': indicators['gross debt']}, 'objectives': items,
            'note': 'The strategy sets qualitative objectives with no numerical targets, target years or headroom. Objective text is quoted from Box 3.1. Paths are the official forecasts and medium-term projections relevant to each objective; this dataset makes no pass/fail assessment.'}


def fetch_outlook(fetcher):
    cache = {}
    def fetch(url):
        if url not in cache:
            cache[url] = fetcher(url)
        return cache[url]
    gdp_raw = fetch(GDP_URL)
    vintages = [build_vintage(spec, fetch, gdp_raw) for spec in VINTAGES]
    latest = next(v for v in vintages if v['id'] == LATEST)
    spec = next(s for s in VINTAGES if s['id'] == LATEST)
    goal, objectives = parse_strategy(fetch(spec['fiscal']))
    history, real_growth = parse_history(fetch(HISTORY_URL), parse_gdp(gdp_raw, f'Nominal GDP - {spec["chartLabel"]}'))
    for row in latest['rows']:
        row['spendingRealGrowth'] = real_growth.get(row['year']) if row['status'] == 'forecast' else next((h['spendingRealGrowth'] for h in history if h['year'] == row['year']), None)
    history = [r for r in history if r['year'] < latest['forecastStart']]
    caps, sheets = captions(fetch(spec['fiscal'])), chart_sheets(fetch(spec['chart']), spec['chartBook'])
    sbb = structural(sheets, caps)
    for row in history:
        s = sbb['structural'].get(row['year'])
        if s is not None:
            row.update(structuralBalancePct=s, cyclicalFactorsPct=sbb['cyclical'][row['year']], temporaryMeasuresPct=sbb['temporary'][row['year']],
                       structuralBorrowingPct=-s, structuralBorrowingBn=round(-s * row['gdpBn'] / 100, 6),
                       structuralPrimaryBalancePct=round(s + row['interestBn'] / row['gdpBn'] * 100, 6))
    for row in latest['rows']:
        if row['status'] == 'outturn':
            past = next((h for h in history if h['year'] == row['year']), None)
            if past is None or abs(past['borrowingBn'] - row['borrowingBn']) > .051 or abs(past['debtBn'] - row['debtBn']) > .051:
                raise ValueError(f'Statement 11 history disagrees with Table 3.1 actual {row["year"]}')
    # Copies: retrieval times belong to this release, not to the archived vintages.
    sources = [dict(s) for v in vintages for s in v['sources']] + [
        {'id': 'au-outlook-history', 'name': '2026-27 Budget Paper No. 1, Statement 11: Historical Australian Government Data (Tables 11.1, 11.3-11.5)', 'publisher': 'Australian Treasury', 'url': HISTORY_URL, 'publicationDate': '2026-05-12', 'licence': LICENCE, 'attribution': ATTRIBUTION},
        {'id': 'au-outlook-gdp', 'name': '2026-27 Budget: nominal GDP (Budget and 2025-26 MYEFO)', 'publisher': 'Australian Treasury', 'url': GDP_URL, 'publicationDate': '2026-05-12', 'licence': LICENCE, 'attribution': ATTRIBUTION}]
    for source in sources:
        record = next((r for r in reversed(getattr(fetcher, 'records', [])) if r['url'] == source['url']), {})
        source['retrievedAt'] = record.get('retrievedAt')
    published = 'Published by Treasury/Finance in the cited table'
    meta = {}
    for key in sorted({k for v in vintages for r in v['rows'] for k in r} - {'year', 'status'}):
        derived = key in ('primaryBalancePct', 'structuralBorrowingBn', 'structuralPrimaryBalancePct')
        meta[key] = {'units': 'AUD billion' if key.endswith('Bn') else 'percent', 'basis': 'derived' if derived else 'published',
                     'method': {'primaryBalancePct': '(net interest payments - borrowing) / nominal GDP x 100',
                                'structuralBorrowingBn': 'minus structural budget balance (% GDP) x nominal GDP / 100',
                                'structuralPrimaryBalancePct': 'structural budget balance (% GDP) + net interest payments / nominal GDP x 100 (interest not cyclically adjusted)'}.get(key, published),
                     'frequency': 'Financial year July-June'}
    for key in ('outputGapPct', 'earningsGrowth', 'bankRate', 'giltYield', 'netInvestmentBn'):
        meta[key].update(basis='not published', method='Not published in the imported Budget/MYEFO tables; always null.')
    data = {'schemaVersion': 1, 'asOf': latest['publicationDate'], 'country': 'au', 'latestVintage': LATEST, 'vintages': vintages,
            'history': history, 'historyAsOf': '2026-05-12', 'deficitHistory': None,
            'deficitHistoryMetadata': {'source': next(s for s in sources if s['id'] == 'au-outlook-history'), 'outturnAsOf': '2026-05-12',
                                       'note': 'History is Budget Paper No. 1 Statement 11 (published in the 2026-27 Budget). Structural, cyclical and temporary components from 2016-17 are the 2026-27 Budget chart-data estimates; earlier years have no published structural estimate. GDP before 2020-21 is implied from the receipts ratio (gdpBasis).'},
            'rules': None, 'currentBudgetUpdate': None, 'headroomHistory': None, 'sensitivities': None,
            'strategy': strategy_paths(goal, objectives, latest),
            'seriesMetadata': meta, 'sources': sources,
            'notes': ['Australian Government general government sector, cash basis; financial years July-June. Two pinned vintages (2025-26 MYEFO, 2026-27 Budget); new Budget/MYEFO editions need adapter review and are added, never substituted. 2022 and 2025 PEFO comparison paths in the chart data are not imported (no verified $b tables or GDP).',
                      'Australia has no numerical fiscal rules. The Economic and Fiscal Strategy (Charter of Budget Honesty Act 1998) sets qualitative objectives, shown on the fiscal strategy page. There are no numerical targets or headroom, and no pass/fail verdict is made.',
                      'History: Statement 11 tables 11.1 (in 2005-06 to 2019-20 published receipts include net Future Fund earnings, which the UCB excludes: borrowing = payments - receipts + Future Fund earnings in those years; see receiptsIncludeFutureFundEarnings) , 11.3 (tax receipts), 11.4 (net debt, net interest) and 11.5 (AGS on issue = gross debt), 1970-71 to the latest actual year. Nominal GDP is the published Budget series from 2020-21; earlier years are implied from receipts / receipts-to-GDP (rounded to 0.1, so within about 0.3%).',
                      'Debt dynamics inputs (net interest, net debt, nominal GDP growth, primary balance) come from one vintage; the effective interest rate and debt-stabilising primary balance are dashboard calculations, not Treasury figures. Net interest payments are cash and net debt is at market value, so r is approximate.',
                      'The underlying cash balance is cash-based, covers the Australian Government general government sector only, and excludes net Future Fund earnings.']}
    return data


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_outlook(data):
    """Reject incomplete vintages, broken identities, invented verdicts and relabelled data."""
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported outlook schema')
    vintages = data.get('vintages') or []
    ids = [v.get('id') for v in vintages]
    if len(vintages) < 2 or len(set(ids)) != len(ids) or data.get('latestVintage') not in ids:
        raise ValueError('Missing or duplicate outlook vintage')
    for v in vintages:
        rows = v.get('rows') or []
        years = [r.get('year') for r in rows]
        if len(rows) < 4 or years != sorted(set(years)) or any(fy(y) is None for y in years):
            raise ValueError('Incomplete or unordered vintage years')
        if any(int(b[:4]) - int(a[:4]) != 1 for a, b in zip(years, years[1:])):
            raise ValueError('Vintage years not consecutive')
        if v.get('rules'):
            raise ValueError('Australian outlook must not carry rule verdicts')
        for row in rows:
            for key in ('borrowingBn', 'borrowingPct', 'receiptsBn', 'spendingBn', 'interestBn', 'debtBn', 'debtPct', 'grossDebtBn', 'grossDebtPct', 'gdpBn', 'primaryBalancePct'):
                if not _finite(row.get(key)):
                    raise ValueError(f'Invalid outlook {key} {v["id"]} {row.get("year")}')
            for key in ('outputGapPct', 'earningsGrowth', 'bankRate', 'giltYield'):
                if row.get(key) is not None:
                    raise ValueError(f'{key} is not published for Australia and must stay null')
            if row['gdpBn'] <= 0:
                raise ValueError('Nonpositive GDP')
            expected = 'forecast' if row['year'] >= v['forecastStart'] else 'outturn'
            if row.get('status') != expected:
                raise ValueError('Vintage outturn/forecast classification changed')
            if abs(row['spendingBn'] - row['receiptsBn'] - row['borrowingBn']) > .151:
                raise ValueError(f'UCB identity failed {v["id"]} {row["year"]}')
            if abs(row['taxReceiptsBn'] + row['nonTaxReceiptsBn'] - row['receiptsBn']) > .151:
                raise ValueError('Receipts components do not sum')
            if abs(row['borrowingBn'] / row['gdpBn'] * 100 - row['borrowingPct']) > .06 or abs(row['debtBn'] / row['gdpBn'] * 100 - row['debtPct']) > .06:
                raise ValueError(f'GDP denominator inconsistent with published ratios {v["id"]} {row["year"]}')
            if abs((row['interestBn'] - row['borrowingBn']) / row['gdpBn'] * 100 - row['primaryBalancePct']) > 1e-5:
                raise ValueError('Primary balance sign/units mismatch')
            if row.get('structuralBalancePct') is not None:
                parts = row['structuralBalancePct'] + row['cyclicalFactorsPct'] + row['temporaryMeasuresPct']
                if abs(parts + row['borrowingPct']) > .151:
                    raise ValueError(f'Structural decomposition does not reconcile {v["id"]} {row["year"]}')
                if abs(row['structuralBorrowingPct'] + row['structuralBalancePct']) > 1e-9:
                    raise ValueError('Structural borrowing sign error')
        if not any(_finite(r.get('structuralBalancePct')) for r in rows):
            raise ValueError(f'No structural balance in {v["id"]}')
        for p in v.get('projections') or []:
            if p.get('status') != 'projection' or p['year'] <= years[-1]:
                raise ValueError('Projection rows overlap forecasts')
    for key in ('rules', 'headroomHistory', 'currentBudgetUpdate', 'sensitivities'):
        if data.get(key):
            raise ValueError(f'{key} has no Australian equivalent and must be null')
    hist = data.get('history') or []
    years = [r['year'] for r in hist]
    if len(hist) < 50 or len(set(years)) != len(years) or years != sorted(years):
        raise ValueError('History coverage incomplete or duplicated')
    for row in hist:
        if row.get('status') != 'outturn' or not all(_finite(row.get(k)) for k in ('borrowingBn', 'receiptsBn', 'spendingBn', 'interestBn', 'debtBn', 'gdpBn')):
            raise ValueError(f'Invalid history row {row.get("year")}')
        ff = row['futureFundEarningsBn'] if row.get('receiptsIncludeFutureFundEarnings') else 0
        if abs(row['spendingBn'] - row['receiptsBn'] + ff - row['borrowingBn']) > .0025:
            raise ValueError(f'History UCB identity failed {row["year"]}')
        if abs(row['borrowingBn'] / row['gdpBn'] * 100 - row['borrowingPct']) > .06:
            raise ValueError(f'History GDP denominator inconsistent {row["year"]}')
        if row.get('structuralBalancePct') is not None and abs(row['structuralBalancePct'] + row['cyclicalFactorsPct'] + row['temporaryMeasuresPct'] + row['borrowingPct']) > .151:
            raise ValueError(f'Historical structural decomposition does not reconcile {row["year"]}')
    strategy = data.get('strategy') or {}
    if strategy.get('numericTargets') is not False or strategy.get('assessment') is not None or not strategy.get('objectives'):
        raise ValueError('Fiscal strategy must be quoted objectives without verdicts')
    if not strategy.get('overarchingGoal', {}).get('indicator', {}).get('peak'):
        raise ValueError('Gross debt path missing for overarching goal')
    return data
