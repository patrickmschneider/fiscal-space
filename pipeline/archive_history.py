"""Keep compact, immutable dashboard vintages in a separate Git checkout.

Only normalized JSON is copied. Source workbooks, PDFs and raw downloads stay
local. Commit the destination to the data-history branch after this completes.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CORE_GROUPS = ('fiscal', 'composition', 'forecast', 'debt', 'curve')
GROUPS = (*CORE_GROUPS, 'outlook', 'reliefs', 'monitor')
RELEASE = re.compile(r'((?:au-)?(?:' + '|'.join(GROUPS) + r'))-([a-f0-9]{64})\.json$')
# The Australian edition's saved data; archived alongside the UK bundle under an au/ prefix.
AU_DATA = 'public-au/data'
AU_FILES = {f'au/{name}.json' for name in (*GROUPS, 'manifest')}


def object_stem(name):
    return name[:-5].replace('/', '-')


def saved_path(root, name):
    return root / AU_DATA / name[3:] if name.startswith('au/') else root / 'public/data' / name


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def immutable(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Archive object does not match its content address: {path}')
    else:
        atomic(path, raw)


def compressed_object(destination, directory, name, raw):
    # JSON validation rejects accidentally supplied binary/raw source files.
    json.loads(raw)
    relative = f'{directory}/{name}.json.gz'
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, compresslevel=9, mtime=0) as output:
        output.write(raw)
    immutable(destination / relative, buffer.getvalue())
    return {'path': relative, 'sha256': digest(raw), 'bytes': len(raw)}


def archive(destination, code_sha, migrate_local=False, root=ROOT):
    root, destination = Path(root), Path(destination)
    if not re.fullmatch(r'[a-f0-9]{40}', code_sha):
        raise ValueError('Provide the full 40-character Git commit SHA')
    migrated = 0
    if migrate_local:
        for source in sorted((root / 'data/archive/releases').glob('*.json')):
            match = RELEASE.fullmatch(source.name)
            if not match:
                continue
            group, release_id = match.groups()
            raw = source.read_bytes()
            if digest(raw) != release_id:
                raise ValueError(f'Local release checksum mismatch: {source.name}')
            compressed_object(destination, 'releases', f'{group}-{release_id}', raw)
            metadata_path = source.with_name(source.stem + '.metadata.json')
            if metadata_path.exists():
                metadata_raw = metadata_path.read_bytes()
                metadata = json.loads(metadata_raw)
                if metadata.get('group') != group.removeprefix('au-') or metadata.get('releaseId') != release_id:
                    raise ValueError(f'Local metadata mismatch: {metadata_path.name}')
                compressed_object(destination, 'metadata',
                                  f'{group}-{release_id}-{digest(metadata_raw)}', metadata_raw)
            migrated += 1

    files = {}
    # An explicit allowlist avoids publishing future private files in this directory.
    for name in (*GROUPS, 'manifest'):
        source = root / f'public/data/{name}.json'
        if name not in (*CORE_GROUPS, 'manifest') and not source.exists():
            continue
        raw = source.read_bytes()
        files[f'{name}.json'] = compressed_object(destination, 'releases',
                                                   f'{name}-{digest(raw)}', raw)
    for name in sorted(AU_FILES):
        source = saved_path(root, name)
        if source.exists():
            raw = source.read_bytes()
            files[name] = compressed_object(destination, 'releases', f'{object_stem(name)}-{digest(raw)}', raw)
    record = {'schemaVersion': 1, 'codeSha': code_sha, 'files': files}
    record_raw = encode(record)
    snapshot_id = digest(record_raw)
    immutable(destination / f'deployments/{snapshot_id}.json', record_raw)
    atomic(destination / 'latest.json', encode({
        'schemaVersion': 1, 'snapshotId': snapshot_id,
        'record': f'deployments/{snapshot_id}.json',
    }))
    return {'snapshotId': snapshot_id, 'migratedReleases': migrated,
            'compressedBytes': sum(p.stat().st_size for folder in ('releases', 'metadata')
                                   for p in (destination / folder).glob('*.gz'))}


def restore(destination, snapshot_id, root=ROOT, code_sha=None):
    destination, root = Path(destination), Path(root)
    if not re.fullmatch(r'[a-f0-9]{64}', snapshot_id):
        raise ValueError('Snapshot ID must be a SHA-256 hash')
    raw = (destination / f'deployments/{snapshot_id}.json').read_bytes()
    if digest(raw) != snapshot_id:
        raise ValueError('Deployment record checksum mismatch')
    record = json.loads(raw)
    if record.get('schemaVersion') != 1:
        raise ValueError('Unsupported deployment record schema')
    if code_sha is not None and code_sha != record['codeSha']:
        raise ValueError(f"Snapshot requires code SHA {record['codeSha']}")
    expected = {f'{name}.json' for name in (*CORE_GROUPS, 'manifest')}
    allowed = {f'{name}.json' for name in (*GROUPS, 'manifest')} | AU_FILES
    if not expected.issubset(record['files']) or not set(record['files']).issubset(allowed):
        raise ValueError('Snapshot does not contain the expected dashboard bundle')
    pending = {}
    for name, ref in record['files'].items():
        expected_path = f"releases/{object_stem(name)}-{ref['sha256']}.json.gz"
        if not re.fullmatch(r'[a-f0-9]{64}', ref['sha256']) or ref['path'] != expected_path:
            raise ValueError('Invalid snapshot object path')
        payload = gzip.decompress((destination / ref['path']).read_bytes())
        if digest(payload) != ref['sha256'] or len(payload) != ref['bytes']:
            raise ValueError(f'Snapshot payload checksum mismatch: {name}')
        json.loads(payload)
        pending[name] = payload
    # Validate the whole bundle before replacing any file.
    for name, payload in pending.items():
        atomic(saved_path(root, name), payload)
    for name in allowed - set(record['files']):
        saved_path(root, name).unlink(missing_ok=True)
    return {'snapshotId': snapshot_id, 'requiredCodeSha': record['codeSha'],
            'restoredFiles': len(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--code-sha', help='Required when archiving; when restoring, enforces the matching code SHA')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--restore', metavar='SNAPSHOT_ID', help='Restore a verified bundle; reports its required code SHA')
    parser.add_argument('--migrate-local', action='store_true',
                        help='Include every locally archived normalized release and its input metadata')
    args = parser.parse_args()
    if args.restore:
        if args.migrate_local:
            parser.error('--restore and --migrate-local cannot be combined')
        result = restore(args.destination, args.restore, args.root, args.code_sha)
    else:
        if not args.code_sha:
            parser.error('--code-sha is required when archiving')
        result = archive(args.destination, args.code_sha, args.migrate_local, args.root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
