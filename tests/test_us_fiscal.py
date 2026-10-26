import copy
import json
import unittest
from pathlib import Path

from pipeline.us import fiscal as F

FIX = Path(__file__).parent / 'fixtures/us/fiscal'
FIRST = '2024-10'


def fetcher(cbo=True):
    files = {
        F.T1_URL.format(size=F.PAGE_SIZE, page=1): 'mts_table_1.json',
        F.T9_URL.format(size=F.PAGE_SIZE, page=1): 'mts_table_9.json',
        F.MSPD_URL.format(start=FIRST, size=F.PAGE_SIZE, page=1): 'mspd_table_1.json',
        F.LATEST_T1_URL: 'mts_table_1-latest.json',
        F.META_URL: 'metadata.json',
        F.CALENDAR_URL: 'calendar.json',
        F.GDP_NSA_URL: 'fred-NA000334Q.csv',
        F.GDP_SAAR_URL: 'fred-GDP.csv',
        F.CBO_CATALOG_URL: 'cbo-catalog.json',
        F.CBO_RAW + 'data/economic/economic_projections/quarterly_2026-02.csv': 'cbo-quarterly_2026-02.csv',
        F.CBO_RAW + 'data/economic/economic_projections/schema.json': 'cbo-schema.json',
    }

    def fetch(url, headers=None):
        if url.startswith(F.CBO_RAW) and not cbo:
            raise RuntimeError(f'Official download failed: {url} (503)')
        if url in files:
            return (FIX / files[url]).read_bytes()
        raise RuntimeError(f'Official download failed: {url} (404)')
    return fetch


class FiscalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = F.fetch_fiscal(fetcher(), first_month=FIRST)
        cls.rows = {r['date']: r for r in cls.data['observations']}

    def test_totals_match_published_mts(self):
        self.assertEqual(self.data['asOf'], '2026-09')
        self.assertEqual(len(self.data['observations']), 24)
        fy26 = [r for r in self.data['observations'] if r['date'] >= '2025-10']
        fy25 = [r for r in self.data['observations'] if r['date'] < '2025-10']
        # MTS Table 1 year-to-date lines in the September 2026 statement (USD).
        self.assertAlmostEqual(sum(r['borrowing'] for r in fy26), 1992473.224, places=2)
        self.assertAlmostEqual(sum(r['receipts'] for r in fy26), 5403326.759, places=2)
        self.assertAlmostEqual(sum(r['spending'] for r in fy25), 7009985.662, places=2)
        self.assertAlmostEqual(sum(r['borrowing'] for r in fy25), 1775369.190, places=2)
        sep = self.rows['2026-09']
        self.assertEqual((sep['receipts'], sep['spending'], sep['borrowing']), (557874.519, 584774.866, 26900.347))
        self.assertLess(self.rows['2025-09']['borrowing'], 0)  # September 2025 was a surplus

    def test_revisions_use_newest_statement(self):
        # August 2026 outlays were revised down by $18.1m in the September 2026 statement.
        self.assertEqual(self.rows['2026-08']['spending'], 526811.548)

    def test_detail_series_and_methods(self):
        self.assertEqual(self.rows['2025-09']['detailMethod'], 'revised')
        self.assertEqual(self.rows['2025-10']['detailMethod'], 'first-published')
        sep = self.rows['2026-09']
        self.assertEqual(sep['individualIncomeTax'], 297529.296)
        self.assertAlmostEqual(sep['payrollTaxes'], 147369.229 + 449.268 + 695.713, places=2)
        self.assertEqual(sep['defense'], 89015.2)
        for r in self.data['observations']:
            self.assertAlmostEqual(sum(r[k] for k in F.RECEIPTS), r['receipts'], delta=2000)
            self.assertAlmostEqual(sum(r[k] for k in (*F.OUTLAYS, F.OTHER_OUTLAYS)), r['spending'], delta=2000)
        for key in F.DETAIL_KEYS:
            self.assertIn(key, self.data['series'])

    def test_debt_and_gdp_gap_fill(self):
        sep = self.rows['2026-09']
        self.assertEqual(sep['debtBillion'], 32425.013)
        gdp = {o['date']: o for o in self.data['gdp']['observations']}
        self.assertEqual(gdp['2026-06']['rollingAnnualMillion'], 7830587 + 7980561 + 7792918 + 8182055)
        q3 = 7830587 * 32468.3 / 30968.3  # BEA 2025Q3 grown by CBO projected year-on-year growth
        self.assertAlmostEqual(gdp['2026-09']['rollingAnnualMillion'], 7980561 + 7792918 + 8182055 + q3, delta=0.1)
        self.assertEqual(gdp['2026-09']['forecastQuarters'], ['2026Q3'])
        self.assertEqual(self.data['gdp']['forecastExtension']['quarters'], ['2026Q3'])
        self.assertEqual(self.data['gdp']['asOf'], '2026-06')
        self.assertAlmostEqual(sep['debtPct'], 32425.013e3 / gdp['2026-09']['rollingAnnualMillion'] * 100, places=2)

    def test_without_cbo_the_gap_stays_null(self):
        data = F.fetch_fiscal(fetcher(cbo=False), first_month=FIRST)
        self.assertNotIn('forecastExtension', data['gdp'])
        rows = {r['date']: r for r in data['observations']}
        self.assertIsNotNone(rows['2026-08']['debtPct'])  # June quarter carried forward two months
        self.assertIsNone(rows['2026-09']['debtPct'])
        F.validate_fiscal(data, previous={})

    def test_release_dates(self):
        self.assertEqual(self.data['releaseDate'], '2026-10-23')
        self.assertEqual(self.data['nextRelease'], 'November 12, 2026')

    def test_validator_accepts_and_rejects(self):
        F.validate_fiscal(self.data, previous={})
        bad = copy.deepcopy(self.data)
        bad['observations'][-1]['borrowing'] += 50
        with self.assertRaisesRegex(ValueError, 'identity'):
            F.validate_fiscal(bad, previous={})
        units = copy.deepcopy(self.data)
        for r in units['observations']:
            r['debtBillion'] *= 1000
        with self.assertRaisesRegex(ValueError, 'debt'):
            F.validate_fiscal(units, previous={})
        gap = copy.deepcopy(self.data)
        del gap['observations'][5]
        with self.assertRaisesRegex(ValueError, 'Missing or unordered'):
            F.validate_fiscal(gap, previous={})
        hidden = copy.deepcopy(self.data)
        del hidden['gdp']['forecastExtension']
        with self.assertRaisesRegex(ValueError, 'forecastExtension'):
            F.validate_fiscal(hidden, previous={})
        with self.assertRaisesRegex(ValueError, 'regressed'):
            F.validate_fiscal(self.data, previous={'asOf': '2026-10', 'observations': []})

    def test_source_changes_fail_loudly(self):
        raw = json.loads((FIX / 'mts_table_9.json').read_text())
        raw['data'][1]['classification_desc'] = 'Individual Income Tax'
        with self.assertRaisesRegex(ValueError, 'receipt lines changed'):
            F.parse_table9(raw['data'])
        raw = json.loads((FIX / 'mts_table_1.json').read_text())
        row = next(r for r in raw['data'] if r['classification_desc'] == 'March')
        row['current_month_dfct_sur_amt'] = str(float(row['current_month_dfct_sur_amt']) + 1e6)
        with self.assertRaisesRegex(ValueError, 'identity'):
            F.parse_table1(raw['data'])
        with self.assertRaisesRegex(ValueError, 'units'):
            nsa = F.parse_fred((FIX / 'fred-NA000334Q.csv').read_bytes(), 'NA000334Q')
            F.check_gdp_units({k: v * 1000 for k, v in nsa.items()}, F.parse_fred((FIX / 'fred-GDP.csv').read_bytes(), 'GDP'))


class ForecastTests(unittest.TestCase):
    def test_no_monthly_profile(self):
        data = F.fetch_forecast(fetcher())
        F.validate_forecast(data)
        self.assertEqual((data['status'], data['fiscalYear'], data['cumulative']), ('unavailable', '2025-26', []))
        self.assertIn('February 2026', data['vintage'])
        bad = dict(data, cumulative=[{'period': '2025-10', 'value': 100.0}])
        with self.assertRaisesRegex(ValueError, 'carries values'):
            F.validate_forecast(bad)


if __name__ == '__main__':
    unittest.main()
