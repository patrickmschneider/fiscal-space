// Headroom tracker: how far news since the latest OBR forecast has moved the margin against the
// stability rule, using only the OBR's own published ready-reckoners. An indicative estimate, not
// an OBR forecast. Also: debt dynamics from the forecast's own matched rows (r, g, primary balance).
import {total,type Bundle,type CurveObservation,type Gdp} from './data';
import {latestVintage,type OutlookRow} from './policyData';

export type Contribution={id:'rates'|'growth'|'inyear'|'policy';label:string;bn:number|null;counted:boolean;detail:string;sourceUrl?:string;measure?:number};
export type DebtDynamics={year:string;prevYear:string;debtPct:number;prevDebtPct:number;effectiveRate:number;nominalGrowth:number;stabilisingPrimaryPct:number;primaryBalancePct:number;gap:number;direction:'falling'|'stable'|'rising'};
export type Verdict='Rules at risk'|'Headroom thin'|'Headroom eroding'|'On track'|'Room for manoeuvre';
export type Tracker={baseline:{bn:number;label:string;date:string;year:string;sourceUrl:string};formal?:{bn:number;date:string;sourceUrl:string};items:Contribution[];estimateBn:number;changeBn:number;verdict:Verdict;tone:'erode'|'neutral'|'add';driver?:Contribution;debt?:DebtDynamics;marketDate?:string};

const day=(d:string)=>new Date(`${d.length===7?`${d}-15`:d}T12:00:00Z`).toLocaleDateString('en-GB',d.length===7?{month:'long',year:'numeric',timeZone:'UTC'}:{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
const SIGNIFICANT=5;  // £bn: a change this large counts as eroding or adding room
const THIN=10;        // £bn: below this the margin is thin (the OBR's rates sensitivity is £15bn per 1pp)

export function curveMean(obs:CurveObservation,minTenor=1,maxTenor=20):number|null{
 const rates=obs.points.filter(p=>p.tenor>=minTenor&&p.tenor<=maxTenor&&typeof p.rate==='number'&&Number.isFinite(p.rate)).map(p=>p.rate as number);
 return rates.length?rates.reduce((a,b)=>a+b,0)/rates.length:null;
}

/** Change in the average 1–20-year gilt spot rate since the OBR's conditioning window, and its effect on headroom. */
export function ratesContribution(curves:CurveObservation[],window:{end:string;workingDays:number},perPpBn:number):{changePp:number;bn:number;from:string;to:string;latest:string}|null{
 const base=curves.filter(c=>c.date<=window.end).slice(-window.workingDays);const latest=curves.at(-1);
 if(base.length<window.workingDays||!latest||latest.date<=window.end)return null;
 const means=base.map(c=>curveMean(c)).filter((x):x is number=>x!=null);const now=curveMean(latest);
 if(means.length<window.workingDays||now==null)return null;
 const changePp=now-means.reduce((a,b)=>a+b,0)/means.length;
 return {changePp,bn:-perPpBn*changePp,from:base[0].date,to:base.at(-1)!.date,latest:latest.date};
}

/** Latest four-quarter nominal GDP against the OBR's fiscal-year path for the same four quarters (% gap). */
export function nominalGdpGap(gdp:Gdp|undefined,rows:OutlookRow[]):{gapPct:number;end:string}|null{
 const latest=gdp?.observations.filter(r=>typeof r.rollingAnnualMillion==='number'&&r.rollingAnnualMillion>0).at(-1);if(!latest)return null;
 const [y,m]=latest.date.split('-').map(Number);const fyStart=m>=4?y:y-1;const label=(s:number)=>`${s}-${String(s+1).slice(-2)}`;
 const quartersInCurrentFy=Math.floor(((m-4+12)%12)/3)+1;   // quarters of the latest four that fall in the fiscal year containing the end month
 const cur=rows.find(r=>r.year===label(fyStart))?.gdpBn,prev=rows.find(r=>r.year===label(fyStart-1))?.gdpBn;
 if(cur==null||prev==null)return null;
 const implied=(quartersInCurrentFy*cur+(4-quartersInCurrentFy)*prev)/4;
 return {gapPct:((latest.rollingAnnualMillion as number)/1000/implied-1)*100,end:latest.date};
}

/** Cumulative borrowing this fiscal year against the OBR monthly profile (£bn, positive = above profile). */
export function inYearSurprise(bundle:Bundle):{bn:number;period:string;vintage:string}|null{
 const p=bundle.forecast;if(p.status!=='available'||!p.cumulative?.length||!p.vintage)return null;
 const last=p.cumulative.filter(r=>r.period<=bundle.fiscal.asOf&&total(bundle.fiscal.observations,'borrowing',r.period,'ytd')!=null).at(-1);
 if(!last)return null;
 return {bn:(total(bundle.fiscal.observations,'borrowing',last.period,'ytd') as number)/1000-last.value,period:last.period,vintage:p.vintage};
}

/** Debt dynamics in a forecast year from the same vintage's rows: s* = d·(r − g)/(1 + g). */
export function debtDynamics(rows:OutlookRow[],year?:string):DebtDynamics|undefined{
 const forecast=rows.filter(r=>r.debtPct!=null&&r.interestBn!=null&&r.nominalGdpGrowth!=null&&r.primaryBalancePct!=null&&(r as OutlookRow&{debtBn?:number}).debtBn!=null);
 const i=year?forecast.findIndex(r=>r.year===year):forecast.length-1;if(i<1)return undefined;
 const cur=forecast[i] as OutlookRow&{debtBn:number},prev=forecast[i-1] as OutlookRow&{debtBn:number};
 const d=(prev.debtPct as number)/100,r=(cur.interestBn as number)/prev.debtBn*100,g=cur.nominalGdpGrowth as number;
 const s=d*(r-g)/(1+g/100),gap=(cur.primaryBalancePct as number)-s;
 return {year:cur.year,prevYear:prev.year,debtPct:cur.debtPct as number,prevDebtPct:prev.debtPct as number,effectiveRate:r,nominalGrowth:g,stabilisingPrimaryPct:s,primaryBalancePct:cur.primaryBalancePct as number,gap,direction:gap>0.25?'falling':gap<-0.25?'rising':'stable'};
}

export function verdictFor(estimateBn:number,changeBn:number):{verdict:Verdict;tone:Tracker['tone']}{
 if(estimateBn<=0)return {verdict:'Rules at risk',tone:'erode'};
 if(estimateBn<THIN)return {verdict:'Headroom thin',tone:'erode'};
 if(changeBn<=-SIGNIFICANT)return {verdict:'Headroom eroding',tone:'erode'};
 if(changeBn>=SIGNIFICANT)return {verdict:'Room for manoeuvre',tone:'add'};
 return {verdict:'On track',tone:'neutral'};
}

export function buildTracker(bundle:Bundle):Tracker|null{
 const outlook=bundle.policy?.outlook;const vintage=latestVintage(outlook||null);const update=outlook?.currentBudgetUpdate;
 if(!outlook||!vintage||!update)return null;
 const sens=Object.fromEntries((outlook.sensitivities||[]).map(s=>[s.id,s]));const window=outlook.marketConditioning;
 const items:Contribution[]=[];
 const rates=window&&sens.rates?ratesContribution(bundle.curve.curves||[],window,sens.rates.borrowingChangeBn):null;
 if(rates)items.push({id:'rates',label:'Gilt yields since the forecast',bn:rates.bn,counted:true,sourceUrl:sens.rates.sourceUrl,measure:rates.changePp,
  detail:`The average 1–20-year gilt yield is ${Math.abs(rates.changePp).toFixed(2)}pp ${rates.changePp>=0?'higher':'lower'} on ${day(rates.latest)} than over the OBR’s window (${day(rates.from)} to ${day(rates.to)}). OBR ready-reckoner: £${sens.rates.borrowingChangeBn}bn of borrowing per 1pp on Bank Rate and gilt yields.`});
 const growth=sens['nominal-growth']?nominalGdpGap(bundle.fiscal.gdp,vintage.rows):null;
 if(growth){const perPct=sens['nominal-growth'].borrowingChangeBn/0.5;items.push({id:'growth',label:'Nominal GDP against the forecast',bn:perPct*growth.gapPct,counted:false,sourceUrl:sens['nominal-growth'].sourceUrl,
  detail:`Four-quarter nominal GDP to ${day(growth.end)} is ${Math.abs(growth.gapPct).toFixed(1)}% ${growth.gapPct>=0?'above':'below'} the OBR path, worth about £${Math.abs(perPct*growth.gapPct).toFixed(0)}bn on the OBR’s growth ready-reckoner (£${sens['nominal-growth'].borrowingChangeBn}bn for 0.1pp a year over five years). Not counted: part is data revisions, and higher inflation also raises RPI-linked debt interest.`});}
 const inyear=inYearSurprise(bundle);
 if(inyear)items.push({id:'inyear',label:'Borrowing so far this year',bn:-inyear.bn,counted:false,
  detail:`Borrowing to ${day(inyear.period)} is £${Math.abs(inyear.bn).toFixed(1)}bn ${inyear.bn>=0?'above':'below'} the OBR’s ${inyear.vintage} monthly profile. Not counted: in-year surprises say little on their own about the target year.`});
 const ledger=bundle.policy?.monitor?.policyLedger||[];const uncosted=ledger.filter(x=>x.fiscal_cost==null);
 if(uncosted.length)items.push({id:'policy',label:'Announced, not yet costed',bn:null,counted:false,detail:`${uncosted.length} announcement${uncosted.length>1?'s':''} since the forecast without an OBR costing: ${uncosted.map(x=>x.measure).join('; ')}.`});
 const changeBn=items.filter(i=>i.counted&&i.bn!=null).reduce((a,i)=>a+(i.bn as number),0);
 const estimateBn=update.surplusBn+changeBn;const {verdict,tone}=verdictFor(estimateBn,changeBn);
 const counted=items.filter(i=>i.counted&&i.bn!=null).sort((a,b)=>Math.abs(b.bn as number)-Math.abs(a.bn as number));
 const stability=(outlook.rules||[]).find(r=>/stability/i.test(r.name)&&r.headroomBn!=null);
 return {baseline:{bn:update.surplusBn,label:`${vintage.label} forecast`,date:update.publicationDate,year:update.year,sourceUrl:update.sourceUrl},
  formal:stability?{bn:stability.headroomBn as number,date:stability.assessmentDate||'',sourceUrl:stability.sourceUrl}:undefined,
  items,estimateBn,changeBn,verdict,tone,driver:counted[0],debt:debtDynamics(vintage.rows),marketDate:rates?.latest};
}
