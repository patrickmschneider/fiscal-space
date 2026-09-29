import {describe,expect,it} from 'vitest';
import {waterfallSteps} from './OverviewComposition';

describe('waterfallSteps',()=>{
 it('runs from the start total through each change to the end total, grouping small categories',()=>{
  const rows=[...Array.from({length:9},(_,i)=>({name:`c${i}`,value:i%2?-(i+1)/10:(i+1)/10})),{name:'Unallocated / rounding difference',value:0.05}];
  const s=waterfallSteps(rows,40,'2019-20','2025-26');
  expect(s[0]).toEqual({name:'2019-20 total',kind:'level',from:0,to:40});
  expect(s).toHaveLength(1+7+1+1+1);
  expect(s.find(x=>x.name==='Other categories (2)')!.to-s.find(x=>x.name==='Other categories (2)')!.from).toBeCloseTo(0.1+-0.2);
  const total=40+rows.reduce((a,r)=>a+r.value,0);
  expect(s.at(-1)!.to).toBeCloseTo(total);
  for(let i=2;i<s.length-1;i++)expect(s[i].from).toBeCloseTo(s[i-1].to);
 });
 it('returns nothing without a start total',()=>{expect(waterfallSteps([{name:'a',value:1}],null,'a','b')).toEqual([]);});
});
