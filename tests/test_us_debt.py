"""US Treasury debt adapter checks on trimmed Fiscal Data API responses (live run 26 Oct 2026; MSPD as at 30 Sep 2026).

Fixtures keep a subset of CUSIPs from MSPD Table III; its subtotal lines and the 30 Sep 2026 marketable lines of
Table I were recomputed from the kept CUSIPs so the published identities still hold. Other values are as downloaded.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest import mock
from pipeline.us import debt

FIX = Path(__file__).parent / 'fixtures' / 'us' / 'debt'
FILES = {  # first match wins
    'mspd_table_1': 'mspd_table_1.json', 'mspd_table_3_market': 'mspd_table_3.json', 'debt_to_penny': 'penny.json',
    'avg_interest_rates': 'rates.json', 'security_type:in:': 'auctions_history.json', 'auctions_query': 'auctions_recent.json',
    'upcoming_auctions': 'upcoming.json'}


class FakeFetch:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers=None):
        self.calls.append(url)
        for key, name in FILES.items():
            if key in url:
                return (FIX / name).read_bytes()
        raise KeyError(url)


def body(name):
    return json.loads((FIX / name).read_text())


class UsDebtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fetch = FakeFetch()
        cls.data = debt.fetch_debt(cls.fetch)

    def test_requests_are_https_api_queries(self):
        self.assertEqual(len(self.fetch.calls), 7)
        for url in self.fetch.calls:
            self.assertTrue(url.startswith(debt.API), url)
            self.assertIn('page[size]=10000', url)
        self.assertTrue(any('filter=record_date:eq:2026-09-30' in u for u in self.fetch.calls))

    def test_cusip_and_isin(self):
        self.assertTrue(debt.cusip_ok('912828YQ7'))
        self.assertFalse(debt.cusip_ok('912828YQ8'))
        self.assertEqual(debt.isin('037833100'), 'US0378331005')  # Apple Inc., a published ISIN
        self.assertEqual(debt.isin('38259P508'), 'US38259P5089')  # Alphabet class A, a CUSIP with a letter
        self.assertEqual(debt.isin('912810UW6'), 'US912810UW61')

    def test_stock_by_cusip(self):
        d = self.data
        self.assertEqual(d['asOf'], '2026-09-30')
        secs = {s['cusip']: s for s in d['securities']}
        self.assertEqual(len(secs), 18)
        u24 = secs['912828U24']  # three issues, $4,855m redeemed
        self.assertEqual((u24['issues'], u24['couponPct'], u24['maturityDate']), (3, 2.0, '2026-11-15'))
        self.assertAlmostEqual(u24['nominalMillion'], 64287.5749)
        self.assertEqual(u24['name'], '2.00% Treasury Note November 15, 2026')
        bill = secs['912797SA6']
        self.assertEqual((bill['couponPct'], bill['issues'], bill['nominalMillion']), (0.0, 4, 334135.4294))
        tips = secs['91282CDC2']  # par 38,254.2488 plus 8,492.06 accrued inflation
        self.assertAlmostEqual(tips['nominalMillion'], 18999.0305 + 19305.2183 - 50)
        self.assertAlmostEqual(tips['upliftedMillion'], 46746.30949112, places=5)
        self.assertEqual(tips['type'], 'index-linked')
        frn = secs['91282CLT6']
        self.assertEqual((frn['couponPct'], frn['type'], frn['instrument']), (None, 'conventional', debt.FRN))
        self.assertEqual(frn['spreadPct'], None)  # its auctions are outside the trimmed window
        self.assertEqual(secs['91282CRD5']['spreadPct'], 0.05)
        self.assertTrue(all(s['upliftedMillion'] == s['nominalMillion'] for s in d['securities'] if s['type'] == 'conventional'))

    def test_totals_and_public_debt(self):
        d = self.data
        by = d['totalsByInstrument']
        self.assertEqual({k: v['lines'] for k, v in by.items()},
                         {debt.BILL: 4, debt.NOTE: 5, debt.BOND: 4, debt.TIPS: 3, debt.FRN: 2})
        self.assertAlmostEqual(sum(v['sharePct'] for v in by.values()), 100, places=3)
        self.assertAlmostEqual(by[debt.NOTE]['maturedNotPresentedMillion'], 34.2645)
        self.assertAlmostEqual(by[debt.BILL]['maturedNotPresentedMillion'], .415)  # MSPD shows "*" (under $0.5m)
        pub = d['publicDebt']
        self.assertEqual(pub['daily']['date'], '2026-10-22')
        self.assertAlmostEqual(pub['daily']['totalPublicDebtMillion'], 40444342.7094, places=4)
        self.assertAlmostEqual(pub['nonmarketable']['intragovernmentalMillion'], 7726330.903337, places=4)
        self.assertAlmostEqual(pub['federalFinancingBankMillion'], 3590.9655)
        self.assertEqual(d['maturity']['redemptionsNext12MonthsLines'], 11)  # 4 bills, 3 notes, 1 bond, 2 TIPS, 1 FRN

    def test_stock_history_handles_old_labels(self):
        hist = {r['date']: r for r in self.data['stockHistory']}
        self.assertIn('2001-01-31', hist)  # total line named 'Total Treasury Securities Outstanding'
        self.assertIsNone(hist['2001-01-31']['frnMillion'])
        self.assertGreater(hist['2004-05-31']['tipsMillion'], 0)  # Inflation-Indexed Notes + Bonds
        self.assertEqual(self.data['stockHistory'][-1]['date'], '2026-09-30')

    def test_auctions(self):
        d = self.data
        a = {(x['cusip'], x['date']): x for x in d['auctions']}
        note = a[('91282CRF0', '2026-10-07')]  # 10-year reopening
        self.assertEqual(note['name'], '10-Year Treasury Note 4.625% due August 15, 2036 (reopening)')
        self.assertEqual((note['offeredMillion'], note['cover'], note['yieldPct']), (39000.0, 2.77, 5.3))
        self.assertAlmostEqual(note['allottedMillion'], 39926.3219 - 926.2902)  # SOMA add-on excluded
        self.assertEqual(note['sourceUrl'], 'https://www.treasurydirect.gov/instit/annceresult/press/preanre/2026/R_20261007_2.pdf')
        bill = a[('912797WF0', '2026-10-15')]
        self.assertEqual((bill['name'], bill['yieldPct'], bill['discountRatePct']),
                         ('8-Week Treasury Bill due December 15, 2026 (reopening)', 4.132, 4.05))
        tips = a[('91282CRE3', '2026-09-17')]
        self.assertEqual((tips['instrument'], tips['yieldBasis']), (debt.TIPS, 'real high yield'))
        frn = a[('91282CRD5', '2026-09-23')]
        self.assertEqual((frn['yieldPct'], frn['discountMarginPct'], frn['spreadPct']), (None, .04, .05))
        self.assertNotIn(('912797TD9', '2026-05-21'), a)  # CMB result older than the 3-month bill window
        self.assertIn('912797TD9', {r[2] for r in d['auctionHistory']['rows']})
        self.assertNotIn(('91282CRR4', '2026-10-22'), a)  # held, results not yet published
        self.assertEqual(d['auctions'][0]['date'], '2026-10-15')
        hist = d['auctionHistory']
        self.assertTrue(all(len(r) == len(hist['columns']) for r in hist['rows']))
        self.assertEqual(d['availability']['auctionHistoryFrom'], '2016-09-12')

    def test_calendar(self):
        cal = {(e['cusip'], e['date']): e for e in self.data['calendar']}
        tips = cal[('91282CRR4', '2026-10-22')]  # pending auction from the auctions dataset, flagged as TIPS there
        self.assertEqual((tips['instrument'], tips['amountMillion'], tips['name']), (debt.TIPS, 26000.0, '5-Year TIPS due October 15, 2031'))
        seven = cal[('91282CRV5', '2026-10-29')]
        self.assertEqual((seven['amountMillion'], seven['publicationDate'], seven['name']), (None, '2026-10-16', '7-Year Treasury Note'))
        self.assertTrue(seven['status'].startswith('tentative'))
        self.assertEqual(len(cal), 16)  # stray 2024 snapshot row and 9 Oct snapshot are ignored
        self.assertNotIn('2024-03-21', {e['date'] for e in self.data['calendar']})

    def test_calendar_labels_floating_rate_notes(self):
        # The snapshot lists the new 2-year FRN 91282CRS2 (Wed 28 Oct) as a second 'Note 2-Year' beside the
        # fixed-rate 2-year 91282CRU7 (Mon 26 Oct); both settle on 2 Nov.
        cal = {(e['cusip'], e['date']): e for e in self.data['calendar']}
        fixed, frn = cal[('91282CRU7', '2026-10-26')], cal[('91282CRS2', '2026-10-28')]
        self.assertEqual((fixed['instrument'], fixed['name']), (debt.NOTE, '2-Year Treasury Note'))
        self.assertEqual((frn['instrument'], frn['name']), (debt.FRN, '2-Year FRN'))
        self.assertEqual(sum(e['name'] == '2-Year Treasury Note' for e in self.data['calendar']), 1)
        row = lambda cusip, term, reopening, auction, issue: {'record_date': '2026-10-16', 'security_type': 'Note', 'security_term': term,
                                                               'reopening': reopening, 'cusip': cusip, 'auction_date': auction, 'issue_date': issue}
        # An FRN reopening is recognised from its CUSIP; a lone new 2-year note stays a fixed-rate note.
        rows = [row('91282CRD5', '1-Year 11-Month', 'Yes', '2026-08-26', '2026-08-29'), row('91282CRU7', '2-Year', 'No', '2026-10-26', '2026-11-02')]
        self.assertEqual(debt.upcoming_frns(rows, {'91282CRD5'}), {'91282CRD5'})
        self.assertEqual(debt.upcoming_frns(rows), set())
        three = [row(c, '2-Year', 'No', d, '2026-11-02') for c, d in (('91282CRU7', '2026-10-26'), ('91282CRS2', '2026-10-28'), ('91282CRT0', '2026-10-29'))]
        with self.assertRaises(ValueError):
            debt.upcoming_frns(three)

    def test_rates(self):
        r = {x['security']: x for x in self.data['averageInterestRates']['rows']}
        self.assertEqual((r['Total Marketable']['ratePct'], r['Total Marketable']['yearEarlierPct']), (3.518, 3.406))

    def test_parsers_reject_bad_input(self):
        t3 = body('mspd_table_3.json')['data']
        broken = deepcopy(t3)
        next(r for r in broken if r['security_class2_desc'] == '912797VQ7')['outstanding_amt'] = '1'
        with self.assertRaises(ValueError):
            debt.parse_mspd3(broken, '2026-09-30')
        renamed = deepcopy(t3)
        renamed[0]['security_class1_desc'] = 'Bills Face Value'
        with self.assertRaises(ValueError):
            debt.parse_mspd3(renamed, '2026-09-30')
        t1 = body('mspd_table_1.json')['data']
        bad = deepcopy(t1)
        next(r for r in bad if r['record_date'] == '2026-09-30' and r['security_class_desc'] == 'Notes')['total_mil_amt'] = '1'
        with self.assertRaises(ValueError):
            debt.parse_mspd1(bad)
        with self.assertRaises(ValueError):
            debt.get_all(lambda url, headers=None: b'<html>maintenance</html>', 'mspd1')

    def test_validator_accepts_and_rejects(self):
        with self.assertRaisesRegex(ValueError, 'implausible'):  # the trimmed stock is far below $10 trillion
            debt.validate_debt(self.data)
        with mock.patch.object(debt, 'PLAUSIBLE_MARKETABLE_MILLION', (1e5, 1e8)):
            self._accepts_and_rejects()

    def _accepts_and_rejects(self):
        debt.validate_debt(self.data)
        cases = {
            'duplicate cusip': lambda d: d['securities'].append(deepcopy(d['securities'][0])),
            'total mismatch': lambda d: d['totals'].update(nominalMillion=d['totals']['nominalMillion'] + 5),
            'matured line': lambda d: d['securities'][0].update(maturityDate='2026-09-01'),
            'empty auctions': lambda d: d.update(auctions=[]),
            'cover inconsistent': lambda d: d['auctions'][0].update(cover=9.9),
            'nominal uplift': lambda d: next(s for s in d['securities'] if s['type'] == 'conventional').update(upliftedMillion=1),
            'missing instrument': lambda d: d.update(securities=[s for s in d['securities'] if s['instrument'] != debt.FRN]),
            'bad isin': lambda d: d['securities'][0].update(isin='US0000000000'),
            'magnitude': lambda d: [s.update(nominalMillion=s['nominalMillion'] / 1e3, upliftedMillion=s['upliftedMillion'] / 1e3)
                                    for s in d['securities']],
            'mspd gap': lambda d: d['publicDebt']['marketable'].update(totalMillion=d['publicDebt']['marketable']['totalMillion'] + 50),
        }
        for name, mutate in cases.items():
            bad = deepcopy(self.data)
            mutate(bad)
            with self.subTest(name), self.assertRaises(ValueError):
                debt.validate_debt(bad)


if __name__ == '__main__':
    unittest.main()
