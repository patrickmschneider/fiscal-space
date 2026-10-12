/** Country edition chosen at build time (`vite --mode au`). UK values reproduce the original wording exactly. */
export type CountryId='uk'|'au';
export const COUNTRY:CountryId=import.meta.env.VITE_COUNTRY==='au'?'au':'uk';

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

export const C:Country=COUNTRY==='au'?au:uk;

/** Inline country wording: the UK text is kept verbatim beside its Australian counterpart. */
export function local<T>(ukValue:T,auValue:T):T{return C.id==='au'?auValue:ukValue;}
/** Calendar month that ends the financial year: 3 (March) or 6 (June). */
export const fyEndMonth=(C.fyStartMonth+10)%12+1;
export const fyEndSuffix=`-${String(fyEndMonth).padStart(2,'0')}`;
