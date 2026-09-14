import {it,expect} from 'vitest';
import {forecastLabelPosition,publicationBoundary} from './chartPlacement';
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
