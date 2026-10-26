import {C,local} from './country';
export type Source = {id:string;attribution?:string; name?:string; title?:string; publisher?:string; url:string; downloadUrl?:string; publicationDate?:string|null; observationDate?:string; retrievedAt?:string; licence?:string};
export type Observation = {date:string; [key:string]:number|string|null};
export type Series = {code:string;label:string;unit:string;scope:string;sourceTitle:string};
export type Gdp = {basis:string;sources:Source[];observations:{date:string;rollingAnnualMillion:number|null;forecastQuarters?:string[]}[];forecastExtension?:{vintage:string;publicationDate:string;quarters:string[]}};
export type Fiscal = {schemaVersion:number;asOf:string;releaseDate:string;nextRelease:string;scope:string;basis:string;sources:Source[];series:Record<string,Series>;observations:Observation[];gdp?:Gdp;notes:string[]};
export type Composition = {socialProtectionSources?:Source[];socialProtection?:{year:string;sourceId?:string;total:number;items:{name:string;value:number}[]}[];history?:import('./budgetMath').FunctionalHistory;
 /** Australia: revenue by type, and the Commonwealth level as a separate (never additive) view. */
 receipts?:import('./budgetMath').FunctionalHistory&{totalLabel?:string};levels?:{commonwealth?:{label:string;history:import('./budgetMath').FunctionalHistory;receipts:import('./budgetMath').FunctionalHistory}};schemaVersion:number;asOf:string;unit:string;basis:string;sources:Source[];years:{year:string;total:number;debtInterest?:number;items:{name:string;value:number}[]}[];notes:string[]};
export type Forecast = {schemaVersion:number;status:string;fiscalYear?:string;vintage?:string;publicationDate?:string;cumulative?:{period:string;value:number}[];sources:Source[];notes?:string[]};
export type Security = {isin:string;name:string;type:string;couponPct:number;maturityDate:string;nominalMillion:number;upliftedMillion:number};
export type Auction = {date:string;isin:string;name:string;offeredMillion:number|null;allottedMillion:number|null;yieldPct:number|null;cover:number|null;tailBp:number|null;postAuctionMillion:number|null;sourceUrl?:string};
export type Operation = {date:string;type:string;name:string;amountMillion:number|null;status:string;sourceUrl:string;datePrecision?:string};
export type Debt = {schemaVersion:number;asOf:string;sources:Source[];securities:Security[];auctions:Auction[];calendar:Operation[];totals:{nominalMillion:number;upliftedMillion:number};availability:Record<string,unknown>;notes?:string[]};
export type CurveObservation = {date:string;points:{tenor:number;rate:number|null}[]};
export type Benchmark = {date:string;[key:string]:number|string|null};
export type Curve = {schemaVersion:number;status?:string;asOf?:string;observationDate?:string|null;sources:Source[];curves:CurveObservation[];realCurves?:CurveObservation[];breakevenCurves?:CurveObservation[];notes?:string[];reason?:string;basis?:string;
 /** Australia: no official real curve, so benchmark yields and a 10-year breakeven are published as time series. */
 benchmarks?:Benchmark[];benchmarkSeries?:Record<string,{seriesId:string;label:string}>;breakeven10y?:{date:string;value:number}[];breakeven10yBasis?:string;benchmarksAsOf?:string;dailyFrom?:string};
export type GroupStatus = {status:string;lastChecked:string;lastSuccess?:string;error?:string;asOf?:string;releaseId?:string};
export type Manifest = {schemaVersion:number;generatedAt:string;groups:Record<string,GroupStatus>};
export type Bundle = {policy?:import('./policyData').PolicyBundle;fiscal:Fiscal;composition:Composition;debt:Debt;forecast:Forecast;curve:Curve;manifest:Manifest|null;loadWarnings?:string[]};

export async function loadBundle(previous?:Bundle):Promise<Bundle> {
  const loadWarnings:string[]=[];
  async function read<T>(name:string, fallback?:T):Promise<T> {
    try {
      const response=await fetch(`${import.meta.env.BASE_URL}data/${name}.json`,{cache:'no-store'});
      if(!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      const value=await response.json();
      if(value.schemaVersion!==1) throw new Error(`${name}: unsupported data format. Refresh the app and data together.`);
      return value as T;
    } catch(error) {if(fallback!==undefined){loadWarnings.push(`${name}: ${error instanceof Error?error.message:String(error)}`);return fallback;}throw error;}
  }
  const [fiscal,composition,debt,forecast,curve,manifest,outlook,reliefs,monitor]=await Promise.all([
    read<Fiscal>('fiscal'),read<Composition>('composition'),read<Debt>('debt'),
    read<Forecast>('forecast',previous?.forecast||{schemaVersion:1,status:'unavailable',sources:[],notes:['Forecast data could not be loaded.']}),
    read<Curve>('curve',previous?.curve||{schemaVersion:1,status:'unavailable',sources:[],curves:[],notes:['The official yield-curve download is not yet available in this snapshot.']}),
    read<Manifest|null>('manifest',previous?.manifest||null),
    read<import('./policyData').Outlook|null>('outlook',previous?.policy?.outlook||null),
    read<import('./policyData').Reliefs|null>('reliefs',previous?.policy?.reliefs||null),
    read<import('./policyData').Monitor|null>('monitor',previous?.policy?.monitor||null),
  ]);
  if(!fiscal.observations?.length || !composition.years?.length || !debt.securities?.length) throw new Error('The saved data are incomplete. Run the documented data refresh.');
  return {fiscal,composition,debt,forecast,curve,manifest,loadWarnings,policy:{outlook,reliefs,monitor}};
}

export type Mode='ytd'|'month'|'rolling';
export function fiscalStart(period:string):number {const [year,month]=period.split('-').map(Number);return year-(month<C.fyStartMonth?1:0);}
/** First month of a financial year, e.g. 2026-04 (UK) or 2026-07 (Australia). */
export function fyStartPeriod(year:number):string {return `${year}-${String(C.fyStartMonth).padStart(2,'0')}`;}
export function fyLabel(year:number):string {return C.id==='us'?`FY${year+1}`:`${year}–${String(year+1).slice(-2)}`;}
export function shiftMonth(period:string,delta:number):string {const [y,m]=period.split('-').map(Number);const d=new Date(Date.UTC(y,m-1+delta,1));return d.toISOString().slice(0,7);}
export function calendarAnniversary(date:string,years=1):string {const [y,m,d]=date.split('-').map(Number);const lastDay=new Date(Date.UTC(y+years,m,0)).getUTCDate();return `${y+years}-${String(m).padStart(2,'0')}-${String(Math.min(d,lastDay)).padStart(2,'0')}`;}
export function operationEnd(event:Operation):string {if(event.datePrecision?.startsWith('week')){const d=new Date(`${event.date}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+6);return d.toISOString().slice(0,10);}return event.date;}
export function periodsFor(end:string,mode:Mode):string[] {const count=mode==='month'?1:mode==='rolling'?12:((Number(end.slice(5))-C.fyStartMonth+12)%12)+1;return Array.from({length:count},(_,i)=>shiftMonth(end,i-count+1));}
export function total(rows:Observation[],key:string,end:string,mode:Mode):number|null {
  const index=new Map(rows.map(r=>[r.date,r]));let sum=0;
  for(const p of periodsFor(end,mode)){const v=index.get(p)?.[key];if(typeof v!=='number'||!Number.isFinite(v))return null;sum+=v;}
  return sum;
}
export function cumulative(rows:Observation[],year:number):Array<number|null> {return Array.from({length:12},(_,i)=>total(rows,'borrowing',shiftMonth(fyStartPeriod(year),i),'ytd'));}
export function fmt(value:number|null|undefined,digits=1):string {return value==null?'Not available':new Intl.NumberFormat('en-GB',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value);}
export function bn(value:number|null|undefined):string {return value==null?'Not available':`${value<0?'−':''}${C.currency}${fmt(Math.abs(value)/1000)}bn`;}
export function dateLabel(value:string,short=false):string {const match=/^\d{4}-\d{2}(?:-\d{2})?$/.test(value);if(!match)return value;return new Date(value.length===7?`${value}-01T12:00:00Z`:`${value}T12:00:00Z`).toLocaleDateString(C.locale,{...(value.length===10?{day:'numeric' as const}:{}),month:short?'short':'long',year:'numeric',timeZone:'UTC'});}
export function csvText(headers:string[],rows:(string|number|null|undefined)[][]):string {const quote=(v:unknown)=>{let s=v==null?'':String(v);if(typeof v==='string'&&/^[=+@\-\t\r]/.test(s))s="'"+s;return `"${s.replaceAll('"','""')}"`;};return [headers,...rows].map(r=>r.map(quote).join(',')).join('\r\n');}
export function downloadCsv(name:string,headers:string[],rows:(string|number|null|undefined)[][],metadata:string):void {
  const text=csvText([...headers,'Source / definitions'],rows.map(r=>[...r,metadata]));
  const url=URL.createObjectURL(new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`the-fiscal-space-${name}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function isOverdue(group:string,asOf:string,now=new Date()):boolean {
  if(!asOf)return true;
  if(group==='composition'){return now.getUTCFullYear()>Number(asOf.slice(0,4))+2;}
  const end=new Date(asOf.length===7?`${asOf}-01T00:00:00Z`:`${asOf}T00:00:00Z`);
  if(Number.isNaN(end.getTime()))return true;
  if(C.id==='au'){
   // Finance publishes about six weeks after month end, so the next month is due by the 20th three months on; June appears only in the Final Budget Outcome and July arrives with August. The RBA zero-coupon curve is monthly.
   if(group==='fiscal'){const months=end.getUTCMonth()===5?4:3;end.setUTCMonth(end.getUTCMonth()+months);end.setUTCDate(20);return now>end;}
   if(group==='curve'){end.setUTCDate(end.getUTCDate()+45);return now>end;}
  }
  // The US debt stock is the month-end Monthly Statement of the Public Debt, published about four business days after the following month ends.
  if(C.id==='us'&&group==='debt'){end.setUTCDate(end.getUTCDate()+45);return now>end;}
  if(group==='fiscal'){end.setUTCMonth(end.getUTCMonth()+2);end.setUTCDate(23);return now>end;}
  // A five-weekday tolerance accommodates next-business-day publication and most bank holidays.
  let weekdays=0;for(let d=new Date(end);d<now;d.setUTCDate(d.getUTCDate()+1)){if(d.getUTCDay()!==0&&d.getUTCDay()!==6)weekdays++;if(weekdays>5)return true;}return false;
}

export function gdpAt(gdp:Gdp|undefined,end:string,maxLagMonths=2){
 const row=gdp?.observations.filter(r=>r.date<=end).sort((a,b)=>a.date.localeCompare(b.date)).at(-1);
 if(!row||row.date<shiftMonth(end,-maxLagMonths)||typeof row.rollingAnnualMillion!=='number'||!Number.isFinite(row.rollingAnnualMillion)||row.rollingAnnualMillion<=0)return null;
 return row;
}
/** Disclosure when the GDP denominator at `end` includes OBR-forecast quarters ONS has not yet published. */
export function gdpForecastNote(gdp:Gdp|undefined,end:string){const quarters=gdpAt(gdp,end)?.forecastQuarters;return quarters?.length?`GDP for ${quarters.map(q=>q.replace('Q',' Q')).join(' and ')} is not yet published, so GDP uses the ${local('ONS','ABS','BEA')} figure a year earlier grown in line with the ${C.forecaster} ${local('forecast','forecast','projection')}${gdp?.forecastExtension?.vintage?` (${gdp.forecastExtension.vintage})`:''}.`:null;}
export function flowValue(value:number|null,end:string,units:string,gdp?:Gdp):number|null {
 if(value==null)return null;
 if(units!=='gdp')return value/1000;
 const denominator=gdpAt(gdp,end);return denominator?value/denominator.rollingAnnualMillion!*100:null;
}

/** Last available observation on or before the previous calendar anniversary. */
export function annualComparisonDate(dates:string[],observation:string):string {
 const sorted=[...dates].sort();
 const anniversary=calendarAnniversary(observation,-1);
 return sorted.filter(date=>date<=anniversary).at(-1)||sorted[0]||'';
}
