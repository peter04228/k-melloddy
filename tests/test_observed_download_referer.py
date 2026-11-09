import pytest
from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess


def test_referer_requires_observed_link_and_is_passed_only_to_download():
    client=FullWorkflowAccess();calls=[]
    client.request=lambda url,kind,paper,route: calls.append((url,paper)) or []
    page='https://example.org/article';url='https://example.org/download'
    bundle={'records':[{'url':page,'observed_links':[url]}],'search_coverage':[]}
    item={'url':url,'kind':'fulltext','referer':page}
    client.additional_discovery({'values':{}},bundle,[item])
    assert calls[0][1]['_observed_referer']==page
    item['referer']='https://example.org/invented'
    with pytest.raises(ValueError,match='observed linking page'):
        client.additional_discovery({},bundle,[item])
