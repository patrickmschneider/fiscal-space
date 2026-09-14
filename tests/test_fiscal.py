import csv
import io
from pathlib import Path
import unittest
from pipeline.fiscal import parse_pusf, parse_gdp, fetch_fiscal, ONS_URL, GDP_URL
from pipeline.fiscal import parse_pesa_history
import openpyxl

FIXTURE=Path(__file__).parent/'fixtures/pusf-sample.csv'

class FiscalTests(unittest.TestCase):
    def test_published_july_2026(self):
        data=parse_pusf(FIXTURE.read_bytes())
        self.assertEqual(data['releaseDate'],'2026-08-21')
        self.assertEqual(data['observations'][-1]['borrowing'],1800)
        ytd=[r for r in data['observations'] if '2026-04'<=r['date']<='2026-07']
        self.assertAlmostEqual(sum(r['borrowing'] for r in ytd),56696)
        self.assertEqual(data['observations'][-1]['debtPct'],94.1)

    def modify(self,fn):
        rows=list(csv.reader(io.StringIO(FIXTURE.read_text())))
        fn(rows);out=io.StringIO();csv.writer(out).writerows(rows);return out.getvalue().encode()

    def test_optional_tax_and_interest_receipt_codes_are_read_by_identity(self):
        def extend(rows):
            for i,row in enumerate(rows):
                row.extend(['Council tax','Interest received','Total taxes'] if i==0 else ['NMHM','JW2L','AHHY'] if i==1 else ['11','22','33'] if i>=7 else ['','',''])
        data=parse_pusf(self.modify(extend))
        self.assertEqual(data['observations'][-1]['councilTax'],11)
        self.assertEqual(data['observations'][-1]['interestReceipts'],22)
        self.assertEqual(data['observations'][-1]['totalTaxes'],33)
        self.assertEqual(data['series']['totalTaxes']['code'],'AHHY')

    def test_missing_month_fails(self):
        raw=self.modify(lambda rows:rows.pop(next(i for i,r in enumerate(rows) if r[0]=='2025 FEB')))
        with self.assertRaisesRegex(ValueError,'Missing month'):parse_pusf(raw)

    def test_bad_identity_is_rejected(self):
        def corrupt(rows):rows[-1][rows[1].index('DZLS')]='-1800'
        with self.assertRaisesRegex(ValueError,'Borrowing reconciliation'):parse_pusf(self.modify(corrupt))

    def test_missing_core_is_not_zero(self):
        def corrupt(rows):rows[-1][rows[1].index('JW2O')]=''
        with self.assertRaisesRegex(ValueError,'Missing core'):parse_pusf(self.modify(corrupt))

    def test_html_and_schema_drift_fail(self):
        with self.assertRaises(ValueError):parse_pusf(b'<html>Denied</html>')
        def corrupt(rows):rows[1][rows[1].index('DZLS')]='OTHER'
        with self.assertRaisesRegex(ValueError,'Missing required'):parse_pusf(self.modify(corrupt))

    def test_revised_old_period_is_preserved(self):
        def revise(rows):
            row=next(r for r in rows if r[0]=='2025 JAN')
            for code in ['DZLS','KX5Q','JW2Q']:row[rows[1].index(code)]=str(float(row[rows[1].index(code)])+235)
        before=parse_pusf(FIXTURE.read_bytes());after=parse_pusf(self.modify(revise))
        a=next(r for r in before['observations'] if r['date']=='2025-01')
        b=next(r for r in after['observations'] if r['date']=='2025-01')
        self.assertEqual(b['borrowing']-a['borrowing'],235)

class PESAHistoryTests(unittest.TestCase):
    fixture = Path(__file__).parent/'fixtures/pesa-2026-chapter4.xlsx'

    def modified(self, fn):
        book = openpyxl.load_workbook(self.fixture)
        fn(book)
        output = io.BytesIO()
        book.save(output)
        return output.getvalue()

    def test_official_long_run_levels_and_published_ratios(self):
        data = parse_pesa_history(self.fixture.read_bytes())
        self.assertEqual(len(data['years']), 23)
        self.assertEqual(data['years'][0]['year'], '2003-04')
        before = next(r for r in data['years'] if r['year'] == '2019-20')
        after = data['years'][-1]
        self.assertEqual(before['tmePctGdp'], 39.1)
        self.assertEqual(after['tmePctGdp'], 44.3)
        self.assertEqual(after['tme'], 1360100)
        self.assertEqual(after['debtInterestPctGdp'], 4.2)
        self.assertEqual(next(i['pctGdp'] for i in after['items'] if i['name'] == 'Health'), 8.4)
        for row in data['years']:
            self.assertAlmostEqual(sum(i['value'] for i in row['items']), row['total'])
            self.assertAlmostEqual(sum(i['pctGdp'] for i in row['items']), row['totalPctGdp'])
        self.assertNotIn('Debt interest', [i['name'] for i in after['items']])
        self.assertLess(next(i['value'] for i in after['items'] if i['name'] == 'EU transactions'), 0)

    def test_missing_or_misaligned_history_is_rejected(self):
        raw = self.modified(lambda book: setattr(book['4_4']['B5'], 'value', '2002-03'))
        with self.assertRaisesRegex(ValueError, 'discontinuous'):
            parse_pesa_history(raw)
        raw = self.modified(lambda book: setattr(book['4_2']['B20'], 'value', None))
        with self.assertRaisesRegex(ValueError, 'Missing PESA history value'):
            parse_pesa_history(raw)

    def test_corrupt_bridge_and_units_are_rejected(self):
        raw = self.modified(lambda book: setattr(book['4_4']['B27'], 'value', 80))
        with self.assertRaisesRegex(ValueError, 'TES to TME bridge'):
            parse_pesa_history(raw)
        raw = self.modified(lambda book: [setattr(c, 'value', '£ million') for c in book['4_2'][3] if c.value == '£ billion'])
        with self.assertRaisesRegex(ValueError, 'units'):
            parse_pesa_history(raw)

class GDPTests(unittest.TestCase):
    fixture = Path(__file__).parent/'fixtures/gdp-bktl.csv'

    def modified(self, fn):
        rows = list(csv.reader(io.StringIO(self.fixture.read_text())))
        fn(rows)
        output = io.StringIO()
        csv.writer(output).writerows(rows)
        return output.getvalue().encode()

    def test_official_four_quarter_total_and_release(self):
        data = parse_gdp(self.fixture.read_bytes())
        self.assertEqual(data['releaseDate'], '2026-08-13')
        self.assertEqual(data['asOf'], '2026-06')
        # Independent sum of published 2025 Q3 through 2026 Q2 observations.
        self.assertEqual(data['observations'][-1]['rollingAnnualMillion'],
                         760095 + 773133 + 789783 + 780013)
        self.assertFalse(any(o['date'] == '2026-07' for o in data['observations']))

    def test_missing_quarter_is_not_bridged(self):
        raw = self.modified(lambda rows: rows.remove(next(r for r in rows if r[0] == '2025 Q4')))
        data = parse_gdp(raw)
        self.assertIsNone(data['observations'][-1]['rollingAnnualMillion'])
        self.assertIsNone(next(r for r in data['observations'] if r['date'] == '2025-12')['rollingAnnualMillion'])

    def test_wrong_series_and_nonpositive_gdp_fail(self):
        raw = self.modified(lambda rows: rows[1].__setitem__(1, 'YBHA'))
        with self.assertRaisesRegex(ValueError, 'Expected ONS BKTL'):
            parse_gdp(raw)
        raw = self.modified(lambda rows: rows[-1].__setitem__(1, '0'))
        with self.assertRaisesRegex(ValueError, 'positive'):
            parse_gdp(raw)

    def test_duplicate_quarter_fails(self):
        raw = self.modified(lambda rows: rows.append(rows[-1].copy()))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_gdp(raw)

    def test_fiscal_refresh_includes_independent_gdp_source(self):
        inputs = {ONS_URL: FIXTURE.read_bytes(), GDP_URL: self.fixture.read_bytes()}
        data = fetch_fiscal(inputs.__getitem__)
        self.assertEqual(data['asOf'], '2026-07')
        self.assertEqual(data['gdp']['asOf'], '2026-06')
        self.assertEqual(data['gdp']['sources'][0]['id'], 'ons-gdp-bktl')

if __name__=='__main__':unittest.main()

class SocialProtectionTests(unittest.TestCase):
    def test_published_pensions_and_services_reconcile(self):
        import json
        data=json.loads((Path(__file__).parents[1]/'public/data/composition.json').read_text())
        years=data['socialProtection']
        self.assertEqual([y['year'] for y in years],['2021-22','2022-23','2023-24','2024-25','2025-26'])
        for year in years:
            self.assertAlmostEqual(sum(i['value'] for i in year['items']),year['total'])
        self.assertEqual([i['value'] for i in years[-1]['items']],[154858,196277,56135])
