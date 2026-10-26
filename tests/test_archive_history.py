import gzip
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.archive_history import GROUPS, CORE_GROUPS, archive, digest, encode, restore


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.destination = Path(self.temp.name) / 'history'
        (self.root / 'public/data').mkdir(parents=True)
        for name in (*GROUPS, 'manifest'):
            (self.root / f'public/data/{name}.json').write_bytes(encode({'name': name, 'value': 1}))
        self.sha = 'a' * 40

    def test_snapshot_round_trip_deduplication_and_new_vintage(self):
        first = archive(self.destination, self.sha, root=self.root)
        record_path = self.destination / f"deployments/{first['snapshotId']}.json"
        self.assertEqual(digest(record_path.read_bytes()), first['snapshotId'])
        record = json.loads(record_path.read_bytes())
        self.assertEqual(record['codeSha'], self.sha)
        for filename, ref in record['files'].items():
            raw = gzip.decompress((self.destination / ref['path']).read_bytes())
            self.assertEqual(digest(raw), ref['sha256'])
            self.assertEqual(raw, (self.root / 'public/data' / filename).read_bytes())
        original_objects = {p.name: p.read_bytes() for p in (self.destination / 'releases').iterdir()}
        self.assertEqual(first, archive(self.destination, self.sha, root=self.root))
        (self.root / 'public/data/fiscal.json').write_bytes(encode({'value': 2}))
        second = archive(self.destination, self.sha, root=self.root)
        self.assertNotEqual(first['snapshotId'], second['snapshotId'])
        self.assertEqual(len(list((self.destination / 'releases').iterdir())), len(GROUPS)+2)
        for name, raw in original_objects.items():
            self.assertEqual((self.destination / 'releases' / name).read_bytes(), raw)
        self.assertEqual(json.loads((self.destination / 'latest.json').read_text())['snapshotId'], second['snapshotId'])

    def test_restore_checks_code_and_all_payloads_before_writing(self):
        result = archive(self.destination, self.sha, root=self.root)
        target = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'requires code SHA'):
            restore(self.destination, result['snapshotId'], target, 'b' * 40)
        self.assertFalse(target.exists())
        restored = restore(self.destination, result['snapshotId'], target, self.sha)
        self.assertEqual(restored['requiredCodeSha'], self.sha)
        for name in (*GROUPS, 'manifest'):
            self.assertEqual((target / f'public/data/{name}.json').read_bytes(),
                             (self.root / f'public/data/{name}.json').read_bytes())
        record = json.loads((self.destination / f"deployments/{result['snapshotId']}.json").read_text())
        final_ref = record['files']['manifest.json']
        (self.destination / final_ref['path']).write_bytes(gzip.compress(b'{}'))
        clean_target = self.root / 'must-not-exist'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            restore(self.destination, result['snapshotId'], clean_target)
        self.assertFalse(clean_target.exists())

    def test_migration_preserves_metadata_and_excludes_original_sources(self):
        releases = self.root / 'data/archive/releases'
        releases.mkdir(parents=True)
        raw = encode({'schemaVersion': 1, 'old': True})
        release_id = digest(raw)
        (releases / f'curve-{release_id}.json').write_bytes(raw)
        metadata = {'group': 'curve', 'releaseId': release_id,
                    'inputs': [{'url': 'https://example.org/curve.xlsx', 'sha256': 'b' * 64}]}
        (releases / f'curve-{release_id}.metadata.json').write_bytes(encode(metadata))
        (self.root / 'data/archive/private.xlsx').write_bytes(b'PRIVATE RAW SOURCE')
        (releases / 'private.json').write_text('{"private": true}')
        result = archive(self.destination, self.sha, migrate_local=True, root=self.root)
        self.assertEqual(result['migratedReleases'], 1)
        stored = list((self.destination / 'metadata').glob('*.gz'))
        self.assertEqual(len(stored), 1)
        self.assertEqual(json.loads(gzip.decompress(stored[0].read_bytes())), metadata)
        self.assertEqual(len(list((self.destination / 'releases').glob('*.gz'))), len(GROUPS)+2)
        self.assertFalse(any('private' in p.name for p in self.destination.rglob('*')))

    def test_old_snapshot_removes_new_optional_datasets(self):
        for name in set(GROUPS)-set(CORE_GROUPS):
            (self.root/f'public/data/{name}.json').unlink()
        snapshot=archive(self.destination,self.sha,root=self.root)
        target=self.root/'old-restore';(target/'public/data').mkdir(parents=True)
        (target/'public/data/reliefs.json').write_text('{}')
        restore(self.destination,snapshot['snapshotId'],target,self.sha)
        self.assertFalse((target/'public/data/reliefs.json').exists())

    def test_checksum_failure_does_not_replace_latest(self):
        archive(self.destination, self.sha, root=self.root)
        latest = (self.destination / 'latest.json').read_bytes()
        releases = self.root / 'data/archive/releases'
        releases.mkdir(parents=True)
        (releases / f"curve-{'b' * 64}.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            archive(self.destination, self.sha, migrate_local=True, root=self.root)
        self.assertEqual((self.destination / 'latest.json').read_bytes(), latest)

    def test_corrupted_destination_is_rejected(self):
        archive(self.destination, self.sha, root=self.root)
        next((self.destination / 'releases').glob('*.gz')).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'content address'):
            archive(self.destination, self.sha, root=self.root)


if __name__ == '__main__':
    unittest.main()


class AustralianHistoryTests(unittest.TestCase):
    def test_australian_edition_is_archived_and_restored_beside_the_uk_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root, destination = Path(temp) / 'project', Path(temp) / 'history'
            for folder in ('public/data', 'public-au/data'):
                (root / folder).mkdir(parents=True)
            for name in (*CORE_GROUPS, 'manifest'):
                (root / f'public/data/{name}.json').write_bytes(encode({'country': 'uk', 'name': name}))
                (root / f'public-au/data/{name}.json').write_bytes(encode({'country': 'au', 'name': name}))
            snapshot = archive(destination, 'b' * 40, root=root)['snapshotId']
            record = json.loads((destination / f'deployments/{snapshot}.json').read_bytes())
            self.assertIn('au/fiscal.json', record['files'])
            self.assertTrue(record['files']['au/fiscal.json']['path'].startswith('releases/au-fiscal-'))
            (root / 'public-au/data/fiscal.json').write_bytes(encode({'country': 'au', 'name': 'changed'}))
            restore(destination, snapshot, root=root)
            self.assertEqual(json.loads((root / 'public-au/data/fiscal.json').read_text())['name'], 'fiscal')
            self.assertEqual(json.loads((root / 'public/data/fiscal.json').read_text())['country'], 'uk')

    def test_us_edition_is_archived_and_restored_beside_the_others(self):
        with tempfile.TemporaryDirectory() as temp:
            root, destination = Path(temp) / 'project', Path(temp) / 'history'
            for folder in ('public/data', 'public-au/data', 'public-us/data'):
                (root / folder).mkdir(parents=True)
            for name in (*CORE_GROUPS, 'manifest'):
                for folder, country in (('public/data', 'uk'), ('public-au/data', 'au'), ('public-us/data', 'us')):
                    (root / f'{folder}/{name}.json').write_bytes(encode({'country': country, 'name': name}))
            snapshot = archive(destination, 'c' * 40, root=root)['snapshotId']
            record = json.loads((destination / f'deployments/{snapshot}.json').read_bytes())
            self.assertTrue(record['files']['us/fiscal.json']['path'].startswith('releases/us-fiscal-'))
            (root / 'public-us/data/debt.json').write_bytes(encode({'country': 'us', 'name': 'changed'}))
            restore(destination, snapshot, root=root)
            self.assertEqual(json.loads((root / 'public-us/data/debt.json').read_text()), {'country': 'us', 'name': 'debt'})
            self.assertEqual(json.loads((root / 'public-au/data/debt.json').read_text())['country'], 'au')
