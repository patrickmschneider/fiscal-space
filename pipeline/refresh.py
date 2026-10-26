"""Manual refresh. Stage each source group, archive, then atomically promote.

Usage: python3 -m pipeline.refresh [--country au|us] [--group fiscal] [--offline] [--validate]
Failures leave last-good data intact and return nonzero while updating status.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import requests

ROOT=Path(__file__).resolve().parents[1]
GROUPS=('fiscal','composition','forecast','debt','curve','outlook','reliefs')
COUNTRIES=('uk','au','us')
# The UK keeps its original paths so existing URLs, archives and tests are unchanged.
def data_dir(root=ROOT,country='uk'):return Path(root)/('public/data' if country=='uk' else f'public-{country}/data')
def release_prefix(country):return '' if country=='uk' else f'{country}-'

def stamp():return datetime.now(timezone.utc).isoformat()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def atomic(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_bytes(raw)
    os.replace(tmp,path)

class Fetcher:
    def __init__(self,root=ROOT,offline=False):
        self.root=Path(root);self.archive=self.root/'data/archive';self.archive.mkdir(parents=True,exist_ok=True)
        self.index_path=self.archive/'index.json';self.offline=offline;self.records=[]
        self.index=json.loads(self.index_path.read_text()) if self.index_path.exists() else {}
    def __call__(self,url,headers=None):
        if not url.startswith('https://'):raise ValueError('Official data downloads must use HTTPS')
        if self.offline:
            if url not in self.index:raise ValueError(f'No archived input for {url}')
            entry=self.index[url];raw=(self.archive/'objects'/entry['sha256']).read_bytes()
            if digest(raw)!=entry['sha256']:raise ValueError('Archive checksum mismatch')
            self.records.append(entry);return raw
        error=None
        for attempt in range(2):
            try:
                response=requests.get(url,timeout=(10,45),headers={'User-Agent':'UKFiscalDashboard/0.1 (public research; https://github.com/patrickmschneider/fiscal-space)',**(headers or {})})
                response.raise_for_status();raw=response.content
                entry={'url':url,'resolvedUrl':response.url,'retrievedAt':stamp(),'sha256':digest(raw),'bytes':len(raw),'contentType':response.headers.get('Content-Type','')}
                atomic(self.archive/'objects'/entry['sha256'],raw)
                self.index[url]=entry;atomic(self.index_path,encode(self.index));self.records.append(entry);return raw
            except requests.RequestException as exc:
                error=exc
                if getattr(exc.response,'status_code',None) in (400,401,403,404):break
                if not attempt:time.sleep(1)
        raise RuntimeError(f'Official download failed: {url} ({error})')

def validate(group,data,country='uk'):
    if data.get('schemaVersion')!=1:raise ValueError('Unsupported schemaVersion')
    encode(data) # Reject NaN/Infinity before any publication.
    if country!='uk':
        from importlib import import_module
        return getattr(import_module(f'pipeline.{country}.validate'),f'validate_{country}')(group,data)
    if group=='fiscal':
        rows=data.get('observations',[])
        if len(rows)<24:raise ValueError('Insufficient fiscal observations')
        for row in rows:
            if abs(row['spending']-row['receipts']-row['borrowing'])>1:raise ValueError('Borrowing identity failed')
    elif group=='composition':
        if not data.get('years'):raise ValueError('No annual composition')
        for year in data['years']:
            if abs(sum(x['value'] for x in year['items'])-year['total'])>0.001:raise ValueError('Annual composition does not reconcile')
        for year in data.get('socialProtection',[]):
            if abs(sum(x['value'] for x in year['items'])-year['total'])>0.001 or any(x['value']<0 for x in year['items']):
                raise ValueError('Social protection breakdown does not reconcile')
    elif group=='debt':
        if not data.get('securities'):raise ValueError('No debt securities')
        if abs(sum(s['nominalMillion'] for s in data['securities'])-data['totals']['nominalMillion'])>.001:raise ValueError('Debt total mismatch')
    elif group=='forecast':
        if data.get('status')!='available' or len(data.get('cumulative',[]))!=12:raise ValueError('Incomplete forecast')
    elif group=='outlook':
        from .outlook import validate_outlook
        validate_outlook(data)
    elif group=='reliefs':
        from .reliefs import validate_reliefs
        validate_reliefs(data)
    elif group=='curve':
        if not data.get('curves'):raise ValueError('No validated curve observations')

def promote(group,data,fetcher,root=ROOT,changes=None,country='uk'):
    validate(group,data,country)
    # Retrieved times belong in a release record, not a claim that old observations are new.
    raw=encode(data);release=digest(raw)
    archive=Path(root)/'data/archive/releases'
    name=f'{release_prefix(country)}{group}-{release}'
    atomic(archive/f'{name}.json',raw)
    atomic(archive/f'{name}.metadata.json',encode({'group':group,'country':country,'releaseId':release,'createdAt':stamp(),'inputs':fetcher.records,'changes':changes}))
    atomic(data_dir(root,country)/f'{group}.json',raw)
    return release

def country_adapters(country):
    from importlib import import_module
    return import_module(f'pipeline.{country}').ADAPTERS

def refresh(groups=GROUPS,offline=False,root=ROOT,adapters=None,country='uk'):
    root=Path(root);path=data_dir(root,country)/'manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else {'schemaVersion':1,'groups':{}}
    if manifest.get('schemaVersion')!=1:raise ValueError('Unsupported manifest schema')
    if adapters is None and country!='uk':adapters=country_adapters(country)
    if adapters is None:
        from .fiscal import fetch_fiscal,fetch_composition
        from .dmo import fetch_debt
        from .obr import fetch_forecast
        from .boe import fetch_curve
        from .outlook import fetch_outlook
        from .reliefs import fetch_reliefs
        adapters=dict(zip(GROUPS,[fetch_fiscal,fetch_composition,fetch_forecast,fetch_debt,fetch_curve,fetch_outlook,fetch_reliefs]))
    failed=[]
    for group in groups:
        previous=manifest['groups'].get(group,{})
        fetcher=Fetcher(root,offline)
        try:
            data=adapters[group](fetcher)
            from .changes import compare_release
            saved=data_dir(root,country)/f'{group}.json'
            changes=compare_release(group,json.loads(saved.read_text()) if saved.exists() else None,data)
            release=promote(group,data,fetcher,root,changes=changes,country=country)
            manifest['groups'][group]={'status':'success','outcome':'unchanged' if previous.get('releaseId')==release else 'new','lastChecked':stamp(),'lastSuccess':stamp(),'asOf':data.get('asOf') or data.get('observationDate') or data.get('publicationDate'),'releaseId':release,'mode':'archive replay' if offline else 'source download','changes':changes}
            print(f'{group}: validated and saved',flush=True)
        except Exception as exc:
            manifest['groups'][group]={**previous,'status':'failed','lastChecked':stamp(),'error':str(exc)}
            failed.append(group);print(f'{group}: FAILED; retained last saved data. {exc}',flush=True)
        manifest['generatedAt']=stamp()
        if os.environ.get('UK_FISCAL_CODE_SHA'):manifest['applicationCommit']=os.environ['UK_FISCAL_CODE_SHA']
        atomic(path,encode(manifest))
    return failed

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--country',choices=COUNTRIES,default='uk')
    parser.add_argument('--group',choices=GROUPS,action='append')
    parser.add_argument('--offline',action='store_true',help='Replay locally archived inputs without networking')
    parser.add_argument('--validate',action='store_true',help='Check saved datasets without modifying them')
    args=parser.parse_args();groups=args.group or GROUPS
    if args.validate:
        failed=[]
        for group in groups:
            try:validate(group,json.loads((data_dir(ROOT,args.country)/f'{group}.json').read_text()),args.country);print(f'{group}: valid')
            except Exception as exc:failed.append(group);print(f'{group}: {exc}')
    else:
        lock=ROOT/'data/archive/refresh.lock';lock.parent.mkdir(parents=True,exist_ok=True)
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise SystemExit('Another refresh may be running; see README for stale-lock recovery.')
        try:
            os.write(fd,str(os.getpid()).encode());os.close(fd)
            failed=refresh(groups,args.offline,country=args.country)
        finally:lock.unlink(missing_ok=True)
    raise SystemExit(1 if failed else 0)

if __name__=='__main__':main()
