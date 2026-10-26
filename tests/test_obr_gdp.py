from pathlib import Path
import unittest
from pipeline.fiscal import parse_gdp
from pipeline.obr_gdp import WORKBOOK, forecast_quarters, load_obr_gdp, parse_obr_gdp

GDP_FIXTURE=Path(__file__).parent/'fixtures/gdp-bktl.csv'
Q=lambda y,q:y*4+q-1


class ObrGdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obr=load_obr_gdp()

    def test_pinned_workbook_reads_bktl_quarters_in_millions(self):
        q=self.obr['quarters']
        self.assertAlmostEqual(q[Q(2025,3)],763026)
        self.assertAlmostEqual(q[Q(2026,3)],785899.389,places=2)
        self.assertEqual(self.obr['fileName'],WORKBOOK.name)

    def test_other_files_are_rejected(self):
        with self.assertRaises(Exception):
            parse_obr_gdp(b'not a workbook')

    def test_missing_quarter_grows_ons_year_earlier_by_obr_growth(self):
        ons={Q(2025,3):760000,Q(2025,4):770000,Q(2026,1):780000,Q(2026,2):790000}
        obr={Q(2025,3):100,Q(2026,3):103}
        self.assertEqual(forecast_quarters(ons,obr,'2026-08'),{})
        self.assertAlmostEqual(forecast_quarters(ons,obr,'2026-09')[Q(2026,3)],782800)
        self.assertEqual(set(forecast_quarters(ons,obr,'2026-11')),{Q(2026,3)})

    def test_stale_ons_or_missing_obr_quarters_add_nothing(self):
        ons={Q(2025,3):1,Q(2025,4):1,Q(2026,1):1,Q(2026,2):1}
        self.assertEqual(forecast_quarters(ons,{Q(2025,3):1,Q(2026,3):1},'2027-03'),{})
        self.assertEqual(forecast_quarters(ons,{Q(2026,3):1},'2026-09'),{})

    def test_gdp_rows_flag_forecast_quarters_and_keep_ons_as_of(self):
        raw=GDP_FIXTURE.read_bytes()
        plain=parse_gdp(raw)
        data=parse_gdp(raw,'2026-09',self.obr)
        self.assertEqual(data['asOf'],plain['asOf'])
        self.assertEqual(data['observations'][:-1],plain['observations'])
        last=data['observations'][-1]
        self.assertEqual((last['date'],last['forecastQuarters']),('2026-09',['2026Q3']))
        self.assertEqual(data['forecastExtension']['quarters'],['2026Q3'])
        self.assertIn('obr-gdp-forecast',[s['id'] for s in data['sources']])
        self.assertNotIn('forecastExtension',parse_gdp(raw,'2026-07',self.obr))


if __name__=='__main__':
    unittest.main()
