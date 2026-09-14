import {describe,it,expect} from 'vitest';
import {socialProtectionItems,separateDebtTransactions,annualBudgets,exactAnnualGdp,budgetValue,budgetComparison} from './budgetMath';
import type {Fiscal} from './data';
const fixture=()=>({schemaVersion:1,asOf:'2020-03',releaseDate:'2026-08-21',nextRelease:'',scope:'test',basis:'test',sources:[],series:{},notes:[],observations:Array.from({length:12},(_,i)=>({date:i<9?`2019-${String(i+4).padStart(2,'0')}`:`2020-${String(i-8).padStart(2,'0')}`,spending:100,receipts:90,goodsServices:40,benefits:20,interest:5,netInvestment:10,depreciation:5,incomeTax:30,nic:20,vat:20,corporationTax:10,councilTax:5})),gdp:{basis:'test',sources:[],observations:[{date:'2020-03',rollingAnnualMillion:2400}]}} as Fiscal);
describe('annual budget decomposition',()=>{
 it('uses full financial years and preserves the expenditure identity',()=>{const [year]=annualBudgets(fixture(),'economic');expect(year.year).toBe('2019-20');expect(year.totalPctGdp).toBe(50);expect(year.items.reduce((s,x)=>s+x.value,0)).toBe(year.total);expect(year.items.at(-1)?.value).toBe(240);});
 it('does not turn a partial year or missing category into a full annual budget',()=>{const fiscal=fixture();fiscal.observations.splice(3,1);expect(annualBudgets(fiscal,'economic')).toEqual([]);const other=fixture();other.observations[0].benefits=null;expect(annualBudgets(other,'economic')).toEqual([]);});
 it('reconciles revenue without mislabelling the residual as only non-tax income',()=>{const [year]=annualBudgets(fixture(),'receipts');expect(year.items.at(-1)?.name).toBe('Other receipts & accounting differences');expect(year.items.reduce((s,x)=>s+x.value,0)).toBe(1080);});
 it('distinguishes GDP shares from shares of spending and handles missing GDP',()=>{expect(budgetValue(100,4,400,'gdp')).toBe(4);expect(budgetValue(100,4,400,'share')).toBe(25);expect(budgetValue(100,null,400,'gdp')).toBeNull();});
});

describe('two-year composition accounting',()=>{
 it('reconciles GDP, cash and named-total changes on their own denominators',()=>{
  const first=annualBudgets(fixture(),'economic')[0];
  const last={...first,year:'2020-21',total:1500,totalPctGdp:60,items:first.items.map((x,i)=>({...x,value:x.value+(i===0?300:0),pctGdp:(x.value+(i===0?300:0))/2500*100}))};
  for(const units of ['gdp','bn','share']){const c=budgetComparison(first,last,units);expect(c.residual).toBeCloseTo(0);expect(c.rows.reduce((s,r)=>s+r.change!,0)).toBeCloseTo(c.change!);}
  expect(budgetComparison(first,last,'gdp').change).toBe(10);
  expect(budgetComparison(first,last,'bn').change).toBeCloseTo(.3);
  expect(budgetComparison(first,last,'share').change).toBe(0);
 });
 it('reports rounding differences and refuses to reconcile missing categories',()=>{
  const first=annualBudgets(fixture(),'economic')[0];
  const last={...first,items:first.items.map((x,i)=>({...x,pctGdp:x.pctGdp!+(i===0?.1:0)}))};
  expect(budgetComparison(first,last,'gdp').residual).toBeCloseTo(-.1);
  const missing={...last,items:last.items.slice(1)};
  expect(budgetComparison(first,missing,'gdp').rows.find(r=>r.name===first.items[0].name)?.change).toBeNull();
  expect(budgetComparison(first,missing,'gdp').residual).toBeNull();
 });
});

 it('requires exact March GDP instead of carrying January or February into annual comparisons',()=>{
  for(const date of ['2020-01','2020-02']){const fiscal=fixture();fiscal.gdp!.observations[0].date=date;const [year]=annualBudgets(fiscal,'economic');expect(year.total).toBe(1200);expect(year.totalPctGdp).toBeNull();expect(year.items.every(i=>i.pctGdp===null)).toBe(true);expect(exactAnnualGdp(fiscal,'2020-03')).toBeNull();}
  expect(exactAnnualGdp(fixture(),'2020-03')).toBe(2400);
 });

it('separates debt transactions and reconciles cash and GDP without double counting',()=>{
 const original={year:'2025-26',total:200000,totalPctGdp:7,debtInterest:130300,debtInterestPctGdp:4.2,items:[{name:'General public services',value:165500,pctGdp:5.4},{name:'Other',value:34500,pctGdp:1.6}]};
 const split=separateDebtTransactions(original);
 expect(split.items.map(i=>i.name)).toEqual(['Public debt transactions','Other general public services','Other']);
 expect(split.items[1].value).toBe(35200);expect(split.items[1].pctGdp).toBeCloseTo(1.2);
 expect(split.items.reduce((s,i)=>s+i.value,0)).toBe(original.total);expect(split.items.reduce((s,i)=>s+i.pctGdp!,0)).toBeCloseTo(original.totalPctGdp);
 expect(original.items).toHaveLength(2);expect(separateDebtTransactions({...original,debtInterest:undefined}).items).toHaveLength(2);
});

it('retains historical pension cash and reconciles revisions in both cash and GDP',()=>{
 const detail={total:150,items:[{name:'Pensions',value:60},{name:'Other',value:70},{name:'Services',value:20}]};
 const parent={year:'2003-04',total:500,totalPctGdp:40,items:[{name:'Social protection',value:160,pctGdp:12}]};
 const items=socialProtectionItems(detail,parent);expect(items[0].value).toBe(60);expect(items.at(-1)?.value).toBe(10);expect(items.reduce((s,i)=>s+i.value,0)).toBe(160);expect(items.reduce((s,i)=>s+i.pctGdp!,0)).toBe(12);
});
