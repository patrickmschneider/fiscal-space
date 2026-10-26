"""Daily check for an OBR Economic and fiscal outlook newer than the pinned vintage.

obr.uk blocks the hosted runner, so this asks GOV.UK, which mirrors each EFO.
GOV.UK search does not index every EFO, so likely publication slugs are also
probed directly. A failed check never clears an earlier detection.
"""
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
import requests
from .obr_gdp import PUBLICATION_DATE, VINTAGE

OUTPUT=Path(__file__).resolve().parents[1]/'public/data/obr-check.json'
OUTLOOK=OUTPUT.with_name('outlook.json')
SEARCH_URL='https://www.gov.uk/api/search.json'
CONTENT_URL='https://www.gov.uk/api/content/government/publications/{slug}'
MONTHS=('january','february','march','april','may','june','july','august','september','october','november','december')
TITLE=re.compile(r'economic and fiscal outlook',re.I)
HEADERS={'User-Agent':'UKFiscalDashboard/0.1 (public research; https://github.com/patrickmschneider/fiscal-space)'}


def get(url,**params):
    response=requests.get(url,params=params,timeout=(10,30),headers=HEADERS)
    if response.status_code==404:return None
    response.raise_for_status();return response.json()


def vintage_month(text):
    """(year, month) named in an EFO title or slug, e.g. 'March 2026 Economic and fiscal outlook'."""
    match=re.search(r'(%s)[\s-]+(\d{4})'%'|'.join(MONTHS),text,re.I)
    return (int(match[2]),MONTHS.index(match[1].lower())+1) if match else None


def candidate_slugs(pinned,today):
    """Month-year slugs after the pinned vintage's month, through the current month."""
    y,m=pinned.year,pinned.month
    while (y,m)<(today.year,today.month):
        y,m=(y+1,1) if m==12 else (y,m+1)
        for name in (f'{MONTHS[m-1]}-{y}-economic-and-fiscal-outlook',f'economic-and-fiscal-outlook-{MONTHS[m-1]}-{y}'):
            yield name


def find_newer(pinned,today,get=get):
    """EFOs whose named month is after the pinned vintage's month. Publication timestamps are
    not compared: GOV.UK search reports a page's latest update, not first publication."""
    found={}
    later=lambda text:(vintage_month(text) or (0,0))>(pinned.year,pinned.month)
    search=get(SEARCH_URL,q='"economic and fiscal outlook"',filter_format='independent_report',order='-public_timestamp',count=20,fields='title,link,public_timestamp')
    for r in (search or {}).get('results',[]):
        if TITLE.search(r.get('title','')) and later(r['title']):
            found[r['link']]={'title':r['title'],'url':f"https://www.gov.uk{r['link']}",'publishedAt':r['public_timestamp'][:10]}
    for slug in candidate_slugs(pinned,today):
        page=get(CONTENT_URL.format(slug=slug))
        published=(page or {}).get('first_published_at','')[:10]
        if page and TITLE.search(page.get('title','')) and later(slug):
            found.setdefault(page['base_path'],{'title':page['title'],'url':f"https://www.gov.uk{page['base_path']}",'publishedAt':published})
    return sorted(found.values(),key=lambda r:r['publishedAt'])


def pinned_vintages(outlook=None):
    """Every dashboard input tied to one EFO: the GDP gap-filler and the latest outlook vintage."""
    pinned=[{'vintage':VINTAGE,'publicationDate':PUBLICATION_DATE,'use':'GDP for unpublished quarters'}]
    if outlook is None and OUTLOOK.exists():outlook=json.loads(OUTLOOK.read_text())
    latest=next((v for v in (outlook or {}).get('vintages',[]) if v['id']==(outlook or {}).get('latestVintage')),None)
    if latest:pinned.append({'vintage':f"{latest['label']} Economic and fiscal outlook",'publicationDate':latest['publicationDate'],'use':'outlook, fiscal rules and forecast paths'})
    return pinned


def check(today=None,get=get,previous=None,outlook=None):
    now=datetime.now(timezone.utc)
    today=today or now.date()
    pinned=pinned_vintages(outlook)
    oldest=min(pinned,key=lambda v:v['publicationDate'])
    record={'schemaVersion':1,'checkedAt':now.isoformat(timespec='seconds'),
            'pinned':{'vintage':oldest['vintage'],'publicationDate':oldest['publicationDate']},'inputs':pinned}
    try:
        newer=find_newer(date.fromisoformat(oldest['publicationDate']),today,get)
        return {**record,'status':'outdated' if newer else 'current','newer':newer}
    except Exception as exc:
        kept=[r for r in (previous or {}).get('newer',[]) if (previous or {}).get('pinned')==record['pinned']]
        return {**record,'status':'outdated' if kept else 'unknown','newer':kept,'error':str(exc)}


def main():
    previous=json.loads(OUTPUT.read_text()) if OUTPUT.exists() else None
    record=check(previous=previous)
    OUTPUT.write_text(json.dumps(record,indent=1,ensure_ascii=False)+'\n')
    print(f"OBR check: {record['status']}"+''.join(f"; newer: {r['title']} ({r['publishedAt']})" for r in record['newer'])+(f"; {record['error']}" if 'error' in record else ''))
    return 0


if __name__=='__main__':
    sys.exit(main())
