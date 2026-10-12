import {ViewLink} from './urlState';
import {C,local} from './country';
const groups=[
 {title:'Fiscal detail',links:[
  ['Monthly and year-to-date finances',local('Track spending, receipts and borrowing against the current-year profile.','Track payments, receipts and the underlying cash balance against the Budget profile.'),'?page=fiscal&section=position'],
  ['Deficit decomposition','Primary, interest, structural and cyclical balances, with reconciliation tables.','?page=fiscal&section=deficits'],
  ['Spending and tax composition','Compare categories over time and investigate changes between years.','?page=fiscal&section=composition'],
  ['Forecasts and assumptions',`Compare ${C.forecaster} vintages, forecast changes and underlying assumptions.`,'?page=fiscal&section=outlook'],
  local(['Fiscal rules and headroom','Inspect the rules, formal assessments and borrowing sensitivities.','?page=fiscal&section=rules'],['Fiscal strategy','The Government’s stated fiscal objectives and the forecast paths they refer to.','?page=fiscal&section=rules'])]},
 {title:'Market pricing',links:[
  ['Yield curves and changes',local('Nominal, real and RPI breakeven curves, with changes in basis points.','The nominal zero-coupon curve with changes in basis points, benchmark yields and the 10-year breakeven.'),'?page=pricing']]},
 {title:'Data and reference',links:[
  ['Find a series','Search series, change units and transformations, and export data.','?page=explore&view=series'],
  [local('Tax reliefs','Tax expenditures'),local('Search the tax-relief inventory and published cost estimates.','Search Treasury’s tax expenditure estimates.'),'?page=explore&view=reliefs'],
  ['Analytical measures','Explore derived fiscal indicators and their definitions.','?page=explore&view=derived'],
  ['Calendar and developments','Upcoming releases and the curated official-source ledger.','?page=explore&view=calendar'],
  ['Sources and downloads','Download the saved datasets and inspect provenance.','?page=explore&view=sources'],
  ['Methodology','Definitions, conventions and data limitations.','?page=explore&view=methodology']]}
];
export function ExploreHome(){return <section className="explore-index"><h1>Explore</h1><p className="intro">Detailed views and reference tools behind the overview.</p><div className="explore-groups">{groups.map(g=><section key={g.title}><h2>{g.title}</h2><ul>{g.links.map(([name,description,href])=><li key={href}><ViewLink href={href}>{name} →</ViewLink><p>{description}</p></li>)}</ul></section>)}</div></section>;}
