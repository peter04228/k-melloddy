"""Explicit reviewer submissions; never generates or guesses a decision."""
import copy
import json
from pathlib import Path
from ..core.storage import digest,dump


class ReviewIncomplete(ValueError):
    """Reviewer-authored, non-final explanation, safe for user-facing output."""


class SubmittedReviewProvider:
    name='codex_session_review'
    model='interactive-review; API model not configured'
    def __init__(self,path):
        self.data=json.loads(Path(path).read_text(encoding='utf-8'))
    def entry(self,paper,policy):
        if self.data['policy_sha256']!=policy['sha256']:raise ValueError('Submitted policy changed')
        entry=self.data['papers'][paper['paper_id']]
        if entry['source_sha256']!=paper.get('_source_sha256',digest(dump(paper).encode())):raise ValueError('Submitted source changed')
        return entry
    def propose(self,phase,paper,policy,evidence,previous):
        entry=self.entry(paper,policy)
        proposal=entry.get('revalidation_'+phase,entry.get(phase)) if previous else entry.get(phase)
        if proposal is None:raise ReviewIncomplete(entry.get('incomplete_reason','원문과 공개 데이터 검증이 완료되지 않아 최종 판정을 내리지 않았습니다.'))
        return copy.deepcopy(proposal)

    def review_evidence(self,paper,policy,bundle,previous):
        """Apply explicit section review only to the same fetched, identity-checked bytes."""
        entry=self.entry(paper,policy)
        review=entry.get('revalidation_evidence_review' if previous else 'evidence_review')
        if not review:return bundle
        matching=[e for e in bundle['records'] if e['url']==review['url'] and e.get('payload_sha256')==review['sha256']
                  and e['status']=='accessible' and e['identity_match'] and e['kind']=='fulltext']
        if not matching:raise ValueError('Reviewed full-text content changed or identity/access check failed')
        e=matching[-1]
        for section in review['sections']:
            if section['quote'] not in e['text']:raise ValueError('Section review quote missing from fetched content')
        bundle['fulltext_reviewed']=True
        from .data_observations import validate_observations
        bundle['data_observations']=validate_observations(review.get('data_observations',[]),paper,bundle)
        bundle['sections_checked']=[x['name'] for x in review['sections']]
        e['sections']=bundle['sections_checked'];bundle['review_attestation']=copy.deepcopy(review)
        for state in bundle.get('workflow',[]):
            if state['step'] in bundle['sections_checked']:state['state']='reviewed'
        return bundle

    def discovery(self,paper,policy):
        return copy.deepcopy(self.entry(paper,policy).get('observed_discovery_urls',[]))


class SubmittedEvidenceCollector:
    def __init__(self,provider):self.provider=provider
    def collect(self,paper,policy,action=''):
        entry=self.provider.entry(paper,policy)
        if not entry.get('evidence'):raise ValueError('No submitted evidence')
        return copy.deepcopy(entry['evidence'])
