"""US CBO outlook adapter on trimmed real cbo-data fixtures (public domain, 17 U.S.C. 105)."""
import copy
import json
import unittest
from pathlib import Path

from pipeline.us import outlook
from pipeline.us.outlook import fetch_outlook, label, validate_outlook

FIXTURES = Path(__file__).parent / 'fixtures/us/outlook'
FILES = {outlook.CATALOG_URL: 'catalog.json', outlook.HISTORY_URL: 'historical_budget_2026-02.csv',
         outlook.STABILIZERS_URL: 'automatic_stabilizers_2024-11.csv'}
for _v in ('2024-06', '2025-01', '2026-02'):
    FILES[outlook.budget_url(_v)] = f'ten_year_budget_{_v}.csv'
    FILES[outlook.economy_url(_v)] = f'economic_fiscal_{_v}.csv'


def fetcher(overrides=None):
    def fetch(url, headers=None):
        if overrides and url in overrides:
            return overrides[url]
        return (FIXTURES / FILES[url]).read_bytes()
    return fetch


def row(data, vintage, year):
    v = next(v for v in data['vintages'] if v['id'] == vintage)
    return next(r for r in v['rows'] if r['year'] == year)


class UsOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_outlook(fetcher())

    def test_fiscal_year_labels_use_start_year(self):
        self.assertEqual(label(2026), '2025-26')
        self.assertEqual(label(2000), '1999-00')
        self.assertEqual([v['forecastStart'] for v in self.data['vintages']], ['2023-24', '2024-25', '2025-26'])

    def test_latest_baseline_values(self):
        r = row(self.data, '2026-02', '2025-26')  # FY2026
        self.assertEqual(r['status'], 'forecast')
        self.assertEqual((r['borrowingBn'], r['receiptsBn'], r['spendingBn'], r['interestBn'], r['debtBn'], r['debtPct']),
                         (1852.703, 5595.916, 7448.619, 1038.976, 32095.165, 100.605))
        self.assertAlmostEqual(r['borrowingPct'], 5.807, 2)  # CBO headline 5.8% of GDP
        self.assertAlmostEqual(r['primaryDeficitBn'], r['borrowingBn'] - r['interestBn'], 6)
        self.assertAlmostEqual(r['primaryBalancePct'], (r['interestBn'] - r['borrowingBn']) / r['gdpBn'] * 100, 6)
        last = row(self.data, '2026-02', '2035-36')
        self.assertEqual(last['debtPct'], 120.209)
        self.assertEqual(row(self.data, '2026-02', '2024-25')['status'], 'outturn')

    def test_economic_assumptions_and_aliases(self):
        r = row(self.data, '2026-02', '2025-26')
        self.assertEqual((r['realGdpGrowth'], r['nominalGdpGrowth'], r['inflation'], r['unemploymentRate'], r['treasuryNoteRate10y'], r['treasuryBillRate3m'], r['fedFundsRate']),
                         (2.286, 5.181, 2.961, 4.55, 4.098, 3.432, 3.572))
        self.assertEqual((r['bankRate'], r['giltYield'], r['outputGapPct']), (3.572, 4.098, 1.1))
        self.assertIsNone(r['netInvestmentBn'])

    def test_structural_only_where_cbo_published_it(self):
        r = row(self.data, '2024-06', '2023-24')
        self.assertEqual((r['structuralBorrowingBn'], r['automaticStabilizersBn']), (2038.8, -123.7))
        self.assertAlmostEqual(r['borrowingBn'] - r['structuralBorrowingBn'], r['automaticStabilizersBn'], 0)
        self.assertNotIn('structuralBorrowingBn', row(self.data, '2026-02', '2025-26'))
        h = {x['year']: x for x in self.data['history']}
        self.assertEqual(h['2019-20']['structuralBorrowingBn'], 2859.1)
        self.assertIsNone(h['2023-24']['structuralBorrowingBn'])  # FY2024 was a projection in the 2024-11 estimates

    def test_history(self):
        h = self.data['history']
        self.assertEqual((h[0]['year'], h[-1]['year'], len(h)), ('1961-62', '2024-25', 64))
        last = h[-1]
        self.assertEqual((last['borrowingBn'], last['debtBn'], last['interestBn'], last['deficitInterestBn']), (1775.37, 30172.402, 969.938, 969.938))
        self.assertEqual(h[0]['borrowingPct'], 1.22)

    def test_rules_are_descriptive(self):
        rules = self.data['rules']
        self.assertEqual([r['id'] for r in rules], ['debt-limit', 'statutory-paygo'])
        self.assertTrue(all(r['headroomBn'] is None and r['met'] is None for r in rules))
        self.assertTrue(rules[0]['indicator']['path'])
        for key in ('strategy', 'headroomHistory', 'currentBudgetUpdate', 'sensitivities'):
            self.assertIsNone(self.data[key])

    def test_sources_cite_cbo_and_download_from_github(self):
        v = self.data['vintages'][-1]
        self.assertEqual((v['publicationDate'], v['sourceUrl']), ('2026-02-11', 'https://www.cbo.gov/publication/51118'))
        self.assertTrue(all(s['downloadUrl'].startswith('https://') for s in self.data['sources']))

    def test_new_baseline_fails_closed(self):
        catalog = json.loads((FIXTURES / 'catalog.json').read_text())
        next(d for d in catalog['datasets'] if d['identifier'] == 'ten_year_budget')['vintages'].insert(0, '2027-01')
        with self.assertRaisesRegex(ValueError, 'New CBO baseline'):
            fetch_outlook(fetcher({outlook.CATALOG_URL: json.dumps(catalog).encode()}))

    def test_changed_layout_fails(self):
        raw = (FIXTURES / 'ten_year_budget_2025-01.csv').read_bytes().replace(b'date,variable,value', b'year,variable,value', 1)
        with self.assertRaisesRegex(ValueError, 'column layout'):
            fetch_outlook(fetcher({outlook.budget_url('2025-01'): raw}))
        dup = (FIXTURES / 'ten_year_budget_2025-01.csv').read_bytes() + b'FY2030,proj_rev_total,1.0\n'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            fetch_outlook(fetcher({outlook.budget_url('2025-01'): dup}))

    def test_validator_rejects_bad_data(self):
        validate_outlook(self.data)
        cases = [
            lambda d: d['vintages'][2]['rows'][3].update(borrowingBn=1900.0),
            lambda d: d['vintages'][2]['rows'][3].update(debtPct=90.0),
            lambda d: d['vintages'][2]['rows'][3].update(status='outturn'),
            lambda d: d['vintages'][2]['rows'][3].update(netInvestmentBn=10.0),
            lambda d: d['vintages'][2]['rows'][3].update(giltYield=9.0),
            lambda d: d['vintages'][0]['rows'][3].update(structuralBorrowingBn=1000.0),
            lambda d: d['vintages'][1].update(rules=[{'name': 'Debt limit', 'met': True}]),
            lambda d: d['rules'][0].update(headroomBn=100.0),
            lambda d: d.update(sensitivities=[{'id': 'x'}]),
            lambda d: d['history'][5].update(borrowingBn=99.0),
            lambda d: d['history'].pop(10),
            lambda d: d['vintages'].pop(0) and d['vintages'].pop(0),
            lambda d: d['vintages'].reverse(),
            lambda d: d['vintages'][2]['rows'].pop(4),
        ]
        for mutate in cases:
            bad = copy.deepcopy(self.data)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_outlook(bad)


if __name__ == '__main__':
    unittest.main()
