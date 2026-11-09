import argparse
import json
from pathlib import Path
import sys

from .core.storage import safe_name
from .db_collect.config import init_project
from .db_collect.engine import Collector
from .db_collect.fake import FakeClient


def main(argv=None):
    p = argparse.ArgumentParser(description='K-Melloddy auditable PubMed collection')
    groups = p.add_subparsers(dest='group', required=True)
    from .db_select.cli import configure, execute
    configure(groups)
    collect = groups.add_parser('collect')
    commands = collect.add_subparsers(dest='command', required=True)
    for command in ['init', 'search', 'run', 'status', 'export', 'demo']:
        cmd = commands.add_parser(command)
        cmd.add_argument('--organ', default='Heart')
        cmd.add_argument('--project-name')
        cmd.add_argument('--base', type=Path, default=Path('projects'))
        if command == 'init':
            cmd.add_argument('--reuse', action='store_true')
            cmd.add_argument('--description', default='')
        if command in ['run', 'export']:
            cmd.add_argument('--resume')
        if command == 'export':
            cmd.add_argument('--current-output', action='store_true', help='Use current fields/formats for cached export only')
        if command == 'demo':
            cmd.add_argument('--count', type=int, default=12)
    args = p.parse_args(argv)
    collector = None
    try:
        if args.group == 'select':
            return execute(args)
        if args.command == 'init':
            print(init_project(args.base, args.organ, args.project_name, args.reuse, args.description))
            return 0
        root = args.base / safe_name(args.project_name or args.organ) / 'DB_Collect'
        client = None
        if args.command == 'demo':
            # Explicit fresh project only; never overwrite real query input.
            if args.count < 0:
                raise ValueError('Demo count must be nonnegative')
            root = init_project(args.base, args.organ, args.project_name)
            (root / 'Input/query.txt').write_text('SYNTHETIC OFFLINE DEMO', encoding='utf-8')
            client = FakeClient(args.count)
        if not (root / 'state.sqlite').exists():
            raise ValueError('Project not initialized; use collect init')
        collector = Collector(root, client)
        if args.command == 'status':
            result = collector.status()
        else:
            result = collector.run(resume=getattr(args, 'resume', None), search_only=args.command == 'search', export_only=args.command == 'export', current_output=getattr(args, 'current_output', False))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if isinstance(result, list) or result['status'] in {'COMPLETED','SEARCHED'} else 2
    except KeyboardInterrupt:
        print('Interrupted. Use collect status, then collect run --resume RUN_ID.', file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    finally:
        if collector:
            collector.close()
