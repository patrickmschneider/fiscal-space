import {gdpAt,total,type Bundle,type Source} from './data';
export type OutlookRow={structuralPrimaryBalanceBn?:number|null;deficitInterestBn?:number|null;structuralBorrowingBn?:number|null;structuralBorrowingPct?:number|null;outputGapPct?:number|null;year:string;borrowingPct:number|null;borrowingBn:number|null;debtPct:number|null;receiptsBn:number|null;spendingBn:number|null;interestBn:number|null;primaryBalancePct:number|null;structuralPrimaryBalancePct:number|null;realGdpGrowth:number|null;nominalGdpGrowth:number|null;inflation:number|null;earningsGrowth:number|null;bankRate:number|null;giltYield:number|null;gdpBn:number|null;investmentBn?:number|null;netInvestmentBn?:number|null;gdpDeflatorGrowth?:number|null;[key:string]:string|number|null|undefined};
export type FiscalRule={name:string;description:string;definition:string;targetYear:string|null;assessmentDate?:string|null;notes?:string;headroomBn:number|null;met:boolean|null;binding?:boolean;sourceUrl:string;assessmentNote?:string};
export type Vintage={id:string;label:string;publicationDate:string;forecastStart:string;rows:OutlookRow[];rules:FiscalRule[];notes?:string[];sources?:Source[]};
export type Outlook={schemaVersion:number;asOf:string;sources:Source[];notes:string[];vintages:Vintage[];history?:OutlookRow[];deficitHistory?:OutlookRow[];deficitHistoryMetadata?:{source:Source;outturnAsOf:string;note:string};rules?:FiscalRule[];currentBudgetUpdate?:{year:string;surplusBn:number;publicationDate:string;sourceUrl:string;note:string};headroomHistory?:{label:string;headroomBn:number;targetYear:string;sourceUrl:string}[];sensitivities?:{id:string;label:string;borrowingChangeBn:number;targetYear:string;vintage:string;sourceUrl:string;note:string}[]};
export type ReliefEstimate={year:string;costMillion:number|null;status:string;claimants:number|null;isForecast?:boolean;claimantStatus?:string};
export type Relief={id:string;aggregationRole?:'component'|'standalone';description?:string;estimateType?:string;retrievalDate?:string;name:string;taxHead:string;classification:string;objective:string|null;notes:string|null;quality:string|null;sourceUrl:string;publicationVintage:string;estimates:ReliefEstimate[]};
export type Reliefs={schemaVersion:number;asOf:string;sources:Source[];notes:string[];aggregate:{year:string;costMillion:number|null;label:string;source?:string};reliefs:Relief[];isa?:{publicationVintage:string;publicationUrl:string;sourceUrl:string;distributionYear:string;history:{year:string;component:string;accountsThousand:number|null;subscriptionsMillion:number|null}[];marketValues:{year:string;component:string;marketValueMillion:number|null}[];byIncome:{group:string;holdersThousand:number|null;averageMarketValuePounds:number|null}[];byAgeSex:{group:string;holdersThousand:number|null;averageMarketValuePounds:number|null}[];commentary:{sourceUrl:string;whyChanged:string;distribution:string};notes:string[]};pensions?:{publicationVintage:string;sourceUrl:string;notes:string[];history:Record<string,string|number|null>[];distribution:Record<string,string|number|null>[]}};
export type MonitorEvent={date:string;event:string;category:string;description:string;likelyFiscalChannel?:string;likely_fiscal_channel?:string;source:string;costing?:string};
export type Monitor={schemaVersion:number;asOf:string;events:MonitorEvent[];calendar:MonitorEvent[];notes:string[];undatedWatch?:{event:string;description:string;source:string}[];channelNote?:string};
export type PolicyBundle={outlook:Outlook|null;reliefs:Reliefs|null;monitor:Monitor|null};
export function latestVintage(outlook:Outlook|null){return outlook?.vintages.slice().sort((a,b)=>a.publicationDate.localeCompare(b.publicationDate)).at(-1);}
export function yearEnd(year:string){return `${Number(year.slice(0,4))+1}-03`;}
export function annualPosition(bundle:Bundle){const end=bundle.fiscal.observations.filter(r=>r.date.endsWith('-03')).at(-1)?.date;if(!end)return null;const amount=(key:string)=>total(bundle.fiscal.observations,key,end,'ytd');const receipts=amount('receipts'),spending=amount('spending'),interest=amount('interest'),borrowing=amount('borrowing');if(receipts==null||spending==null||interest==null||borrowing==null)return null;const gdp=gdpAt(bundle.fiscal.gdp,end)?.rollingAnnualMillion;return {end,year:`${Number(end.slice(0,4))-1}–${end.slice(2,4)}`,receipts,spending,interest,borrowing,primary:spending-interest,gdp:gdp||null};}
export function impulse(current:number|null|undefined,previous:number|null|undefined){return current==null||previous==null?null:previous-current;}
export function borrowingSurprise(actual:number|null,profile:number|null){return actual==null||profile==null?null:actual-profile;}
export function forecastBridge(start:OutlookRow,end:OutlookRow){const keys=['borrowingBn','receiptsBn','spendingBn','interestBn','investmentBn'] as const;if(keys.some(k=>start[k]==null||end[k]==null))return null;const receipts=-(end.receiptsBn!-start.receiptsBn!),interest=end.interestBn!-start.interestBn!,investment=end.investmentBn!-start.investmentBn!;const primaryCurrent=(end.spendingBn!-end.interestBn!-end.investmentBn!)-(start.spendingBn!-start.interestBn!-start.investmentBn!);return {receipts,interest,investment,primaryCurrent,residual:(end.borrowingBn!-start.borrowingBn!)-receipts-interest-investment-primaryCurrent};}
export function reliefValue(estimate:ReliefEstimate|undefined,units:string,gdpMillion:number|null|undefined){if(estimate?.costMillion==null)return null;return units==='gdp'?(gdpMillion?estimate.costMillion/gdpMillion*100:null):estimate.costMillion/1000;}

export function profileOriginMonth(vintage:string|undefined):string|null {const months=['January','February','March','April','May','June','July','August','September','October','November','December'];const match=vintage?.match(/(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})/);return match?`${match[2]}-${String(months.indexOf(match[1])+1).padStart(2,'0')}`:null;}
export function canCompareProfilePeriod(period:string,vintage:string|undefined){const origin=profileOriginMonth(vintage);return origin!==null&&period>origin;}

/** Keep the selected forecast vintage's final outturn as its explicit baseline. */
export function forecastHistoryRows(history:OutlookRow[],vintage:Vintage,key:string){
 const start=Number(vintage.forecastStart.slice(0,4))-10;
 const values=new Map(history.filter(r=>Number(r.year.slice(0,4))>=start&&r.year<vintage.forecastStart).map(r=>[r.year,r]));
 for(const row of vintage.rows)values.set(row.year,row);
 const ordered=[...values.values()].sort((a,b)=>a.year.localeCompare(b.year));
 const baseline=ordered.filter(r=>r.year<vintage.forecastStart&&typeof r[key]==='number').at(-1)?.year;
 return ordered.map(r=>({label:r.year,actual:r.year<vintage.forecastStart&&typeof r[key]==='number'?r[key] as number:null,forecast:(r.year>=vintage.forecastStart||r.year===baseline)&&typeof r[key]==='number'?r[key] as number:null}));
}

/** Annual OBR anchors on a monthly axis; no invented monthly forecast values. */
export function overviewForecastRows(actual:Record<string,string|number|null>[],vintage:Vintage|null|undefined,units:string){
 const rows=new Map<string,Record<string,string|number|null>>(actual.map(r=>[String(r.label),{...r,spendingForecast:null as number|null,receiptsForecast:null as number|null,debtForecast:null as number|null,status:'Outturn'}]));
 if(!vintage||!actual.length)return [...rows.values()];
 const yearEnd=(year:string)=>`${Number(year.slice(0,4))+1}-03`;
 const end=yearEnd(vintage.rows.at(-1)!.year);
 let month=String(actual.at(-1)!.label);
 while(month<end){const [y,m]=month.split('-').map(Number);month=m===12?`${y+1}-01`:`${y}-${String(m+1).padStart(2,'0')}`;rows.set(month,{label:month,spending:null,receipts:null,debt:null,spendingForecast:null,receiptsForecast:null,debtForecast:null,status:'Forecast'});}
 for(const r of vintage.rows){
  const date=yearEnd(r.year);const row=rows.get(date);
  if(!row)continue;
  const flow=(key:string)=>typeof r[key]==='number'?(units==='bn'?r[key] as number:r.gdpBn?(r[key] as number)/r.gdpBn*100:null):null;
  row.spendingForecast=flow('spendingBn');row.receiptsForecast=flow('receiptsBn');
  row.debtForecast=typeof r[units==='bn'?'debtBn':'debtPct']==='number'?r[units==='bn'?'debtBn':'debtPct'] as number:null;
 }
 const baseline=vintage.rows.filter(r=>r.year<vintage.forecastStart).at(-1);
 for(const [date,row] of rows)if(baseline&&date>yearEnd(baseline.year))row.forecastPeriod=1;

 return [...rows.values()].sort((a,b)=>String(a.label).localeCompare(String(b.label)));
}
