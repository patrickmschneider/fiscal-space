"""AOFM adapter checks on trimmed real downloads (live run 12 Oct 2026; stock as at 9 Oct 2026)."""
from copy import deepcopy
from pathlib import Path
import unittest
from pipeline.au import aofm

FIX = Path(__file__).parent / 'fixtures' / 'au' / 'aofm'
FILES = {  # longest/most specific URL fragment first
    'historical-issuance-program-updates': 'historical.html', 'issuance-program-budget': 'budget.html',
    'data-hub': 'data-hub.html', 'treasury-bonds': 'tb.html', 'treasury-indexed-bonds': 'tib.html',
    'treasury-notes': 'tn.html', 'forthcoming-transactions': 'forthcoming.html', 'program/issuance-program': 'program.html',
    'treasury%20bonds%20-%20issuance': 'tb_issuance.xlsx', 'Indexed%20Bonds%20-%20Issuance': 'tib_issuance.xlsx',
    'Notes%20-%20Issuance': 'tn_issuance.xlsx', 'portfolio_aggregate_-_dealt': 'portfolio.xlsx',
    'indexation_factors': 'indexation.xlsx', 'foreign_holdings': 'foreign.xlsx'}


class FakeFetch:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers=None):
        self.calls.append((url, headers))
        for key, name in FILES.items():
            if key in url:
                return (FIX / name).read_bytes()
        raise KeyError(url)


def read(name):
    return (FIX / name).read_bytes()


class AofmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fetch = FakeFetch()
        cls.data = aofm.fetch_debt(cls.fetch)

    def test_every_request_sends_akamai_headers(self):
        for url, headers in self.fetch.calls:
            self.assertTrue(url.startswith('https://www.aofm.gov.au/'), url)
            for h in ('Accept', 'Accept-Language', 'Accept-Encoding', 'User-Agent'):
                self.assertIn(h, headers or {}, url)

    def test_discovery_requires_each_file_once(self):
        hub = aofm.discover(read('data-hub.html'))
        self.assertEqual(set(hub), set(aofm.HUB_FILES))
        self.assertTrue(hub['tib_issuance'].endswith('Treasury%20Indexed%20Bonds%20-%20Issuance_0.xlsx'))
        with self.assertRaises(ValueError):
            aofm.discover(read('data-hub.html').replace(b'foreign_holdings', b'foreign_x'))

    def test_on_issue_tables(self):
        as_of, tb = aofm.parse_on_issue(read('tb.html'), aofm.TB, {'AU3TB0000200', 'AU3TB0000291'})
        self.assertEqual((as_of, len(tb)), ('2026-10-09', 30))
        line = next(s for s in tb if s['isin'] == 'AU3TB0000135')
        self.assertEqual((line['couponPct'], line['maturityDate'], line['nominalMillion']), (4.75, '2027-04-21', 39400))
        self.assertEqual({s['isin'] for s in tb if s['green']}, {'AU3TB0000200', 'AU3TB0000291'})
        _, tib = aofm.parse_on_issue(read('tib.html'), aofm.TIB)
        self.assertEqual(sum(s['nominalMillion'] for s in tib), 41642)
        _, tn = aofm.parse_on_issue(read('tn.html'), aofm.TN)
        self.assertEqual((len(tn), tn[0]['couponPct'], tn[0]['type']), (11, 0.0, 'conventional'))

    def test_totals_and_tib_uplift(self):
        d = self.data
        self.assertEqual(d['asOf'], '2026-10-09')
        self.assertEqual(d['totals']['nominalMillion'], 990792)
        self.assertEqual({k: v['lines'] for k, v in d['totalsByInstrument'].items()}, {aofm.TB: 30, aofm.TIB: 6, aofm.TN: 11})
        sep30 = next(s for s in d['securities'] if s['isin'] == 'AU0000XCLWV6')  # Kt 155.29 for 20 Dec 2026 coupon
        self.assertAlmostEqual(sep30['upliftedMillion'], 8242 * 155.29 / 100)
        self.assertEqual(sep30['indexation']['couponDate'], '2026-12-20')
        self.assertTrue(all(s['upliftedMillion'] == s['nominalMillion'] for s in d['securities'] if s['type'] == 'conventional'))

    def test_month_end_aggregate_reconciles_with_weekly_stock(self):
        # 30 Sep face value + allotments dealt 1-9 Oct = 9 Oct on-issue table (to web rounding of $1m).
        rec = {r['instrument']: r for r in self.data['stockReconciliation']}
        self.assertEqual(rec[aofm.TB]['monthEndMillion'], 891949.274)
        self.assertLess(abs(rec[aofm.TB]['residualMillion']), 1)
        self.assertLess(abs(rec[aofm.TIB]['residualMillion']), 1)

    def test_tender_and_syndication_rows(self):
        rows = aofm.parse_issuance(read('tb_issuance.xlsx'), aofm.TB, 'u')
        t = next(r for r in rows if r['tenderNumber'] == 'TB1720')
        self.assertEqual((t['isin'], t['offeredMillion'], t['bidsMillion'], t['cover']), ('AU0000217101', 1000, 3765, 3.765))
        self.assertAlmostEqual(t['tailBp'], (5.1475 - 5.14605) * 100)
        syn = next(r for r in rows if r['tenderNumber'] == 'TBSYN38')
        self.assertEqual((syn['method'], syn['offeredMillion'], syn['cover'], syn['allottedMillion'], syn['tailBp']),
                         ('syndication', None, None, 13000, None))
        self.assertTrue(next(r for r in rows if r['tenderNumber'].startswith('Green Bond/'))['green'])
        tn = aofm.parse_issuance(read('tn_issuance.xlsx'), aofm.TN, 'u')
        self.assertTrue(all(r['instrument'] == aofm.TN and r['couponPct'] is None for r in tn))
        self.assertEqual(self.data['auctions'][0]['date'], '2026-10-09')
        hist = self.data['auctionHistory']
        self.assertTrue(all(len(r) == len(hist['columns']) for r in hist['rows']))

    def test_forthcoming_calendar(self):
        cal = self.data['calendar']
        self.assertEqual([(e['date'], e['amountMillion']) for e in cal],
                         [('2026-10-13', 300), ('2026-10-14', 700), ('2026-10-15', 1000), ('2026-10-15', 1000),
                          ('2026-10-16', 1000), ('2026-10-22', None)])
        self.assertEqual(cal[-1]['status'], 'planned')
        self.assertEqual(cal[0]['isin'], 'AU000XCLWAS7')
        bad = read('forthcoming.html').replace(b'<h2 id="TB">Treasury Bonds</h2>', b'<h2>Buybacks</h2>')
        with self.assertRaises(ValueError):
            aofm.parse_forthcoming(bad, 'u')

    def test_program_headline_amounts(self):
        head = self.data['issuanceProgram']['headline']
        self.assertEqual((head['fiscalYear'], head['treasuryBondsBillion'], head['treasuryIndexedBondsLowBillion'],
                          head['treasuryIndexedBondsHighBillion']), ('2026-27', 125, 2, 3))
        myefo = ('<article><p>18 December 2025</p><p>Planned issuance of Treasury Bonds (including Green Treasury Bonds) for 2025-26 has '
                 'been revised to around $125 billion (of which $62.5 billion has been completed). Planned issuance of Treasury Indexed '
                 'Bonds in 2025-26 remains between $2 billion and $3 billion.</p></article>')
        h = aofm.parse_headline(myefo, 'u', 'MYEFO')
        self.assertEqual((h['fiscalYear'], h['treasuryBondsBillion'], h['treasuryIndexedBondsHighBillion']), ('2025-26', 125, 3))
        self.assertIsNone(aofm.parse_headline('<p>No amounts here</p>', 'u', 'x')['treasuryBondsBillion'])
        self.assertEqual(len(self.data['issuanceProgram']['guidance']), 7)

    def test_foreign_holdings(self):
        last = self.data['foreignHoldings'][-1]
        self.assertEqual((last['date'], last['sharePct']), ('2026-06-30', 52.3678))

    def test_validator_accepts_and_rejects(self):
        aofm.validate_debt(self.data)
        cases = {
            'duplicate isin': lambda d: d['securities'].append(deepcopy(d['securities'][0])),
            'total mismatch': lambda d: d['totals'].update(nominalMillion=d['totals']['nominalMillion'] + 5),
            'matured line': lambda d: d['securities'][0].update(maturityDate='2026-10-01'),
            'empty auctions': lambda d: d.update(auctions=[]),
            'cover inconsistent': lambda d: next(a for a in d['auctions'] if a['method'] == 'tender').update(cover=9.9),
            'nominal uplift': lambda d: next(s for s in d['securities'] if s['type'] == 'conventional').update(upliftedMillion=1),
            'missing instrument': lambda d: d.update(securities=[s for s in d['securities'] if s['instrument'] != aofm.TN]),
        }
        for name, mutate in cases.items():
            bad = deepcopy(self.data)
            mutate(bad)
            with self.subTest(name), self.assertRaises(ValueError):
                aofm.validate_debt(bad)


if __name__ == '__main__':
    unittest.main()
