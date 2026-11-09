from urllib.parse import urlsplit
from .schema import validate, TIAB, PROPOSAL
from .dataset_verifier import citations, verify_dataset


def tiab_decision(proposal,paper):
    validate(proposal,TIAB)
    text=paper['values']['Title']+'\n'+paper['values']['Abstract']
    if proposal['quote'] not in text: raise ValueError('TIAB quote not in the source')
    from .data_observations import validate_observations
    validate_observations(proposal.get('data_observations',[]),paper)
    return proposal


def fulltext_decision(proposal,evidence):
    validate(proposal,PROPOSAL)
    from .data_observations import validate_observations,merge_observations,source_observations
    validate_observations(proposal.get('data_observations',[]),{'values':{'Title':'','Abstract':''}},evidence)
    status,code=proposal['status'],proposal['code']
    records=evidence['records']
    if proposal['evidence_refs']: citations(proposal['evidence_refs'],evidence)
    for source in proposal['source_databases']:
        lookup=citations(source['evidence_refs'],evidence)
        if source['url'] not in {e['url'] for e in lookup.values()}|{e['final_url'] for e in lookup.values()}:
            raise ValueError('Unobserved source DB URL')
    if status=='confirmed':
        if code or not all(proposal['conditions'].values()) or not evidence['fulltext_reviewed']:
            raise ValueError('All five inclusion conditions and identity-matched full text required')
        citations(proposal['evidence_refs'],evidence)
        if not proposal['datasets']: raise ValueError('Confirmed paper has no verified dataset')
        proposal=dict(proposal,datasets=[verify_dataset(d,evidence) for d in proposal['datasets']])
    elif status=='excluded':
        if code not in {f'E{i:02}' for i in range(3,9)}: raise ValueError('Invalid Full Text exclusion code')
        if not all(evidence[k] for k in ['fulltext_reviewed','supplementary_checked','repository_checked','survey_complete']):
            raise ValueError('Exclusion requires completed Full Text, supplementary and repository investigation')
        if not {'Methods','Results','Data Availability'}<=set(evidence['sections_checked']):
            raise ValueError('Relevant sections not reviewed')
        citations(proposal['evidence_refs'],evidence)
        if proposal['datasets']: raise ValueError('Excluded paper cannot register datasets')
        if code=='E07' and not proposal['source_databases']:
            raise ValueError('E07 must preserve the reused source database relationship')
    else:
        if code not in {'P01','P02','P03','P04'}: raise ValueError('Invalid pending code')
        if not proposal['what_unresolved'] or not proposal['next_verification_action'].strip():
            raise ValueError('Pending review must identify unresolved work and next action')
        if proposal['datasets']: raise ValueError('Pending datasets cannot be registered')
        if code=='P01':
            citations(proposal['evidence_refs'],evidence)
            if not proposal['what_confirmed']: raise ValueError('P01 needs a concrete data clue')
        if code=='P02':
            from .access_workflow import unlocated_fulltext,reviewed_abstract_only,access_pending
            routes={urlsplit(e['url']).netloc for e in records}
            if not (unlocated_fulltext(evidence) or reviewed_abstract_only(evidence) or access_pending(evidence)) and (len(routes)<2 or not any(e['status']=='access_restricted' for e in records)):
                raise ValueError('P02 requires multiple routes and actual access restrictions, not one web error')
        if code=='P03' and not any(e['status']=='accessible' and e['kind'] in {'supplementary','repository','landing'} for e in records):
            raise ValueError('P03 needs an observed material location')
        if code=='P04' and not any(e['status']=='accessible' and e['kind'] in {'file','api'} for e in records):
            raise ValueError('P04 needs an actual public file/API response')
        if code in {'P03','P04'}:
            cited=citations(proposal['evidence_refs'],evidence)
            kinds={'supplementary','repository','landing'} if code=='P03' else {'file','api'}
            if not any(cited[ref['evidence_id']]['kind'] in kinds for ref in proposal['evidence_refs']):raise ValueError('Pending material location must be cited')
        # P01 is a documented data clue without a direct path, not a completed full-text review.
        # P03/P04 likewise describe observed materials; inclusion still requires full review.
    facts=merge_observations(proposal.get('data_observations',[]),source_observations(proposal,evidence))
    if facts:proposal=dict(proposal,data_observations=facts)
    return proposal
