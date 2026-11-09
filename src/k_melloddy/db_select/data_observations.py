"""Evidence-backed descriptive data facts, independent of the final inclusion verdict."""
import copy
import json
from .schema import DATA_OBSERVATION,validate
from ..core.storage import digest

RELATIONS={'reuse':'기존 DB 재사용','new':'신규 구축','derived':'기존 DB 가공','unknown':'관계 미확인'}
LEVELS={'mentioned':'논문 내 DB/자료 언급 확인; 다운로드 미검증','landing_page':'Repository/자료 페이지 접근 확인; 파일 미검증',
        'sample_structure':'실제 응답·표본 구조 확인','metadata_structure':'공식 구조 메타데이터 확인','full_file':'전체 파일 확인','unverified':'공개·다운로드 미검증'}
PUBLIC={'unknown':'공개 여부 미확인','reported_public':'논문에서 공개라고 기술','verified_public':'공개 접근 확인','restricted':'접근 제한 확인','not_public':'비공개 명시'}


def validate_observations(observations,paper,bundle=None):
    lookup={e['evidence_id']:e for e in (bundle or {}).get('records',[])}
    lookup['tiab']={'kind':'tiab','status':'accessible','text':paper['values']['Title']+'\n'+paper['values'].get('Abstract','')}
    for fact in observations:
        validate(fact,DATA_OBSERVATION)
        sources=[]
        for ref in fact['evidence_refs']:
            source=lookup.get(ref['evidence_id'])
            if not source or source['status']!='accessible' or ref['quote'] not in source['text']:raise ValueError('Unsupported data observation quote')
            sources.append(source)
        if not any(fact['name'].casefold() in ref['quote'].casefold() for ref in fact['evidence_refs']):raise ValueError('Data name absent from cited evidence')
        material=[e for e in sources if e['kind'] in {'repository','landing','supplementary','file','api'}]
        if fact['url'] and not any(fact['url'] in {e.get('url'),e.get('final_url')} for e in material):raise ValueError('Unverified data URL; article/search URLs are not data links')
        level=fact['verification_level']
        if level in {'sample_structure','metadata_structure','full_file'} and not any(e['kind'] in {'file','api'} and e['level']==level for e in material):raise ValueError('Data verification level exceeds observed evidence')
        if (level=='landing_page' or fact['public_status']=='verified_public') and not material:raise ValueError('Public data access not verified')
    return copy.deepcopy(observations)


def merge_observations(*groups):
    result=[]
    for group in groups:
        for fact in group:
            if fact not in result:result.append(copy.deepcopy(fact))
    return result


def observation_evidence(store,run,paper):
    records=[]
    for row in store.db.execute("SELECT content_json,sha256 FROM documents WHERE run_id=? AND paper_id=? AND pmid=? AND kind='evidence' ORDER BY rowid",(run,paper['paper_id'],paper['pmid'])):
        if digest(row['content_json'].encode())!=row['sha256']:raise ValueError('Observation evidence hash mismatch')
        records.extend(json.loads(row['content_json']).get('records',[]))
    return {'records':records}


def source_observations(proposal,evidence):
    """Promote already cited source DB facts; never promote article/search URLs."""
    result=[]
    explicit_names={fact['name'].casefold() for fact in proposal.get('data_observations',[])}
    for source in proposal.get('source_databases',[]):
        # An accessible information page must not append an inferred public
        # status over a reviewer's explicitly verified access restriction.
        if source['name'].casefold() in explicit_names:continue
        cited={r['evidence_id'] for r in source['evidence_refs']}
        material=[e for e in evidence['records'] if e['evidence_id'] in cited and e['status']=='accessible'
            and e['kind'] in {'repository','landing','supplementary','file','api'} and source['url'] in {e['url'],e['final_url']}]
        fact={'name':source['name'],'relationship':'reuse','public_status':'verified_public' if material else 'unknown',
            'verification_level':'landing_page' if material else 'mentioned','url':source['url'] if material else None,'evidence_refs':source['evidence_refs']}
        if material and material[0]['kind'] in {'file','api'} and material[0]['level'] in {'sample_structure','metadata_structure','full_file'}:fact['verification_level']=material[0]['level']
        # Older source schemas accepted a shorthand quote without the DB name. Keep that legacy source,
        # but do not claim a new verified observation from an unsupported label.
        if any(fact['name'].casefold() in r['quote'].casefold() for r in fact['evidence_refs']):
            result.extend(validate_observations([fact],{'values':{'Title':'','Abstract':''}},evidence))
    return result


def screening_data_cells(record):
    """J/K/L/M, without a final-status gate or invented download paths."""
    # Retain the complete observation history in JSON. For display only, a
    # later explicit access finding supersedes an earlier pathless unknown.
    facts=[];resolved=set()
    for fact in reversed(record.get('data_observations',[])):
        key=(fact['name'].casefold(),fact['relationship'])
        if (key in resolved and fact['public_status']=='unknown' and not fact.get('url')
                and fact['verification_level'] in {'mentioned','unverified'}):continue
        facts.append(fact)
        if fact['public_status'] in {'verified_public','restricted','not_public'}:resolved.add(key)
    facts.reverse()
    datasets=record.get('datasets',[]);sources=record.get('source_databases',[])
    names=[d['name'] for d in datasets]+[s['name'] for s in sources]+[f['name'] for f in facts]
    relations=[d['independence_reason'] for d in datasets]+(['기존 DB 재사용'] if sources else [])+[RELATIONS[f['relationship']] for f in facts]
    levels=[LEVELS[d['verification_level']] for d in datasets]
    signatures={(f['public_status'],f['verification_level']) for f in facts}
    levels += [('' if len(signatures)==1 else f['name']+': ')+PUBLIC[f['public_status']]+' / '+LEVELS[f['verification_level']] for f in facts]
    if sources and not facts:levels.append('기존 DB 출처 확인; 다운로드 수준 미확인')
    # Legacy source URLs may point to an article. Only validated observations/data files can populate M.
    urls=[d['direct_url'] for d in datasets]+[f['url'] for f in facts if f.get('url')]
    final=record.get('final',{});code=final.get('code','')
    if code in {'E01','E02','ABSTRACT_ABSENT','TIAB_ABSENT'}:
        levels.append('해당 없음 — TI/AB 제외로 공개·다운로드 검증 미수행')
    elif not levels:
        levels.append('조사 범위 내 공개 데이터 미확인' if final.get('status')=='excluded' else '공개·다운로드 미검증')
    join=lambda values:'; '.join(dict.fromkeys(values))
    return [join(names) or '미확인',join(relations) or '미확인',join(levels),join(urls) or '미확인']


def enrich_existing(engine,run,path,render=False):
    """Append reviewed descriptive facts, without repeating or changing scientific decisions."""
    from pathlib import Path
    from ..db_collect.engine import project_lock
    from ..core.storage import now
    from .metadata import load_collect
    if not run:raise ValueError('Enrichment requires --resume RUN_ID')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data['run_id']!=run:raise ValueError('Observation run mismatch')
    with project_lock(engine.root):
        info=engine.store.run(run);engine.run_id=run;engine.policy=json.loads(info['policy_json']);engine.papers=json.loads(info['input_json']);engine.phase='data_enrichment'
        ref=json.loads(info['collect_ref']);load_collect(ref['path'],engine.root.parent/'DB_Collect')
        if digest(Path(ref['path']).read_bytes())!=ref['sha256']:raise ValueError('Collect manifest changed')
        records=engine.store.records(run)
        if set(data['papers'])-set(records):raise ValueError('Unknown observation paper ID')
        checked={}
        for key,entry in data['papers'].items():
            record=records[key]
            if entry['pmid']!=record['pmid']:raise ValueError('Observation PMID mismatch')
            checked[key]=validate_observations(entry['data_observations'],record['source_record'],observation_evidence(engine.store,run,record))
        changed=[]
        for key in sorted(checked):
            r=copy.deepcopy(records[key]);merged=merge_observations(r.get('data_observations',[]),checked[key])
            if merged==r.get('data_observations',[]):continue
            engine.store.document(run,r,'evidence',{'annotation_type':'data_observations','data_observations':checked[key],
                'timestamp':now(),'based_on_revision':r['revision'],'decision_unchanged':True})
            r['data_observations']=merged
            records[key]=engine.store.save(run,r,'data_enrichment');engine.store.aggregate(run);changed.append(key)
        engine.qc(records);result=engine.refresh(records)
        result.update(enriched_papers=changed,manifest=engine.export(records,render))
        engine.store.set_status(run,result['status'])
        return result
