import base64
import copy
import json
import pytest
from k_melloddy.core.storage import digest
from k_melloddy.db_select.full_workflow_access import recover_json_metadata


def sample():
    paper=dict(pmid='123',values=dict(PMCID='PMC123',DOI='10.1234/test',Title='Synthetic title.'))
    data=json.dumps(dict(pmid=123,pmcid='PMC123',doi='10.1234/test',title='Synthetic title')).encode()
    record=dict(kind='metadata',status='fetch_error',failure_reason='redirect_or_empty_body_not_article',
        http_status=200,complete_body=True,final_url='https://example.org/metadata.json',
        format='binary/octet-stream',bytes_observed=len(data),payload_sha256=digest(data),
        body_sample_b64=base64.b64encode(data).decode(),text='')
    return paper,record


def test_binary_json_recovers_actual_bytes_and_independently_matches_identity():
    paper,record=sample();original=copy.deepcopy(record)
    recover_json_metadata(paper,record)
    assert record['status']=='accessible' and record['identity_match'] is True
    assert record['format']=='binary/octet-stream'
    assert record['body_sample_b64']==original['body_sample_b64']
    assert record['payload_sha256']==original['payload_sha256']
    assert record['prior_classification']['status']=='fetch_error'
    again=copy.deepcopy(record);recover_json_metadata(paper,record)
    assert record==again
    paper,record=sample();paper['pmid']='999'
    recover_json_metadata(paper,record)
    assert record['status']=='accessible' and record['identity_match'] is False


@pytest.mark.parametrize('change',[{'complete_body':False},{'http_status':403},
    {'payload_sha256':'tampered'},{'kind':'fulltext'},
    {'body_sample_b64':base64.b64encode(b'<html>challenge</html>').decode()}])
def test_invalid_or_restricted_json_never_gains_access(change):
    paper,record=sample();record.update(change)
    recover_json_metadata(paper,record)
    assert record['status']=='fetch_error'
