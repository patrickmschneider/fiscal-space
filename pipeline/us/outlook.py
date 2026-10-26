"""United States federal budget outlook: pinned CBO baseline vintages plus CBO historical budget data.

Source: Congressional Budget Office open-data repository (https://github.com/US-CBO/cbo-data),
"Standardized, versioned data from public CBO releases" in long format (date, variable, value).
cbo.gov itself blocks scripted requests, so files are downloaded from GitHub; the cited pages
are the CBO data publications (10-year budget projections 51118, economic projections 51135,
historical budget data 51134, automatic stabilizers 51139). Works of the US Government:
public domain (17 U.S.C. 105).

Federal government (unified budget: on- plus off-budget), October-September fiscal years.
Fiscal years are labelled by START calendar year like the other editions: FY2026 (Oct 2025 -
Sep 2026) -> '2025-26'. borrowing = the total deficit (positive = deficit); debtBn/debtPct =
debt held by the public (end of year). gdpBn is implied from CBO's published debt-to-GDP
ratio (the fiscal-year GDP CBO uses for its budget ratios) and cross-checked against CBO's
fiscal-year nominal GDP projection. Vintages are pinned: a new CBO baseline needs adapter
review and is added, never substituted; the refresh fails if catalog.json lists a newer one.
The US has no numerical fiscal rules; the statutory debt limit and statutory PAYGO are
described without headroom or verdicts.
"""
import csv
import io
import json
import math
import re

from .text import month_year

REPO = 'https://raw.githubusercontent.com/US-CBO/cbo-data/main'
CATALOG_URL = f'{REPO}/catalog.json'
LICENCE = 'Public domain (17 U.S.C. 105; work of the United States Government)'
ATTRIBUTION = 'Congressional Budget Office (CBO) data via the CBO open-data repository (US-CBO/cbo-data); presentation by Fiscal Space.'
PUBLISHER = 'Congressional Budget Office'
BUDGET_PAGE = 'https://www.cbo.gov/publication/51118'
ECONOMY_PAGE = 'https://www.cbo.gov/publication/51135'
HISTORY_PAGE = 'https://www.cbo.gov/publication/51134'
STABILIZERS_PAGE = 'https://www.cbo.gov/publication/51139'
HISTORY_VINTAGE = '2026-02'
STABILIZERS_VINTAGE = '2024-11'
STABILIZERS_BASELINE = '2024-06'  # the 2024-11 estimates are built on the June 2024 baseline
# Publication dates are not in the repository; cbo.gov blocks scripted checks. Verified by hand
# 2026-10-26 (CBO testimony on the 2026-2036 outlook: released 11 February 2026; January 2025
# outlook released 17 January 2025; June 2024 update released 18 June 2024).
VINTAGES = [
    {'id': '2024-06', 'label': 'June 2024 CBO baseline', 'title': 'An Update to the Budget and Economic Outlook: 2024 to 2034', 'publicationDate': '2024-06-18', 'firstYear': 2023},
    {'id': '2025-01', 'label': 'January 2025 CBO baseline', 'title': 'The Budget and Economic Outlook: 2025 to 2035', 'publicationDate': '2025-01-17', 'firstYear': 2024},
    {'id': '2026-02', 'label': 'February 2026 CBO baseline', 'title': 'The Budget and Economic Outlook: 2026 to 2036', 'publicationDate': '2026-02-11', 'firstYear': 2025},
]
LATEST = VINTAGES[-1]['id']
BUDGET_VARS = ('proj_rev_total', 'proj_outlays_total', 'proj_outlays_mandatory', 'proj_outlays_discretionary', 'proj_outlays_net_interest',
               'proj_deficit_total', 'proj_primary_deficit', 'proj_debt_held_by_public', 'proj_debt_held_by_public_gdp_share')
OPTIONAL_BUDGET_VARS = ('proj_debt_minus_financial_assets', 'proj_debt_avg_interest_rate', 'proj_debt_subject_to_limit',
                        'proj_outlays_total_gdp_share', 'proj_deficit_total_gdp_share', 'proj_rev_total_gdp_share', 'proj_outlays_net_interest_gdp_share')
# CBO published ratio -> our derived ratio, for the cross-check.
PUBLISHED_RATIOS = {'proj_outlays_total_gdp_share': ('spendingPct', 1), 'proj_rev_total_gdp_share': ('receiptsPct', 1),
                    'proj_deficit_total_gdp_share': ('borrowingPct', -1), 'proj_outlays_net_interest_gdp_share': ('interestPct', 1)}
# Cross-check exclusions, each reviewed by hand. The 2024-06 key-projections table in cbo-data gives a
# FY2024 deficit of 6.992% of GDP, but the same file's deficit ($1,915.2bn) and GDP imply 6.73%, matching
# CBO's headline 6.7%; the FY2024 revenue ratio in the same table matches. Treated as a repository glitch.
KNOWN_RATIO_ERRORS = {('2024-06', 'proj_deficit_total_gdp_share', 2024): 'cbo-data key_projections value -6.992 inconsistent with deficit and GDP in the same file (6.73%)'}
ECONOMY = {'real_gdp_pct_change': 'realGdpGrowth', 'gdp_pct_change': 'nominalGdpGrowth', 'cpiu_pct_change': 'inflation',
           'pce_price_index_pct_change': 'pceInflation', 'core_pce_price_index_pct_change': 'corePceInflation',
           'gdp_price_index_pct_change': 'gdpDeflatorGrowth', 'unemployment_rate': 'unemploymentRate',
           'fed_funds_rate': 'fedFundsRate', 'treasury_bill_rate_3mo': 'treasuryBillRate3m', 'treasury_note_rate_10yr': 'treasuryNoteRate10y',
           'eci_wages_salaries_pct_change': 'earningsGrowth', 'output_gap': 'outputGapPct', 'gdp': 'economicGdpBn'}
HISTORY_VARS = ('revenues', 'revenues_gdp_share', 'outlays', 'outlays_gdp_share', 'deficit_total', 'deficit_total_gdp_share',
                'outlays_net_interest', 'outlays_net_interest_gdp_share', 'debt_held_by_public', 'debt_held_by_public_gdp_share',
                'mand_total', 'disc_total')
STABILIZER_VARS = ('as_deficit_with_stabilizers', 'as_deficit_without_stabilizers', 'as_effect_deficit', 'as_deficit_without_stabilizers_pct_gdp')
FY = re.compile(r'(\d{4})-(\d{2})')


def budget_url(vintage):
    return f'{REPO}/data/budget/ten_year_budget/annual_fy_{vintage}.csv'


def economy_url(vintage):
    return f'{REPO}/data/economic/economic_projections/fiscal_{vintage}.csv'


HISTORY_URL = f'{REPO}/data/budget/historical_budget/annual_fy_{HISTORY_VINTAGE}.csv'
STABILIZERS_URL = f'{REPO}/data/budget/automatic_stabilizers/annual_fy_{STABILIZERS_VINTAGE}.csv'


def label(fiscal_year):
    """US FY2026 (Oct 2025 - Sep 2026) -> '2025-26' (start-year convention shared by all editions)."""
    start = int(fiscal_year) - 1
    return f'{start}-{(start + 1) % 100:02d}'


def fiscal_year(text):
    """'FY2026' or '2026' -> 2026."""
    m = re.fullmatch(r'(?:FY)?(\d{4})', str(text).strip())
    if not m:
        raise ValueError(f'Unexpected CBO fiscal-year date: {text!r}')
    return int(m[1])


def valid_label(year):
    m = FY.fullmatch(str(year))
    return bool(m) and int(m[2]) == (int(m[1]) + 1) % 100


def read_long(raw, name, keep, columns=('date', 'variable', 'value')):
    """Long-format CBO CSV -> {fiscal year: {variable: float}} for the variables in keep (+ estimate_type per year).

    Other variables are not parsed: some CBO files repeat unrelated variables (e.g. the 2024-06
    economic projections list government_c_gi_pct_change three times); a duplicate of a variable
    this adapter uses is an error."""
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not reader.fieldnames or list(reader.fieldnames[:len(columns)]) != list(columns):
        raise ValueError(f'{name}: CBO column layout changed ({reader.fieldnames})')
    out, kinds = {}, {}
    for row in reader:
        if row['variable'] not in keep:
            continue
        year = fiscal_year(row['date'])
        try:
            value = float(row['value'])
        except ValueError:
            raise ValueError(f'{name}: non-numeric value {row["value"]!r} for {row["variable"]} {row["date"]}') from None
        if not math.isfinite(value):
            raise ValueError(f'{name}: non-finite value for {row["variable"]} {row["date"]}')
        if row['variable'] in out.setdefault(year, {}):
            raise ValueError(f'{name}: duplicate {row["variable"]} {row["date"]}')
        out[year][row['variable']] = value
        if row.get('estimate_type'):
            kinds.setdefault(year, set()).add(row['estimate_type'])
    if not out:
        raise ValueError(f'{name}: none of the expected variables found')
    return out, kinds


def check_catalog(raw):
    catalog = json.loads(raw)
    sets = {d.get('identifier'): d for d in catalog.get('datasets', [])}
    needs = {'ten_year_budget': [v['id'] for v in VINTAGES], 'economic_projections': [v['id'] for v in VINTAGES],
             'historical_budget': [HISTORY_VINTAGE], 'automatic_stabilizers': [STABILIZERS_VINTAGE]}
    for identifier, wanted in needs.items():
        listed = (sets.get(identifier) or {}).get('vintages') or []
        missing = [v for v in wanted if v not in listed]
        if missing:
            raise ValueError(f'CBO catalog no longer lists {identifier} vintages {missing}')
    newer = [v for v in sets['ten_year_budget']['vintages'] if v > LATEST]
    if newer:
        raise ValueError(f'New CBO baseline {newer} in catalog.json: review the new vintage before importing (add, never substitute)')
    return {'generated': catalog.get('generated'), 'pages': {k: sets[k].get('landingPage') for k in needs}}


def contiguous(years, name):
    if not years or years != list(range(years[0], years[-1] + 1)):
        raise ValueError(f'{name}: fiscal years not contiguous')


def build_vintage(spec, fetch, stabilizers):
    budget, _ = read_long(fetch(budget_url(spec['id'])), f'ten_year_budget {spec["id"]}', BUDGET_VARS + OPTIONAL_BUDGET_VARS)
    economy, kinds = read_long(fetch(economy_url(spec['id'])), f'economic_projections {spec["id"]}', set(ECONOMY), ('date', 'variable', 'value', 'estimate_type'))
    years = sorted(y for y in budget if all(k in budget[y] for k in BUDGET_VARS))
    contiguous(years, f'ten_year_budget {spec["id"]}')
    if years[0] != spec['firstYear'] or len(years) < 11:
        raise ValueError(f'{spec["label"]}: expected FY{spec["firstYear"]} actual plus a 10-year projection, got FY{years[0]}-FY{years[-1]}')
    forecast_start = label(spec['firstYear'] + 1)
    rows, ratio_check, gdp_check = [], {}, {}
    for year in years:
        b = budget[year]
        debt, debt_pct = b['proj_debt_held_by_public'], b['proj_debt_held_by_public_gdp_share']
        if debt_pct <= 0:
            raise ValueError(f'{spec["id"]} FY{year}: nonpositive debt ratio')
        gdp = debt / debt_pct * 100
        econ = economy.get(year)
        if not econ or any(k not in econ for k in ECONOMY):
            raise ValueError(f'{spec["id"]} FY{year}: economic projections missing')
        gdp_check[label(year)] = round(gdp / econ['gdp'] * 100 - 100, 4)
        if abs(gdp_check[label(year)]) > .5:
            raise ValueError(f'{spec["id"]} FY{year}: implied budget GDP {gdp:.1f} disagrees with economic projection {econ["gdp"]:.1f}')
        borrowing = -b['proj_deficit_total']
        pct = lambda v: round(v / gdp * 100, 4)
        row = {'year': label(year), 'status': 'outturn' if year < spec['firstYear'] + 1 else 'forecast',
               'borrowingBn': round(borrowing, 3), 'borrowingPct': pct(borrowing),
               'receiptsBn': round(b['proj_rev_total'], 3), 'receiptsPct': pct(b['proj_rev_total']),
               'spendingBn': round(b['proj_outlays_total'], 3), 'spendingPct': pct(b['proj_outlays_total']),
               'mandatoryOutlaysBn': round(b['proj_outlays_mandatory'], 3), 'discretionaryOutlaysBn': round(b['proj_outlays_discretionary'], 3),
               'interestBn': round(b['proj_outlays_net_interest'], 3), 'interestPct': pct(b['proj_outlays_net_interest']),
               'primaryDeficitBn': round(-b['proj_primary_deficit'], 3),
               'debtBn': round(debt, 3), 'debtPct': round(debt_pct, 4),
               'debtNetOfFinancialAssetsBn': round(b['proj_debt_minus_financial_assets'], 3) if 'proj_debt_minus_financial_assets' in b else None,
               'debtSubjectToLimitBn': round(b['proj_debt_subject_to_limit'], 3) if 'proj_debt_subject_to_limit' in b else None,
               'averageInterestRateOnDebt': round(b['proj_debt_avg_interest_rate'], 3) if 'proj_debt_avg_interest_rate' in b else None,
               'gdpBn': round(gdp, 3), 'gdpBasis': 'implied from CBO debt-to-GDP ratio',
               'primaryBalancePct': round((b['proj_outlays_net_interest'] - borrowing) / gdp * 100, 6),
               'netInvestmentBn': None}
        for source, key in ECONOMY.items():
            row[key] = round(econ[source], 3)
        row['economicGdpBn'] = round(econ['gdp'], 3)
        row['economicStatus'] = 'actual' if kinds.get(year) == {'actual'} else 'projected'
        # Frontend assumption keys shared with the UK edition: policy rate and 10-year government bond yield.
        row['bankRate'], row['giltYield'] = row['fedFundsRate'], row['treasuryNoteRate10y']
        for source, (key, sign) in PUBLISHED_RATIOS.items():
            if source in b and (spec['id'], source, year) not in KNOWN_RATIO_ERRORS:
                ratio_check[f'{key}:{row["year"]}'] = round(sign * b[source] - row[key], 4)
        s = stabilizers.get(year) if spec['id'] == STABILIZERS_BASELINE else None
        if s:
            if abs(s['as_deficit_with_stabilizers'] - b['proj_deficit_total']) > .151:
                raise ValueError(f'Automatic-stabilizer baseline disagrees with {spec["id"]} FY{year}')
            add_structural(row, s)
        rows.append(row)
    if any(abs(d) > .06 for d in ratio_check.values()):
        raise ValueError(f'{spec["label"]}: derived ratios disagree with CBO published ratios {ratio_check}')
    page_note = f'{spec["title"]} ({spec["label"]}). CBO data publication: 10-year budget projections ({BUDGET_PAGE}) and economic projections ({ECONOMY_PAGE}).'
    notes = [page_note,
             f'Fiscal years run October to September and are named by the calendar year in which they end. FY{spec["firstYear"]} is the actual year in this baseline; later years are CBO baseline projections under current law, not a forecast of policy.',
             'The deficit is the total (unified) federal deficit; positive values are deficits. Debt is debt held by the public at the end of the fiscal year. Net interest is net interest outlays. The primary balance is net interest minus the deficit, as a share of GDP.',
             'GDP is fiscal-year nominal GDP implied by CBO\'s published debt-to-GDP ratio. Other ratios are calculated from dollar amounts and that GDP, and match CBO\'s published ratios where both exist.',
             'Economic assumptions are fiscal-year averages from CBO\'s economic projections: real and nominal GDP growth, CPI-U and PCE inflation, the unemployment rate, the federal funds rate, the 3-month Treasury bill rate, the 10-year Treasury note yield, private-wage growth (employment cost index) and CBO\'s output gap (% of potential GDP).']
    if spec['id'] == STABILIZERS_BASELINE:
        notes.append(f'Structural (cyclically adjusted) deficit: CBO\'s deficit excluding automatic stabilizers ({STABILIZERS_PAGE}, {month_year(STABILIZERS_VINTAGE)} estimates, built on this baseline). Shares of GDP here use actual GDP; CBO also publishes them as shares of potential GDP.')
    else:
        notes.append('CBO has published no automatic-stabilizer (cyclically adjusted) estimates for this baseline in machine-readable form, so no structural deficit is shown for it.')
    sources = [{'id': f'us-outlook-{spec["id"]}-budget', 'name': f'CBO {spec["title"]}: 10-year budget projections', 'publisher': PUBLISHER,
                'url': BUDGET_PAGE, 'downloadUrl': budget_url(spec['id']), 'publicationDate': spec['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION},
               {'id': f'us-outlook-{spec["id"]}-economy', 'name': f'CBO {spec["title"]}: economic projections (fiscal years)', 'publisher': PUBLISHER,
                'url': ECONOMY_PAGE, 'downloadUrl': economy_url(spec['id']), 'publicationDate': spec['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION}]
    return {'id': spec['id'], 'label': spec['label'], 'title': spec['title'], 'publicationDate': spec['publicationDate'], 'forecastStart': forecast_start,
            'rows': rows, 'projections': [], 'rules': [], 'reconstructed': False, 'sourceUrl': BUDGET_PAGE, 'downloadUrl': budget_url(spec['id']),
            'tables': 'CBO 10-year budget projections (Tables 1-1/1-3 or B-1/B-3) and economic projections, fiscal years',
            'publishedRatioCheck': {'maxAbsDifferencePct': max((abs(d) for d in ratio_check.values()), default=None), 'comparisons': len(ratio_check)},
            'gdpCrossCheck': {'maxAbsDifferencePercent': max(abs(d) for d in gdp_check.values()), 'note': 'Implied budget GDP vs CBO fiscal-year GDP projection, percent difference'},
            'sources': sources, 'notes': notes}


def add_structural(row, s):
    gdp = row['gdpBn']
    structural = -s['as_deficit_without_stabilizers']
    row.update({'structuralBorrowingBn': round(structural, 3), 'structuralBorrowingPct': round(structural / gdp * 100, 4),
                'structuralBorrowingPotentialGdpPct': round(-s['as_deficit_without_stabilizers_pct_gdp'], 4),
                'automaticStabilizersBn': round(-s['as_effect_deficit'], 3),
                'structuralPrimaryBalancePct': round((row['interestBn'] - structural) / gdp * 100, 6)})


def parse_history(raw, stabilizers):
    data, _ = read_long(raw, f'historical_budget {HISTORY_VINTAGE}', HISTORY_VARS)
    years = sorted(data)
    contiguous(years, 'historical_budget')
    rows = []
    for year in years:
        d = data[year]
        missing = [k for k in HISTORY_VARS if k not in d]
        if missing:
            raise ValueError(f'historical_budget FY{year}: missing {missing}')
        if abs(d['revenues'] - d['outlays'] - d['deficit_total']) > .002:
            raise ValueError(f'historical_budget FY{year}: deficit identity failed')
        gdp = d['debt_held_by_public'] / d['debt_held_by_public_gdp_share'] * 100
        row = {'year': label(year), 'status': 'outturn',
               'borrowingBn': round(-d['deficit_total'], 3), 'borrowingPct': round(-d['deficit_total_gdp_share'], 4),
               'receiptsBn': round(d['revenues'], 3), 'receiptsPct': round(d['revenues_gdp_share'], 4),
               'spendingBn': round(d['outlays'], 3), 'spendingPct': round(d['outlays_gdp_share'], 4),
               'mandatoryOutlaysBn': round(d['mand_total'], 3), 'discretionaryOutlaysBn': round(d['disc_total'], 3),
               'interestBn': round(d['outlays_net_interest'], 3), 'deficitInterestBn': round(d['outlays_net_interest'], 3), 'interestPct': round(d['outlays_net_interest_gdp_share'], 4),
               'debtBn': round(d['debt_held_by_public'], 3), 'debtPct': round(d['debt_held_by_public_gdp_share'], 4),
               'gdpBn': round(gdp, 3), 'gdpBasis': 'implied from CBO debt-to-GDP ratio',
               'primaryBalancePct': round((d['outlays_net_interest'] + d['deficit_total']) / gdp * 100, 6),
               'structuralBorrowingBn': None, 'structuralBorrowingPct': None, 'structuralPrimaryBalancePct': None, 'outputGapPct': None}
        for key, published in (('receiptsBn', 'receiptsPct'), ('spendingBn', 'spendingPct'), ('borrowingBn', 'borrowingPct')):
            if abs(row[key] / gdp * 100 - row[published]) > .01:
                raise ValueError(f'historical_budget FY{year}: GDP ratios inconsistent ({published})')
        rows.append(row)
    return rows


def parse_stabilizers(raw):
    data, _ = read_long(raw, f'automatic_stabilizers {STABILIZERS_VINTAGE}', STABILIZER_VARS)
    for year, d in data.items():
        if any(k not in d for k in STABILIZER_VARS):
            raise ValueError(f'automatic_stabilizers FY{year}: variables missing')
        if abs(d['as_deficit_with_stabilizers'] - d['as_effect_deficit'] - d['as_deficit_without_stabilizers']) > .151:
            raise ValueError(f'automatic_stabilizers FY{year}: with/without identity failed')
    contiguous(sorted(data), 'automatic_stabilizers')
    return data


def statutory_constraints(latest):
    path = [{'year': r['year'], 'value': r['debtSubjectToLimitBn'], 'status': r['status']} for r in latest['rows'] if r.get('debtSubjectToLimitBn') is not None]
    common = {'targetYear': None, 'assessmentDate': None, 'headroomBn': None, 'met': None, 'binding': False}
    return [
        {**common, 'id': 'debt-limit', 'name': 'Statutory debt limit',
         'description': 'A cap set in law (31 U.S.C. 3101) on the total amount of debt the Treasury may issue, including debt held by the public and debt held by federal trust funds. It limits the financing of obligations already made; it does not limit spending or deficits themselves.',
         'definition': 'Applies to debt subject to limit, a measure that differs from debt held by the public (used elsewhere in this dashboard). Congress raises, suspends or redefines the limit by legislation.',
         'assessmentNote': 'Descriptive only: the limit is not a fiscal target and has no forecast headroom in CBO\'s baseline. The chart shows CBO\'s projection of debt subject to limit; the statutory dollar limit itself is not shown.',
         'sourceUrl': 'https://home.treasury.gov/policy-issues/financial-markets-financial-institutions-and-fiscal-service/debt-limit',
         'indicator': {'measure': f'Debt subject to limit, $ billions ({latest["label"]})', 'path': path} if path else None},
        {**common, 'id': 'statutory-paygo', 'name': 'Statutory Pay-As-You-Go (PAYGO)',
         'description': 'The Statutory Pay-As-You-Go Act of 2010 (Title I of Public Law 111-139) requires that new mandatory spending and revenue legislation, taken together, not increase projected deficits; a net cost recorded on OMB\'s scorecards at the end of a congressional session triggers sequestration of certain mandatory programs.',
         'definition': 'A budget-enforcement procedure for new legislation, not a target for the deficit or debt. Congress can and does exclude legislation from the scorecards.',
         'assessmentNote': 'Descriptive only: no headroom or compliance verdict is computed.',
         'sourceUrl': 'https://www.govinfo.gov/app/details/PLAW-111publ139', 'indicator': None},
    ]


def fetch_outlook(fetcher):
    cache = {}
    def fetch(url):
        if not url.startswith('https://'):
            raise ValueError(f'Refusing non-HTTPS source {url}')
        if url not in cache:
            cache[url] = fetcher(url)
        return cache[url]
    catalog = check_catalog(fetch(CATALOG_URL))
    stabilizers = parse_stabilizers(fetch(STABILIZERS_URL))
    vintages = [build_vintage(spec, fetch, stabilizers) for spec in VINTAGES]
    latest = vintages[-1]
    history = parse_history(fetch(HISTORY_URL), stabilizers)
    # Historical structural deficit: only years that are actuals in the stabilizer publication (before its baseline's first year).
    first_projected = next(s['firstYear'] for s in VINTAGES if s['id'] == STABILIZERS_BASELINE) + 1
    for row in history:
        year = int(row['year'][:4]) + 1
        s = stabilizers.get(year)
        if s and year < first_projected:
            if abs(s['as_deficit_with_stabilizers'] + row['borrowingBn']) > .151:
                raise ValueError(f'Automatic-stabilizer actual disagrees with historical deficit FY{year}')
            add_structural(row, s)
    for row in latest['rows']:
        if row['status'] == 'outturn':
            past = next((h for h in history if h['year'] == row['year']), None)
            if past is None or abs(past['borrowingBn'] - row['borrowingBn']) > .051 or abs(past['debtBn'] - row['debtBn']) > .051 or abs(past['interestBn'] - row['interestBn']) > .051:
                raise ValueError(f'Historical budget data disagree with the {latest["label"]} actual year {row["year"]}')
    history = [r for r in history if r['year'] < latest['forecastStart']]
    sources = [dict(s) for v in vintages for s in v['sources']] + [
        {'id': 'us-outlook-history', 'name': f'CBO Historical Budget Data ({month_year(HISTORY_VINTAGE)} release)', 'publisher': PUBLISHER, 'url': HISTORY_PAGE,
         'downloadUrl': HISTORY_URL, 'publicationDate': latest['publicationDate'], 'licence': LICENCE, 'attribution': ATTRIBUTION},
        {'id': 'us-outlook-stabilizers', 'name': f'CBO Estimates of Automatic Stabilizers ({month_year(STABILIZERS_VINTAGE)})', 'publisher': PUBLISHER, 'url': STABILIZERS_PAGE,
         'downloadUrl': STABILIZERS_URL, 'publicationDate': None, 'licence': LICENCE, 'attribution': ATTRIBUTION},
        {'id': 'us-outlook-catalog', 'name': 'CBO open-data repository catalog (US-CBO/cbo-data)', 'publisher': PUBLISHER, 'url': 'https://github.com/US-CBO/cbo-data',
         'downloadUrl': CATALOG_URL, 'publicationDate': (catalog['generated'] or '')[:10] or None, 'licence': LICENCE, 'attribution': ATTRIBUTION}]
    for source in sources:
        record = next((r for r in reversed(getattr(fetcher, 'records', [])) if r['url'] == source['downloadUrl']), {})
        source['retrievedAt'] = record.get('retrievedAt')
    derived = {'borrowingPct': 'minus CBO total deficit / implied fiscal-year GDP x 100 (history: CBO published ratio)',
               'receiptsPct': 'revenues / implied GDP x 100 (history: CBO published ratio)',
               'spendingPct': 'outlays / implied GDP x 100 (history: CBO published ratio)',
               'interestPct': 'net interest / implied GDP x 100 (history: CBO published ratio)',
               'gdpBn': 'debt held by the public / CBO published debt-to-GDP ratio x 100',
               'primaryBalancePct': '(net interest - deficit) / GDP x 100',
               'structuralBorrowingPct': 'CBO deficit excluding automatic stabilizers / actual GDP x 100',
               'structuralPrimaryBalancePct': '(net interest - CBO deficit excluding automatic stabilizers) / actual GDP x 100 (interest not cyclically adjusted)',
               'bankRate': 'Same as the CBO federal funds rate projection; used for the policy interest rate assumption chart',
               'giltYield': 'Same as the CBO 10-year Treasury note yield projection; used for the government bond yield assumption chart'}
    meta = {}
    for key in sorted({k for v in vintages for r in v['rows'] for k in r} - {'year', 'status', 'gdpBasis', 'economicStatus'}):
        meta[key] = {'units': 'USD billion' if key.endswith('Bn') else 'percent', 'basis': 'derived' if key in derived else 'published',
                     'method': derived.get(key, 'Published by CBO in the cited dataset'), 'frequency': 'Federal fiscal year October-September'}
    meta['netInvestmentBn'].update(basis='not published', method='CBO baseline tables do not split out federal net investment, so no value is shown.')
    meta['outputGapPct'].update(method='CBO output gap, fiscal-year average, % of potential GDP (positive = output above potential)')
    data = {'schemaVersion': 1, 'asOf': latest['publicationDate'], 'country': 'us', 'latestVintage': LATEST, 'vintages': vintages,
            'history': history, 'historyAsOf': latest['publicationDate'], 'deficitHistory': None,
            'deficitHistoryMetadata': {'source': next(s for s in sources if s['id'] == 'us-outlook-history'), 'outturnAsOf': latest['publicationDate'],
                                       'note': f'History is CBO Historical Budget Data ({month_year(HISTORY_VINTAGE)} release), FY1962 onward. Structural (cyclically adjusted) deficits are CBO\'s deficits excluding automatic stabilizers ({month_year(STABILIZERS_VINTAGE)} estimates) for actual years through FY{first_projected - 1}; later years have no published estimate except within the {month_year(STABILIZERS_BASELINE)} baseline.'},
            'rules': statutory_constraints(latest), 'currentBudgetUpdate': None, 'headroomHistory': None, 'sensitivities': None, 'strategy': None,
            'catalog': catalog, 'seriesMetadata': meta, 'sources': sources,
            'notes': ['US federal government, unified budget (on-budget plus off-budget, including Social Security and the Postal Service); federal fiscal years run October to September and are named by the year in which they end (FY2026 ends September 2026). Three CBO baselines are shown (June 2024, January 2025 and February 2026); each new baseline is added alongside the earlier ones after review rather than replacing them.',
                      'CBO baselines are projections under current law (with CBO\'s conventions, e.g. discretionary funding grown with inflation); they are not forecasts of future legislation.',
                      'The United States has no numerical fiscal rules. The statutory debt limit and Statutory PAYGO are listed as descriptive budget constraints with no headroom or verdict.',
                      f'History: CBO Historical Budget Data ({month_year(HISTORY_VINTAGE)}), FY1962 to the latest actual year. Debt is debt held by the public; GDP is implied from CBO\'s published debt-to-GDP ratio.',
                      'Debt dynamics inputs (net interest, debt held by the public, nominal GDP growth, primary balance) come from one CBO vintage; the effective interest rate and debt-stabilizing primary balance are dashboard calculations. CBO also publishes its own average interest rate on debt held by the public.',
                      'The forecast bridge needs a net-investment split, which CBO does not publish, so it is not shown. CBO publishes no machine-readable borrowing sensitivities in its open-data repository, so none are shown.']}
    return data


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


REQUIRED = ('borrowingBn', 'borrowingPct', 'receiptsBn', 'receiptsPct', 'spendingBn', 'spendingPct', 'interestBn', 'debtBn', 'debtPct', 'gdpBn', 'primaryBalancePct')
VINTAGE_REQUIRED = REQUIRED + ('primaryDeficitBn', 'realGdpGrowth', 'nominalGdpGrowth', 'inflation', 'unemploymentRate', 'treasuryNoteRate10y', 'treasuryBillRate3m', 'fedFundsRate')


def _check_row(row, where, required):
    for key in required:
        if not _finite(row.get(key)):
            raise ValueError(f'Invalid outlook {key} {where} {row.get("year")}')
    if row['gdpBn'] <= 0:
        raise ValueError(f'Nonpositive GDP {where} {row["year"]}')
    if abs(row['spendingBn'] - row['receiptsBn'] - row['borrowingBn']) > .01:
        raise ValueError(f'Deficit identity failed {where} {row["year"]}')
    for bn, pct in (('borrowingBn', 'borrowingPct'), ('receiptsBn', 'receiptsPct'), ('spendingBn', 'spendingPct'), ('debtBn', 'debtPct')):
        if abs(row[bn] / row['gdpBn'] * 100 - row[pct]) > .011:
            raise ValueError(f'GDP denominator inconsistent with {pct} {where} {row["year"]}')
    if abs((row['interestBn'] - row['borrowingBn']) / row['gdpBn'] * 100 - row['primaryBalancePct']) > 1e-4:
        raise ValueError(f'Primary balance sign/units mismatch {where} {row["year"]}')
    if row.get('primaryDeficitBn') is not None and abs(row['borrowingBn'] - row['interestBn'] - row['primaryDeficitBn']) > .01:
        raise ValueError(f'Primary deficit identity failed {where} {row["year"]}')
    if row.get('structuralBorrowingBn') is not None:
        if abs(row['borrowingBn'] - row['structuralBorrowingBn'] - row['automaticStabilizersBn']) > .251:
            raise ValueError(f'Structural decomposition does not reconcile {where} {row["year"]}')
        if abs(row['structuralBorrowingBn'] / row['gdpBn'] * 100 - row['structuralBorrowingPct']) > .001:
            raise ValueError(f'Structural ratio inconsistent {where} {row["year"]}')


def validate_outlook(data):
    """Reject incomplete vintages, broken identities, invented verdicts and relabelled data."""
    if data.get('schemaVersion') != 1 or data.get('country') != 'us':
        raise ValueError('Unsupported outlook schema')
    vintages = data.get('vintages') or []
    ids = [v.get('id') for v in vintages]
    if len(vintages) < 2 or len(set(ids)) != len(ids) or data.get('latestVintage') != ids[-1]:
        raise ValueError('Missing, duplicate or misdeclared outlook vintage')
    dates = [v.get('publicationDate') for v in vintages]
    if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d or '') for d in dates) or dates != sorted(set(dates)):
        raise ValueError('Vintages not ordered by publication date')
    for v in vintages:
        rows = v.get('rows') or []
        years = [r.get('year') for r in rows]
        if len(rows) < 11 or years != sorted(set(years)) or not all(valid_label(y) for y in years):
            raise ValueError(f'Incomplete or unordered vintage years {v.get("id")}')
        if any(int(b[:4]) - int(a[:4]) != 1 for a, b in zip(years, years[1:])):
            raise ValueError('Vintage years not consecutive')
        if v.get('rules'):
            raise ValueError('US outlook vintages must not carry rule verdicts')
        if not valid_label(v.get('forecastStart')) or sum(r['year'] < v['forecastStart'] for r in rows) != 1:
            raise ValueError(f'Each CBO baseline must have exactly one actual year {v.get("id")}')
        start = int(v['forecastStart'][:4])
        if not f'{start}-10-01' <= v['publicationDate'] <= f'{start + 1}-09-30':
            raise ValueError('A CBO baseline must be published during its first projected fiscal year')
        for row in rows:
            _check_row(row, v['id'], VINTAGE_REQUIRED)
            expected = 'forecast' if row['year'] >= v['forecastStart'] else 'outturn'
            if row.get('status') != expected:
                raise ValueError('Vintage outturn/forecast classification changed')
            if row.get('netInvestmentBn') is not None:
                raise ValueError('netInvestmentBn is not published by CBO and must stay null')
            if row.get('bankRate') != row.get('fedFundsRate') or row.get('giltYield') != row.get('treasuryNoteRate10y'):
                raise ValueError('Assumption aliases must mirror the CBO series')
        if v.get('projections'):
            raise ValueError('CBO baselines have no separate medium-term projection rows')
    if not any(r.get('structuralBorrowingBn') is not None for v in vintages for r in v['rows']):
        raise ValueError('No CBO automatic-stabilizer estimates in any vintage')
    for key in ('headroomHistory', 'currentBudgetUpdate', 'sensitivities', 'strategy'):
        if data.get(key):
            raise ValueError(f'{key} has no US equivalent and must be null')
    for rule in data.get('rules') or []:
        if rule.get('headroomBn') is not None or rule.get('met') is not None or not str(rule.get('sourceUrl', '')).startswith('https://'):
            raise ValueError('Statutory constraints are descriptive: no headroom or verdict')
    hist = data.get('history') or []
    years = [r.get('year') for r in hist]
    if len(hist) < 60 or years[0] != '1961-62' or years != sorted(set(years)) or not all(valid_label(y) for y in years):
        raise ValueError('History coverage incomplete or duplicated')
    if any(int(b[:4]) - int(a[:4]) != 1 for a, b in zip(years, years[1:])) or years[-1] >= vintages[-1]['forecastStart']:
        raise ValueError('History years not contiguous or overlap the forecast')
    for row in hist:
        if row.get('status') != 'outturn' or row.get('deficitInterestBn') != row.get('interestBn'):
            raise ValueError(f'Invalid history row {row.get("year")}')
        _check_row(row, 'history', REQUIRED)
    if not any(r.get('structuralBorrowingBn') is not None for r in hist):
        raise ValueError('Historical structural deficit missing')
    return data
