import unittest
from pathlib import Path
from pipeline.pesa_history import parse_source,load_history,merge_releases

FIXTURES=Path(__file__).parent/'fixtures'

class PesaBackHistoryTests(unittest.TestCase):
    def test_pinned_history_is_complete_and_uses_latest_available_release(self):
        data=load_history();years={y['year']:y for y in data['years']}
        self.assertEqual(len(years),18)
        self.assertEqual(years['2003-04']['items'][0]['value'],56039)
        self.assertEqual(years['2003-04']['total'],155614)
        self.assertEqual(years['2019-20']['sourceId'],'pesa-2024-social')
        self.assertEqual(years['2020-21']['sourceId'],'pesa-2025-social')
        source_ids={s['id'] for s in data['sources']}
        for row in years.values():
            self.assertIn(row['sourceId'],source_ids)
            self.assertTrue(all(i['value']>=0 for i in row['items']))

    def test_xlsx_extracts_social_services_subtotal_not_repeated_subfunction_rows(self):
        rows=parse_source((FIXTURES/'pesa-2021-chapter5.xlsx').read_bytes(),{'id':'2021','kind':'xlsx'})
        self.assertEqual(rows[0]['year'],'2016-17')
        self.assertEqual(rows[0]['items'][0]['value'],111413)
        self.assertEqual(len(rows),5)
        self.assertAlmostEqual(sum(i['value'] for i in rows[-1]['items']),rows[-1]['total'])

    def test_ods_and_overlapping_vintages(self):
        rows=parse_source((FIXTURES/'pesa-2019-chapter5.ods').read_bytes(),{'id':'2019','kind':'ods'})
        self.assertEqual(rows[0]['year'],'2014-15')
        self.assertEqual(len(rows),5)
        later={'year':rows[0]['year'],'total':1,'sourceId':'new','items':[]}
        merged=merge_releases([({'vintage':2020},[later]),({'vintage':2019},rows)])
        self.assertEqual(merged[0]['sourceId'],'new')
