import {ChartPanel,type ChartRow} from './components';
import {dateLabel,fmt,shiftMonth,type Curve} from './data';
import {useParam} from './urlState';

/** Benchmark yields and a 10-year breakeven as time series, where no official real curve exists (Australia). */
export function MarketSeries({curve,compact=false}:{curve:Curve;compact?:boolean}){
 const [range,setRange]=useParam('marketHistory','5y');
 const benchmarks=curve.benchmarks||[];const latest=benchmarks.at(-1)?.date||'';
 const start=range==='all'?'':shiftMonth(latest.slice(0,7),range==='1y'?-12:-60);
 const rows:ChartRow[]=benchmarks.filter(r=>r.date>=start).map(r=>({label:r.date,nominal2y:r.nominal2y as number|null,nominal5y:r.nominal5y as number|null,nominal10y:r.nominal10y as number|null,indexed10y:r.indexed10y as number|null}));
 const breakeven:ChartRow[]=(curve.breakeven10y||[]).filter(r=>r.date>=start).map(r=>({label:r.date,value:r.value}));
 const last=curve.breakeven10y?.at(-1);const lastRow=benchmarks.at(-1);
 const source=curve.sources.filter(s=>s.id==='rba-f2');
 if(!benchmarks.length)return null;
 return <>
  <div className="toolbar"><label className="select-label"><span>History</span><select aria-label="Market history" value={range} onChange={e=>setRange(e.target.value)}><option value="1y">Last 12 months</option><option value="5y">Last 5 years</option><option value="all">Since 2017</option></select></label><span className="period-caption">Daily observations to {dateLabel(latest)}</span></div>
  <div className={compact?'composition-grid':''}>
  <ChartPanel headingLevel={compact?3:2} id="benchmark-yields" title="Benchmark bond yields" subtitle="Daily · % per annum" summary={`${dateLabel(latest)}: 10-year nominal ${fmt(lastRow?.nominal10y as number,2)}%, 10-year real (indexed) ${fmt(lastRow?.indexed10y as number,2)}%.`} rows={rows} xLabel="Date" unit="%" zero={false} lines={[{key:'nominal2y',label:'2-year nominal',colour:'#829097'},{key:'nominal5y',label:'5-year nominal',colour:'#7285a6'},{key:'nominal10y',label:'10-year nominal',colour:'#175d65'},{key:'indexed10y',label:'10-year indexed (real)',colour:'#a76232'}]} sources={source} note="RBA F2 interpolated yields to maturity on Australian Government bonds. Indexed bonds are linked to the CPI; their yields are real. These are not zero-coupon rates and are not comparable point-for-point with the fitted curve above."/>
  <ChartPanel headingLevel={compact?3:2} id="breakeven-10y" title="10-year CPI breakeven inflation" subtitle="Daily · % per annum" summary={last?`${dateLabel(last.date)}: ${fmt(last.value,2)}%. Nominal minus indexed 10-year yield.`:'Unavailable.'} rows={breakeven} xLabel="Date" unit="%" zero={false} lines={[{key:'value',label:'10-year breakeven',colour:'#175d65'}]} sources={source} note={`${curve.breakeven10yBasis||''} Includes inflation risk and relative liquidity premia; not a pure inflation forecast.`}/>
  </div>
 </>;
}
