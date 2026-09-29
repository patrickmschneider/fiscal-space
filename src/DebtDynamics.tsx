import {fmt} from './data';
import type {OutlookRow,Vintage} from './policyData';

export type DebtDynamics={year:string;prevYear:string;debtPct:number;prevDebtPct:number;effectiveRate:number;nominalGrowth:number;stabilisingPrimaryPct:number;primaryBalancePct:number};
type Row=OutlookRow&{debtBn?:number|null};
const pp=(x:number,digits=1)=>`${x<0?'−':''}${fmt(Math.abs(x),digits)}`;

/** Debt arithmetic for one forecast year from a single vintage: s* = d·(r − g)/(1 + g), r = net interest ÷ previous net debt. */
export function debtDynamics(rows:Row[],year?:string):DebtDynamics|undefined{
 const usable=rows.filter(r=>r.debtPct!=null&&r.interestBn!=null&&r.nominalGdpGrowth!=null&&r.primaryBalancePct!=null&&r.debtBn!=null);
 const i=year?usable.findIndex(r=>r.year===year):usable.length-1;if(i<1)return undefined;
 const cur=usable[i],prev=usable[i-1];
 const d=prev.debtPct!/100,r=cur.interestBn!/prev.debtBn!*100,g=cur.nominalGdpGrowth!;
 return {year:cur.year,prevYear:prev.year,debtPct:cur.debtPct!,prevDebtPct:prev.debtPct!,effectiveRate:r,nominalGrowth:g,stabilisingPrimaryPct:d*(r-g)/(1+g/100),primaryBalancePct:cur.primaryBalancePct!};
}

export function DebtDynamicsTable({vintage}:{vintage:Vintage}){
 const d=debtDynamics(vintage.rows);if(!d)return <p className="small">This forecast does not supply net debt, interest, nominal growth and the primary balance on a matched basis.</p>;
 const rows:[string,string,string][]=[
  ['Net debt, % of GDP',`${fmt(d.prevDebtPct)} → ${fmt(d.debtPct)}`,`${d.prevYear} → ${d.year}`],
  ['Effective interest rate on debt (r)',`${fmt(d.effectiveRate,2)}%`,`Net debt interest in ${d.year} ÷ net debt at end-${d.prevYear}`],
  ['Nominal GDP growth (g)',`${fmt(d.nominalGrowth)}%`,`OBR forecast for ${d.year}`],
  ['Debt-stabilising primary balance',`${pp(d.stabilisingPrimaryPct,2)}% of GDP`,'Debt ratio × (r − g) ÷ (1 + g)'],
  ['Forecast primary balance',`${pp(d.primaryBalancePct)}% of GDP`,'Borrowing excluding net interest, sign reversed'],
 ];
 return <><p className="small">Debt falls as a share of GDP when the primary balance exceeds the level that holds it steady; that level rises with the gap between the interest rate on debt and nominal growth. All figures come from the {vintage.label} forecast, so definitions match. The effective rate responds to gilt yields only gradually, as debt is refinanced.</p>
  <div className="table-wrap" role="region" aria-label="Debt dynamics" tabIndex={0}><table><thead><tr><th scope="col">{vintage.label}</th><th scope="col" className="num">Value</th><th scope="col">Basis</th></tr></thead>
   <tbody>{rows.map(([a,b,c])=><tr key={a}><th scope="row">{a}</th><td className="num">{b}</td><td>{c}</td></tr>)}</tbody></table></div></>;
}
