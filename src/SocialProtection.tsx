import {budgetValue} from './budgetMath';
import {DataTable,SourceLine} from './components';
import {downloadCsv,fmt,type Bundle} from './data';

export function SocialProtection({bundle,from,to,changes,units}:{bundle:Bundle;from:string;to:string;changes:boolean;units:string}){
 const years=bundle.composition.socialProtection||[];
 const end=years.find(y=>y.year===to),start=years.find(y=>y.year===from);
 const unit=units==='gdp'?(changes?'pp of GDP':'% of GDP'):units==='share'?(changes?'pp of TES':'% of TES'):'£bn';
 function values(year:typeof end){
  if(!year)return null;
  const parent=bundle.composition.history?.years.find(y=>y.year===year.year);
  const social=parent?.items.find(i=>i.name==='Social protection');
  return year.items.map(i=>({name:i.name,value:budgetValue(i.value, social?.pctGdp!=null?social.pctGdp*i.value/year.total:null,parent?.total??0,units)}));
 }
 const last=values(end),first=values(start);
 const rows=last&&(!changes||first)?last.map(r=>{const previous=first?.find(i=>i.name===r.name)?.value;return [r.name,changes?(r.value!=null&&previous!=null?r.value-previous:null):r.value] as [string,number|null];}):null;
 const note='PESA table 5.2. Pensions are the published “of which: pensions” under old age, not all old-age spending. Personal social services are the published social-protection subtotal. Other spending is the residual, including non-pension benefits, administration and compensation; it is not a pure working-age benefits measure. GDP shares allocate the parent category’s rounded PESA GDP share; £ amounts retain table 5.2 values. Named-total shares use TES, matching the parent chart. Detailed coverage: 2021–22 to 2025–26.';
 return <details className="social-protection-detail" open><summary>Within social protection</summary>{rows?<><DataTable caption={`Social protection breakdown · ${changes?from+' to ':''}${to}`} headers={['Component',unit]} rows={rows.map(([name,value])=>[name,value==null?'Not available':fmt(value,2)])}/><button className="plain-button" onClick={()=>downloadCsv('social-protection',['Component',unit],rows,`${changes?from+' to ':''}${to}. ${note}`)}>CSV</button><SourceLine sources={bundle.composition.sources} note={note}/></>:<p className="small">Detailed breakdown is available for 2021–22 to 2025–26. {changes?'Both comparison years must be within that range.':'Choose a year in that range to see pensions and other spending.'}</p>}</details>;
}
