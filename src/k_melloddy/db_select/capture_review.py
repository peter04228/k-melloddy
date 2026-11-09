"""Capture bounded real HTTP observations for explicitly selected pilot papers."""
import argparse,json,copy,xml.etree.ElementTree as ET
from pathlib import Path
from ..core.storage import dump,digest,immutable_write,now
from .metadata import paper_order
from .policy import load_policy
from .evidence_collector import HttpEvidenceCollector


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--ids',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    artifact=next(a for a in manifest['artifacts'] if a['path'].endswith('/internal_master.json'))
    raw=(args.root/artifact['path']).read_bytes()
    if digest(raw)!=artifact['sha256']:raise ValueError('Source hash mismatch')
    papers=json.loads(raw)
    policy=load_policy(Path('config/db_select'),'Liver')
    bounded=copy.deepcopy(policy);bounded['rules']['max_urls']=3;bounded['rules']['timeout_seconds']=15
    result={'timestamp':now(),'policy_sha256':policy['sha256'],'papers':{}}
    for p in sorted(papers,key=paper_order,reverse=True):
        if p['paper_id'] not in args.ids:continue
        tree=ET.parse(args.root/p['raw_xml_path'])
        article=next(a for a in tree.findall('.//PubmedArticle') if a.findtext('MedlineCitation/PMID')==p['pmid'])
        ids={n.get('IdType'):n.text for n in article.findall('PubmedData/ArticleIdList/ArticleId')}
        corrected=copy.deepcopy(p);corrected['values'].update(DOI=ids.get('doi',''),PMCID=ids.get('pmc',''))
        evidence=HttpEvidenceCollector().collect(corrected,bounded)
        result['papers'][p['paper_id']]={'source_sha256':digest(dump(p).encode()),'resolved_article_identifiers':ids,'evidence':evidence}
        print(p['paper_id'],[(r['url'],r['status'],r['identity_match']) for r in evidence['records']],flush=True)
    immutable_write(args.output,dump(result))

if __name__=='__main__':main()
