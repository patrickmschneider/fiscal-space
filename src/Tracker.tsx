import {type ReactNode,useId} from 'react';
import {fmt} from './data';
import type {Outlook} from './policyData';
import type {Contribution,Tracker} from './headroom';

const money=(bn:number,digits=1)=>`${bn<0?'−':''}£${fmt(Math.abs(bn),digits)}bn`;
const signed=(bn:number,digits=1)=>`${bn>0?'+':bn<0?'−':''}£${fmt(Math.abs(bn),digits)}bn`;
const pp=(x:number,digits=1)=>`${x<0?'−':''}${fmt(Math.abs(x),digits)}`;
const longDate=(d:string)=>new Date(`${d}T12:00:00Z`).toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});

/** A label with a plain-language explanation on hover or keyboard focus. */
export function Term({children,explain}:{children:ReactNode;explain:string}){
 const id=useId();
 return <span className="term" tabIndex={0} aria-describedby={id}>{children}<span role="tooltip" id={id} className="term-tip">{explain}</span></span>;
}

const EXPLAIN={
 headroom:'The margin by which the government is forecast to meet its main fiscal rule, the stability rule: a current-budget surplus (receipts cover day-to-day spending) in the target year. It is the room the Chancellor has before tax rises or spending cuts are needed to meet the rule.',
 estimate:'An indicative update of that margin between forecasts: the latest OBR margin, adjusted for how far gilt yields have moved since the OBR fixed its assumptions, using the OBR’s own ready-reckoner. Not an OBR forecast.',
 debt:'Whether debt is heading up or down as a share of GDP on the OBR forecast. Debt falls when the primary balance (borrowing excluding interest) is better than the level that would hold the debt ratio steady, which depends on the gap between the interest rate on debt and nominal GDP growth.',
 stabilising:'The primary balance that would keep debt constant as a share of GDP: debt ratio × (effective interest rate − nominal growth) ÷ (1 + nominal growth). If interest rates exceed growth, a primary surplus is needed just to stand still.',
};

export function TrackerBanner({tracker,next}:{tracker:Tracker;next?:{event:string;when:string}}){
 const {estimateBn,baseline,debt}=tracker;const max=Math.max(40,baseline.bn*1.5,estimateBn*1.2);const pos=(x:number)=>`${Math.min(100,Math.max(0,x/max*100))}%`;
 const gapMax=3;const gpos=(x:number)=>`${50+Math.max(-gapMax,Math.min(gapMax,x))/gapMax*50}%`;
 return <section className="fs-verdict" aria-label="Verdict">
  <div className="fs-verdict-main"><p className="fs-verdict-label">Verdict</p><p className={`fs-verdict-word ${tracker.tone}`}>{tracker.verdict}</p>{tracker.driver&&<p className="fs-verdict-driver">driven by <a href="#changes">{tracker.driver.label.toLowerCase()}</a></p>}</div>
  <div className="fs-dial"><h2><Term explain={EXPLAIN.estimate}>Headroom, estimated</Term><span className={tracker.tone}>{money(estimateBn)}</span></h2>
   <div className="fs-dial-bar"><span className="fs-track"><span className={`fs-fill ${tracker.tone}`} style={{width:pos(estimateBn)}}/><span className="fs-tick" style={{left:pos(baseline.bn)}} title={`${baseline.label}: ${money(baseline.bn)}`}/></span>
   <span className="fs-ends" aria-hidden="true"><span>£0</span><span>{baseline.label} {money(baseline.bn)} ▲</span></span></div></div>
  {debt&&<div className="fs-dial"><h2><Term explain={EXPLAIN.debt}>Debt in {debt.year}</Term><span>{debt.direction==='falling'?'Falling':debt.direction==='rising'?'Rising':'Stable'}</span></h2>
   <div className="fs-dial-bar"><span className="fs-track"><span className="fs-zero"/><span className="fs-mark" style={{left:gpos(debt.gap)}}/></span>
   <span className="fs-ends" aria-hidden="true"><span>← Rising</span><span>Falling →</span></span></div></div>}
  <p className="fs-verdict-facts">{tracker.formal&&<>Formal headroom <strong>{money(tracker.formal.bn)}</strong> at the Budget on {longDate(tracker.formal.date)} · </>}<strong>{money(baseline.bn)}</strong> in the {baseline.label.replace(' forecast','')} update{next&&<> · Next: <strong>{next.event}</strong>{next.when?`, ${next.when}`:''}</>}</p>
 </section>;
}

export function trackerSentence(t:Tracker):string{
 const rates=t.items.find(i=>i.id==='rates'),inyear=t.items.find(i=>i.id==='inyear');const parts:string[]=[];
 if(rates&&rates.bn!=null&&rates.measure!=null)parts.push(`Gilt yields are ${fmt(Math.abs(rates.measure),2)} percentage points ${rates.measure>=0?'higher':'lower'} than when the OBR fixed its ${t.baseline.label} assumptions. On its ready-reckoner that ${rates.bn<0?'takes':'adds'} about ${money(Math.abs(rates.bn),0)} ${rates.bn<0?'off':'to'} the ${money(t.baseline.bn)} margin against the stability rule, leaving an estimated ${money(t.estimateBn)}.`);
 if(inyear&&inyear.bn!=null)parts.push(`Borrowing so far this year is ${money(Math.abs(inyear.bn))} ${inyear.bn<0?'above':'below'} the OBR’s monthly profile.`);
 if(t.debt)parts.push(`On the OBR forecast, debt is ${t.debt.direction} in ${t.debt.year}: the primary balance (${pp(t.debt.primaryBalancePct)}% of GDP) is ${t.debt.gap>=0?'above':'below'} the ${pp(t.debt.stabilisingPrimaryPct)}% that would hold debt steady.`);
 return parts.join(' ');
}

function Waterfall({t}:{t:Tracker}){
 const counted=t.items.filter(i=>i.counted&&i.bn!=null);const steps:{label:string;from:number;to:number;kind:'base'|'step'|'total'}[]=[{label:t.baseline.label,from:0,to:t.baseline.bn,kind:'base'}];
 let run=t.baseline.bn;for(const i of counted){steps.push({label:i.label,from:run,to:run+(i.bn as number),kind:'step'});run+=i.bn as number;}
 steps.push({label:'Estimated headroom now',from:0,to:run,kind:'total'});
 const W=640,rowH=34,left=210,right=70,H=steps.length*rowH+24;const max=Math.max(...steps.map(s=>Math.max(s.from,s.to)),10);const min=Math.min(0,...steps.map(s=>Math.min(s.from,s.to)));
 const x=(v:number)=>left+(v-min)/(max-min)*(W-left-right);
 return <svg className="fs-waterfall" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={steps.map(s=>`${s.label}: ${s.kind==='step'?signed(s.to-s.from):money(s.to)}`).join('; ')}>
  <line x1={x(0)} x2={x(0)} y1={4} y2={H-18} className="fs-wf-zero"/>
  {steps.map((s,k)=>{const y=8+k*rowH,a=Math.min(x(s.from),x(s.to)),w=Math.max(2,Math.abs(x(s.to)-x(s.from)));const cls=s.kind==='step'?(s.to<s.from?'erode':'add'):'level';
   return <g key={s.label}><text x={left-10} y={y+rowH/2} className="fs-wf-label">{s.label}</text><rect x={a} y={y+6} width={w} height={rowH-14} className={`fs-wf-bar ${cls}`}/>
    <text x={Math.max(x(s.from),x(s.to))+6} y={y+rowH/2} className="fs-wf-value">{s.kind==='step'?signed(s.to-s.from):money(s.to)}</text>
    {k<steps.length-1&&s.kind!=='total'&&<line x1={x(s.to)} x2={x(s.to)} y1={y+rowH-8} y2={y+rowH+6} className="fs-wf-link"/>}</g>;})}
  <text x={x(0)} y={H-4} className="fs-wf-axis">£0</text>
 </svg>;
}

function ItemRow({i}:{i:Contribution}){
 return <tr className={i.counted?'':'fs-muted'}><th scope="row">{i.label}</th><td className="num">{i.bn==null?'–':signed(i.bn)}</td><td>{i.counted?'Counted':'Shown, not counted'}</td>
  <td><details className="fs-note"><summary>{i.detail.split('. ')[0].replace(/\.$/,'')}.</summary><p>{i.detail.split('. ').slice(1).join('. ')}{i.sourceUrl&&<> <a href={i.sourceUrl}>OBR source ↗</a></>}</p></details></td></tr>;
}

export function ChangesSection({t}:{t:Tracker}){
 return <section className="story-section fs-changes" id="changes" aria-labelledby="changes-title">
  <div className="story-heading"><div><p className="eyebrow">SINCE THE {t.baseline.label.toUpperCase()}</p><h2 id="changes-title">The headroom tracker</h2>
   <p className="takeaway">The <Term explain={EXPLAIN.headroom}>headroom</Term> is only formally assessed at each OBR forecast. Between forecasts, this tracks the news that moves it, using the OBR’s own ready-reckoners. It is an indicative estimate, not an OBR forecast.</p></div></div>
  <Waterfall t={t}/>
  <div className="table-wrap" role="region" aria-label="Headroom tracker items" tabIndex={0}><table className="fs-changes-table"><thead><tr><th scope="col">Since the forecast</th><th scope="col" className="num">Headroom effect</th><th scope="col">In the estimate?</th><th scope="col">Detail</th></tr></thead>
   <tbody>{t.items.map(i=><ItemRow key={i.id} i={i}/>)}</tbody></table></div>
  <p className="small">Only the market move is counted: it is observed daily and priced with the OBR’s published sensitivity against the OBR’s own starting point. The other items are real news but map less cleanly onto the target year ({t.baseline.year}), so they are shown for judgement rather than added.</p>
 </section>;
}

export function DebtDynamicsSection({t}:{t:Tracker}){
 const d=t.debt;if(!d)return null;
 const rows:[string,string,string][]=[
  ['Debt, % of GDP',`${fmt(d.prevDebtPct)} → ${fmt(d.debtPct)}`,`${d.prevYear} → ${d.year}`],
  ['Effective interest rate on debt (r)',`${fmt(d.effectiveRate,2)}%`,`Net debt interest in ${d.year} ÷ net debt at end-${d.prevYear}`],
  ['Nominal GDP growth (g)',`${fmt(d.nominalGrowth)}%`,`OBR forecast for ${d.year}`],
  ['Debt-stabilising primary balance',`${pp(d.stabilisingPrimaryPct,2)}% of GDP`,'Debt ratio × (r − g) ÷ (1 + g)'],
  ['OBR primary balance',`${pp(d.primaryBalancePct)}% of GDP`,'Borrowing excluding net interest, sign reversed'],
  ['Gap',`${pp(d.gap,2)}pp`,d.direction==='falling'?'Debt falling':d.direction==='rising'?'Debt rising':'Debt broadly stable'],
 ];
 return <section className="story-section" id="debt-dynamics" aria-labelledby="debt-dynamics-title">
  <div className="story-heading"><div><p className="eyebrow">DEBT DYNAMICS</p><h2 id="debt-dynamics-title">Is debt on a falling path?</h2>
   <p className="takeaway">Debt falls as a share of GDP when the <Term explain={EXPLAIN.stabilising}>primary balance beats the debt-stabilising level</Term>, which rises with the gap between the interest rate on debt and nominal growth. All figures come from the same OBR forecast, so the definitions match.</p></div></div>
  <div className="table-wrap" role="region" aria-label="Debt dynamics" tabIndex={0}><table><thead><tr><th scope="col">OBR {t.baseline.label}</th><th scope="col" className="num">Value</th><th scope="col">Basis</th></tr></thead>
   <tbody>{rows.map(([a,b,c])=><tr key={a}><th scope="row">{a}</th><td className="num">{b}</td><td>{c}</td></tr>)}</tbody></table></div>
  <p className="small">Higher gilt yields since the forecast raise the effective interest rate only gradually, as debt is refinanced; the headroom tracker above captures their effect on borrowing.</p>
 </section>;
}

export function SensitivityBars({outlook,headroom}:{outlook:Outlook;headroom:number}){
 const s=outlook.sensitivities||[];if(!s.length)return null;const max=Math.max(headroom,...s.map(x=>x.borrowingChangeBn));
 return <div className="fs-sens"><h3>What could change the picture</h3><p className="small">OBR ready-reckoners: the change in borrowing in {s[0].targetYear} from each shock, against today’s estimated headroom of {money(headroom)}.</p>
  <ul>{s.map(x=><li key={x.id}><span className="fs-sens-label">{x.label}</span><span className="fs-sens-track"><span className="fs-sens-fill" style={{width:`${x.borrowingChangeBn/max*100}%`}}/><span className="fs-sens-head" style={{left:`${Math.min(100,headroom/max*100)}%`}} title="Estimated headroom"/></span><span className="fs-sens-value">£{fmt(x.borrowingChangeBn,0)}bn · {fmt(x.borrowingChangeBn/headroom*100,0)}% of headroom</span></li>)}</ul>
  <p className="small">The vertical line marks the estimated headroom. <a href={s[0].sourceUrl}>OBR source ↗</a></p></div>;
}

export function Part({n,title,intro,id}:{n:number;title:string;intro:string;id:string}){
 return <header className="fs-part" id={id}><p className="fs-part-number">Part {n}</p><h2>{title}</h2><p>{intro}</p></header>;
}

