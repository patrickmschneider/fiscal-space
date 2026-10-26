from datetime import date
import unittest
from pipeline import obr_check
from pipeline.obr_check import check, find_newer, vintage_month

MARCH=date(2026,3,3)
EFO={'title':'November 2026 Economic and fiscal outlook','base_path':'/government/publications/november-2026-economic-and-fiscal-outlook','first_published_at':'2026-11-25T12:00:00+00:00'}


def fake(search=(),pages=None):
    def get(url,**params):
        if url==obr_check.SEARCH_URL:return {'results':list(search)}
        return (pages or {}).get(url.rsplit('/',1)[1])
    return get


class ObrCheckTests(unittest.TestCase):
    def test_titles_and_slugs_name_their_month(self):
        self.assertEqual(vintage_month('March 2026 Economic and fiscal outlook'),(2026,3))
        self.assertEqual(vintage_month('Economic and fiscal outlook: October 2018'),(2018,10))
        self.assertEqual(vintage_month('november-2026-economic-and-fiscal-outlook'),(2026,11))

    def test_pinned_vintage_updated_later_is_not_newer(self):
        search=[{'title':'March 2026 Economic and fiscal outlook','link':'/government/publications/march-2026-economic-and-fiscal-outlook','public_timestamp':'2026-03-12T00:00:00Z'}]
        self.assertEqual(find_newer(MARCH,date(2026,10,26),fake(search)),[])

    def test_unindexed_newer_efo_is_found_by_slug(self):
        found=find_newer(MARCH,date(2026,11,30),fake(pages={'november-2026-economic-and-fiscal-outlook':EFO}))
        self.assertEqual([(r['title'],r['publishedAt']) for r in found],[('November 2026 Economic and fiscal outlook','2026-11-25')])

    def test_other_publications_are_ignored(self):
        search=[{'title':'Fiscal risks and sustainability – July 2026','link':'/x','public_timestamp':'2026-07-07T00:00:00Z'}]
        self.assertEqual(find_newer(MARCH,date(2026,10,26),fake(search)),[])

    def test_failed_check_keeps_an_earlier_detection(self):
        def broken(url,**params):raise RuntimeError('timeout')
        previous=check(date(2026,11,30),fake(pages={'november-2026-economic-and-fiscal-outlook':EFO}))
        self.assertEqual(previous['status'],'outdated')
        failed=check(date(2026,12,1),broken,previous)
        self.assertEqual((failed['status'],failed['newer']),('outdated',previous['newer']))
        self.assertEqual(check(date(2026,12,1),broken)['status'],'unknown')

    def test_oldest_pinned_input_sets_the_comparison(self):
        outlook={'latestVintage':'2025-11','vintages':[{'id':'2025-11','label':'November 2025','publicationDate':'2025-11-26'}]}
        efo={**EFO,'title':'March 2026 Economic and fiscal outlook','base_path':'/government/publications/march-2026-economic-and-fiscal-outlook','first_published_at':'2026-03-03T12:30:00+00:00'}
        result=check(date(2026,10,26),fake(pages={'march-2026-economic-and-fiscal-outlook':efo}),outlook=outlook)
        self.assertEqual((result['status'],result['pinned']['vintage']),('outdated','November 2025 Economic and fiscal outlook'))
        current={'latestVintage':'2026-03','vintages':[{'id':'2026-03','label':'March 2026','publicationDate':'2026-03-03'}]}
        self.assertEqual(check(date(2026,10,26),fake(),outlook=current)['status'],'current')


if __name__=='__main__':
    unittest.main()
