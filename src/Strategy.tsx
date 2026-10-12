import {ChartPanel,type ChartRow} from './components';
import {dateLabel,fmt,type Bundle,type Source} from './data';
import {ViewLink} from './urlState';

type PathPoint={year:string;value:number|null;status:string};
type Indicator={measure:string;path:PathPoint[];paymentsPct?:PathPoint[];peak?:PathPoint;end?:PathPoint;firstYearAtOrAboveZero?:PathPoint}|null;
export type Strategy={name:string;legalBasis:string;vintage:string;publicationDate:string;sourceUrl:string;location:string;note?:string;
 overarchingGoal:{text:string;indicator:Indicator};objectives:{id:string;text:string;indicator:Indicator;indicatorNote?:string|null}[]};

/** One line per status so outturn, forecast and projection read as different kinds of number. */
function pathRows(path:PathPoint[]):ChartRow[]{
 return path.map((p,i)=>{const next=path[i+1];const joins=(status:string)=>p.status===status||next?.status===status&&p.status!==status;
  return {label:p.year,outturn:p.status==='outturn'?p.value:null,forecast:joins('forecast')?p.value:null,projection:joins('projection')&&p.status!=='outturn'?p.value:null};});
}
function IndicatorChart({id,title,indicator,sources,note}:{id:string;title:string;indicator:NonNullable<Indicator>;sources:Source[];note:string}){
 const key=indicator.peak?`Peaks at ${fmt(indicator.peak.value)}% in ${indicator.peak.year}`:indicator.firstYearAtOrAboveZero?`First at or above zero in ${indicator.firstYearAtOrAboveZero.year} (${indicator.firstYearAtOrAboveZero.status})`:'';
 const end=indicator.end?`${fmt(indicator.end.value)}% in ${indicator.end.year} (${indicator.end.status})`:'';
 const summary=[key,end&&`ends at ${end}`].filter(Boolean).join('; ')||`Official path for ${indicator.measure.toLowerCase()}`;
 return <ChartPanel headingLevel={3} id={id} title={title} subtitle={indicator.measure} summary={`${summary}.`} rows={pathRows(indicator.path)} lines={[{key:'outturn',label:'Outturn',colour:'#175d65'},{key:'forecast',label:'Budget forecast',colour:'#a76232',dash:'6 5'},{key:'projection',label:'Medium-term projection',colour:'#829097',dash:'2 4'}]} xLabel="Financial year" unit={/growth/i.test(indicator.measure)?'% change':'% of GDP'} zero={false} sources={sources} note={note}/>;
}

export function StrategyPage({bundle}:{bundle:Bundle}){
 const outlook=bundle.policy?.outlook as (NonNullable<Bundle['policy']>['outlook']&{strategy?:Strategy})|null|undefined;const strategy=outlook?.strategy;
 if(!strategy)return <p className="notice">The fiscal strategy is unavailable in the saved snapshot.</p>;
 const sources:Source[]=[{id:'budget-strategy',name:`${strategy.location}, ${dateLabel(strategy.publicationDate)}`,url:strategy.sourceUrl}];
 const note=`Official ${strategy.vintage==='2026-05'?'2026-27 Budget':strategy.vintage} forecasts (to four years ahead) and medium-term projections (to ten years ahead). Projections are mechanical extrapolations on Treasury assumptions, not forecasts.`;
 return <div className="editorial"><header className="page-heading"><div><p className="eyebrow">STATED OBJECTIVES, NOT NUMERICAL RULES</p><h1>The fiscal strategy.</h1><p className="intro">What the Government says it is aiming for, and the official forecast paths each objective refers to.</p></div></header>
  <p>Australia has no legislated numerical fiscal rules. Under the {strategy.legalBasis}, each Budget sets out a fiscal strategy. The current strategy is qualitative: it names directions, not targets or deadlines. This page therefore shows the relevant official paths without judging whether an objective is being met.</p>
  <section className="story-section"><h2>Overarching goal</h2><blockquote><p>{strategy.overarchingGoal.text.replace(/ This will be underpinned by the following actions:$/,'')}</p></blockquote>
   {strategy.overarchingGoal.indicator&&<IndicatorChart id="strategy-gross-debt" title="Gross debt" indicator={strategy.overarchingGoal.indicator} sources={sources} note={`${note} Gross debt is the face value of Australian Government Securities on issue; net debt (used elsewhere in this dashboard) deducts financial assets.`}/>}</section>
  <section className="story-section"><h2>Supporting actions</h2><ol className="strategy-list">{strategy.objectives.map(o=><li key={o.id}><p>{o.text}</p>{o.indicator?<IndicatorChart id={`strategy-${o.id}`} title={o.indicator.measure.split(' (')[0].split(' and ')[0]} indicator={o.indicator} sources={sources} note={note}/>:<p className="small">{o.indicatorNote}</p>}</li>)}</ol></section>
  <p className="small">{strategy.note} Objectives are quoted from {strategy.location}. <ViewLink href={strategy.sourceUrl}>Budget Statement 3 ↗</ViewLink></p>
  <section className="story-section"><h2>Debt dynamics: why growth and financing costs matter</h2><p className="formula">Δd ≈ [(r − g) / (1 + g)] dₜ₋₁ − pb</p><p>Here d is debt/GDP, r the effective nominal interest rate on the debt stock, g nominal GDP growth, and pb the primary surplus/GDP. The first term is the interest-growth “snowball”; a primary surplus offsets it.</p><p className="small">This is a stylised identity, not Treasury’s full balance-sheet reconciliation. Asset transactions, valuation changes, indexation and the choice of gross or net debt matter. A market bond yield is not r. <ViewLink href="?page=fiscal&section=outlook#debt-dynamics">See the debt-dynamics table on the Outlook page →</ViewLink></p><ViewLink href="?page=debt">Explore the actual refinancing profile →</ViewLink></section>
 </div>;
}
