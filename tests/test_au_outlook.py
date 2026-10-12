"""Australian Budget/MYEFO outlook adapter on trimmed real Budget-paper fixtures (CC BY 4.0)."""
import copy
import unittest
from pathlib import Path

from pipeline.au import outlook
from pipeline.au.outlook import fetch_outlook, number, validate_outlook

FIXTURES = Path(__file__).parent / 'fixtures/au/outlook'
B, M = outlook.BUDGET_BASE, outlook.MYEFO_BASE
FILES = {
    f'{B}/bp1/download/bp1_bs-3.docx': 'bp1_bs-3.docx', f'{B}/bp1/download/bp1_bs-2.docx': 'bp1_bs-2.docx',
    f'{B}/bp1/download/bp1_bs-11.docx': 'bp1_bs-11.docx', f'{B}/bp1/download/bp1_prelims.docx': 'bp1_prelims.docx',
    f'{B}/download/chart-data-final.zip': 'chart-data-final.zip', outlook.GDP_URL: 'nominal-gdp.xlsx',
    f'{M}/index.htm': 'myefo_index.htm', f'{M}/download/03_Part_3.docx': 'myefo_part3.docx',
    f'{M}/download/02_Part_2.docx': 'myefo_part2.docx', f'{M}/download/myefo-2025-26-chart-data.zip': 'myefo-chart-data.zip',
}


def fetcher(overrides=None):
    def fetch(url, headers=None):
        if overrides and url in overrides:
            return overrides[url]
        return (FIXTURES / FILES[url]).read_bytes()
    return fetch


def row(data, vintage, year):
    v = next(v for v in data['vintages'] if v['id'] == vintage)
    return next(r for r in v['rows'] + v['projections'] if r['year'] == year)


class AuOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_outlook(fetcher())

    def test_fractions_and_signs(self):
        self.assertEqual([number(x) for x in ('2 1/4', '- 1/4', '3/4', '-7 1/4', '1,051.0', '−0.4', '305,000', '-')],
                         [2.25, -0.25, 0.75, -7.25, 1051.0, -0.4, 305000.0, None])
        with self.assertRaises(ValueError):
            number('n/a?')

    def test_budget_table_3_1_values(self):
        r = row(self.data, '2026-05', '2026-27')
        self.assertEqual((r['status'], r['borrowingBn'], r['underlyingCashBalancePct'], r['grossDebtBn'], r['grossDebtPct'], r['debtBn'], r['debtPct'], r['interestBn']),
                         ('forecast', 31.5, -1.0, 1051.0, 34.0, 616.6, 19.9, 19.9))
        self.assertEqual((r['gdpBn'], r['nominalGdpGrowth'], r['inflation'], r['realGdpGrowth']), (3094.0, 4.25, 2.5, 1.75))
        self.assertEqual(row(self.data, '2026-05', '2024-25')['status'], 'outturn')
        self.assertAlmostEqual(r['primaryBalancePct'], (19.9 - 31.5) / 3094 * 100, 6)

    def test_myefo_layout_picks_myefo_rows(self):
        r = row(self.data, '2025-12', '2025-26')
        self.assertEqual((r['borrowingBn'], r['borrowingPct'], r['grossDebtBn'], r['debtBn'], r['gdpBn']), (36.8, 1.3, 993.0, 587.5, 2922.0))
        self.assertEqual((r['nominalGdpGrowth'], r['inflation']), (5.25, 3.75))  # MYEFO column, not Budget
        self.assertEqual(r['structuralBalancePct'], -1.5)

    def test_structural_decomposition_and_projections(self):
        r = row(self.data, '2026-05', '2026-27')
        self.assertEqual((r['structuralBalancePct'], r['cyclicalFactorsPct'], r['temporaryMeasuresPct'], r['structuralBorrowingPct']), (-1.5, 0.5, 0.0, 1.5))
        self.assertAlmostEqual(r['structuralBorrowingBn'], 1.5 * 3094 / 100, 6)
        p = row(self.data, '2026-05', '2036-37')
        self.assertEqual((p['status'], p['grossDebtPct'], p['underlyingCashBalancePct'], p['structuralBalancePct']), ('projection', 27.2, 0.8, 0.8))
        self.assertIsNone(r['outputGapPct'])

    def test_history_from_statement_11(self):
        h = self.data['history']
        self.assertEqual((h[0]['year'], h[-1]['year'], len(h)), ('1970-71', '2024-25', 55))
        last = h[-1]
        self.assertEqual((last['borrowingBn'], last['debtBn'], last['grossDebtBn'], last['gdpBasis']), (9.99, 532.346, 928.639, 'published'))
        self.assertEqual(h[0]['gdpBasis'], 'implied from receipts ratio')
        ff = next(r for r in h if r['year'] == '2018-19')
        self.assertTrue(ff['receiptsIncludeFutureFundEarnings'])
        self.assertAlmostEqual(ff['spendingBn'] - ff['receiptsBn'] + ff['futureFundEarningsBn'], ff['borrowingBn'], 2)
        self.assertEqual(next(r for r in h if r['year'] == '2020-21')['structuralBalancePct'], 0.4)

    def test_strategy_quotes_objectives_without_verdicts(self):
        s = self.data['strategy']
        self.assertIsNone(s['assessment'])
        self.assertFalse(s['numericTargets'])
        self.assertIn('reduce gross debt as a share of the economy over time', s['overarchingGoal']['text'])
        self.assertEqual(s['overarchingGoal']['indicator']['peak'], {'year': '2028-29', 'value': 35.8, 'status': 'forecast'})
        self.assertEqual(len(s['objectives']), 6)
        balance = s['objectives'][0]['indicator']
        self.assertEqual(balance['firstYearAtOrAboveZero']['year'], '2034-35')
        self.assertIsNone(s['objectives'][-1]['indicator'])
        for key in ('rules', 'headroomHistory', 'currentBudgetUpdate', 'sensitivities'):
            self.assertIsNone(self.data[key])
        self.assertTrue(all(v['rules'] == [] for v in self.data['vintages']))

    def test_derived_series_are_labelled(self):
        meta = self.data['seriesMetadata']
        self.assertEqual(meta['primaryBalancePct']['basis'], 'derived')
        self.assertEqual(meta['grossDebtPct']['basis'], 'published')
        self.assertEqual(meta['outputGapPct']['basis'], 'not published')

    def test_unconfirmed_publication_date_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'publication date not confirmed'):
            fetch_outlook(fetcher({f'{M}/index.htm': b'<p>The Mid-Year Economic and Fiscal Outlook 2026-27 was released</p>'}))

    def test_validator_rejects_bad_data(self):
        validate_outlook(self.data)
        cases = [
            lambda d: d['vintages'][1]['rows'][2].update(borrowingBn=40.0),
            lambda d: d['vintages'][1]['rows'][2].update(outputGapPct=0.5),
            lambda d: d['vintages'][1]['rows'][2].update(structuralBalancePct=-3.0),
            lambda d: d['vintages'][1].update(rules=[{'name': 'Debt rule', 'met': True}]),
            lambda d: d.update(headroomHistory=[{'headroomBn': 10}]),
            lambda d: d['strategy'].update(assessment='on track'),
            lambda d: d['history'][5].update(borrowingBn=99.0),
            lambda d: d['vintages'].pop(0),
            lambda d: d['vintages'][1]['rows'][3].update(status='outturn'),
        ]
        for mutate in cases:
            bad = copy.deepcopy(self.data)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_outlook(bad)


if __name__ == '__main__':
    unittest.main()
