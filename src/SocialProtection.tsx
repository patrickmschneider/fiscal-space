import {budgetValue,socialProtectionItems} from './budgetMath';
import {ChartPanel,DataTable,Disclosure,SourceLine} from './components';
import {downloadCsv,fmt,type Bundle} from './data';

export function SocialProtection({bundle,from,to,changes,units}:{bundle:Bundle;from:string;to:string;changes:boolean;units:string}){
 const years=bundle.composition.socialProtection||[];
 const end=years.find(y=>y.year===to),start=years.find(y=>y.year===from);
 const unit=units==='gdp'?(changes?'pp of GDP':'% of GDP'):units==='share'?(changes?'pp of TES':'% of TES'):'£bn';
 function values(year:typeof end){
  if(!year)return null;
  const parent=bundle.composition.history?.years.find(y=>y.year===year.year);
  return parent?socialProtectionItems(year,parent).map(i=>({name:i.name,value:budgetValue(i.value,i.pctGdp,parent.total,units)})):null;
 }
 const last=values(end),first=values(start);
 const rows=last&&(!changes||first)?last.map(r=>{const previous=first?.find(i=>i.name===r.name)?.value;return [r.name,changes?(r.value!=null&&previous!=null?r.value-previous:null):r.value] as [string,number|null];}):null;
 const sourceIds=new Set([end?.sourceId,...(changes?[start?.sourceId]:[])]);
 const allSources=bundle.composition.socialProtectionSources||bundle.composition.sources;
 const sources=allSources.filter(s=>sourceIds.has(s.id));
 const vintage=(year:typeof end)=>allSources.find(s=>s.id===year?.sourceId)?.name||'Treasury PESA';
 const historyRows=years.map(y=>{const items=values(y);return {label:y.year,pensions:items?.[0].value??null,other:items?.[1].value??null,services:items?.[2].value??null,revisions:items?.[3].value??null,vintage:vintage(y)};});
 const historyUnit=units==='gdp'?'% of GDP':units==='share'?'% of TES':'£bn';
 const note='PESA table 5.2. Pensions are the published “of which: pensions” under old age, not all old-age spending. Personal social services are the published subtotal. Other spending is the residual, including non-pension benefits, administration and compensation; it is not a pure working-age benefits measure. Historical components retain the newest available published cash amounts for each year. Revisions / rounding reconciles their source-vintage total to the current PESA parent; it is not an extra spending programme. GDP shares use the denominator implied by the current parent’s rounded PESA amount and GDP share. TES shares use the current parent chart’s TES total. Cross-vintage changes include revisions and classification changes, not just spending changes. In particular, the 2010 release reclassified some social-protection administration into personal social services. Coverage: 2003–04 to 2025–26.';
 return <details className="social-protection-detail" open><summary>Within social protection</summary>{rows?<><DataTable caption={`Social protection breakdown · ${changes?from+' to ':''}${to}`} headers={['Component',unit]} rows={rows.map(([name,value])=>[name,value==null?'Not available':fmt(value,2)])}/><p className="small">{changes?`${from}: ${vintage(start)}; ${to}: ${vintage(end)}`:`${to}: ${vintage(end)}`}. The reconciliation row captures revisions and rounding, not spending.</p><button className="plain-button" onClick={()=>downloadCsv('social-protection',['Component',unit],rows,`${changes?from+' to ':''}${to}. ${note} ${sources.map(s=>s.url).join(' ')}`)}>CSV</button><SourceLine sources={sources} note={note}/></>:<p className="small">No detailed breakdown is loaded for the selected year.</p>}<Disclosure title="Social protection history · 2003–04 onward"><ChartPanel headingLevel={4} id="social-protection-history" title="Pensions, benefits and social services" summary="Historical source vintages are retained. The reconciliation line shows revisions and rounding against the current social-protection total." rows={historyRows} lines={[{key:'pensions',label:'Pensions',colour:'#175d65'},{key:'other',label:'Other benefits and spending',colour:'#a76232'},{key:'services',label:'Personal social services',colour:'#657c9c'},{key:'revisions',label:'Revisions / rounding',colour:'#777777',dash:'5 5'}]} unit={historyUnit} xLabel="Financial year" extraColumns={[{key:'vintage',label:'Source vintage'}]} sources={allSources} note={note}/></Disclosure></details>;
}
