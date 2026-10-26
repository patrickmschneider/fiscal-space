"""Pinned, user-supplied OBR quarterly nominal GDP (BKTL basis) for the GDP publication gap.

ONS publishes monthly borrowing for a quarter's last month before that quarter's
GDP. The missing quarter is the ONS value a year earlier grown by the OBR's
year-on-year forecast growth for that quarter, so the latest ONS level and
seasonal pattern carry through. Forecast quarters are replaced as soon as ONS
publishes them. obr.uk blocks automated downloads, so a new EFO vintage must be
downloaded by hand and reviewed before it replaces this one.
"""
import hashlib
import io
import re
from pathlib import Path
import openpyxl

WORKBOOK=Path(__file__).resolve().parents[1]/'data/efo-march-2026-detailed-forecast-tables-economy.xlsx'
SOURCE_URL='https://obr.uk/download/march-2026-economic-and-fiscal-outlook-detailed-forecast-tables-economy/'
EFO_PAGE='https://obr.uk/efo/economic-and-fiscal-outlook-march-2026/'
VINTAGE='March 2026 Economic and fiscal outlook'
PUBLICATION_DATE='2026-03-03'
MAX_FORECAST_QUARTERS=2


def parse_obr_gdp(raw):
    """Quarter index (year*4 + quarter-1) -> OBR nominal GDP, £ million, NSA."""
    book=openpyxl.load_workbook(io.BytesIO(raw),data_only=True,read_only=True)
    contents=[c for r in book['Contents'].iter_rows(max_row=4,values_only=True) for c in r if isinstance(c,str)]
    if f'{VINTAGE} – detailed forecast tables: economy' not in contents:
        raise ValueError('Review the new OBR economy tables vintage before importing')
    rows=list(book['1.4'].iter_rows(values_only=True))
    text=[c for r in rows for c in r if isinstance(c,str)]
    if '1.4 Nominal GDP (£ billion, non-seasonally adjusted)' not in text or not any('BKTL' in c for c in text):
        raise ValueError('Expected OBR table 1.4 nominal GDP on the ONS BKTL basis')
    quarters={}
    for r in rows:
        label=next((c for c in r if isinstance(c,str)),None)
        match=re.fullmatch(r'(\d{4})Q([1-4])',label or '')
        if not match:continue
        value=r[r.index(label)+1]
        if not isinstance(value,(int,float)) or value<=0:raise ValueError(f'Nonpositive or missing OBR GDP in {label}')
        index=int(match[1])*4+int(match[2])-1
        if index in quarters:raise ValueError('Duplicate OBR GDP quarter')
        quarters[index]=value*1000
    if not quarters or sorted(quarters)!=list(range(min(quarters),max(quarters)+1)):
        raise ValueError('OBR GDP quarters are not contiguous')
    return quarters


def load_obr_gdp():
    raw=WORKBOOK.read_bytes()
    return {'quarters':parse_obr_gdp(raw),'fileSha256':hashlib.sha256(raw).hexdigest(),'fileName':WORKBOOK.name}


def forecast_quarters(ons,obr,through):
    """ONS quarters plus OBR-grown quarters ending on or before the `through` month (YYYY-MM)."""
    last=max(i for i,v in ons.items() if v is not None)
    y,m=map(int,through.split('-'))
    target=y*4+(m-1)//3-(0 if m%3==0 else 1)
    if target-last>MAX_FORECAST_QUARTERS:return {}
    extended,added={**ons},{}
    for index in range(last+1,target+1):
        base=extended.get(index-4)
        if base is None or index not in obr or index-4 not in obr:return {}
        extended[index]=added[index]=base*obr[index]/obr[index-4]
    return added
