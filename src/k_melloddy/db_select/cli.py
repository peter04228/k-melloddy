from pathlib import Path
import json
import sys
from ..core.storage import safe_name
from .verified_workflow import VerifiedSelector as Selector
from .documentation import project_docs


def configure(groups):
    parser=groups.add_parser('select',help='Sequential evidence-validated literature selection')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ['validate','run','revalidate','status','export','enrich-data','init','demo']:
        p=commands.add_parser(name)
        p.add_argument('--organ',default='Heart');p.add_argument('--project-name');p.add_argument('--base',type=Path,default=Path('projects'))
        p.add_argument('--policy-dir',type=Path,default=Path('config/db_select'))
        if name in {'validate','run'}:p.add_argument('--manifest',type=Path)
        if name in {'run','revalidate'}:
            p.add_argument('--review-file',type=Path,help='Explicit session reviewer submissions; no inference API calls')
        if name=='revalidate':
            p.add_argument('--additional-pass',action='store_true',help='Explicitly authorize one bounded pass beyond the normal attempt cap')
            p.add_argument('--paper-id',action='append',help='Revalidate only specified pending IDs, preserving the full run scope')
        if name=='run':
            p.add_argument('--limit',type=int)
            p.add_argument('--order',choices=['asc','desc'],default='asc')
        if name in {'run','revalidate','export','enrich-data'}:p.add_argument('--resume')
        if name in {'run','revalidate','export','enrich-data','demo'}:p.add_argument('--render',action='store_true')
        if name=='enrich-data':p.add_argument('--observations-file',type=Path,required=True)


def execute(args):
    if args.command=='demo':
        from .fixtures import run_demo
        result=run_demo(args.base,args.project_name or 'SelectOfflineDemo',args.policy_dir,args.render)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    root=args.base/safe_name(args.project_name or args.organ)/'DB_Select'
    project_docs(root,args.organ,args.project_name or args.organ)
    engine=Selector(root,args.policy_dir,args.organ,log=lambda x:print(x,file=sys.stderr))
    if getattr(args,'review_file',None):
        from .submitted_review import SubmittedReviewProvider
        engine.provider=SubmittedReviewProvider(args.review_file)
    try:
        manifest=getattr(args,'manifest',None)
        if not manifest and (root/'Input/collect_manifest.txt').exists():
            value=(root/'Input/collect_manifest.txt').read_text(encoding='utf-8').strip()
            if value:manifest=Path(value)
        if args.command=='init':result={'status':'INITIALIZED','input':str(root/'Input/collect_manifest.txt')}
        elif args.command=='status':result=engine.status()
        elif args.command=='validate':
            if not manifest:raise ValueError('Provide --manifest or Input/collect_manifest.txt')
            result=engine.validate(manifest)
        elif args.command=='enrich-data':
            from .data_observations import enrich_existing
            try:result=enrich_existing(engine,args.resume,args.observations_file,args.render)
            except BaseException:
                if args.resume:engine.store.set_status(args.resume,'PARTIAL')
                raise
        elif args.command=='export':
            if not args.resume:raise ValueError('Export requires --resume RUN_ID')
            result={'manifest':engine.export_run(args.resume,args.render)}
        else:
            result=engine.run(manifest,resume=args.resume,revalidate_only=args.command=='revalidate',render=args.render,
                limit=getattr(args,'limit',None),order=getattr(args,'order','asc'),additional_pass=getattr(args,'additional_pass',False),revalidate_ids=getattr(args,'paper_id',None))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if isinstance(result,dict) and result.get('status')=='PARTIAL' else 0
    finally:engine.close()
