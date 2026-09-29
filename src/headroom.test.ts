import {describe,it,expect} from 'vitest';
import {curveMean,ratesContribution,nominalGdpGap,debtDynamics,verdictFor} from './headroom';
import type {OutlookRow} from './policyData';

const curve=(date:string,rate:number)=>({date,points:[0.5,1,5,10,20,25].map(tenor=>({tenor,rate:tenor<1||tenor>20?99:rate}))});
const row=(year:string,o:Partial<OutlookRow>&{debtBn?:number})=>({year,borrowingPct:null,borrowingBn:null,debtPct:null,receiptsBn:null,spendingBn:null,interestBn:null,primaryBalancePct:null,structuralPrimaryBalancePct:null,realGdpGrowth:null,nominalGdpGrowth:null,inflation:null,earningsGrowth:null,bankRate:null,giltYield:null,gdpBn:null,...o}) as OutlookRow;

describe('headroom tracker',()=>{
 it('averages 1–20-year spot rates only',()=>{expect(curveMean(curve('2026-01-01',4))).toBe(4);});
 it('prices the change in yields since the OBR window with its ready-reckoner',()=>{
  const days=Array.from({length:12},(_,i)=>curve(`2026-01-${String(19+i).padStart(2,'0')}`,4.5));
  const r=ratesContribution([...days,curve('2026-09-25',5.3)],{end:'2026-01-30',workingDays:10},15)!;
  expect(r.changePp).toBeCloseTo(0.8);expect(r.bn).toBeCloseTo(-12);expect([r.from,r.to]).toEqual(['2026-01-21','2026-01-30']);
  expect(ratesContribution(days.slice(0,5),{end:'2026-01-30',workingDays:10},15)).toBeNull();   // window incomplete
 });
 it('compares four-quarter GDP with the OBR path for the same quarters',()=>{
  const rows=[row('2025-26',{gdpBn:3000}),row('2026-27',{gdpBn:3100})];
  const g=nominalGdpGap({basis:'',sources:[],observations:[{date:'2026-06',rollingAnnualMillion:3050_000}]},rows)!;
  expect(g.gapPct).toBeCloseTo((3050/(0.75*3000+0.25*3100)-1)*100);   // one quarter of the four falls in 2026-27
 });
 it('derives the debt-stabilising primary balance from matched forecast rows',()=>{
  const rows=[row('2029-30',{debtPct:96,debtBn:3400,interestBn:110,nominalGdpGrowth:3.5,primaryBalancePct:1.4}),row('2030-31',{debtPct:95,debtBn:3500,interestBn:112,nominalGdpGrowth:3.6,primaryBalancePct:1.5})];
  const d=debtDynamics(rows)!;const r=112/3400*100;
  expect(d.effectiveRate).toBeCloseTo(r);expect(d.stabilisingPrimaryPct).toBeCloseTo(0.96*(r-3.6)/1.036);expect(d.direction).toBe('falling');
 });
 it('grades the verdict by level and change',()=>{
  expect(verdictFor(-1,-20).verdict).toBe('Rules at risk');expect(verdictFor(8,0).verdict).toBe('Headroom thin');
  expect(verdictFor(12,-12).verdict).toBe('Headroom eroding');expect(verdictFor(30,8).verdict).toBe('Room for manoeuvre');
  expect(verdictFor(22,-1).verdict).toBe('On track');
 });
});
