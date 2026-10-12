"""TEIS tax expenditures adapter on trimmed real Treasury fixtures (CC BY 4.0)."""
import copy
import io
import unittest
from pathlib import Path

import openpyxl

from pipeline.au import teis
from pipeline.au.teis import fetch_reliefs, links, parse_reliefs, validate_reliefs

FIXTURES = Path(__file__).parent / 'fixtures/au/teis'
PAGE = (FIXTURES / 'page.html').read_bytes()
XLSX = (FIXTURES / 'chart-data.xlsx').read_bytes()
DOCX = (FIXTURES / 'appendix.docx').read_bytes()
XLSX_URL = 'https://treasury.gov.au/sites/default/files/2025-12/p2025-721342-chart-data.xlsx'
DOCX_URL = 'https://treasury.gov.au/sites/default/files/2025-12/p2025-721342.docx'


def fetcher(url, headers=None):
    return {teis.PAGE: PAGE, XLSX_URL: XLSX, DOCX_URL: DOCX}[url]


def item(data, code):
    return next(r for r in data['reliefs'] if r['id'] == code)


class TeisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_reliefs(fetcher)

    def test_publication_page_gives_edition_links(self):
        self.assertEqual(links(PAGE.decode()), ('2025-12-17', XLSX_URL, DOCX_URL))
        with self.assertRaises(ValueError):
            links(PAGE.decode().replace('2025–26 Tax', '2026–27 Tax'))

    def test_inventory_and_join(self):
        d = self.data
        self.assertEqual((len(d['reliefs']), d['years'][0], d['years'][-1], d['asOf']), (304, '2021-22', '2028-29', '2025-12-17'))
        food = item(d, 'H25')
        self.assertEqual((food['taxHead'], food['estimates'][4]['costMillion'], food['estimates'][4]['status']), ('Goods and services tax', 9900.0, 'forecast'))
        self.assertEqual(food['estimates'][3]['status'], 'estimate')
        c2 = item(d, 'C2')
        self.assertEqual((c2['taxExpenditureType'], c2['reliability'], c2['functionalCategory'], c2['previousCode']),
                         ('Exemption, Concessional rate', 'Medium', 'Social security and welfare', 'C2'))
        self.assertEqual(item(d, 'E8')['estimates'][4]['costMillion'], 32000.0)

    def test_missing_codes_stay_null(self):
        d = self.data
        a14 = item(d, 'A14')
        self.assertEqual({(e['status'], e['costMillion']) for e in a14['estimates']}, {('unquantifiable', None)})
        self.assertEqual(a14['magnitudeCategory']['sign'], 'negative')
        a13 = item(d, 'A13')
        self.assertEqual((a13['estimates'][0]['status'], a13['estimates'][0]['includedIn']), ('included elsewhere', 'A43'))
        counts = {}
        for r in d['reliefs']:
            for e in r['estimates']:
                counts[e['rawValue']] = counts.get(e['rawValue'], 0) + 1
        self.assertEqual((counts['*'], counts['-'], counts['..'], counts['nfp']), (1175, 123, 91, 4))

    def test_no_official_total_and_derived_sums(self):
        d = self.data
        self.assertIsNone(d['aggregate']['costMillion'])
        total = next(t for t in d['derivedTotals']['all'] if t['year'] == '2025-26')
        expected = sum(r['estimates'][4]['costMillion'] for r in d['reliefs'] if r['estimates'][4]['costMillion'] is not None)
        self.assertEqual(total['quantifiedSumMillion'], expected)
        self.assertEqual(total['quantifiedCount'] + sum(total['excluded'].values()), 304)
        self.assertEqual(d['superannuation']['codes'], [f'C{i}' for i in range(1, 13)])
        self.assertIsNone(d['isa'])

    def test_workbook_appendix_disagreement_fails(self):
        book = openpyxl.load_workbook(io.BytesIO(XLSX))
        ws = book['Revenue forgone estimates']
        row = next(r for r in ws.iter_rows() if r[0].value == 'H25')
        row[6].value = 9901
        out = io.BytesIO()
        book.save(out)
        with self.assertRaisesRegex(ValueError, 'disagrees with appendix'):
            parse_reliefs(out.getvalue(), DOCX, '2025-12-17', XLSX_URL, DOCX_URL)

    def test_validator_rejects_bad_data(self):
        validate_reliefs(self.data)
        cases = [
            lambda d: item(d, 'A14')['estimates'][0].update(costMillion=0.0),
            lambda d: d['aggregate'].update(costMillion=230000),
            lambda d: d.update(isa={'history': []}),
            lambda d: d['reliefs'].append(copy.deepcopy(d['reliefs'][0])),
            lambda d: d['derivedTotals']['all'][4].update(quantifiedSumMillion=1.0),
            lambda d: d.update(reliefs=d['reliefs'][:100]),
        ]
        for mutate in cases:
            bad = copy.deepcopy(self.data)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_reliefs(bad)


if __name__ == '__main__':
    unittest.main()
