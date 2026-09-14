"""ONS PUSF and Treasury PESA, with explicit series and accounting checks."""
import csv
import io
import re
from datetime import datetime
import openpyxl

ONS_URL = 'https://www.ons.gov.uk/file?uri=/economy/governmentpublicsectorandtaxes/publicsectorfinance/datasets/publicsectorfinances/current/pusf.csv'
ONS_PAGE = 'https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/datasets/publicsectorfinances'
GDP_PAGE = 'https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/bktl/pn2'
GDP_URL = 'https://www.ons.gov.uk/generator?format=csv&uri=%2Feconomy%2Fgrossdomesticproductgdp%2Ftimeseries%2Fbktl%2Fpn2'
GDP_METHOD = 'https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/methodologies/theuseofgrossdomesticproductgdpinpublicsectorfiscalratiostatistics'
PESA_PAGE = 'https://www.gov.uk/government/statistics/public-expenditure-statistical-analyses-2026'
PESA_URL = 'https://assets.publishing.service.gov.uk/media/6a5772f59e63154454413701/PESA_2026_CP_Chapter_5_tables.xlsx'
PESA_HISTORY_URL = 'https://assets.publishing.service.gov.uk/media/6a5772e09e63154454413700/PESA_2026_CP_Chapter_4_tables.xlsx'
SCOPE = 'UK public sector excluding public sector banks'
SERIES = {
 'borrowing': ('DZLS', 'Net borrowing', '£ million', SCOPE),
 'receipts': ('JW2O', 'Current receipts', '£ million', SCOPE),
 'spending': ('KX5Q', 'Total managed expenditure', '£ million', SCOPE),
 'debtPct': ('HF6X', 'Public sector net debt', '% of GDP', SCOPE),
 'debtBillion': ('HF6W', 'Public sector net debt', '£ billion', SCOPE),
 'incomeTax': ('LIBR', 'Income tax & capital gains tax', '£ million', 'Central government'),
 'nic': ('AIIH', 'Compulsory social contributions', '£ million', 'Central government'),
 'vat': ('NZGF', 'VAT', '£ million', 'Central government'),
 'corporationTax': ('CPRN', 'Corporation tax (gross of tax credits)', '£ million', 'Central government'),
 'goodsServices': ('FV4W', 'Goods & services', '£ million', SCOPE),
 'benefits': ('CWNZ', 'Net social benefits', '£ million', SCOPE),
 'interest': ('JW2P', 'Interest & dividends to private sector / rest of world', '£ million', SCOPE),
 'netInvestment': ('DZLW', 'Net investment', '£ million', SCOPE),
 'depreciation': ('JW2S', 'Consumption of fixed capital', '£ million', SCOPE),
 'currentSpending': ('JW2Q', 'Current expenditure', '£ million', SCOPE),
}

# Additional breakdown series remain optional for older saved/test vintages.
EXTRA_SERIES = {
 'totalTaxes': ('AHHY','Public sector taxes and NICs','£ million',SCOPE),
 'councilTax': ('NMHM','Council tax','£ million','Local government'),
 'interestReceipts': ('JW2L','Interest & dividends received from private sector / rest of world','£ million',SCOPE),
}

def number(value):
    if value is None or str(value).strip() in ('', '..', '...', 'NA', 'N/A', '-'):
        return None
    result = float(str(value).replace(',', '').strip())
    if not (-1e15 < result < 1e15):
        raise ValueError('Non-finite or implausible number')
    return result

def parse_pusf(raw):
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    if len(rows) < 9 or rows[0][0] != 'Title' or rows[1][0] != 'CDID':
        raise ValueError('Expected ONS PUSF CSV headers')
    indices = {code: i for i, code in enumerate(rows[1])}
    missing = [v[0] for v in SERIES.values() if v[0] not in indices]
    if missing:
        raise ValueError(f'Missing required ONS series: {missing}')
    series = {**SERIES, **{key: spec for key, spec in EXTRA_SERIES.items() if spec[0] in indices}}
    metadata = {r[0]: r for r in rows[2:7]}
    release = datetime.strptime(metadata['Release Date'][indices['DZLS']], '%d-%m-%Y').date().isoformat()
    next_release = metadata['Next release'][indices['DZLS']]
    observations = []
    for row in rows[7:]:
        if not re.fullmatch(r'\d{4} [A-Z]{3}', row[0]):
            continue
        date = datetime.strptime(row[0], '%Y %b').strftime('%Y-%m')
        if date < '2000-04':
            continue
        obs = {'date': date, **{key: number(row[indices[spec[0]]]) for key, spec in series.items()}}
        if any(obs[k] is None for k in ['borrowing','receipts','spending','debtPct','debtBillion']):
            raise ValueError(f'Missing core observation in {date}')
        if abs(obs['spending'] - obs['receipts'] - obs['borrowing']) > 1:
            raise ValueError(f'Borrowing reconciliation failed in {date}')
        # Named source components, not a derived residual disguised as expenditure.
        if all(obs[k] is not None for k in ['currentSpending','depreciation','netInvestment']):
            if abs(obs['currentSpending'] + obs['depreciation'] + obs['netInvestment'] - obs['spending']) > 2:
                raise ValueError(f'Expenditure bridge failed in {date}')
        observations.append(obs)
    if len(observations) < 24 or len({o['date'] for o in observations}) != len(observations):
        raise ValueError('Insufficient or duplicate monthly observations')
    observations.sort(key=lambda r: r['date'])
    for left,right in zip(observations,observations[1:]):
        y,m=map(int,left['date'].split('-')); expected=f'{y+(m==12):04d}-{m%12+1:02d}'
        if right['date'] != expected: raise ValueError(f'Missing month after {left["date"]}')
    return {
      'schemaVersion': 1, 'asOf': observations[-1]['date'], 'releaseDate': release,
      'nextRelease': next_release, 'scope': SCOPE, 'basis': 'Current prices, accruals, not seasonally adjusted',
      'sources': [{'id':'ons-pusf','name':'ONS · Public sector finances','url':ONS_PAGE,'downloadUrl':ONS_URL,
                   'publicationDate':release,'observationDate':observations[-1]['date'],'licence':'Open Government Licence v3.0'}],
      'series': {key:{'code':spec[0],'label':spec[1],'unit':spec[2],'scope':spec[3],
                       'sourceTitle':rows[0][indices[spec[0]]]} for key,spec in series.items()},
      'observations': observations,
      'notes': ['Positive borrowing is a deficit; negative borrowing is a surplus.',
                'Total managed expenditure − current receipts = net borrowing (all excluding public sector banks).',
                'Total managed expenditure = current expenditure + consumption of fixed capital + net investment.',
                'Selected tax details cover central government and do not form an exhaustive public-sector receipts decomposition.',
                'Debt/GDP is the published ONS ratio; optional flow/GDP scaling is calculated by this dashboard using separately sourced nominal GDP.',
                'All historical observations use this release vintage and are subject to revision.'],
    }

def parse_pesa(raw):
    book = openpyxl.load_workbook(io.BytesIO(raw),data_only=True,read_only=True)
    if '5_2' not in book.sheetnames: raise ValueError('Missing PESA table 5.2')
    rows = list(book['5_2'].values)
    if 'Public sector expenditure on services' not in str(rows[0][1]): raise ValueError('Unexpected PESA table')
    year_columns = [(i,str(v)) for i,v in enumerate(rows[4]) if re.fullmatch(r'\d{4}-\d{2}',str(v))]
    names = ['General public services','Defence','Public order and safety','Economic affairs','Environment protection',
             'Housing and community amenities','Health','Recreation, culture and religion','Education','Social protection','EU transactions']
    by_label = {str(r[1]).strip().lower():r for r in rows if r[1] is not None}
    social_index=next(i for i,r in enumerate(rows) if str(r[1]).strip()=='10. Social protection')
    services_row=rows[social_index+1]
    if str(services_row[1]).strip()!='of which: personal social services':
        raise ValueError('Missing social protection personal services subtotal')
    pension_row=by_label['of which: pensions']
    social_years=[]
    years=[]
    for col,year in year_columns:
        items=[]
        for name in names:
            row=by_label.get('total '+name.lower())
            if row is None: raise ValueError(f'Missing PESA category {name}')
            value=number(row[col])
            if value is None: raise ValueError(f'Missing PESA value {year}/{name}')
            items.append({'name':name,'value':value})
        total=number(by_label['public sector expenditure on services'][col])
        # Eleven independently rounded categories and the rounded total can differ slightly.
        residual=round(total-sum(x['value'] for x in items),6)
        if abs(residual)>6: raise ValueError(f'PESA composition fails reconciliation in {year}')
        if residual: items.append({'name':'Rounding adjustment','value':residual})
        debt_row=next(r for r in rows if str(r[1]).startswith('1.7 Public debt transactions'))
        debt_transactions=number(debt_row[col])
        if debt_transactions is None:raise ValueError('Missing public debt transactions')
        years.append({'year':year,'total':total,'items':items,'debtInterest':debt_transactions})
        social_total=number(by_label['total social protection'][col])
        pensions=number(pension_row[col]);services=number(services_row[col])
        if any(v is None or v<0 for v in [social_total,pensions,services]) or pensions+services>social_total:
            raise ValueError('Invalid social protection breakdown')
        social_years.append({'year':year,'total':social_total,'items':[
            {'name':'Pensions','value':pensions},
            {'name':'Other benefits and social-protection spending','value':social_total-pensions-services},
            {'name':'Personal social services','value':services}]})
    return {'schemaVersion':1,'asOf':years[-1]['year'],'years':years,'socialProtection':social_years,'unit':'£ million',
       'basis':'Public sector expenditure on services (TES), current prices; includes EU transactions. Different coverage from total managed expenditure.',
       'sources':[{'id':'pesa-2026','name':'HM Treasury · PESA 2026, table 5.2','url':PESA_PAGE,'downloadUrl':PESA_URL,
                   'publicationDate':'2026-07-16','observationDate':years[-1]['year'],'licence':'Open Government Licence v3.0'}],
       'notes':['Five years on a consistent PESA 2026 classification; older vintages are not spliced into this view.',
                'Negative EU transactions are retained, not hidden. Shares use the published TES total.']}

def parse_pesa_history(raw):
    """One Treasury vintage, retaining published GDP shares and classification breaks."""
    book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    tables = {}
    names = ['General public services', 'Defence', 'Public order and safety', 'Economic affairs',
             'Environment protection', 'Housing and community amenities', 'Health',
             'Recreation, culture and religion', 'Education', 'Social protection', 'EU transactions']
    for sheet, unit in [('4_2', '£ billion'), ('4_4', 'per cent')]:
        if sheet not in book.sheetnames:
            raise ValueError(f'Missing PESA table {sheet}')
        rows = list(book[sheet].values)
        if 'Public sector expenditure on services by function' not in str(rows[0][0]) or unit not in rows[2]:
            raise ValueError(f'Unexpected PESA history title or units in {sheet}')
        years = [(i, str(v)) for i, v in enumerate(rows[4]) if re.fullmatch(r'\d{4}-\d{2}', str(v))]
        if len(years) < 10 or any(int(b[1][:4]) != int(a[1][:4]) + 1 for a, b in zip(years, years[1:])):
            raise ValueError('Insufficient or discontinuous PESA history')
        def label(v):
            return re.sub(r'\s*\(\d+\)', '', re.sub(r'^\d+\.\s*', '', str(v).strip())).lower()
        labels = {label(r[0]): r for r in rows if r[0] is not None}
        required = names + ['Public sector expenditure on services', 'Accounting adjustments',
                            'Total Managed Expenditure', 'of which: public sector debt interest']
        if any(name.lower() not in labels for name in required):
            raise ValueError('Missing PESA history category')
        table = {}
        for col, year in years:
            vals = {name: number(labels[name.lower()][col]) for name in required}
            if any(v is None for v in vals.values()):
                raise ValueError(f'Missing PESA history value in {year}')
            tes = vals['Public sector expenditure on services']
            if abs(tes - sum(vals[n] for n in names)) > 0.600001:
                raise ValueError(f'PESA history composition fails reconciliation in {year}')
            if abs(tes + vals['Accounting adjustments'] - vals['Total Managed Expenditure']) > 0.150001:
                raise ValueError(f'PESA TES to TME bridge fails in {year}')
            table[year] = vals
        tables[sheet] = table
    if tables['4_2'].keys() != tables['4_4'].keys():
        raise ValueError('PESA value and GDP-share years differ')
    history = []
    for year, values in tables['4_2'].items():
        shares = tables['4_4'][year]
        items = [{'name': n, 'value': round(values[n] * 1000, 6), 'pctGdp': shares[n]} for n in names]
        total = round(values['Public sector expenditure on services'] * 1000, 6)
        total_pct = shares['Public sector expenditure on services']
        residual = round(total - sum(x['value'] for x in items), 6)
        residual_pct = round(total_pct - sum(x['pctGdp'] for x in items), 6)
        items.append({'name': 'Rounding adjustment', 'value': residual, 'pctGdp': residual_pct})
        history.append({'year': year, 'total': total, 'totalPctGdp': total_pct, 'items': items,
                        'tme': round(values['Total Managed Expenditure'] * 1000, 6),
                        'tmePctGdp': shares['Total Managed Expenditure'],
                        'accountingAdjustments': round(values['Accounting adjustments'] * 1000, 6),
                        'accountingAdjustmentsPctGdp': shares['Accounting adjustments'],
                        'debtInterest': round(values['of which: public sector debt interest'] * 1000, 6),
                        'debtInterestPctGdp': shares['of which: public sector debt interest']})
    return {'years': history, 'unit': '£ million',
            'basis': 'Public sector expenditure on services (TES), with a separate published accounting bridge to total managed expenditure (TME). Current prices and published fiscal-year GDP shares.',
            'sources': [{'id': 'pesa-2026-history', 'name': 'HM Treasury · PESA 2026, tables 4.2 and 4.4',
                         'url': PESA_PAGE, 'downloadUrl': PESA_HISTORY_URL, 'publicationDate': '2026-07-16',
                         'observationDate': history[-1]['year'], 'licence': 'Open Government Licence v3.0'}],
            'notes': [
                'One PESA 2026 vintage, 2003-04 onwards. GDP shares use ONS GDP published 30 June 2026, rather than the dashboard’s later GDP vintage.',
                'Source values are rounded to £0.1 billion and 0.1 percentage point; rounding is retained explicitly. Published TES, accounting adjustments and TME may differ by rounding.',
                'Social protection includes pensions and social services as well as benefits; it is not a measure of working-age benefit spending alone.',
                'The source includes public debt transactions within general public services; the dashboard separates that component without changing total spending.',
                'Classification breaks: education excludes the grant-equivalent element of student loans from 2011-12; transport adds the local-government part of Transport Trading Limited from 2011-12 and Network Rail from 2015-16 (Network Rail is in TME throughout).',
                'EU VAT-based payments cease to be deducted from EU transactions from 2010-11. COFOG defence differs from NATO defence definitions.',
                'Economic affairs includes financial-sector interventions and temporary Covid and cost-of-living measures. TME excludes temporary public-sector bank classifications.'
            ]}

def parse_gdp(raw):
    """Published quarterly nominal GDP; never infer it from rounded fiscal ratios."""
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    metadata = {r[0]: r[1] for r in rows if len(r) == 2 and not re.match(r'^\d{4}', r[0])}
    if metadata.get('CDID') != 'BKTL' or metadata.get('Source dataset ID') != 'PN2':
        raise ValueError('Expected ONS BKTL nominal GDP from PN2')
    if metadata.get('Title') != 'Gross Domestic Product at market prices: CP: NSA £m' or metadata.get('Unit') != 'm':
        raise ValueError('Unexpected GDP title or units')
    release = datetime.strptime(metadata['Release date'], '%d-%m-%Y').date().isoformat()
    quarters = {}
    for row in rows:
        match = re.fullmatch(r'(\d{4}) Q([1-4])', row[0])
        if not match:
            continue
        y, q = map(int, match.groups())
        index = y * 4 + q - 1
        if index in quarters:
            raise ValueError('Duplicate GDP quarter')
        value = number(row[1])
        if value is not None and value <= 0:
            raise ValueError('GDP must be positive')
        quarters[index] = value
    if len(quarters) < 8:
        raise ValueError('Insufficient GDP quarters')
    observations = []
    # Missing quarters leave a null denominator rather than bridging a gap.
    for index in range(min(quarters), max(quarters) + 1):
        y, q0 = divmod(index, 4)
        if y < 1999:
            continue
        values = [quarters.get(i) for i in range(index - 3, index + 1)]
        observations.append({'date': f'{y:04d}-{(q0 + 1) * 3:02d}',
                             'rollingAnnualMillion': sum(values) if all(v is not None for v in values) else None})
    if not observations or not any(r['rollingAnnualMillion'] is not None for r in observations):
        raise ValueError('No complete four-quarter GDP totals')
    return {
        'code': 'BKTL', 'asOf': observations[-1]['date'], 'releaseDate': release,
        'nextRelease': metadata.get('Next release'), 'unit': '£ million',
        'basis': 'Latest available four-quarter nominal GDP, current prices, not seasonally adjusted. Dashboard scaling, not an official ONS fiscal ratio.',
        'methodologyUrl': GDP_METHOD,
        'notes': [
            'Sum four consecutive published BKTL quarters. No interpolation, forecast or inference from rounded debt/GDP ratios.',
            'Scale flows by the latest quarter-end denominator at or before the flow endpoint, with at most two months of carry-forward; otherwise unavailable.',
            'Monthly and year-to-date flows are shares of annual GDP, without annualising the numerator.',
            'Historical GDP is the latest release vintage and may differ from the vintage underlying published fiscal ratios.'
        ],
        'sources': [{'id': 'ons-gdp-bktl', 'name': 'ONS · Nominal GDP (BKTL, PN2)',
                     'url': GDP_PAGE, 'downloadUrl': GDP_URL, 'publicationDate': release,
                     'observationDate': observations[-1]['date'], 'licence': 'Open Government Licence v3.0'}],
        'observations': observations,
    }

def fetch_fiscal(fetch):
    fiscal = parse_pusf(fetch(ONS_URL))
    fiscal['gdp'] = parse_gdp(fetch(GDP_URL))
    return fiscal
def fetch_composition(fetch):
    data = parse_pesa(fetch(PESA_URL))
    data['history'] = parse_pesa_history(fetch(PESA_HISTORY_URL))
    from .pesa_history import load_history
    historical=load_history()
    for row in data['socialProtection']:row['sourceId']='pesa-2026'
    current={row['year']:row for row in data['socialProtection']}
    data['socialProtection']=sorted([row for row in historical['years'] if row['year'] not in current]+list(current.values()),key=lambda row:row['year'])
    data['socialProtectionSources']=historical['sources']+data['sources']
    return data
