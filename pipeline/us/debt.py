"""US Treasury marketable debt: stock by CUSIP, auction results and the auction calendar (Fiscal Data API).

Stock: Monthly Statement of the Public Debt (MSPD) Table III, marketable securities by CUSIP at the
latest month end. Each CUSIP has one row per issue (original issue and reopenings); the first row
carries the CUSIP's outstanding amount. Face value = amount issued less redemptions; for TIPS the
MSPD outstanding amount adds accrued inflation compensation (the "uplift"). MSPD Table I gives the
class totals, debt held by the public, intragovernmental holdings and non-marketable debt, and its
monthly history since 2001 becomes stockHistory. Debt to the Penny adds the latest daily total.
Auctions: Treasury Securities Auctions Data (results by auction). Calendar: Upcoming Auctions (latest
weekly snapshot) plus announced auctions whose results are not yet in the auctions dataset.
All amounts in USD million. No API key; JSON; paginated with page[size]/page[number].
"""
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

CATALOGUE = Path(__file__).resolve().parents[2] / 'catalogue' / 'us' / 'debt.json'
API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/'
ENDPOINTS = {
    'mspd1': 'v1/debt/mspd/mspd_table_1',
    'mspd3': 'v1/debt/mspd/mspd_table_3_market',
    'penny': 'v2/accounting/od/debt_to_penny',
    'rates': 'v2/accounting/od/avg_interest_rates',
    'auctions': 'v1/accounting/od/auctions_query',
    'upcoming': 'v1/accounting/od/upcoming_auctions',
}
PAGE_SIZE = 10000
PLAUSIBLE_MARKETABLE_MILLION = (1e7, 1e8)  # $10-100 trillion
T1_TOL = 3.0  # USD million: MSPD Table I identities carry source rounding of up to $2 million
BILL, NOTE, BOND, TIPS, FRN = 'Treasury Bill', 'Treasury Note', 'Treasury Bond', 'TIPS', 'Floating Rate Note'
INSTRUMENTS = (BILL, NOTE, BOND, TIPS, FRN)
CODES = {BILL: 'BILL', NOTE: 'NOTE', BOND: 'BOND', TIPS: 'TIPS', FRN: 'FRN'}
KEYS = {BILL: 'billsMillion', NOTE: 'notesMillion', BOND: 'bondsMillion', TIPS: 'tipsMillion', FRN: 'frnMillion'}
MSPD3_CLASSES = {'Bills Maturity Value': BILL, 'Notes': NOTE, 'Bonds': BOND,
                 'Inflation-Protected Securities': TIPS, 'Floating Rate Notes': FRN}
MSPD1_CLASSES = {'Bills': BILL, 'Notes': NOTE, 'Bonds': BOND, 'Treasury Inflation-Protected Securities': TIPS,
                 'Inflation-Indexed Notes': TIPS, 'Inflation-Indexed Bonds': TIPS, 'Floating Rate Notes': FRN,
                 'Federal Financing Bank': 'FFB'}
UPCOMING_TYPES = {'Bill': BILL, 'CMB': BILL, 'Note': NOTE, 'Bond': BOND, 'TIPS Note': TIPS, 'TIPS Bond': TIPS,
                  'FRN Note': FRN, 'FRN': FRN}
MSPD3_FIELDS = ['record_date', 'security_type_desc', 'security_class1_desc', 'security_class2_desc', 'interest_rate_pct',
                'issue_date', 'maturity_date', 'issued_amt', 'inflation_adj_amt', 'redeemed_amt', 'outstanding_amt', 'src_line_nbr']
MSPD1_FIELDS = ['record_date', 'security_type_desc', 'security_class_desc', 'debt_held_public_mil_amt',
                'intragov_hold_mil_amt', 'total_mil_amt', 'src_line_nbr']
AUCTION_FIELDS = ['cusip', 'security_type', 'security_term', 'original_security_term', 'reopening', 'cash_management_bill_cmb',
                  'inflation_index_security', 'floating_rate', 'announcemt_date', 'auction_date', 'issue_date', 'maturity_date',
                  'int_rate', 'spread', 'offering_amt', 'total_tendered', 'total_accepted', 'soma_accepted', 'soma_tendered',
                  'comp_accepted', 'bid_to_cover_ratio', 'high_yield', 'avg_med_yield', 'low_yield', 'high_investment_rate',
                  'high_discnt_rate', 'high_discnt_margin', 'primary_dealer_accepted', 'direct_bidder_accepted',
                  'indirect_bidder_accepted', 'pdf_filenm_announcemt', 'pdf_filenm_comp_results']
AUCTION_MONTHS = 12      # full records of note and bond (incl. TIPS and FRN) auctions kept in auctions
BILL_MONTHS = 3          # bills are auctioned several times a week: full records for 3 months, compact for 12
HISTORY_YEARS = 10       # compact note and bond (incl. TIPS and FRN) auction history
CUSIP = re.compile(r'[0-9]{3}[0-9A-Z]{5}[0-9]')
PRESS = 'https://www.treasurydirect.gov/instit/annceresult/press/preanre/'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']


# ---------- primitives ----------

def api_url(endpoint, fields=None, filter=None, sort=None, page=1):
    q = [f'fields={",".join(fields)}'] if fields else []
    q += [f'filter={filter}'] if filter else []
    q += [f'sort={sort}'] if sort else []
    q += [f'page[number]={page}', f'page[size]={PAGE_SIZE}']
    return API + ENDPOINTS[endpoint] + '?' + '&'.join(q)


def get_all(fetch, endpoint, **kw):
    """Every row of a query, following pagination; the row count must match meta total-count."""
    rows, page = [], 1
    while True:
        url = api_url(endpoint, page=page, **kw)
        try:
            body = json.loads(fetch(url))
        except json.JSONDecodeError as exc:
            raise ValueError(f'Fiscal Data {endpoint} did not return JSON') from exc
        if not isinstance(body, dict) or 'data' not in body or 'meta' not in body:
            raise ValueError(f'Fiscal Data {endpoint} response lacks data/meta: {str(body)[:200]}')
        rows += body['data']
        pages = int(body['meta'].get('total-pages') or 1)
        if page >= pages:
            break
        page += 1
    if len(rows) != int(body['meta'].get('total-count', len(rows))):
        raise ValueError(f'Fiscal Data {endpoint} row count mismatch')
    return rows, url if page == 1 else api_url(endpoint, page=1, **kw)


def blank(v):
    return v is None or (isinstance(v, str) and v.strip() in ('', 'null'))


def num(v, what='value'):
    if blank(v):
        return None
    try:
        n = float(str(v).replace(',', ''))
    except ValueError:
        raise ValueError(f'Non-numeric Fiscal Data {what}: {v!r}') from None
    if not math.isfinite(n):
        raise ValueError(f'Non-finite Fiscal Data {what}')
    return n


def need(v, what):
    n = num(v, what)
    if n is None:
        raise ValueError(f'Missing Fiscal Data {what}')
    return n


def day(v, what='date'):
    if blank(v):
        raise ValueError(f'Missing {what}')
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f'Unparseable {what}: {v!r}') from None


def mill(v):
    """Full dollars to USD million (to the nearest $100, the precision of auction amounts)."""
    n = num(v)
    return None if n is None else round(n / 1e6, 4)


def r6(x):
    return round(x, 6)


def char_value(c):
    return int(c) if c.isdigit() else ord(c) - 55


def cusip_ok(c):
    if not CUSIP.fullmatch(c or ''):
        return False
    total = 0
    for i, ch in enumerate(c[:8]):
        v = char_value(ch) * (2 if i % 2 else 1)
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(c[8])


def isin(cusip):
    """US ISIN = 'US' + CUSIP + Luhn check digit over the letter-expanded string."""
    digits = ''.join(str(char_value(ch)) for ch in 'US' + cusip)
    total = 0
    for i, d in enumerate(reversed(digits)):
        v = int(d) * (2 if i % 2 == 0 else 1)
        total += v // 10 + v % 10
    return f'US{cusip}{(10 - total % 10) % 10}'


def when(d):
    return f'{MONTHS[d.month - 1]} {d.day}, {d.year}'


def pct_text(c):
    s = f'{c:.4f}'.rstrip('0')
    return s + '0' * max(0, 2 - len(s.split('.')[1]))


def label(instrument, maturity, coupon=None):
    if instrument in (BILL, FRN):
        return f'{instrument} {when(maturity)}'
    return f'{pct_text(coupon)}% {instrument} {when(maturity)}'


def months_back(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, 1)


# ---------- MSPD ----------

def parse_mspd1(rows):
    """Month-end summary by security class: {date: {'classes': {...}, 'totals': {...}, 'nonmarketable': [...]}}."""
    out = {}
    for r in rows:
        d = day(r['record_date'], 'MSPD record date').isoformat()
        m = out.setdefault(d, {'classes': {}, 'totals': {}, 'nonmarketable': []})
        kind, cls = r['security_type_desc'], r['security_class_desc']
        vals = {'heldByPublicMillion': need(r['debt_held_public_mil_amt'], 'MSPD held by public'),
                'intragovernmentalMillion': need(r['intragov_hold_mil_amt'], 'MSPD intragovernmental'),
                'totalMillion': need(r['total_mil_amt'], 'MSPD total')}
        if abs(vals['heldByPublicMillion'] + vals['intragovernmentalMillion'] - vals['totalMillion']) > T1_TOL:
            raise ValueError(f'MSPD Table I row does not add up: {d} {kind} {cls}')
        if kind == 'Marketable':
            key = MSPD1_CLASSES.get(cls)
            if key is None:
                raise ValueError('Unrecognised MSPD marketable class: ' + cls)
            t = m['classes'].setdefault(key, dict.fromkeys(vals, 0.0))
            for k, v in vals.items():
                t[k] += v
        elif kind == 'Nonmarketable':
            m['nonmarketable'].append({'class': cls, **vals})
        elif kind in ('Total Marketable', 'Total Nonmarketable', 'Total Public Debt Outstanding', 'Total Treasury Securities Outstanding'):
            m['totals'][{'Total Marketable': 'marketable', 'Total Nonmarketable': 'nonmarketable'}.get(kind, 'public')] = vals
        else:
            raise ValueError('Unrecognised MSPD security type: ' + kind)
    for d, m in out.items():
        if set(m['totals']) != {'marketable', 'nonmarketable', 'public'}:
            raise ValueError(f'MSPD Table I {d} lacks a total line')
        mk = sum(v['totalMillion'] for v in m['classes'].values())
        if abs(mk - m['totals']['marketable']['totalMillion']) > T1_TOL:
            raise ValueError(f'MSPD Table I {d}: marketable classes do not sum to total')
        nm = sum(v['totalMillion'] for v in m['nonmarketable'])
        if abs(nm - m['totals']['nonmarketable']['totalMillion']) > T1_TOL:
            raise ValueError(f'MSPD Table I {d}: non-marketable classes do not sum to total')
        if abs(mk + nm - m['totals']['public']['totalMillion']) > T1_TOL:
            raise ValueError(f'MSPD Table I {d}: marketable plus non-marketable differs from total public debt')
    return out


def stock_history(summary):
    rows = []
    for d in sorted(summary):
        m = summary[d]
        r2 = lambda x: round(x, 2)
        c = lambda k: r2(m['classes'][k]['totalMillion']) if k in m['classes'] else None
        rows.append({'date': d, **{KEYS[i]: c(i) for i in INSTRUMENTS}, 'ffbMillion': c('FFB'),
                     'marketableMillion': r2(m['totals']['marketable']['totalMillion']),
                     'marketableHeldByPublicMillion': r2(m['totals']['marketable']['heldByPublicMillion']),
                     'nonmarketableMillion': r2(m['totals']['nonmarketable']['totalMillion']),
                     'totalPublicDebtMillion': r2(m['totals']['public']['totalMillion']),
                     'heldByPublicMillion': r2(m['totals']['public']['heldByPublicMillion']),
                     'intragovernmentalMillion': r2(m['totals']['public']['intragovernmentalMillion'])})
    return rows


def parse_mspd3(rows, as_of):
    """Unmatured marketable securities by CUSIP plus the MSPD class subtotals (USD million)."""
    groups, subtotals, other = {}, {}, {}
    for r in sorted(rows, key=lambda r: int(r['src_line_nbr'])):
        if r['record_date'] != as_of:
            raise ValueError(f"MSPD Table III row dated {r['record_date']}, expected {as_of}")
        cls, c2 = r['security_class1_desc'], (r['security_class2_desc'] or '').strip()
        if cls in ('Federal Financing Bank', 'Total Marketable'):
            other[cls] = need(r['outstanding_amt'], cls)
            continue
        inst = MSPD3_CLASSES.get(cls)
        if inst is None:
            raise ValueError('Unrecognised MSPD Table III class: ' + cls)
        if c2.startswith('Total '):
            kind = 'unmatured' if 'Unmatured' in c2 else 'matured' if 'Matured' in c2 else 'total'
            v = r['outstanding_amt']
            subtotals.setdefault(inst, {})[kind] = '*' if str(v).strip() == '*' else need(v, c2)  # '*' = under $500,000
            continue
        if not cusip_ok(c2):
            raise ValueError(f'Malformed CUSIP in MSPD Table III: {c2!r}')
        g = groups.setdefault(c2, {'instrument': inst, 'rows': []})
        if g['instrument'] != inst:
            raise ValueError(f'CUSIP {c2} listed under two classes')
        g['rows'].append(r)
    securities = []
    for cusip, g in groups.items():
        inst, rs = g['instrument'], g['rows']
        heads = [r for r in rs if not blank(r['outstanding_amt'])]
        if len(heads) != 1:
            raise ValueError(f'CUSIP {cusip} has {len(heads)} outstanding amounts')
        maturities = {r['maturity_date'] for r in rs}
        if len(maturities) != 1:
            raise ValueError(f'CUSIP {cusip} has several maturity dates')
        maturity = day(maturities.pop(), f'{cusip} maturity')
        issued = sum(need(r['issued_amt'], 'issued amount') for r in rs)
        infl = sum(num(r['inflation_adj_amt']) or 0.0 for r in rs)
        redeemed = sum(num(r['redeemed_amt']) or 0.0 for r in rs)
        outstanding = need(heads[0]['outstanding_amt'], 'outstanding amount')
        if abs(issued + infl + redeemed - outstanding) > .01:
            raise ValueError(f'CUSIP {cusip}: issued + inflation adjustment - redeemed differs from outstanding')
        if inst != TIPS and abs(infl) > 1e-9:
            raise ValueError(f'Nominal CUSIP {cusip} carries an inflation adjustment')
        coupons = {num(r['interest_rate_pct']) for r in rs}
        if len(coupons) != 1:
            raise ValueError(f'CUSIP {cusip} has several coupons')
        coupon = coupons.pop()
        if inst == BILL:
            coupon = 0.0
        elif inst == FRN:
            coupon = None
        elif coupon is None:
            raise ValueError(f'Coupon security {cusip} lacks an interest rate')
        first = min(day(r['issue_date'], f'{cusip} issue date') for r in rs)
        securities.append({'isin': isin(cusip), 'cusip': cusip, 'name': label(inst, maturity, coupon),
                           'type': 'index-linked' if inst == TIPS else 'conventional', 'instrument': inst,
                           'couponPct': coupon, 'maturityDate': maturity.isoformat(), 'firstIssueDate': first.isoformat(),
                           'issues': len(rs), 'nominalMillion': r6(issued + redeemed), 'upliftedMillion': r6(outstanding)})
    for inst in INSTRUMENTS:
        sub = subtotals.get(inst, {})
        lines = sum(s['upliftedMillion'] for s in securities if s['instrument'] == inst)
        if not isinstance(sub.get('total'), float):
            raise ValueError(f'MSPD Table III lacks the {inst} total line')
        if sub.get('matured') == '*':  # under $500,000: implied by total less unmatured
            sub['matured'] = sub['total'] - sub.get('unmatured', lines)
            if not 0 <= sub['matured'] < .5:
                raise ValueError(f'MSPD Table III {inst} matured amount marked under $0.5 million is not')
        if abs(lines - sub.get('unmatured', sub['total'] - sub.get('matured', 0.0))) > .05:
            raise ValueError(f'MSPD Table III {inst} lines do not sum to the unmatured subtotal')
        if abs(sub.get('unmatured', lines) + sub.get('matured', 0.0) - sub['total']) > .05:
            raise ValueError(f'MSPD Table III {inst} unmatured plus matured differs from total')
    if 'Total Marketable' not in other:
        raise ValueError('MSPD Table III lacks the Total Marketable line')
    if abs(sum(s['total'] for s in subtotals.values()) + other.get('Federal Financing Bank', 0.0) - other['Total Marketable']) > .05:
        raise ValueError('MSPD Table III class totals do not sum to Total Marketable')
    securities.sort(key=lambda s: (s['maturityDate'], s['cusip']))
    return securities, subtotals, other


# ---------- auctions ----------

def auction_instrument(r):
    if r['inflation_index_security'] == 'Yes':
        return TIPS
    if r['floating_rate'] == 'Yes':
        return FRN
    inst = {'Bill': BILL, 'Note': NOTE, 'Bond': BOND}.get(r['security_type'])
    if inst is None:
        raise ValueError('Unrecognised auction security type: ' + str(r['security_type']))
    return inst


def kind_label(inst, cmb=False):
    return 'Cash Management Bill' if cmb else {FRN: 'FRN'}.get(inst, inst)


def press_url(filename):
    if blank(filename):
        return None
    m = re.fullmatch(r'[A-Z]+_(\d{4})\d{4}_\d+\.pdf', filename.strip())
    if not m:
        raise ValueError('Unexpected TreasuryDirect file name: ' + filename)
    return f'{PRESS}{m[1]}/{filename.strip()}'


def has_results(r):
    return not blank(r['total_accepted']) and not blank(r['bid_to_cover_ratio'])


def parse_auction(r):
    cusip = r['cusip']
    if not cusip_ok(cusip):
        raise ValueError(f'Malformed auction CUSIP: {cusip!r}')
    inst = auction_instrument(r)
    cmb = r['cash_management_bill_cmb'] == 'Yes'
    auction, maturity = day(r['auction_date'], 'auction date'), day(r['maturity_date'], 'auction maturity date')
    reopening = r['reopening'] == 'Yes'
    # Bills are named by the term auctioned (a 13-week reopening of a 26-week bill is a 13-week bill);
    # notes and bonds by their original term (a reopened 10-year note is still the 10-year).
    term = r['original_security_term'] if inst != BILL and reopening and not blank(r['original_security_term']) else r['security_term']
    coupon = None if inst in (BILL, FRN) else num(r['int_rate'])
    name = f"{term} {kind_label(inst, cmb)}{f' {pct_text(coupon)}%' if coupon is not None else ''} due {when(maturity)}"
    name += ' (reopening)' if reopening else ''
    soma = mill(r['soma_accepted']) or 0.0
    tendered, accepted = mill(r['total_tendered']), mill(r['total_accepted'])
    allotted = None if accepted is None else round(accepted - soma, 4)
    bids = None if tendered is None else round(tendered - (mill(r['soma_tendered']) or 0.0), 4)
    if inst == BILL:
        yld, basis = num(r['high_investment_rate']), 'investment rate'
    elif inst == FRN:
        yld, basis = None, 'discount margin'
    else:
        yld, basis = num(r['high_yield']), ('real' if inst == TIPS else 'nominal') + ' high yield'
    split = {k: mill(r[f]) for k, f in (('primaryDealerMillion', 'primary_dealer_accepted'),
                                        ('directMillion', 'direct_bidder_accepted'), ('indirectMillion', 'indirect_bidder_accepted'))}
    return {'date': auction.isoformat(), 'isin': isin(cusip), 'cusip': cusip, 'name': name,
            'type': 'index-linked' if inst == TIPS else 'conventional', 'instrument': inst,
            'term': term, 'reopening': reopening, 'cashManagementBill': cmb, 'maturityDate': maturity.isoformat(),
            'couponPct': coupon, 'spreadPct': num(r['spread']) if inst == FRN else None,
            'offeredMillion': mill(r['offering_amt']), 'allottedMillion': allotted, 'somaMillion': soma,
            'bidsMillion': bids, 'cover': num(r['bid_to_cover_ratio']),
            'yieldPct': yld, 'yieldBasis': basis, 'medianYieldPct': num(r['avg_med_yield']), 'lowYieldPct': num(r['low_yield']),
            'discountRatePct': num(r['high_discnt_rate']) if inst == BILL else None,
            'discountMarginPct': num(r['high_discnt_margin']) if inst == FRN else None,
            'tailBp': None, 'postAuctionMillion': None, **split,
            'competitiveMillion': mill(r['comp_accepted']),
            'settlementDate': day(r['issue_date'], 'issue date').isoformat(),
            'announcementDate': None if blank(r['announcemt_date']) else day(r['announcemt_date']).isoformat(),
            'sourceUrl': press_url(r['pdf_filenm_comp_results']), 'announcementUrl': press_url(r['pdf_filenm_announcemt'])}


HISTORY_COLUMNS = ['date', 'instrument', 'cusip', 'term', 'reopening', 'maturityDate', 'couponPct', 'offeredMillion',
                   'allottedMillion', 'somaMillion', 'cover', 'yieldPct', 'discountMarginPct',
                   'primaryDealerMillion', 'directMillion', 'indirectMillion']


def compact(rows):
    def cell(r, c):
        v = r[c]
        if c == 'instrument':
            return CODES[v]
        return round(v, 3) if isinstance(v, float) and c.endswith('Million') else v
    return {'columns': HISTORY_COLUMNS, 'instrumentCodes': {v: k for k, v in CODES.items()},
            'rows': [[cell(r, c) for c in HISTORY_COLUMNS] for r in rows]}


def upcoming_frns(rows, known=()):
    """CUSIPs in one upcoming snapshot that are floating rate notes although listed as plain 'Note'.

    The snapshot has no floating-rate flag. An FRN reopening carries the CUSIP of an FRN already outstanding or
    auctioned. A new 2-year FRN is auctioned in the same week as the fixed-rate 2-year note, after it, and settles
    on the same day, so of two new 2-year notes with one issue date the later-auctioned one is the FRN.
    """
    frns = {r['cusip'] for r in rows if r['security_type'] == 'Note' and r['cusip'] in known}
    new_two_year = {}
    for r in rows:
        if r['security_type'] == 'Note' and r['security_term'] == '2-Year' and r['reopening'] != 'Yes' and r['cusip'] not in frns:
            new_two_year.setdefault(r['issue_date'], []).append(r)
    for same_issue in new_two_year.values():
        if len(same_issue) == 2 and same_issue[0]['auction_date'] != same_issue[1]['auction_date']:
            frns.add(max(same_issue, key=lambda r: r['auction_date'])['cusip'])
        elif len(same_issue) > 2:
            raise ValueError('More than two new 2-year notes settle on ' + str(same_issue[0]['issue_date']))
    return frns


def parse_upcoming(rows, pending, url, known_frns=()):
    """Latest upcoming-auction snapshot merged with announced auctions that lack results."""
    if not rows:
        raise ValueError('Upcoming auctions dataset is empty')
    latest = max(day(r['record_date'], 'upcoming record date') for r in rows).isoformat()
    rows = [r for r in rows if r['record_date'] == latest]  # the dataset keeps stray rows from old snapshots
    frns = upcoming_frns(rows, set(known_frns))
    events = {}
    for r in rows:
        inst = FRN if r['cusip'] in frns else UPCOMING_TYPES.get(r['security_type'])
        if inst is None:
            raise ValueError('Unrecognised upcoming auction security type: ' + str(r['security_type']))
        cusip = r['cusip']
        if not cusip_ok(cusip):
            raise ValueError(f'Malformed upcoming auction CUSIP: {cusip!r}')
        reopening = r['reopening'] == 'Yes'
        amount = mill(r['offering_amt'])
        d = day(r['auction_date'], 'upcoming auction date').isoformat()
        events[(cusip, d)] = {
            'date': d, 'type': 'auction',
            'name': f"{r['security_term']} {kind_label(inst, r['security_type'] == 'CMB')}{' (reopening)' if reopening else ''}",
            'instrument': inst, 'isin': isin(cusip), 'cusip': cusip, 'amountMillion': amount,
            'settlementDate': day(r['issue_date'], 'upcoming issue date').isoformat(),
            'announcementDate': None if blank(r['announcemt_date']) else day(r['announcemt_date']).isoformat(),
            'status': 'announced' if amount is not None else 'tentative: offering amount not yet announced',
            'datePrecision': 'day', 'sourceUrl': url, 'publicationDate': latest}
    for a in pending:
        events[(a['cusip'], a['date'])] = {
            'date': a['date'], 'type': 'auction', 'name': a['name'], 'instrument': a['instrument'], 'isin': a['isin'],
            'cusip': a['cusip'], 'amountMillion': a['offeredMillion'], 'settlementDate': a['settlementDate'],
            'announcementDate': a['announcementDate'], 'status': 'announced; results not yet in the auctions dataset',
            'datePrecision': 'day', 'sourceUrl': a['announcementUrl'] or url, 'publicationDate': a['announcementDate']}
    return latest, sorted(events.values(), key=lambda e: (e['date'], e['name']))


# ---------- other ----------

def parse_penny(rows):
    if not rows:
        raise ValueError('Debt to the Penny returned no rows')
    r = max(rows, key=lambda r: r['record_date'])
    out = {'date': day(r['record_date']).isoformat(), 'totalPublicDebtMillion': mill(need(r['tot_pub_debt_out_amt'], 'total public debt')),
           'heldByPublicMillion': mill(need(r['debt_held_public_amt'], 'debt held by the public')),
           'intragovernmentalMillion': mill(need(r['intragov_hold_amt'], 'intragovernmental holdings'))}
    if abs(out['heldByPublicMillion'] + out['intragovernmentalMillion'] - out['totalPublicDebtMillion']) > .01:
        raise ValueError('Debt to the Penny components do not add up')
    return out


def parse_rates(rows):
    by = {}
    for r in rows:
        if r['security_type_desc'] in ('Marketable', 'Interest-bearing Debt') or r['security_desc'].startswith('Total'):
            by.setdefault(r['record_date'], {})[r['security_desc']] = need(r['avg_interest_rate_amt'], 'average interest rate')
    if not by:
        raise ValueError('No average interest rates')
    latest = max(by)
    prior = (day(latest) - timedelta(days=365)).isoformat()
    year_ago = max((d for d in by if d <= prior), default=None)
    return {'date': latest, 'yearEarlierDate': year_ago,
            'rows': [{'security': k, 'ratePct': v, 'yearEarlierPct': by.get(year_ago, {}).get(k)} for k, v in by[latest].items()]}


def fetch_debt(fetch):
    cat = json.loads(CATALOGUE.read_text())
    now = datetime.now(timezone.utc).isoformat()
    pages = cat['pages']
    t1_rows, t1_url = get_all(fetch, 'mspd1', fields=MSPD1_FIELDS, sort='record_date,src_line_nbr')
    summary = parse_mspd1(t1_rows)
    as_of = max(summary)
    t3_rows, t3_url = get_all(fetch, 'mspd3', fields=MSPD3_FIELDS, filter=f'record_date:eq:{as_of}', sort='src_line_nbr')
    if not t3_rows:
        raise ValueError(f'MSPD Table III has no rows for {as_of}')
    securities, subtotals, other = parse_mspd3(t3_rows, as_of)
    latest = summary[as_of]
    for inst in INSTRUMENTS:
        if abs(latest['classes'][inst]['totalMillion'] - subtotals[inst]['total']) > .05:
            raise ValueError(f'MSPD Table I and Table III disagree on {inst}')
    asof = date.fromisoformat(as_of)
    penny_rows, penny_url = get_all(fetch, 'penny', filter=f'record_date:gte:{(asof - timedelta(days=10)).isoformat()}', sort='-record_date')
    penny = parse_penny(penny_rows)
    rate_rows, rate_url = get_all(fetch, 'rates', filter=f'record_date:gte:{months_back(asof, 13).isoformat()}', sort='-record_date,src_line_nbr')
    rates = parse_rates(rate_rows)
    recent_from = months_back(asof, AUCTION_MONTHS + 1).isoformat()
    recent_rows, auction_url = get_all(fetch, 'auctions', fields=AUCTION_FIELDS, filter=f'auction_date:gte:{recent_from}', sort='-auction_date,cusip')
    history_from = date(asof.year - HISTORY_YEARS, asof.month, 1).isoformat()
    hist_rows, hist_url = get_all(fetch, 'auctions', fields=AUCTION_FIELDS,
                                  filter=f'security_type:in:(Note,Bond),auction_date:gte:{history_from}', sort='auction_date,cusip')
    parsed = [parse_auction(r) for r in recent_rows]
    results = [a for a, r in zip(parsed, recent_rows) if has_results(r)]
    pending = [a for a, r in zip(parsed, recent_rows) if not has_results(r)]
    if not results:
        raise ValueError('No auction results returned')
    last_result = max(a['date'] for a in results)
    cutoff = months_back(date.fromisoformat(last_result), AUCTION_MONTHS).isoformat()
    bill_cutoff = months_back(date.fromisoformat(last_result), BILL_MONTHS).isoformat()
    auctions = sorted((a for a in results if a['date'] > (bill_cutoff if a['instrument'] == BILL else cutoff)),
                      key=lambda a: (a['date'], a['cusip']), reverse=True)
    coupons = [parse_auction(r) for r in hist_rows if has_results(r)]
    if any(a['instrument'] == BILL for a in coupons):
        raise ValueError('Note/bond auction query returned bills')
    bills = [a for a in results if a['instrument'] == BILL and a['date'] > cutoff]
    history = sorted(coupons + bills, key=lambda a: (a['date'], a['cusip']))
    up_rows, up_url = get_all(fetch, 'upcoming', sort='-record_date,auction_date')
    known_frns = {s['cusip'] for s in securities if s['instrument'] == FRN} | {a['cusip'] for a in history + parsed if a['instrument'] == FRN}
    snapshot, calendar = parse_upcoming(up_rows, pending, pages['upcomingLanding'], known_frns)
    frn_spread = {}
    for a in history + auctions:
        if a['instrument'] == FRN and a['spreadPct'] is not None:
            frn_spread[a['cusip']] = a['spreadPct']
    for s in securities:
        if s['instrument'] == FRN:
            s['spreadPct'] = frn_spread.get(s['cusip'])
    total_nom = r6(sum(s['nominalMillion'] for s in securities))
    total_upl = r6(sum(s['upliftedMillion'] for s in securities))
    by_inst = {}
    for inst in INSTRUMENTS:
        lines = [s for s in securities if s['instrument'] == inst]
        cls = latest['classes'][inst]
        by_inst[inst] = {'lines': len(lines), 'nominalMillion': r6(sum(s['nominalMillion'] for s in lines)),
                         'upliftedMillion': r6(sum(s['upliftedMillion'] for s in lines)),
                         'sharePct': round(sum(s['upliftedMillion'] for s in lines) / total_upl * 100, 4),
                         'heldByPublicMillion': r6(cls['heldByPublicMillion']), 'intragovernmentalMillion': r6(cls['intragovernmentalMillion']),
                         'maturedNotPresentedMillion': r6(subtotals[inst].get('matured', 0.0)), 'observationDate': as_of}
    tot = latest['totals']
    public = {'date': as_of,
              'totalPublicDebtMillion': r6(tot['public']['totalMillion']), 'heldByPublicMillion': r6(tot['public']['heldByPublicMillion']),
              'intragovernmentalMillion': r6(tot['public']['intragovernmentalMillion']),
              'marketable': {k: r6(v) for k, v in tot['marketable'].items()},
              'nonmarketable': {**{k: r6(v) for k, v in tot['nonmarketable'].items()},
                                'byClass': [{k: (r6(v) if isinstance(v, float) else v) for k, v in c.items()} for c in latest['nonmarketable']]},
              'federalFinancingBankMillion': r6(other.get('Federal Financing Bank', 0.0)),
              'maturedNotPresentedMillion': r6(sum(s.get('matured', 0.0) for s in subtotals.values())),
              'daily': penny}
    wam = sum(s['nominalMillion'] * (date.fromisoformat(s['maturityDate']) - asof).days for s in securities) / total_nom / 365.25
    redemptions = [s for s in securities if s['maturityDate'] <= (asof + timedelta(days=365)).isoformat()]
    meta = {k: cat[k] for k in ('publisher', 'licence', 'attribution', 'licenceUrl')}
    src = lambda id, name, url, landing, obs, **kw: {'id': id, 'name': name, 'title': name, **meta, 'url': url, 'landingUrl': landing,
                                                    'observationDate': obs, 'publicationDate': kw.pop('publicationDate', None),
                                                    'retrievedAt': now, **kw}
    sources = [
        src('mspd-table-3-market', 'Monthly Statement of the Public Debt, Table III-A: detail of marketable Treasury securities outstanding',
            t3_url, pages['mspdLanding'], as_of, units='USD million (par; TIPS outstanding includes inflation adjustment)', frequency='Monthly'),
        src('mspd-table-1', 'Monthly Statement of the Public Debt, Table I: summary of Treasury securities outstanding',
            t1_url, pages['mspdLanding'], as_of, units='USD million', frequency='Monthly'),
        src('debt-to-the-penny', 'Debt to the Penny', penny_url, pages['pennyLanding'], penny['date'], units='USD (converted to USD million)', frequency='Daily (business days)'),
        src('auctions-query', 'Treasury Securities Auctions Data (last 12 months, all securities)', auction_url, pages['auctionsLanding'],
            last_result, units='USD (converted to USD million)', frequency='Daily'),
        src('auctions-query-history', 'Treasury Securities Auctions Data (notes and bonds, incl. TIPS and FRNs)', hist_url, pages['auctionsLanding'],
            max((a['date'] for a in coupons), default=None), units='USD (converted to USD million)', frequency='Daily'),
        src('upcoming-auctions', 'Upcoming Auctions', up_url, pages['upcomingLanding'], None, publicationDate=snapshot, frequency='Weekly snapshot'),
        src('avg-interest-rates', 'Average Interest Rates on U.S. Treasury Securities', rate_url, pages['ratesLanding'], rates['date'], units='Percent', frequency='Monthly'),
    ]
    return {'schemaVersion': 1, 'asOf': as_of, 'retrievedAt': now, 'sources': sources,
            'securities': securities,
            'totals': {'nominalMillion': total_nom, 'upliftedMillion': total_upl},
            'totalsByInstrument': by_inst,
            'publicDebt': public,
            'maturity': {'weightedAverageYears': round(wam, 4), 'basis': 'face-value-weighted contractual maturity at the statement date',
                         'redemptionsNext12MonthsMillion': r6(sum(s['nominalMillion'] for s in redemptions)),
                         'redemptionsNext12MonthsLines': len(redemptions),
                         'billsSharePct': by_inst[BILL]['sharePct']},
            'averageInterestRates': rates,
            'auctions': auctions,
            'auctionHistory': compact(history),
            'calendar': calendar,
            'stockHistory': stock_history(summary),
            'availability': {**cat['availability'], 'auctionsFrom': auctions[-1]['date'], 'auctionHistoryFrom': min((a['date'] for a in coupons), default=None),
                             'billAuctionsFrom': min((a['date'] for a in auctions if a['instrument'] == BILL), default=None),
                             'billAuctionHistoryFrom': min((a['date'] for a in bills), default=None),
                             'calendarSnapshot': snapshot, 'lastSourceDiscoveryDate': now[:10]},
            'definitions': cat['definitions'], 'notes': cat['notes']}


# ---------- validation ----------

def validate_debt(data):
    for key in ('asOf', 'sources', 'securities', 'totals', 'totalsByInstrument', 'publicDebt', 'auctions', 'calendar',
                'availability', 'definitions', 'notes'):
        if key not in data:
            raise ValueError('Debt dataset lacks ' + key)
    as_of = date.fromisoformat(data['asOf'])
    secs = data['securities']
    if not secs:
        raise ValueError('No debt securities')
    if len({s['cusip'] for s in secs}) != len(secs) or len({s['isin'] for s in secs}) != len(secs):
        raise ValueError('Duplicate CUSIP in securities')
    kinds = {s['instrument'] for s in secs}
    if kinds != set(INSTRUMENTS):
        raise ValueError(f'Securities missing an instrument: {kinds}')
    for s in secs:
        if not cusip_ok(s['cusip']) or s['isin'] != isin(s['cusip']):
            raise ValueError('Malformed CUSIP/ISIN ' + s['cusip'])
        if date.fromisoformat(s['maturityDate']) <= as_of:
            raise ValueError('Matured line in stock: ' + s['name'])
        if not s['nominalMillion'] > 0 or not s['upliftedMillion'] > 0:
            raise ValueError('Non-positive face value: ' + s['name'])
        if s['type'] == 'conventional' and abs(s['upliftedMillion'] - s['nominalMillion']) > 1e-6:
            raise ValueError('Nominal line has an uplift: ' + s['name'])
        if s['type'] == 'index-linked' and not s['upliftedMillion'] >= s['nominalMillion'] * .95:
            raise ValueError('Inflation-adjusted principal implausibly below par: ' + s['name'])  # deflation floor applies only at maturity
        if (s['type'] == 'index-linked') != (s['instrument'] == TIPS):
            raise ValueError('Instrument/type mismatch: ' + s['name'])
        if s['instrument'] in (NOTE, BOND, TIPS) and not (isinstance(s['couponPct'], (int, float)) and 0 <= s['couponPct'] < 20):
            raise ValueError('Implausible coupon: ' + s['name'])
    for k in ('nominalMillion', 'upliftedMillion'):
        if abs(sum(s[k] for s in secs) - data['totals'][k]) > .01:
            raise ValueError('Debt total mismatch: ' + k)
    low, high = PLAUSIBLE_MARKETABLE_MILLION
    if not low < data['totals']['upliftedMillion'] < high:
        raise ValueError(f'Marketable debt of {data["totals"]["upliftedMillion"]:,.0f} million is implausible')
    by = data['totalsByInstrument']
    if set(by) != set(INSTRUMENTS):
        raise ValueError('totalsByInstrument incomplete')
    for inst, t in by.items():
        for k in ('nominalMillion', 'upliftedMillion'):
            if abs(sum(s[k] for s in secs if s['instrument'] == inst) - t[k]) > .01:
                raise ValueError(f'Instrument total mismatch: {inst} {k}')
    if abs(sum(t['sharePct'] for t in by.values()) - 100) > .01:
        raise ValueError('Instrument shares do not sum to 100')
    if abs(sum(t['upliftedMillion'] for t in by.values()) - data['totals']['upliftedMillion']) > .01:
        raise ValueError('Instrument totals do not sum to the stock total')
    pub = data['publicDebt']
    if abs(pub['heldByPublicMillion'] + pub['intragovernmentalMillion'] - pub['totalPublicDebtMillion']) > T1_TOL:
        raise ValueError('Public debt components do not add up')
    if abs(pub['marketable']['totalMillion'] + pub['nonmarketable']['totalMillion'] - pub['totalPublicDebtMillion']) > T1_TOL:
        raise ValueError('Marketable plus non-marketable differs from total public debt')
    gap = pub['marketable']['totalMillion'] - pub['federalFinancingBankMillion'] - pub['maturedNotPresentedMillion'] - data['totals']['upliftedMillion']
    if abs(gap) > .5:
        raise ValueError(f'Securities do not reconcile to MSPD total marketable (gap {gap:.3f} million)')
    daily = pub.get('daily') or {}
    if daily and date.fromisoformat(daily['date']) < as_of:
        raise ValueError('Debt to the Penny older than the MSPD snapshot')
    auctions = data['auctions']
    if not auctions:
        raise ValueError('No auction results')
    if len({(a['date'], a['cusip']) for a in auctions}) != len(auctions):
        raise ValueError('Duplicate auction result')
    if date.fromisoformat(max(a['date'] for a in auctions)) < as_of - timedelta(days=45):
        raise ValueError('Auction results are stale relative to the stock snapshot')
    for a in auctions:
        what = f"{a['date']} {a['name']}"
        date.fromisoformat(a['date']), date.fromisoformat(a['maturityDate'])
        if not cusip_ok(a['cusip']):
            raise ValueError('Malformed auction CUSIP: ' + what)
        if not (a['allottedMillion'] or 0) > 0 or a['offeredMillion'] is None or a['bidsMillion'] is None or a['cover'] is None:
            raise ValueError('Incomplete auction result: ' + what)
        if abs(a['bidsMillion'] / a['allottedMillion'] - a['cover']) > .0051:
            raise ValueError('Bid-to-cover inconsistent: ' + what)
        if (a['yieldPct'] if a['instrument'] != FRN else a['discountMarginPct']) is None:
            raise ValueError('Auction lacks a yield: ' + what)
        if a['yieldPct'] is not None and not -5 < a['yieldPct'] < 25:
            raise ValueError('Implausible auction yield: ' + what)
        split = [a[k] for k in ('primaryDealerMillion', 'directMillion', 'indirectMillion')]
        if None not in split and a['competitiveMillion'] is not None and abs(sum(split) - a['competitiveMillion']) > 1:
            raise ValueError('Investor-class allotments do not sum to competitive accepted: ' + what)
    hist = data.get('auctionHistory')
    if hist and any(len(r) != len(hist['columns']) for r in hist['rows']):
        raise ValueError('Malformed auction history row')
    for e in data['calendar']:
        date.fromisoformat(e['date'])
        if not cusip_ok(e.get('cusip') or ''):
            raise ValueError('Malformed calendar CUSIP')
        if e['amountMillion'] is not None and not e['amountMillion'] > 0:
            raise ValueError('Non-positive announced amount')
    prev = None
    for row in data.get('stockHistory', []):
        if prev and row['date'] <= prev:
            raise ValueError('stockHistory out of order')
        prev = row['date']
        parts = sum(row[k] or 0 for k in (*KEYS.values(), 'ffbMillion'))
        if abs(parts - row['marketableMillion']) > T1_TOL:
            raise ValueError('stockHistory classes do not sum to marketable debt: ' + row['date'])
