"""Pinned OBR forecast vintage plus latest ONS history. Never discover a new vintage silently.

The source PDF contains machine-readable table text. Labels, year headers and
accounting identities are checked before publishing. November comparison values
are reconstructed from March's published change tables, retaining rounding.
"""
import csv
import io
import re
from datetime import datetime
from pypdf import PdfReader

EFO_URL = 'https://assets.publishing.service.gov.uk/media/69a6d7b62e1f4fbda4252208/economic-and-fiscal-outlook-march-2026-web-accessible.pdf'
EFO_PAGE = 'https://www.gov.uk/government/publications/march-2026-economic-and-fiscal-outlook'
NOV_PAGE = 'https://obr.uk/efo/economic-and-fiscal-outlook-november-2025/'
CHARTER_URL = 'https://assets.publishing.service.gov.uk/media/699c2194d2b9c6ec5b6fbb7d/260220_-_Updated_Charter_-_February_2026.pdf'
BUDGET_URL = 'https://www.gov.uk/government/publications/budget-2025-document/budget-2025-html'
ONS_URL = 'https://www.ons.gov.uk/file?uri=/economy/governmentpublicsectorandtaxes/publicsectorfinance/datasets/publicsectorfinances/current/pusf.csv'
GDP_URL = 'https://www.ons.gov.uk/generator?format=csv&uri=%2Feconomy%2Fgrossdomesticproductgdp%2Ftimeseries%2Fbktl%2Fpn2'
YEARS = [f'{y}-{str(y+1)[2:]}' for y in range(2024,2031)]
NUMBER = r'-?\d[\d,]*(?:\.\d+)?'


def vector(text,label,n=7):
    matches=re.findall(r'^'+label+r'\s+((?:'+NUMBER+r'\s+){'+str(n-1)+r'}'+NUMBER+r')(?:\s|$)',text,re.M)
    if len(matches)!=1:raise ValueError(f'Expected exactly one OBR row: {label}; found {len(matches)}')
    return [float(x.replace(',','')) for x in matches[0].split()]


def parse_efo(raw):
    pages=[p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages]
    def table(number):
        found=[p for p in pages if re.search(r'Table A\.'+str(number)+r':',p) and '2024-25 2025-26 2026-27 2027-28 2028-29 2029-30 2030-31' in p]
        if len(found)!=1:raise ValueError(f'OBR table A.{number} or expected year header missing')
        return found[0]
    specs={
      'borrowingPct':(9,r'Public sector net borrowing \(b-a\)'),
      'borrowingBn':(9,r'Public sector net borrowing'),
      'debtPct':(9,r'Public sector net debt1'),
      'debtBn':(9,r'Public sector net debt'),
      'netFinancialLiabilitiesPct':(9,r'Public sector net financial liabilities1'),
      'receiptsPct':(9,r'Public sector current receipts \(a\)'),
      'spendingPct':(9,r'Total managed expenditure \(b\)'),
      'receiptsBn':(5,r'Current receipts'),
      'spendingBn':(7,r'Total managed expenditure'),
      'interestBn':(9,r'Net debt interest'),
      'currentBudgetDeficitBn':(9,r'Current budget deficit'),
      'netInvestmentBn':(9,r'Public sector net investment'),
      'primaryDeficitPct':(9,r'Primary deficit'),
      'structuralPrimaryDeficitPct':(9,r'Cyclically adjusted primary deficit'),
      'structuralBorrowingPct':(9,r'Cyclically adjusted net borrowing'),
      'structuralBorrowingBn':(9,r'Cyclically adjusted net borrowing'),
      'outputGapPct':(9,r'Memo: output gap \(per cent of GDP\)'),
      'gdpBn':(3,r'Nominal GDP \(£ billion\)1,2'),
      'debtGdpBn':(3,r'Nominal GDP \(centred end-March £bn\)1,3'),
      'realGdpGrowth':(3,r'Real GDP'),
      'nominalGdpGrowth':(3,r'Nominal GDP1'),
      'gdpDeflatorGrowth':(3,r'GDP deflator'),
      'inflation':(3,r'CPI'),
      'rpiInflation':(3,r'RPI'),
      'earningsGrowth':(3,r'Average weekly earnings5'),
      'bankRate':(3,r'Bank Rate \(per cent\)'),
      'giltYield':(3,r'Market gilt rates \(per cent\)9'),
    }
    def read_series(key,t,label):
        text=table(t)
        if key in ('structuralBorrowingPct','structuralBorrowingBn'):
            parts=text.split('International comparisons')
            if len(parts)!=2:raise ValueError('OBR fiscal aggregate sections missing')
            text=parts[0 if key.endswith('Pct') else 1]
        elif key=='netFinancialLiabilitiesPct':text=text.split('Other deficit measures')[0]
        if t==4 and key in ('bankRate','giltYield'):label=label.replace(r' \(per cent\)', '')
        return vector(text,label)
    current={key:read_series(key,t,label) for key,(t,label) in specs.items()}
    previous={key:[round(a-b,6) for a,b in zip(current[key],read_series(key,t+1,label))] for key,(t,label) in specs.items()}
    vintages=[]
    for id,label,date,values,reconstructed in [('2025-11','November 2025 (reconstructed)','2025-11-26',previous,True),('2026-03','March 2026','2026-03-03',current,False)]:
        rows=[]
        for i,year in enumerate(YEARS):
            row={'year':year,'status':'outturn' if i==0 else 'forecast',**{key:vals[i]for key,vals in values.items()}}
            row['primaryBalancePct']=-row.pop('primaryDeficitPct')
            row['structuralPrimaryBalancePct']=-row.pop('structuralPrimaryDeficitPct')
            row['interestPct']=round(100*row['interestBn']/row['gdpBn'],6)
            row['interestBurdenPct']=round(100*row['interestBn']/row['receiptsBn'],6)
            if abs(row['spendingBn']-row['receiptsBn']-row['borrowingBn'])>1.6:raise ValueError('OBR borrowing identity exceeds published rounding')
            rows.append(row)
        vintages.append({'id':id,'label':label,'publicationDate':date,'forecastStart':'2025-26','rows':rows,'reconstructed':reconstructed,'sourceUrl':EFO_URL,'tables':'A.3–A.10','notes':[
          'Fiscal years April–March. Forecast classification is as known at this vintage; 2024-25 is published outturn.',
          'Net debt interest; primary balance is minus the OBR primary deficit. Cyclically adjusted is not a measure of discretionary policy alone.',
          'Fiscal ratios use fiscal-year GDP for flows and centred end-March GDP for debt. Market gilt rates are a weighted conventional-gilt assumption, not a 10-year yield.',
          'November values are March levels minus published November-to-March changes. This is a rounded reconstruction, not an original archived November workbook.' if reconstructed else 'Values retain source rounding; totals may differ by up to £1bn.']})
    return vintages


def parse_history(pusf,gdp):
    rows=list(csv.reader(io.StringIO(pusf.decode('utf-8-sig')))); indices={v:i for i,v in enumerate(rows[1])}
    if rows[0][0]!='Title' or rows[1][0]!='CDID':raise ValueError('Expected ONS PUSF metadata')
    required=['KX5Q','JW2O','JW2P','JW2L','HF6X','HF6W','DZLW','JW2M']
    if any(k not in indices for k in required):raise ValueError('Missing ONS history series')
    series={r[0]:r for r in rows if re.fullmatch(r'\d{4} Q[1-4]',r[0])}
    gdprows=list(csv.reader(io.StringIO(gdp.decode('utf-8-sig'))));gdpseries={r[0]:float(r[1]) for r in gdprows if re.fullmatch(r'\d{4} Q[1-4]',r[0]) and r[1]}
    release=next(r[indices['KX5Q']] for r in rows if r[0]=='Release Date')
    result=[]
    for y in range(1990,datetime.now().year+1):
        periods=[f'{y} Q2',f'{y} Q3',f'{y} Q4',f'{y+1} Q1']
        if not all(p in series and p in gdpseries for p in periods):continue
        def total(code):
            vals=[series[p][indices[code]]for p in periods]
            return sum(float(v) for v in vals)/1000 if all(v not in ('','..','...')for v in vals) else None
        receipts,spending=total('JW2O'),total('KX5Q')
        if receipts is None or spending is None:continue
        g=sum(gdpseries[p]for p in periods)/1000
        net=total('JW2P');income=total('JW2L');interest=net-income if net is not None and income is not None else None
        # OBR Working Paper 17, table A.1: primary deficit is
        # -J5II - (JW2P - JW2L + JW2M). Retain the existing financing
        # proxy separately because other views already use it.
        internal_interest=total('JW2M')
        deficit_interest=interest+internal_interest if interest is not None and internal_interest is not None else None
        borrowing=round(spending-receipts,6)
        end=series[periods[-1]]
        def endval(code):
            v=end[indices[code]];return float(v)if v not in ('','..','...')else None
        result.append({'year':f'{y}-{str(y+1)[2:]}','status':'outturn','borrowingBn':borrowing,'borrowingPct':round(100*borrowing/g,6),'receiptsBn':receipts,'spendingBn':spending,'receiptsPct':100*receipts/g,'spendingPct':100*spending/g,'deficitInterestBn':deficit_interest,'interestBn':interest,'interestPct':100*interest/g if interest is not None else None,'primaryBalancePct':100*(deficit_interest-borrowing)/g if deficit_interest is not None else None,'structuralPrimaryBalancePct':None,'debtPct':endval('HF6X'),'debtBn':endval('HF6W'),'gdpBn':g,'netInvestmentBn':total('DZLW')})
    if len(result)<30:raise ValueError('Insufficient ONS annual fiscal history')
    return result,datetime.strptime(release,'%d-%m-%Y').date().isoformat()


def fetch_outlook(fetch):
    vintages=parse_efo(fetch(EFO_URL))
    history,release=parse_history(fetch(ONS_URL),fetch(GDP_URL))
    from .obr_history import WORKBOOK,parse_databank
    deficit_history=parse_databank(WORKBOOK.read_bytes())
    rules=[{'name':'Stability rule','description':'Cover current spending with receipts.','definition':'Current budget surplus in 2029-30 until that is the third forecast year; thereafter balance or surplus from the third year of the rolling forecast.','targetYear':'2029-30','headroomBn':21.7,'met':True,'binding':True,'assessmentDate':'2025-11-26','sourceUrl':BUDGET_URL,'definitionUrl':CHARTER_URL},
      {'name':'Investment rule','description':'Net financial liabilities fall relative to GDP.','definition':'Public sector net financial liabilities fall as a share of GDP by 2029-30 until that is the third forecast year; thereafter by the third rolling forecast year.','targetYear':'2029-30','headroomBn':24.4,'met':True,'binding':False,'assessmentDate':'2025-11-26','sourceUrl':BUDGET_URL,'definitionUrl':CHARTER_URL},
      {'name':'Welfare cap','description':'Covered welfare expenditure stays within the Treasury cap and margin.','definition':'A supplementary cap on specified welfare expenditure; this is not a cap on all welfare or pension spending.','targetYear':None,'headroomBn':None,'met':None,'binding':False,'assessmentDate':None,'sourceUrl':CHARTER_URL,'notes':'Numerical cap assessment not imported.'}]
    vintages[0]['rules']=rules[:2]
    vintages[1]['rules']=[]
    data={'schemaVersion':1,'asOf':'2026-03-03','latestVintage':'2026-03','vintages':vintages,'history':history,'historyAsOf':release,'deficitHistory':deficit_history['rows'],'deficitHistoryMetadata':{k:v for k,v in deficit_history.items() if k!='rows'},'rules':rules,
      'currentBudgetUpdate':{'year':'2029-30','surplusBn':-next(r['currentBudgetDeficitBn'] for r in vintages[-1]['rows'] if r['year']=='2029-30'),'publicationDate':'2026-03-03','formalAssessment':False,'sourceUrl':EFO_URL,'note':'The March 2026 EFO does not formally assess compliance with the fiscal rules. £23.6bn is the updated current-budget surplus forecast, not a new formal rule assessment.'},
      'headroomHistory':[{'vintage':'2025-03','label':'March 2025','publicationDate':'2025-03-26','headroomBn':9.9,'targetYear':'2029-30','sourceUrl':NOV_PAGE},{'vintage':'2025-11','label':'November 2025','publicationDate':'2025-11-26','headroomBn':21.7,'targetYear':'2029-30','sourceUrl':BUDGET_URL}],
      'sensitivities':[{'id':'rates','label':'Bank Rate and gilt yields +1pp','shock':1,'unit':'percentage points','borrowingChangeBn':15,'targetYear':'2030-31','vintage':'2026-03','sourceUrl':EFO_URL+'#page=103','note':'Sustained rise from 2026-27. Official borrowing sensitivity, not an elasticity of headroom.'},{'id':'nominal-growth','label':'Nominal GDP growth −0.1pp each year','shock':-0.1,'unit':'percentage points per year','borrowingChangeBn':8,'targetYear':'2030-31','vintage':'2026-03','sourceUrl':EFO_URL+'#page=103','note':'Official isolated ready-reckoner shock from 2026-27.'},{'id':'rpi','label':'RPI inflation +1pp','shock':1,'unit':'percentage points','borrowingChangeBn':11,'targetYear':'2030-31','vintage':'2026-03','sourceUrl':EFO_URL+'#page=103','note':'Sustained rise from 2026-27. Downward 1pp shock reduces borrowing £10bn; asymmetry is official.'}],
      'sources':[{'name':'OBR March 2026 EFO, Annex A tables A.3–A.10','url':EFO_URL,'publicationDate':'2026-03-03'},{'name':'OBR primary-deficit methodology, Working Paper 17 table A.1','url':'https://obr.uk/docs/dlm_uploads/working_paper_no17_uncertainty.pdf'},{'name':'ONS PUSF','url':ONS_URL,'publicationDate':release},{'name':'ONS GDP BKTL','url':GDP_URL},{'name':'Charter for Budget Responsibility Autumn 2025','url':CHARTER_URL},{'name':'Budget 2025 fiscal-rule assessment','url':BUDGET_URL}],
      'notes':['Pinned EFO vintage; new publications require adapter review and are added, never substituted for older forecasts.','History is the latest ONS vintage, separate from OBR vintage rows. Borrowing history = TME minus current receipts; flow ratios divide by the sum of April–March nominal GDP quarters. Debt is the published end-March debt/GDP ratio.','Historical net interest uses interest and dividends paid outside the public sector minus those received (JW2P−JW2L); it is a net-financing-cost proxy, not necessarily identical to the OBR net-interest definition.','Historical primary deficit = borrowing minus (JW2P−JW2L+JW2M), following OBR Working Paper 17 table A.1. Annual non-seasonally-adjusted totals use matched financial-year GDP. Missing cyclical estimates remain null.','Forecast assumptions use fiscal years. No current macro outturn or consensus feed is yet attached to these annual assumptions.']}

    for i,source in enumerate(data['sources']):
        source['id']=f'outlook-source-{i}'
        record=next((r for r in reversed(getattr(fetch,'records',[])) if r['url']==source['url']),{})
        source['retrievedAt']=record.get('retrievedAt')
    data['seriesMetadata']={key:{'sourceUrl':EFO_URL,'publicationDate':'2026-03-03','frequency':'Financial year April–March','units':'GBP billion' if key.endswith('Bn') else 'percent' if key.endswith('Pct') or key.endswith('Growth') or key in ('inflation','bankRate','giltYield') else 'see source','seasonalAdjustment':'Annual totals/averages; see source definitions','status':'Per vintage row','vintageSelection':'Selected OBR publication; November rows explicitly reconstructed from rounded published changes'} for key in vintages[-1]['rows'][0] if key not in ('year','status')}
    return data


def validate_outlook(data):
    """Reject incomplete vintages, broken accounting and silently relabelled data."""
    import math
    if data.get('schemaVersion')!=1:raise ValueError('Unsupported outlook schema')
    vintages=data.get('vintages',[])
    ids=[v.get('id')for v in vintages]
    if len(vintages)<2 or len(set(ids))!=len(ids) or data.get('latestVintage') not in ids:
        raise ValueError('Missing or duplicate outlook vintage')
    for v in vintages:
        rows=v.get('rows',[])
        if [r.get('year') for r in rows]!=YEARS:raise ValueError('Incomplete fiscal-year forecast')
        for row in rows:
            for key in ('borrowingBn','borrowingPct','debtPct','receiptsBn','spendingBn','interestBn','gdpBn'):
                value=row.get(key)
                if not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(f'Invalid outlook {key}')
            for key in ('structuralBorrowingBn','structuralBorrowingPct','outputGapPct'):
                if key in row and (not isinstance(row[key],(int,float)) or not math.isfinite(row[key])):raise ValueError(f'Invalid outlook {key}')
            if row['gdpBn']<=0:raise ValueError('Nonpositive GDP')
            if abs(row['spendingBn']-row['receiptsBn']-row['borrowingBn'])>1.6:raise ValueError('Forecast borrowing identity failed')
            expected='forecast' if row['year']>=v['forecastStart'] else 'outturn'
            if row.get('status')!=expected:raise ValueError('Vintage outturn/forecast classification changed')
            if abs((row['interestBn']-row['borrowingBn'])/row['gdpBn']*100-row['primaryBalancePct'])>.15:
                raise ValueError('Primary balance sign/units mismatch')
    hist=data.get('history',[])
    if len(hist)<30 or len({r['year']for r in hist})!=len(hist):raise ValueError('History coverage incomplete or duplicated')
    for row in hist:
        if row.get('status')!='outturn':raise ValueError('Historical ONS row misclassified')
        if row.get('deficitInterestBn') is not None:
            if not math.isfinite(row['deficitInterestBn']):raise ValueError('Invalid historical net interest')
            if abs((row['deficitInterestBn']-row['borrowingBn'])/row['gdpBn']*100-row['primaryBalancePct'])>.00001:
                raise ValueError('Historical primary balance identity failed')
        if abs(row['spendingBn']-row['receiptsBn']-row['borrowingBn'])>.002:raise ValueError('History borrowing identity failed')
    for row in data.get('deficitHistory',[]):
        if row['gdpBn']<=0 or any(not math.isfinite(row[k]) for k in ('borrowingBn','structuralBorrowingBn','primaryBalanceBn','structuralPrimaryBalanceBn','deficitInterestBn')):
            raise ValueError('Invalid OBR deficit history')
        if abs(row['borrowingBn']+row['primaryBalanceBn']-row['deficitInterestBn'])>.00001:
            raise ValueError('OBR deficit history primary identity failed')
    update=data['currentBudgetUpdate']
    latest=next(v for v in vintages if v['id']==data['latestVintage'])
    target=next(r for r in latest['rows'] if r['year']==update['year'])
    if abs(update['surplusBn']+target['currentBudgetDeficitBn'])>.001:raise ValueError('Current budget update inconsistent with forecast')
    if latest['id']=='2026-03' and (latest.get('rules') or update.get('formalAssessment') is not False):
        raise ValueError('Spring 2026 is not a formal fiscal-rule assessment')
    return data
