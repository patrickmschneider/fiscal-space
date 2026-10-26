import {describe,it,expect} from 'vitest';
import {axisTicks,yearTicks,forecastLabelPosition,publicationBoundary} from './chartPlacement';
it('puts labels opposite high or low forecast data',()=>{
 expect(forecastLabelPosition([{v:20,status:'Outturn'},{v:95,status:'Forecast'}],['v'])).toBe('insideBottom');
 expect(forecastLabelPosition([{v:95,status:'Outturn'},{v:20,status:'Forecast'}],['v'])).toBe('insideTop');
});
it('accounts for both ends of signed stacks and avoids a crowded plot',()=>{
 const rows=[{a:8,b:-2,total:6,status:'Forecast'}];
 expect(forecastLabelPosition(rows,['a','b'],true,'total',[-3,9])).toBe('top');
 expect(forecastLabelPosition(rows,['a','b'],true,'total',[-3,20])).toBe('insideTop');
});

it('places publication between monthly or annual period ends',()=>{
 const monthly=publicationBoundary(['2026-02','2026-03','2026-04'],'2026-03-03');expect(monthly?.index).toBe(0);expect(monthly?.fraction).toBeCloseTo(3/31);
 const annual=publicationBoundary(['2024-25','2025-26','2026-27'],'2026-03-03',true);expect(annual?.index).toBe(0);expect(annual?.fraction).toBeCloseTo(337/365);
 expect(publicationBoundary(['2026-02'],'2026-03-03')).toBeNull();
});

describe('axis ticks',()=>{
 it('rounds a narrow range to exact, evenly spaced ticks',()=>{const a=axisTicks([2.27,2.46])!;expect(a.ticks).toEqual([2,2.2,2.4,2.6,2.8]);expect(a.domain).toEqual([2,2.8]);expect(a.digits).toBe(1);});
 it('gives each step enough decimals to label it exactly',()=>{expect(axisTicks([0.1,0.2],0.01)!.digits).toBe(2);expect(axisTicks([0,9],0)!.ticks).toEqual([0,2.5,5,7.5,10]);expect(axisTicks([0,9],0)!.digits).toBe(1);});
 it('keeps wide ranges on whole numbers',()=>{const a=axisTicks([90,101])!;expect(a.ticks).toEqual([85,90,95,100,105]);expect(a.digits).toBe(0);});
 it('returns null without data',()=>{expect(axisTicks([])).toBeNull();});
});

describe('maturity axis',()=>{
 it('labels whole years only',()=>{expect(yearTicks([1/12,0.5,2,10,30])!.ticks).toEqual([0,5,10,15,20,25,30]);expect(yearTicks([0.5,2.5,40])!.ticks).toEqual([0,5,10,15,20,25,30,35,40]);expect(yearTicks([5,7,10])!.ticks).toEqual([0,2,4,6,8,10]);expect(yearTicks([0.25,0.5])!.ticks).toEqual([0,1]);});
});
