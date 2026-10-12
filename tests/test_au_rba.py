"""RBA F17/F2 curve adapter on trimmed real RBA CSV fixtures (CC BY 4.0)."""
import copy
import unittest
from pathlib import Path

from pipeline.au.rba import F17_URL, F2_URL, fetch_curve, parse_f17, parse_f2, validate_curve

FIXTURES = Path(__file__).parent / 'fixtures/au/rba'
F17 = (FIXTURES / 'f17-yields.csv').read_bytes()
F2 = (FIXTURES / 'f2-data.csv').read_bytes()


def fetcher(f17=F17, f2=F2):
    return lambda url, headers=None: {F17_URL: f17, F2_URL: f2}[url]


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
        self.assertEqual((d['realCurves'], d['breakevenCurves']), ([], []))
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
