import {fyEndMonth} from './country';
/** Choose clear vertical space across the forecast region, including signed stacks.
 * If neither edge has room, put the label just outside the plot instead.
 */
export function forecastLabelPosition(rows:Record<string,string|number|null>[],keys:string[],stacked=false,overlayKey?:string,domain?:[number,number]):'insideTop'|'insideBottom'|'top'{
 const bounds=(row:Record<string,string|number|null>)=>{
  const values=keys.map(k=>row[k]).filter((v):v is number=>typeof v==='number'&&Number.isFinite(v));
  const points=stacked&&values.length?[values.reduce((s,v)=>s+Math.min(0,v),0),values.reduce((s,v)=>s+Math.max(0,v),0)]:values;
  const overlay=overlayKey?row[overlayKey]:null;
  if(typeof overlay==='number'&&Number.isFinite(overlay))points.push(overlay);
  return points;
 };
 const all=rows.flatMap(bounds),forecast=rows.filter(r=>r.status==='Forecast').flatMap(bounds);
 if(!all.length||!forecast.length)return 'insideTop';
 const low=domain?.[0]??Math.min(...all),high=domain?.[1]??Math.max(...all);
 const topGap=high-Math.max(...forecast),bottomGap=Math.min(...forecast)-low;
 const clearance=(high-low)*.14;
 if(Math.max(topGap,bottomGap)<=clearance)return 'top';
 return topGap>=bottomGap?'insideTop':'insideBottom';
}

/** Locate publication between period-end observations on a categorical time axis. */
export function publicationBoundary(labels:string[],publication:string,annual=false){
 const ends=labels.map(label=>{const year=Number(label.slice(0,4));const month=annual?fyEndMonth:Number(label.slice(5,7));return Date.UTC(year+(annual?1:0),month,0);});
 const date=Date.parse(publication+'T00:00:00Z');
 if(!ends.length||!Number.isFinite(date)||date>ends.at(-1)!)return null;
 if(date<=ends[0])return {index:0,fraction:0};
 const next=ends.findIndex(end=>end>=date);const index=next-1;
 return {index,fraction:(date-ends[index])/(ends[next]-ends[index])};
}

/** Pad the data range, then round both ends to a 1/2/2.5/5 step so every tick is an exact, cleanly labelled value. */
export function axisTicks(values:number[],pad=0.15,count=5){if(!values.length)return null;const lo=Math.min(...values)-pad,hi=Math.max(...values)+pad;const raw=(hi-lo)/(count-1);const mag=10**Math.floor(Math.log10(raw));const step=[1,2,2.5,5,10].map(m=>m*mag).find(x=>x>=raw)!;const start=Math.floor(lo/step)*step,end=Math.ceil(hi/step)*step;const n=Math.round((end-start)/step);const ticks=Array.from({length:n+1},(_,i)=>Number((start+i*step).toFixed(10)));return {domain:[ticks[0],ticks[n]] as [number,number],ticks,digits:Math.max(0,-Math.floor(Math.log10(step)+1e-9))+(String(step/mag).includes('.')?1:0)};}

/** Maturity axes: whole years from 0, in steps of 1, 2, 5 or 10 so there are at most eight intervals. */
export function yearTicks(tenors:number[]){if(!tenors.length)return null;const max=Math.max(...tenors);const step=[1,2,5,10,20].find(s=>Math.ceil(max/s)<=8)||20;const end=Math.max(step,Math.ceil(max/step)*step);return {domain:[0,end] as [number,number],ticks:Array.from({length:end/step+1},(_,i)=>i*step)};}
