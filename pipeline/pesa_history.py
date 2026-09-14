"""Rebuild pinned historical social protection data from official PESA table 5.2.

Run explicitly with python -m pipeline.pesa_history. Daily refreshes read the
reviewed JSON and update the latest five years from the current PESA workbook.
"""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
import openpyxl
from pypdf import PdfReader

DESTINATION=Path(__file__).resolve().parents[1]/'data/pesa-social-history.json'


def spreadsheet_rows(raw,kind):
    if kind=='xlsx':
        book=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
        sheet=next(s for s in book.sheetnames if s.replace('_','.')=='5.2')
        return list(book[sheet].values)
    ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0','o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
    root=ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read('content.xml'))
    table=next(t for t in root.findall('.//t:table',ns) if t.get('{'+ns['t']+'}name').replace('_','.')=='5.2')
    rows=[]
    for row in table.findall('t:table-row',ns):
        cells=[]
        for cell in row:
            value=cell.get('{'+ns['o']+'}value')
            value=float(value) if value is not None else ''.join(cell.itertext()).strip()
            repeat=min(int(cell.get('{'+ns['t']+'}number-columns-repeated','1')),30)
            cells.extend([value]*repeat)
        if any(v not in ('',None) for v in cells):rows.append(cells)
    return rows


def parse_source(raw,source):
    if source['kind']=='pdf':
        text=PdfReader(io.BytesIO(raw)).pages[source['pageIndex']].extract_text().replace('–','-').replace('T otal','Total').replace('T able','Table')
        if 'Table 5.2' not in text or '£ million' not in text:raise ValueError('Unexpected PDF table')
        lines=[' '.join(line.split()) for line in text.splitlines()]
        years=next(re.findall(r'\d{4}-\d{2}',line) for line in lines if len(re.findall(r'\d{4}-\d{2}',line))>=5)
        begin=lines.index('10. Social protection')
        def vector(label):
            line=next(l for l in lines[begin:] if l.startswith(label+' '))
            values=[float(v.replace(',','')) for v in line[len(label):].split()]
            if len(values)!=len(years):raise ValueError('PDF year/value mismatch')
            return values
        pensions=vector('of which: pensions');services=vector('of which: personal social services');totals=vector('Total social protection')
    else:
        rows=spreadsheet_rows(raw,source['kind'])
        if not any('Public sector expenditure on services by sub-function' in str(x) for r in rows[:5] for x in r):raise ValueError('Unexpected workbook table')
        header=next(r for r in rows if sum(bool(re.fullmatch(r'\d{4}-\d{2}',str(x))) for x in r)>=5)
        cols=[(i,str(x)) for i,x in enumerate(header) if re.fullmatch(r'\d{4}-\d{2}',str(x))]
        years=[y for _,y in cols]
        begin=next(i for i,r in enumerate(rows) if any(str(x).strip()=='10. Social protection' for x in r))
        def vector(label):
            row=next(r for r in rows[begin:] if any(' '.join(str(x).split()).lower()==label.lower() for x in r))
            return [float(row[i]) for i,_ in cols]
        pensions=vector('of which: pensions');services=vector('of which: personal social services');totals=vector('Total social protection')
    result=[]
    for year,pension,service,total in zip(years,pensions,services,totals):
        # Exclude estimated final years from the early spring publications.
        if year>source.get('lastOutturn','9999-99'):continue
        if not (0<=pension<=total and 0<=service<=total-pension):raise ValueError('Invalid social protection identity')
        result.append({'year':year,'total':total,'sourceId':source['id'],'items':[
            {'name':'Pensions','value':pension},
            {'name':'Other benefits and social-protection spending','value':total-pension-service},
            {'name':'Personal social services','value':service}]})
    return result


def merge_releases(releases):
    years={}
    for source,rows in sorted(releases,key=lambda pair:pair[0]['vintage']):
        for row in rows:
            if row['year']>='2003-04':years[row['year']]=row
    return [years[y] for y in sorted(years)]


def load_history():
    data=json.loads(DESTINATION.read_text())
    years=data['years']
    if [y['year'] for y in years]!=[f'{y}-{str(y+1)[2:]}' for y in range(2003,2021)]:raise ValueError('Historical PESA coverage changed')
    for year in years:
        if abs(sum(i['value'] for i in year['items'])-year['total'])>0.001:raise ValueError('Historical PESA identity failed')
    return data


def rebuild():
    import requests
    data=json.loads(DESTINATION.read_text());releases=[]
    for source in data['sources']:
        response=requests.get(source['downloadUrl'],timeout=45);response.raise_for_status();raw=response.content
        if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError(f"Source changed: {source['id']}; review before importing")
        releases.append((source,parse_source(raw,source)))
    data['years']=[y for y in merge_releases(releases) if y['year']<'2021-22']
    DESTINATION.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
    load_history()

if __name__=='__main__':rebuild()
