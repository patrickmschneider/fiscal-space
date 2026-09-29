import {describe,expect,it} from 'vitest';
import {debtDynamics} from './DebtDynamics';

describe('debtDynamics',()=>{
 it('uses net interest over the previous year’s net debt and the textbook stabilising balance',()=>{
  const row=(year:string,debtPct:number,debtBn:number,interestBn:number)=>({year,debtPct,debtBn,interestBn,nominalGdpGrowth:3.6,primaryBalancePct:1.5,borrowingPct:null,borrowingBn:null,receiptsBn:null,spendingBn:null} as never);
  const d=debtDynamics([row('2029-30',95,3400,100),row('2030-31',94,3500,112)])!;const r=112/3400*100;
  expect(d.effectiveRate).toBeCloseTo(r);
  expect(d.stabilisingPrimaryPct).toBeCloseTo(.95*(r-3.6)/1.036);
  expect(d.year).toBe('2030-31');
 });
 it('needs two matched years',()=>{expect(debtDynamics([])).toBeUndefined();});
});
