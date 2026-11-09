import hashlib

import pytest

from k_melloddy.core.storage import dump
from k_melloddy.db_select.persistence import atomic_json, json_digest


def test_projection_bytes_and_hash_match_existing_format(tmp_path):
    value={'papers':[{'reason':'간독성 확인 · café', 'n':i, 'raw':'x'*10000}
                     for i in range(20)],'missing':None,'flag':False}
    expected=dump(value).encode('utf-8')
    path=tmp_path/'evidence_log.json'
    sha=atomic_json(path,value)
    assert path.read_bytes()==expected
    assert sha==json_digest(value)==hashlib.sha256(expected).hexdigest()


def test_encoding_failure_preserves_previous_projection(tmp_path):
    path=tmp_path/'evidence_log.json'
    original=b'{"previous":"complete"}'
    path.write_bytes(original)
    with pytest.raises(TypeError):atomic_json(path,{'bad':object()})
    assert path.read_bytes()==original
    assert not list(tmp_path.glob('.pending-*'))


def test_failed_publish_keeps_old_projection_and_cleans_temp(tmp_path,monkeypatch):
    import k_melloddy.db_select.persistence as persistence
    path=tmp_path/'evidence_log.json'
    path.write_bytes(b'previous')
    calls=[]
    def locked(*args):
        calls.append(args)
        raise PermissionError('locked')
    monkeypatch.setattr(persistence.os,'replace',locked)
    monkeypatch.setattr(persistence.time,'sleep',lambda seconds:None)
    with pytest.raises(PermissionError):atomic_json(path,{'new':'complete'})
    assert path.read_bytes()==b'previous'
    assert len(calls)==6
    assert not list(tmp_path.glob('.pending-*'))
