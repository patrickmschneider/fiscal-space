import copy
import json
import unittest
from pathlib import Path

from pipeline.au import fiscal as F

FIX = Path(__file__).parent / 'fixtures/au/fiscal'
FBO_2526 = 'https://archive.budget.gov.au/2025-26/fbo/download/06_appendix_b.docx'


def fetcher(aggregates='aggregates-recent.xlsx', fbo=True):
    def fetch(url, headers=None):
        if url == F.PACKAGE_URL:
            return (FIX / 'package.json').read_bytes()
        if url == F.GDP_URL:
            assert headers == F.GDP_HEADERS
            return (FIX / 'gdp.csv').read_bytes()
        if url == FBO_2526 and fbo:
            return (FIX / 'fbo-appendix-b.docx').read_bytes()
        if url.endswith('6.-aggregates.xlsx'):
            return (FIX / aggregates).read_bytes()
        if url.endswith('1.-aggregates-mp.xlsx'):
            return (FIX / 'aggregates-mp.xlsx').read_bytes()
        raise RuntimeError(f'Official download failed: {url} (404)')
    return fetch


class FiscalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = F.fetch_fiscal(fetcher())
        cls.rows = {r['date']: r for r in cls.data['observations']}

    def test_latest_month_matches_published_ytd(self):
        self.assertEqual(self.data['asOf'], '2026-08')
        ytd = [self.rows['2026-07'], self.rows['2026-08']]
        self.assertAlmostEqual(sum(r['receipts'] for r in ytd), 129184.126, places=2)
        self.assertAlmostEqual(sum(r['spending'] for r in ytd), 137143.804, places=2)
        self.assertAlmostEqual(sum(r['borrowing'] for r in ytd), 7959.678, places=2)
        self.assertEqual(self.rows['2026-07']['method'], 'published-month')

    def test_june_is_fbo_residual_and_year_reconciles(self):
        june = self.rows['2026-06']
        self.assertEqual(june['method'], 'fbo-residual')
        self.assertAlmostEqual(june['borrowing'], 22254 - 10947.312, places=2)
        self.assertEqual(june['debtBillion'], 549.969)
        self.assertEqual(june['debtPct'], 18.79)  # FBO publishes 18.8% using the same ABS GDP total
        year = [r for r in self.data['observations'] if '2025-07' <= r['date'] <= '2026-06']
        self.assertAlmostEqual(sum(r['borrowing'] for r in year), 22254, places=2)

    def test_units_rounding_and_future_fund_years(self):
        self.assertEqual(self.rows['2020-07']['roundingMillion'], 100)
        self.assertEqual(self.rows['2026-07']['roundingMillion'], 1)
        self.assertIsNotNone(self.rows['2019-10']['futureFundEarnings'])
        self.assertIsNone(self.rows['2020-10']['futureFundEarnings'])
        for r in self.data['observations']:
            self.assertLessEqual(abs(r['spending'] - r['receipts'] + (r['futureFundEarnings'] or 0) - r['borrowing']), 3 * r['roundingMillion'])

    def test_annual_history_and_gdp(self):
        annual = self.data['annual']['rows']
        self.assertEqual(annual[0]['year'], '1970-71')
        last = annual[-1]
        self.assertEqual((last['year'], last['underlyingCashBalanceMillion'], last['netDebtMillion'], last['grossDebtFaceValueMillion']),
                         ('2025-26', -22254, 549969, 971447))
        self.assertTrue(next(a for a in annual if a['year'] == '2010-11')['futureFundDeducted'])
        gdp = {o['date']: o['rollingAnnualMillion'] for o in self.data['gdp']['observations']}
        self.assertEqual(gdp['2026-06'], 2927146)

    def test_validator_accepts_and_rejects(self):
        F.validate_fiscal(self.data, previous={})
        bad = copy.deepcopy(self.data)
        bad['observations'][-1]['borrowing'] += 50
        with self.assertRaisesRegex(ValueError, 'identity'):
            F.validate_fiscal(bad, previous={})
        short = copy.deepcopy(self.data)
        short['observations'] = short['observations'][-20:]
        with self.assertRaisesRegex(ValueError, '24 months'):
            F.validate_fiscal(short, previous={})
        with self.assertRaisesRegex(ValueError, 'regressed'):
            F.validate_fiscal(self.data, previous={'asOf': '2026-09', 'observations': []})
        lost = copy.deepcopy(self.data)
        lost['observations'][-3].update(borrowing=None, receipts=None, spending=None, method='unavailable')
        with self.assertRaisesRegex(ValueError, 'lost'):
            F.validate_fiscal(lost, previous=self.data)

    def test_missing_fbo_leaves_june_null(self):
        def fetch(url, headers=None):
            if 'archive.budget.gov.au' in url and '2024-25' in url:
                return (FIX / 'fbo-appendix-b.docx').read_bytes()  # simulates only an older edition reachable
            return fetcher(fbo=False)(url, headers)
        with self.assertRaisesRegex(ValueError, 'does not end in 2024-25'):
            F.fetch_fiscal(fetch)
        with self.assertRaisesRegex(ValueError, 'No Final Budget Outcome'):
            F.fetch_fiscal(fetcher(fbo=False))
        years = F.parse_aggregates((FIX / 'aggregates-recent.xlsx').read_bytes())
        fbo = [r for r in F.parse_fbo((FIX / 'fbo-appendix-b.docx').read_bytes()) if r['year'] != '2025-26']
        june = {r['date']: r for r in F.monthly(years, fbo, None)}['2026-06']
        self.assertEqual((june['method'], june['borrowing']), ('unavailable', None))


class EarlyYearsTests(unittest.TestCase):
    def setUp(self):
        self.fbo = F.parse_fbo((FIX / 'fbo-appendix-b.docx').read_bytes())

    def test_future_fund_separate_and_underlying_receipts(self):
        years = F.parse_aggregates((FIX / 'aggregates-2012.xlsx').read_bytes())
        rows = {r['date']: r for r in F.monthly(years, self.fbo, None)}
        self.assertEqual(rows['2013-10']['futureFundEarnings'], 1064)
        self.assertEqual(rows['2013-07']['futureFundEarnings'], 0)
        # 2012-13 MFS receipts exclude net Future Fund earnings, so June uses FBO receipts less FBO earnings.
        self.assertEqual(rows['2013-06']['receipts'], 351052 - 2682 - 317378)
        for r in rows.values():
            self.assertLessEqual(abs(r['spending'] - r['receipts'] + (r['futureFundEarnings'] or 0) - r['borrowing']), 3)
        for fy, start in (('2012-13', '2012-07'), ('2013-14', '2013-07')):
            months = [r for d, r in rows.items() if start <= d <= f'{int(start[:4]) + 1}-06']
            ucb = next(a for a in self.fbo if a['year'] == fy)['underlyingCashBalanceMillion']
            self.assertAlmostEqual(sum(r['borrowing'] for r in months), -ucb)

    def test_2000_01_single_month_august_and_blank_march(self):
        years = F.parse_aggregates((FIX / 'aggregates-2000.xlsx').read_bytes())
        rows = {r['date']: r for r in F.monthly(years, self.fbo, None)}
        self.assertEqual(rows['2000-08']['borrowing'], 5263)
        self.assertEqual(rows['2000-09']['borrowing'], -(-4691 - (1894 - 5263)))
        self.assertIsNone(rows['2001-03']['borrowing'])
        self.assertIsNone(rows['2001-04']['borrowing'])
        self.assertIsNone(rows['2000-07']['receipts'])


class SourceTests(unittest.TestCase):
    def test_discovery_requires_unique_resources(self):
        package = json.loads((FIX / 'package.json').read_text())
        found = F.discover(json.dumps(package).encode())
        self.assertTrue(found['aggregates']['url'].endswith('6.-aggregates.xlsx'))
        package['result']['resources'].append(dict(package['result']['resources'][0]))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            F.discover(json.dumps(package).encode())

    def test_gdp_rejects_other_series(self):
        raw = (FIX / 'gdp.csv').read_text().replace(',GPM,10,', ',GPM,20,')
        with self.assertRaisesRegex(ValueError, 'Unexpected ABS series'):
            F.parse_gdp(raw.encode())

    def test_fbo_identity_checked(self):
        import io, zipfile
        with zipfile.ZipFile(FIX / 'fbo-appendix-b.docx') as z:
            files = {n: z.read(n) for n in z.namelist()}
        files['word/document.xml'] = files['word/document.xml'].replace(b'-22,254', b'-22,999', 1)
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for n, b in files.items():
                z.writestr(n, b)
        with self.assertRaisesRegex(ValueError, 'identity failed in 2025-26'):
            F.parse_fbo(out.getvalue())


class ForecastTests(unittest.TestCase):
    def test_profile_is_partial_budget_vintage(self):
        data = F.fetch_forecast(fetcher())
        F.validate_forecast(data)
        self.assertEqual((data['status'], data['fiscalYear'], data['vintage'], data['publicationDate']),
                         ('partial', '2026-27', '2026-27 Budget', '2026-10-02'))
        self.assertEqual(data['cumulative'], [{'period': '2026-08', 'value': 12.547}])
        self.assertEqual(data['profileColumns'][0]['kind'], 'actual')

    def test_validator_requires_twelve_months_when_available(self):
        data = F.fetch_forecast(fetcher())
        with self.assertRaisesRegex(ValueError, '12 cumulative'):
            F.validate_forecast({**data, 'status': 'available'})
        full = {**data, 'status': 'available', 'cumulative': [{'period': F.period(2026, i), 'value': float(i)} for i in range(12)]}
        F.validate_forecast(full)
        with self.assertRaisesRegex(ValueError, 'carries values'):
            F.validate_forecast({**data, 'status': 'unavailable'})
        with self.assertRaisesRegex(ValueError, 'unique months'):
            F.validate_forecast({**data, 'cumulative': [{'period': '2026-08', 'value': 1}, {'period': '2026-07', 'value': 2}]})


if __name__ == '__main__':
    unittest.main()
