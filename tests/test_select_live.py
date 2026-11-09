"""External transport check, never enabled by the default offline suite."""
import os
import json
from pathlib import Path
import pytest
from k_melloddy.db_select.official_metadata import OfficialMetadataVerifier,verified_paper
from k_melloddy.db_select.access_workflow import AccessInvestigator


@pytest.mark.live
@pytest.mark.skipif(os.environ.get('KMELLODDY_LIVE_SELECT')!='1',reason='Explicit live opt-in required')
def test_live_official_pubmed_and_pmc(tmp_path):
    path=Path('projects/Liver/DB_Collect/Output/Liver_2026-11-03/internal_master.json')
    paper=next(p for p in json.loads(path.read_text(encoding='utf8')) if p['paper_id']=='Liver-15752')
    check=OfficialMetadataVerifier().verify(paper)
    (tmp_path/'official_response.json').write_text(json.dumps(check,ensure_ascii=False),encoding='utf8')
    assert check['status']=='verified'
    official=verified_paper(paper,check);official['_official_verified']=True
    pmc=official['values']['PMCID'];assert pmc
    access=AccessInvestigator().request('https://www.ebi.ac.uk/europepmc/webservices/rest/'+pmc+'/fullTextXML','fulltext',official,'PMC_XML')
    (tmp_path/'access.json').write_text(json.dumps(access,ensure_ascii=False),encoding='utf8')
    assert access[-1]['status']=='accessible' and access[-1]['identity_match']
