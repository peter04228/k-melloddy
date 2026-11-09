import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'src/k_melloddy/restore_checkpoint.ps1'
POWERSHELL = shutil.which('powershell')
pytestmark = pytest.mark.skipif(not POWERSHELL, reason='Windows PowerShell required')


def checkpoint(tmp_path, member='projects/example/record.txt'):
    downloads = tmp_path / 'downloads'
    destination = tmp_path / 'clone'
    downloads.mkdir()
    destination.mkdir()
    name = 'k-melloddy-liver-15860-checkpoint-20261109.zip'
    archive = tmp_path / name
    content = b'captured evidence, unchanged\n'
    internal = dict(schema='k-melloddy-checkpoint-v1', files=[dict(
        path=member, bytes=len(content), sha256=hashlib.sha256(content).hexdigest())])
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(member, content)
        z.writestr('CHECKPOINT_MANIFEST_20261109.json', json.dumps(internal))
    raw = archive.read_bytes()
    pieces = [raw[:len(raw)//2], raw[len(raw)//2:]]
    parts = []
    for i, block in enumerate(pieces, 1):
        part_name = name + f'.part{i:03d}'
        (downloads / part_name).write_bytes(block)
        parts.append(dict(name=part_name, bytes=len(block), sha256=hashlib.sha256(block).hexdigest()))
    manifest = dict(schema='k-melloddy-download-v1', archive_name=name,
                    archive_bytes=len(raw), archive_sha256=hashlib.sha256(raw).hexdigest(), parts=parts)
    (downloads / 'checkpoint_download.json').write_text(json.dumps(manifest), encoding='utf-8')
    return downloads, destination, member, content


def restore(downloads, destination):
    return subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(SCRIPT), '-DownloadDirectory', str(downloads),
                           '-Destination', str(destination)], capture_output=True, timeout=30)


def test_restore_and_idempotent_resume(tmp_path):
    downloads, destination, member, content = checkpoint(tmp_path)
    result = restore(downloads, destination)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (destination/member).read_bytes() == content
    before = (destination/member).stat().st_mtime_ns
    result = restore(downloads, destination)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (destination/member).stat().st_mtime_ns == before


def test_existing_modified_file_is_preserved(tmp_path):
    downloads, destination, member, _ = checkpoint(tmp_path)
    p = destination/member
    p.parent.mkdir(parents=True)
    p.write_bytes(b'user modification')
    assert restore(downloads, destination).returncode != 0
    assert p.read_bytes() == b'user modification'
    assert not (destination/'CHECKPOINT_MANIFEST_20261109.json').exists()


def test_parent_traversal_is_rejected_before_extraction(tmp_path):
    downloads, destination, _, _ = checkpoint(tmp_path, '../escape.txt')
    assert restore(downloads, destination).returncode != 0
    assert not (tmp_path/'escape.txt').exists()
    assert not list(destination.iterdir())


def test_corrupt_part_rejected_before_zip_creation(tmp_path):
    downloads, destination, _, _ = checkpoint(tmp_path)
    part = next(downloads.glob('*.part001'))
    part.write_bytes(b'corrupted')
    assert restore(downloads, destination).returncode != 0
    assert not list(downloads.glob('*.zip'))
    assert not list(destination.iterdir())
