"""US Treasury par yield curve adapter on trimmed real Treasury CSV fixtures (public domain)."""
import copy
import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from pipeline.us import curve as us_curve
from pipeline.us.curve import csv_url, fetch_curve, parse_csv, validate_curve

FIXTURES = Path(__file__).parent / 'fixtures/us/curve'
TODAY = date(2026, 10, 26)


def read(kind, year):
    name = 'daily_treasury_yield_curve' if kind == 'nominal' else 'daily_treasury_real_yield_curve'
    return (FIXTURES / f'{name}-{year}.csv').read_bytes()


def fetcher(overrides=None):
    overrides = overrides or {}
    def fetch(url, headers=None):
        if not url.startswith('https://'):
            raise ValueError('HTTPS only')
        match = re.search(r'csv/(\d{4})/all\?type=(\w+)&field_tdr_date_value=\1&page&_format=csv$', url)
        kind = 'real' if match[2] == 'daily_treasury_real_yield_curve' else 'nominal'
        key = (kind, int(match[1]))
        return overrides[key] if key in overrides else read(*key)
    return fetch


def small_thresholds():
    return mock.patch.multiple(us_curve, MIN_CURVE_DATES=20, MIN_BENCHMARKS=40)


class UsCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_curve(fetcher(), today=TODAY)

    def test_url_is_https_yearly_csv(self):
        self.assertEqual(csv_url(2026, 'real'), 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026&page&_format=csv')

    def test_nominal_tenors_converted_to_years_and_sorted(self):
        curves = parse_csv(read('nominal', 2026), 'nominal', 2026)
        points = curves['2026-10-23']
        self.assertEqual([p['tenor'] for p in points], [0.083333, 0.125, 0.166667, 0.25, 0.333333, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
        self.assertEqual(points[-1], {'tenor': 30.0, 'rate': 5.33})
        self.assertEqual(points[7], {'tenor': 2.0, 'rate': 4.69})

    def test_blank_cells_stay_null_and_missing_columns_are_omitted(self):
        early_2018 = parse_csv(read('nominal', 2018), 'nominal', 2018)['2018-01-02']
        self.assertIn({'tenor': 0.166667, 'rate': None}, early_2018)
        y2006 = parse_csv(read('nominal', 2006), 'nominal', 2006)
        self.assertIn({'tenor': 30.0, 'rate': None}, y2006['2006-01-03'])
        self.assertNotIn(0.166667, [p['tenor'] for p in y2006['2006-01-03']])
        real_2006 = parse_csv(read('real', 2006), 'real', 2006)['2006-12-29']
        self.assertEqual([p['tenor'] for p in real_2006], [5.0, 7.0, 10.0, 20.0])

    def test_output_shape_and_identities(self):
        d = self.data
        with small_thresholds():
            validate_curve(d)
        self.assertEqual((d['asOf'], d['realAsOf'], d['breakevenAsOf'], d['benchmarksAsOf']), ('2026-10-23',) * 4)
        self.assertEqual(d['curves'][0]['date'], '2017-01-04')  # last January 2017 row in the trimmed fixture
        self.assertEqual([c['date'] for c in d['curves']], [c['date'] for c in d['realCurves']])
        latest = d['breakevenCurves'][-1]['points']
        self.assertEqual([p['tenor'] for p in latest], [5.0, 7.0, 10.0, 20.0, 30.0])
        self.assertAlmostEqual(latest[2]['rate'], 5.00 - 2.66, places=9)
        self.assertEqual(d['benchmarks'][-1], {'date': '2026-10-23', 'nominal2y': 4.69, 'nominal5y': 4.82, 'nominal10y': 5.0, 'nominal30y': 5.33, 'indexed10y': 2.66})
        self.assertAlmostEqual(d['breakeven10y'][-1]['value'], 2.34, places=9)
        self.assertTrue(all(s['url'].startswith('https://') for s in d['sources']))
        self.assertIn('par', d['basis'].lower())
        self.assertIn('not zero-coupon', d['basis'])

    def test_old_history_thinned_to_month_ends(self):
        dates = [c['date'] for c in self.data['curves']]
        self.assertNotIn('2017-01-03', dates)  # superseded by the later January 2017 observation
        self.assertIn('2017-12-29', dates)
        self.assertNotIn('2017-12-28', dates)
        self.assertIn('2017-01-03', [r['date'] for r in self.data['benchmarks']])  # benchmarks keep every day

    def test_missing_real_value_gives_null_breakeven(self):
        raw = read('real', 2026).replace(b'10/23/2026,2.34,2.49,2.66,', b'10/23/2026,2.34,2.49,,')
        d = fetch_curve(fetcher({('real', 2026): raw}), today=TODAY)
        self.assertEqual(d['breakevenCurves'][-1]['points'][2], {'tenor': 10.0, 'rate': None})
        self.assertNotIn('2026-10-23', [b['date'] for b in d['breakeven10y']])
        with small_thresholds():
            validate_curve(d)

    def test_empty_current_year_tolerated_but_not_past_years(self):
        header = read('nominal', 2026).split(b'\n', 1)[0]
        real_header = read('real', 2026).split(b'\n', 1)[0]
        d = fetch_curve(fetcher({('nominal', 2027): header, ('real', 2027): real_header}), today=date(2027, 1, 1))
        self.assertEqual(d['asOf'], '2026-10-23')
        with self.assertRaises(ValueError):
            fetch_curve(fetcher({('nominal', 2020): header}), today=TODAY)

    def test_validator_rejects_bad_data(self):
        def broken(change):
            d = copy.deepcopy(self.data)
            change(d)
            with small_thresholds(), self.assertRaises(ValueError):
                validate_curve(d)
        broken(lambda d: d['curves'][-1]['points'][3].update(rate=40.0))
        broken(lambda d: d['curves'][-1]['points'][3].update(rate=float('nan')))
        broken(lambda d: d['curves'][-1]['points'].reverse())
        broken(lambda d: d['curves'][-1]['points'][3].update(tenor=0.3))
        broken(lambda d: d['realCurves'][-1]['points'][0].update(tenor=1.0))
        broken(lambda d: d['curves'].insert(0, d['curves'][-1]))
        broken(lambda d: d.update(realCurves=d['realCurves'][:-1]))
        broken(lambda d: d['breakevenCurves'][-1]['points'][2].update(rate=2.0))
        broken(lambda d: d['breakevenCurves'].pop(5))
        broken(lambda d: d['benchmarks'][-1].update(nominal10y=4.9))
        broken(lambda d: d['benchmarks'].append(d['benchmarks'][-1]))
        broken(lambda d: d['breakeven10y'][-1].update(value=d['breakeven10y'][-1]['value'] + 1e-4))
        broken(lambda d: d['breakeven10y'].pop())
        broken(lambda d: d.update(asOf='2026-10-22'))
        broken(lambda d: d.update(curves=d['curves'][:10]))
        with self.assertRaises(ValueError):
            validate_curve(self.data)  # fixture is far below the live minimum counts

    def test_parser_rejects_bad_source(self):
        raw = read('nominal', 2026)
        for bad in (raw.replace(b'"4 Mo"', b'"9 Mo"'), raw.replace(b'"10 Yr"', b'"10 Wk"'),
                    raw.replace(b',5.00,5.37,', b',50.00,5.37,'), raw.replace(b',5.00,5.37,', b',N/A,5.37,'),
                    raw.replace(b'10/22/2026', b'10/23/2026'), raw.replace(b'10/22/2026', b'2026-10-22'),
                    b'<!DOCTYPE html><html></html>'):
            with self.assertRaises(ValueError):
                parse_csv(bad, 'nominal', 2026)
        with self.assertRaises(ValueError):
            parse_csv(raw, 'nominal', 2025)
        with self.assertRaises(ValueError):
            parse_csv(raw, 'real', 2026)


if __name__ == '__main__':
    unittest.main()


def with_frb(raw=None):
    base = fetcher()
    def fetch(url, headers=None):
        if url == us_curve.FRB_URL:
            return raw if raw is not None else (FIXTURES / 'feds200805-trimmed.csv').read_bytes()
        return base(url, headers)
    return fetch


class FedTipsOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fetch_curve(with_frb(), today=TODAY)

    def test_overlay_kept_on_treasury_dates_only_with_2_to_20_year_par_points(self):
        dates = [c['date'] for c in self.data['frbBreakevenCurves']]
        self.assertEqual(dates, ['2017-01-04', '2017-12-29', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16'])
        self.assertNotIn('2026-10-12', dates)  # Columbus Day: in the Fed file, no Treasury curve.
        self.assertEqual(self.data['frbAsOf'], '2026-10-16')
        latest = self.data['frbBreakevenCurves'][-1]['points']
        self.assertEqual([p['tenor'] for p in latest], [float(t) for t in range(2, 21)])
        self.assertEqual(latest[0]['rate'], 2.3649)  # BKEVENPY02 on 2026-10-16, rounded to 4 decimals.
        self.assertIn('frb-tips', [s['id'] for s in self.data['sources']])
        with small_thresholds():
            validate_curve(self.data)

    def test_overlay_failure_keeps_treasury_curves_and_is_recorded(self):
        data = fetch_curve(with_frb(b'<html>maintenance</html>'), today=TODAY)
        self.assertEqual(data['frbRealCurves'], [])
        self.assertIn('Date header', data['frbError'])
        self.assertTrue(data['curves'])
        with small_thresholds():
            validate_curve(data)
            silent = {**data, 'frbError': None}
            with self.assertRaisesRegex(ValueError, 'download failure'):
                validate_curve(silent)

    def test_overlay_dates_must_have_a_treasury_curve(self):
        data = copy.deepcopy(self.data)
        data['frbRealCurves'][-1]['date'] = '2026-10-17'
        with small_thresholds(), self.assertRaisesRegex(ValueError, 'without a Treasury curve'):
            validate_curve(data)
