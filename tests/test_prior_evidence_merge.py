import copy
import json
from types import SimpleNamespace
import pytest
from k_melloddy.core.storage import digest, dump

from k_melloddy.db_select.fixtures import scenario
from k_melloddy.db_select.full_workflow import CachedCollector
from k_melloddy.db_select.full_workflow_access import extract_context


def test_revalidation_preserves_prior_response_without_mutating_cache(tmp_path):
    cached = scenario('pending', 'P02')['evidence']
    prior = copy.deepcopy(cached)
    prior['records'][0] = copy.deepcopy(scenario('confirmed')['evidence']['records'][0])
    prior['records'][0]['evidence_id'] = 'prior-successful-response'
    original_cache = copy.deepcopy(cached)
    original_prior = copy.deepcopy(prior)
    engine = SimpleNamespace(
        run_id='run',
        session=tmp_path, round=2,
        cached=lambda paper, kind, operation: cached,
        store=SimpleNamespace(read_ref=lambda ref, run, paper: prior),
        provider=SimpleNamespace(entry=lambda paper, policy: {}),
    )
    result = CachedCollector(engine, object()).collect(
        {'paper_id': 'synthetic', 'values': {}}, {}, {'prior_evidence_ref': {'path': 'sqlite:prior'}})
    carried = [e for e in result['records'] if e['evidence_id'] == 'prior-successful-response']
    assert len(carried) == 1
    assert carried[0]['status'] == 'accessible'
    assert carried[0]['reused_from_prior_round'] is True
    assert cached == original_cache and prior == original_prior
    assert len(result['records']) == len(cached['records']) + 1


def test_changed_discovery_retains_saved_success_and_checks_hash(tmp_path):
    cached = scenario('pending', 'P02')['evidence']
    extended = copy.deepcopy(cached)
    record = copy.deepcopy(scenario('confirmed')['evidence']['records'][0])
    record['evidence_id'] = 'saved-discovery-success'
    extended['records'].append(record)
    folder = tmp_path / 'cache' / 'synthetic'
    folder.mkdir(parents=True)
    path = folder / 'additional_discovery_previous_1.json'
    path.write_text(dump({'sha256': digest(dump(extended).encode()), 'value': extended}), encoding='utf8')
    original = path.read_bytes()
    engine = SimpleNamespace(session=tmp_path, round=1,
        cached=lambda paper, kind, operation: cached,
        provider=SimpleNamespace(entry=lambda paper, policy: {}))
    result = CachedCollector(engine, object()).collect({'paper_id': 'synthetic', 'values': {}}, {})
    assert sum(e['evidence_id'] == record['evidence_id'] for e in result['records']) == 1
    assert path.read_bytes() == original
    assert len(cached['records']) + 1 == len(result['records'])
    assert result['extracted_context'] == extract_context(result)
    assert result == CachedCollector(engine, object()).collect({'paper_id': 'synthetic', 'values': {}}, {})
    wrapper = json.loads(original)
    wrapper['value']['records'].pop()
    path.write_text(dump(wrapper), encoding='utf8')
    with pytest.raises(ValueError, match='checkpoint changed'):
        CachedCollector(engine, object()).collect({'paper_id': 'synthetic', 'values': {}}, {})
