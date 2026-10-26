/** Country edition chosen at build time (`vite --mode au|us`). UK values reproduce the original wording exactly. */
export type CountryId='uk'|'au'|'us';
export const COUNTRY:CountryId=import.meta.env.VITE_COUNTRY==='au'?'au':import.meta.env.VITE_COUNTRY==='us'?'us':'uk';

const uk={
 id:'uk' as CountryId,
 name:'UK',possessive:'The UK’s',
 tagline:'A GUIDE TO THE UK PUBLIC FINANCES',
 currency:'£',locale:'en-GB',timeZone:'Europe/London',
 fyStartMonth:4, // April–March
 fyMonths:'April–March',fyFirstMonth:'April',
 statAgency:'ONS',forecaster:'OBR',debtAgency:'DMO',centralBank:'Bank of England',taxAgency:'HMRC',
 bond:'gilt',bonds:'gilts',Bond:'Gilt',Bonds:'Gilts',
 borrowing:'Net borrowing',borrowingMeasure:'PSNB ex',borrowingLong:'public-sector net borrowing',
 receipts:'Current receipts',spending:'Total managed expenditure',spendingShort:'Total spending',
 debt:'Public-sector net debt',debtShort:'Net debt',debtMeasure:'PSND ex',
 scopeShort:'Public sector excluding banks',
 forecastLabel:'OBR forecast',
 pricingEyebrow:'MARKET PRICING · UK GILTS',
 curveNote:'Bank of England fitted spot curves, continuously compounded. Only matching published dates and tenors are compared; missing observations are not interpolated.',
 /** Official real and breakeven spot curves exist (UK) or only benchmark series (Australia). */
 realCurves:true,
 receiptSeries:['incomeTax','nic','vat','corporationTax'],receiptSeriesNote:'Income tax, National Insurance, VAT and corporation tax',
 spendSeries:['goodsServices','benefits','interest','netInvestment','currentSpending'],spendSeriesNote:'Goods and services, benefits, interest and investment',
 flowSummary:'The gap between total managed expenditure and current receipts is net borrowing. Both series use the same public-sector coverage.',
 officialRatio:'official ONS fiscal ratio',
 /** Last full financial year before Covid: the UK year ends in March 2020, before the pandemic response. */
 preCovidYear:'2019-20',
};
export type Country=typeof uk;

const au:Country={
 ...uk,
 id:'au',
 name:'Australian',possessive:'Australia’s',
 tagline:'A GUIDE TO THE AUSTRALIAN PUBLIC FINANCES',
 currency:'A$',locale:'en-AU',timeZone:'Australia/Sydney',
 fyStartMonth:7, // July–June
 fyMonths:'July–June',fyFirstMonth:'July',
 statAgency:'Finance',forecaster:'Treasury',debtAgency:'AOFM',centralBank:'Reserve Bank of Australia',taxAgency:'Treasury',
 bond:'bond',bonds:'bonds',Bond:'Bond',Bonds:'Bonds',
 borrowing:'Underlying cash deficit',borrowingMeasure:'UCB',borrowingLong:'the underlying cash deficit',
 receipts:'Receipts',spending:'Payments',spendingShort:'Payments',
 debt:'Net debt',debtShort:'Net debt',debtMeasure:'net debt',
 scopeShort:'Australian Government general government sector',
 forecastLabel:'Treasury forecast',
 pricingEyebrow:'MARKET PRICING · AUSTRALIAN GOVERNMENT BONDS',
 curveNote:'Reserve Bank of Australia fitted zero-coupon yields (F17), continuously compounded, 0.25 to 10 years. Only matching published dates and tenors are compared; missing observations are not interpolated.',
 realCurves:false,
 receiptSeries:[] as string[],receiptSeriesNote:'',
 spendSeries:[] as string[],spendSeriesNote:'',
 flowSummary:'The gap between payments and receipts is the cash deficit; the underlying cash balance also excludes net Future Fund earnings where they applied. Both series cover the Australian Government general government sector.',
 officialRatio:'official Australian Government ratio',
 // 2019-20 runs to June 2020 and includes JobKeeper and other pandemic support.
 preCovidYear:'2018-19',
};

const us:Country={
 ...uk,
 id:'us',
 name:'US',possessive:'America’s',
 tagline:'A GUIDE TO THE US FEDERAL FINANCES',
 currency:'$',locale:'en-US',timeZone:'America/New_York',
 fyStartMonth:10, // October–September; FY2026 runs October 2025 to September 2026
 fyMonths:'October–September',fyFirstMonth:'October',
 statAgency:'Treasury',forecaster:'CBO',debtAgency:'Treasury',centralBank:'Federal Reserve',taxAgency:'Treasury',
 bond:'Treasury',bonds:'Treasuries',Bond:'Treasury',Bonds:'Treasuries',
 borrowing:'Deficit',borrowingMeasure:'unified deficit',borrowingLong:'the federal deficit',
 receipts:'Receipts',spending:'Outlays',spendingShort:'Outlays',
 debt:'Debt held by the public',debtShort:'Debt held by the public',debtMeasure:'debt held by the public',
 scopeShort:'Federal government, unified budget',
 forecastLabel:'CBO projection',
 pricingEyebrow:'MARKET PRICING · US TREASURIES',
 curveNote:'US Treasury daily par yield curves (bond-equivalent, semiannual), not zero-coupon spot rates. Only matching published dates and tenors are compared; missing observations are not interpolated.',
 realCurves:true,
 receiptSeries:['individualIncomeTax','payrollTaxes','corporationTax','customsDuties','exciseTaxes','estateGiftTaxes','miscellaneousReceipts'],receiptSeriesNote:'Income, payroll, corporation, excise, estate and gift taxes, customs duties and other receipts',
 spendSeries:['socialSecurity','medicare','health','defense','netInterest','incomeSecurity','veterans','otherOutlays'],spendSeriesNote:'Social Security, Medicare, health, defense, net interest, income security, veterans and other outlays',
 flowSummary:'The gap between outlays and receipts is the unified federal deficit, including off-budget Social Security and the Postal Service. Both series come from the Monthly Treasury Statement.',
 officialRatio:'official CBO or OMB ratio',
 // FY2019 ends September 2019, before the pandemic response.
 preCovidYear:'2018-19',
};

export const C:Country=COUNTRY==='au'?au:COUNTRY==='us'?us:uk;

/** Inline country wording: the UK text is kept verbatim beside its Australian and US counterparts. */
export function local<T>(ukValue:T,auValue:T,usValue:T):T{return C.id==='au'?auValue:C.id==='us'?usValue:ukValue;}
const US_SPELLING:[RegExp,string][]=[[/annualis/g,'annualiz'],[/labelled/g,'labeled'],[/behaviour/g,'behavior'],[/centre/g,'center'],[/programme/g,'program'],[/stabilis/g,'stabiliz'],[/modelled/g,'modeled']];
/** US wording: 'fiscal year' where the UK and Australia say 'financial year', and US spelling of shared text. */
export function fyTerm(text:string):string{return C.id==='us'?US_SPELLING.reduce((t,[from,to])=>t.replace(from,to),text.replace(/(F|f)inancial([- ])year/g,(_,f:string,sep:string)=>`${f==='F'?'Fiscal':'fiscal'}${sep}year`)):text;}
/** US fiscal years are named by their final calendar year: '2025-26' is FY2026. Other editions keep 'YYYY-YY'. */
export function fyDisplay(label:string):string{const m=/^(\d{4})[-–](\d{2})$/.exec(label);return C.id==='us'&&m&&(Number(m[1])+1)%100===Number(m[2])?`FY${Number(m[1])+1}`:label;}
/** Calendar month that ends the financial year: 3 (March) or 6 (June). */
export const fyEndMonth=(C.fyStartMonth+10)%12+1;
export const fyEndSuffix=`-${String(fyEndMonth).padStart(2,'0')}`;

/** Both editions are published together: the UK at the site root and Australia beneath it at au/. */
const root=COUNTRY==='uk'?'./':'../';
export const EDITIONS:{id:CountryId;label:string;name?:string;path:string}[]=[
 {id:'uk',label:'UK',path:root},
 {id:'au',label:'AUS',name:'Australia',path:COUNTRY==='au'?'./':`${root}au/`},
 {id:'us',label:'US',name:'United States',path:COUNTRY==='us'?'./':`${root}us/`},
];
