import {describe,it,expect} from 'vitest';
import {annualComparisonDate,gdpAt,gdpForecastNote,flowValue,fiscalStart,periodsFor,total,cumulative,csvText,calendarAnniversary,operationEnd,isOverdue,type Observation} from './data';
describe('fiscal accounting boundaries',()=>{
 it('uses April financial years',()=>{expect(fiscalStart('2026-03')).toBe(2025);expect(fiscalStart('2026-04')).toBe(2026);expect(periodsFor('2026-03','ytd')).toHaveLength(12);expect(periodsFor('2026-04','ytd')).toEqual(['2026-04']);});
 it('requires every month, including explicit nulls',()=>{const rows:Observation[]=[{date:'2026-04',borrowing:4},{date:'2026-06',borrowing:3}];expect(total(rows,'borrowing','2026-06','ytd')).toBeNull();expect(total(rows,'borrowing','2026-04','rolling')).toBeNull();expect(total([{date:'2026-04',borrowing:null}],'borrowing','2026-04','month')).toBeNull();});
 it('retains surplus signs and leaves future cumulative values missing',()=>{const rows=[{date:'2026-04',borrowing:4},{date:'2026-05',borrowing:-6}];expect(cumulative(rows,2026).slice(0,3)).toEqual([4,-2,null]);});
 it('quotes CSV and neutralises text formulas without corrupting negative numbers',()=>{const result=csvText(['name','value'],[['=BAD',-3],['a,"b',null]]);expect(result).toContain("\"'=BAD\",\"-3\"");expect(result).toContain('"a,""b"');});
 it('uses a calendar anniversary including leap day',()=>{expect(calendarAnniversary('2026-09-06')).toBe('2027-09-06');expect(calendarAnniversary('2024-02-29')).toBe('2025-02-28');});
 it('keeps a syndication window open during its week',()=>{expect(operationEnd({date:'2026-09-07',datePrecision:'week',type:'syndication',name:'test',amountMillion:null,status:'planned',sourceUrl:''})).toBe('2026-09-13');});
 it('flags an old curve even on a current build',()=>{expect(isOverdue('curve','2026-08-01',new Date('2026-09-06'))).toBe(true);expect(isOverdue('curve','2026-09-04',new Date('2026-09-06'))).toBe(false);});
});

describe('GDP scaling',()=>{
 const gdp={basis:'test',sources:[],observations:[{date:'2025-12',rollingAnnualMillion:2000},{date:'2026-03',rollingAnnualMillion:2400},{date:'2026-06',rollingAnnualMillion:3000}]};
 it('uses the latest completed quarter, never a future denominator',()=>{expect(gdpAt(gdp,'2026-05')?.date).toBe('2026-03');expect(gdpAt(gdp,'2026-07')?.date).toBe('2026-06');expect(gdpAt(gdp,'2026-09')).toBeNull();});
 it('discloses OBR-forecast quarters only where the denominator uses them',()=>{const g={...gdp,forecastExtension:{vintage:'March 2026 EFO',publicationDate:'2026-03-03',quarters:['2026Q3']},observations:[...gdp.observations,{date:'2026-09',rollingAnnualMillion:3100,forecastQuarters:['2026Q3']}]};expect(gdpAt(g,'2026-09')?.rollingAnnualMillion).toBe(3100);expect(gdpForecastNote(g,'2026-09')).toContain('2026 Q3');expect(gdpForecastNote(g,'2026-09')).toContain('March 2026 EFO');expect(gdpForecastNote(g,'2026-08')).toBeNull();expect(gdpForecastNote(gdp,'2026-09')).toBeNull();});
 it('allows the publication lag for a current stock, while rejecting stale or future GDP',()=>{expect(gdpAt(gdp,'2026-09',5)?.date).toBe('2026-06');expect(gdpAt(gdp,'2026-12',5)).toBeNull();expect(gdpAt(gdp,'2026-05',5)?.date).toBe('2026-03');});
 it('preserves fiscal identities and does not annualise monthly/YTD flows',()=>{expect(flowValue(30,'2026-07','gdp',gdp)).toBe(1);expect(flowValue(-30,'2026-07','gdp',gdp)).toBe(-1);expect(flowValue(90,'2026-07','gdp',gdp)!-flowValue(60,'2026-07','gdp',gdp)!).toBe(flowValue(30,'2026-07','gdp',gdp));expect(flowValue(30,'2026-07','bn',gdp)).toBe(.03);});
 it('returns missing for unknown flows or invalid GDP',()=>{expect(flowValue(null,'2026-07','gdp',gdp)).toBeNull();expect(flowValue(30,'2026-07','gdp')).toBeNull();expect(flowValue(30,'2026-07','gdp',{...gdp,observations:[{date:'2026-06',rollingAnnualMillion:0}]})).toBeNull();});
});

describe('annual pricing comparison',()=>{
 it('uses the previous available trading day around the anniversary',()=>{expect(annualComparisonDate(['2026-09-07','2025-09-08','2025-09-05'],'2026-09-07')).toBe('2025-09-05');});
 it('clamps leap day to February and preserves exact anniversaries',()=>{expect(annualComparisonDate(['2023-02-28','2023-03-01'],'2024-02-29')).toBe('2023-02-28');expect(annualComparisonDate(['2025-09-04','2025-09-05'],'2026-09-05')).toBe('2025-09-05');});
 it('falls back to earliest available history',()=>{expect(annualComparisonDate(['2026-09-04','2026-09-03'],'2026-09-04')).toBe('2026-09-03');expect(annualComparisonDate([],'')).toBe('');});
});
