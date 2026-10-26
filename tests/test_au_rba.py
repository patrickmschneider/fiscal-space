"""RBA F17/F2 curve adapter on trimmed real RBA CSV fixtures (CC BY 4.0)."""
import copy
import unittest
from pathlib import Path

from pipeline.au.rba import F16_URL, F17_URL, F2_URL, fetch_curve, indexed_curves, parse_f16, parse_f17, parse_f2, validate_curve

FIXTURES = Path(__file__).parent / 'fixtures/au/rba'
F17 = (FIXTURES / 'f17-yields.csv').read_bytes()
F2 = (FIXTURES / 'f2-data.csv').read_bytes()
F16 = (FIXTURES / 'f16-data.csv').read_bytes()


def fetcher(f17=F17, f2=F2, f16=F16):
    return lambda url, headers=None: {F17_URL: f17, F2_URL: f2, F16_URL: f16}[url]


class RbaCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_curve(fetcher())

    def test_f17_drops_cash_rate_anchor_and_maps_tenors(self):
        curves, published = parse_f17(F17)
        self.assertEqual(published, '2026-10-02')
        points = curves['2026-09-30']
        self.assertEqual([p['tenor'] for p in points], [i / 4 for i in range(1, 41)])
        self.assertEqual(points[0], {'tenor': 0.25, 'rate': 4.63})
        self.assertEqual(points[-1], {'tenor': 10.0, 'rate': 5.32})

    def test_f2_parses_series_by_id(self):
        rows, published = parse_f2(F2)
        self.assertEqual(published, '2026-10-09')
        self.assertEqual(rows[-1], {'date': '2026-10-07', 'nominal2y': 4.94, 'nominal3y': 4.933, 'nominal5y': 5.014, 'nominal10y': 5.404, 'indexed10y': 3.002})

    def test_output_shape_and_breakeven_identity(self):
        d = self.data
        validate_curve(d)
        self.assertEqual((d['asOf'], d['benchmarksAsOf']), ('2026-09-30', '2026-10-07'))
        self.assertEqual(d['realAsOf'], '2026-09-30')
        self.assertTrue({c['date'] for c in d['breakevenCurves']} <= {c['date'] for c in d['curves']})
        self.assertGreaterEqual(len(d['curves']), 200)
        self.assertAlmostEqual(d['breakeven10y'][-1]['value'], 5.404 - 3.002, places=12)

    def test_breakeven_only_on_matched_dates(self):
        line = next(l for l in F2.decode('utf-8-sig').splitlines() if l.startswith('07-Oct-2026'))
        d = fetch_curve(fetcher(f2=F2.replace(line.encode(), line.rsplit(',', 1)[0].encode() + b',')))
        self.assertIsNone(d['benchmarks'][-1]['indexed10y'])
        self.assertNotIn('2026-10-07', [b['date'] for b in d['breakeven10y']])
        validate_curve(d)

    def test_validator_rejects_bad_data(self):
        def broken(change):
            d = copy.deepcopy(self.data)
            change(d)
            with self.assertRaises(ValueError):
                validate_curve(d)
        broken(lambda d: d['curves'][-1]['points'][3].update(rate=40.0))
        broken(lambda d: d['curves'][-1]['points'][3].update(rate=float('nan')))
        broken(lambda d: d['curves'][-1]['points'].reverse())
        broken(lambda d: d.update(curves=d['curves'][:150]))
        broken(lambda d: d['curves'].insert(0, d['curves'][-1]))
        broken(lambda d: d['benchmarks'].append(d['benchmarks'][-1]))
        broken(lambda d: d['breakeven10y'][-1].update(value=d['breakeven10y'][-1]['value'] + 1e-6))
        broken(lambda d: d['breakeven10y'].pop())
        broken(lambda d: d.update(realCurves=d['curves'][:1]))
        broken(lambda d: d.update(benchmarksAsOf='2026-10-08'))

    def test_parser_rejects_bad_source(self):
        with self.assertRaises(ValueError):
            parse_f17(F17.replace(b'FZCY1000D', b'FZCY1100D'))
        with self.assertRaises(ValueError):
            parse_f2(F2.replace(b'FCMYGBAGID', b'FCMYGBAGXX'))
        with self.assertRaises(ValueError):
            parse_f2(F2.replace(b',5.404,', b',55.404,'))


if __name__ == '__main__':
    unittest.main()


class IndexedBondCurveTests(unittest.TestCase):
    def test_real_and_breakeven_points_at_indexed_bond_maturities(self):
        bonds, _ = parse_f16(F16)
        real, breakeven = indexed_curves(bonds['2026-09-30'], '2026-09-30')
        self.assertEqual(real[0], {'tenor': 1.1417, 'rate': 1.791})  # TIB 414, Nov 2027
        self.assertEqual(len(real), 6)
        self.assertEqual([p['tenor'] for p in breakeven], [p['tenor'] for p in real])
        self.assertAlmostEqual(breakeven[-1]['rate'], 2.339956, places=6)  # Feb 2050 TIB against bracketing nominal bonds

    def test_short_indexed_bonds_and_unbracketed_maturities_are_left_out(self):
        day = {'nominal': [('2030-01-01', 4.0), ('2040-01-01', 5.0)], 'indexed': [('2027-03-01', 1.0), ('2035-01-01', 2.0), ('2045-01-01', 2.5)]}
        real, breakeven = indexed_curves(day, '2026-09-30')
        self.assertEqual(len(real), 2)  # March 2027 has under a year to run.
        self.assertEqual(len(breakeven), 1)  # 2045 lies beyond the longest nominal bond.
        self.assertAlmostEqual(breakeven[0]['rate'], 2.5, places=2)

    def test_breakevens_must_sit_on_real_maturities(self):
        data = copy.deepcopy(fetch_curve(fetcher()))
        data['breakevenCurves'][-1]['points'][0]['tenor'] += 0.5
        with self.assertRaisesRegex(ValueError, 'indexed-bond maturities|maturities invalid'):
            validate_curve(data)
