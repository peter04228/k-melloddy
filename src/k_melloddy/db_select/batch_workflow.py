"""Sequential, independently resumable review batches with range-named workbooks."""
import argparse
import csv
import io
import json
from pathlib import Path

from ..core.storage import digest, dump, immutable_write
from ..db_collect.engine import project_lock
from .persistence import atomic_replace
from .policy import load_policy
from .spreadsheet_workflow import SpreadsheetWorkflow, prepare, read_workbook


def prepare_batches(source, root, organ='Liver', batch_size=1500):
    source, root = Path(source).resolve(), Path(root).resolve()
    if source.suffix.lower() != '.csv':
        raise ValueError('Batch input must be CSV')
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    _, papers, reference = read_workbook(source, organ)
    numbers = [int(p['source_workbook']['internal_number']) for p in papers]
    if numbers != list(range(1, len(papers) + 1)):
        raise ValueError('Batch ranges require original consecutive numbers starting at 1; never renumber input')
    with source.open(encoding='utf-8-sig', newline='') as handle:
        headers = csv.DictReader(handle).fieldnames
    policy = load_policy('config/db_select', organ)
    batches = []
    for offset in range(0, len(papers), batch_size):
        selected = papers[offset:offset + batch_size]
        start, end = offset + 1, offset + len(selected)
        label = f'{start:05d}-{end:05d}'
        batches.append(dict(label=label, start=start, end=end, paper_count=len(selected),
                            root=f'Batches/{label}', workbook=f'DB_Select_{label}.xlsx'))
    plan = dict(schema_version='select-batches-v1', organ=organ, source_path=str(source),
                source_sha256=reference['sha256'], policy_sha256=policy['sha256'],
                input_count=len(papers), batch_size=batch_size, batch_count=len(batches),
                numbering='original_internal_number', batches=batches)
    # Validate the complete scope before writing any split input.
    immutable_write(root / 'Input/batch_plan.json', dump(plan))
    immutable_write(root / 'Input/source.csv', source.read_bytes())
    for batch in batches:
        folder = root / batch['root']
        selected = papers[batch['start'] - 1:batch['end']]
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(p['source_workbook']['raw_values'] for p in selected)
        part = folder / 'Input/selection.csv'
        immutable_write(part, stream.getvalue().encode('utf-8-sig'))
        prepare(part, folder, organ)
        immutable_write(folder / 'Input/batch_reference.json', dump(dict(
            parent_source_sha256=reference['sha256'], plan_sha256=digest(dump(plan).encode()), **batch)))
        immutable_write(folder / 'README.md',
            f'# DB_Select {batch["label"]}\n\n'
            f'Original numbers {batch["start"]}–{batch["end"]}; {batch["paper_count"]} papers. '
            f'Final workbook: {batch["workbook"]}. IDs are not restarted.\n\n'
            'Inputs: frozen selection CSV, organ policy, explicit session review and hash-bound answers. '
            'One paper completes presence/relevance/data/deep review and SQLite save before the next. '
            'Missing Title or Abstract excludes at Step 0. Reasons are Korean. '
            'States: planned, AWAITING_REVIEW, PARTIAL, COMPLETED. Units: papers; datasets are separate. '
            'Each batch retains SQLite, three cumulative JSON files, stage PRISMA and five-sheet Excel. '
            'Publish only after scope/count/identity validation. A staged immutable publication resumes '
            'without re-review or re-rendering. Prior artifacts and original input remain preserved.\n\n'
            'Commands, tests, retry limits and limitations: '
            '[batch workflow](../../../../../../../src/k_melloddy/db_select/batch_workflow.README.md). '
            'The provider remains unconfigured; preparing this folder performs no scientific review.\n')
    return plan


def _safe_path(base, relative):
    path = (Path(base) / relative).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise ValueError('Publication path escapes its root')
    return path


def stage_batch(folder, batch, plan, result):
    """Freeze validated export bytes before copying them to the user-facing folder."""
    folder = Path(folder)
    publication = folder / 'Publication'
    header = publication / 'staged.json'
    if header.exists():
        return json.loads(header.read_text(encoding='utf-8'))
    snapshot = _safe_path(folder / 'Runs/review/published', result['publication_id'])
    manifest = json.loads((snapshot / 'Output/select_output_manifest.json').read_text(encoding='utf-8'))
    counts = manifest['counts']
    if (manifest['status'] != 'COMPLETED' or manifest['record_count'] != batch['paper_count']
            or counts['input_count'] != batch['paper_count']
            or sum(counts[k] for k in ['N_confirmed', 'N_excluded', 'N_pending']) != batch['paper_count']
            or any(counts[k] for k in ['incomplete_count', 'fetch_error_count', 'unreviewed_count', 'revalidation_due_count'])):
        raise ValueError('Incomplete batch cannot publish or advance')
    if manifest['run_id'] != result['run_id'] or manifest['policy_sha256'] != plan['policy_sha256']:
        raise ValueError('Batch publication context mismatch')
    selected_ref = json.loads((folder / 'Input/source_reference.json').read_text(encoding='utf-8'))
    if manifest['collect_ref']['sha256'] != selected_ref['sha256']:
        raise ValueError('Batch source changed')
    for item in manifest['artifacts'] + manifest['prisma_artifacts']:
        if digest(_safe_path(snapshot, item['path']).read_bytes()) != item['sha256']:
            raise ValueError('Frozen export artifact hash mismatch')
    screening = json.loads((snapshot / 'JSON/screening_results.json').read_text(encoding='utf-8'))
    ids = [r['paper_id'] for r in screening['papers']]
    expected = [f'{plan["organ"]}-{i:05d}' for i in range(batch['start'], batch['end'] + 1)]
    source_papers = json.loads((folder / 'Input/normalized_papers.json').read_text(encoding='utf-8'))
    pairs = [(r['paper_id'], r['pmid']) for r in screening['papers']]
    source_pairs = [(p['paper_id'], p['pmid']) for p in source_papers]
    if (ids != expected or pairs != source_pairs or screening['counts'] != counts
            or len({r['pmid'] for r in screening['papers']}) != len(expected)):
        raise ValueError('Batch identities missing, duplicated or renumbered')
    metadata = f'Batches/{batch["label"]}'
    files = []

    def add(source, relative):
        raw = source.read_bytes()
        immutable_write(_safe_path(publication / 'files', relative), raw)
        files.append(dict(path=relative, sha256=digest(raw)))

    add(snapshot / 'Output/DB_Select_Final.xlsx', batch['workbook'])
    add(snapshot / 'Output/select_output_manifest.json', metadata + '/source_export_manifest.json')
    for name in ['JSON', 'PRISMA']:
        for path in sorted((snapshot / name).rglob('*')):
            if path.is_file():
                add(path, metadata + '/' + str(path.relative_to(snapshot)).replace('\\', '/'))
    for path in sorted((folder / 'Runs/review/PRISMA').rglob('*.json')):
        relative = path.relative_to(folder / 'Runs/review/PRISMA')
        add(path, metadata + '/PRISMA/' + relative.as_posix())
    add(folder / 'Input/source_reference.json', metadata + '/source_reference.json')
    staged = dict(schema_version='select-batch-publication-v1', batch=batch,
                  source_sha256=plan['source_sha256'], policy_sha256=plan['policy_sha256'],
                  plan_sha256=digest(dump(plan).encode()), run_id=result['run_id'],
                  counts=counts, state_root=str(folder.resolve()), files=files)
    immutable_write(header, dump(staged))
    return staged


def publish_batch(folder, destination, batch, plan):
    folder, destination = Path(folder), Path(destination)
    header = folder / 'Publication/staged.json'
    staged = json.loads(header.read_text(encoding='utf-8'))
    if (staged['batch'] != batch or staged['source_sha256'] != plan['source_sha256']
            or staged['policy_sha256'] != plan['policy_sha256']
            or staged['plan_sha256'] != digest(dump(plan).encode())):
        raise ValueError('Staged batch context changed')
    for item in staged['files']:
        raw = _safe_path(folder / 'Publication/files', item['path']).read_bytes()
        if digest(raw) != item['sha256']:
            raise ValueError('Staged publication bytes changed')
        immutable_write(_safe_path(destination, item['path']), raw)
    immutable_write(destination / 'Batches' / batch['label'] / 'batch_output_manifest.json', dump(staged))
    immutable_write(folder / 'Publication/completed.json', header.read_bytes())
    return staged


def _progress(root, destination, plan, completed, **details):
    published_papers=sum(item['batch']['paper_count'] for item in completed)
    terminal=details.get('terminal_in_current_batch',0)
    value = dict(source_sha256=plan['source_sha256'], input_count=plan['input_count'],
                 batch_count=plan['batch_count'], completed_batches=len(completed),
                 completed_papers=published_papers,
                 processed_papers=published_papers+terminal if terminal is not None else None,
                 completed_batch_counts={key:sum(item['counts'][key] for item in completed)
                                         for key in ['N_confirmed', 'N_excluded', 'N_pending']},
                 status='COMPLETED' if len(completed) == plan['batch_count'] else 'PARTIAL',
                 workbooks=[item['batch']['workbook'] for item in completed], **details)
    current=next((b for b in plan['batches'] if b['label']==details.get('current_batch')),None)
    if current:
        progress_file=Path(destination)/'In_Progress'/current['workbook']
        if progress_file.exists():value['progress_workbook']=str(progress_file.resolve())
    atomic_replace(Path(root) / 'batch_progress.json', dump(value))
    atomic_replace(Path(destination) / 'batch_progress.json', dump(value))
    return value


def run_batches(source, root, destination, organ='Liver', batch_size=1500, render=False,
                engine_factory=SpreadsheetWorkflow):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    plan = prepare_batches(source, root, organ, batch_size)
    destination.mkdir(parents=True, exist_ok=True)
    with project_lock(root):
        immutable_write(destination / 'batch_plan.json', dump(plan))
        completed = []
        for batch in plan['batches']:
            folder = root / batch['root']
            # A failed copy is resumed from frozen bytes, without another export.
            if not (folder / 'Publication/staged.json').exists():
                part = folder / 'Input/selection.csv'
                info = json.loads((folder / 'Input/source_reference.json').read_text(encoding='utf-8'))
                engine = engine_factory(folder, source=part, organ=organ,
                                        review_file=folder / 'Input/session_review.json')
                from .progress_excel import export_progress
                engine.progress_callback=lambda:export_progress(
                    engine.store,engine.run_id,engine.policy,engine.papers,
                    destination/'In_Progress'/batch['workbook'])
                try:
                    result = engine.execute(info['sha256'], 'review', render=render)
                finally:
                    engine.close()
                if result.get('counts', {}).get('status') != 'COMPLETED':
                    progress = _progress(root, destination, plan, completed,
                                         current_batch=batch['label'], review_state=result.get('status', 'PARTIAL'),
                                         saved_in_current_batch=result.get('saved_count'),
                                         terminal_in_current_batch=result.get('terminal_count'),
                                         current_batch_counts=result.get('terminal_outcomes'),
                                         request=result.get('request'))
                    return progress
                stage_batch(folder, batch, plan, result)
            completed.append(publish_batch(folder, destination, batch, plan))
            _progress(root, destination, plan, completed)
        return _progress(root, destination, plan, completed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--organ', default='Liver')
    parser.add_argument('--batch-size', type=int, default=1500)
    parser.add_argument('--publish', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        result = prepare_batches(args.source, args.root, args.organ, args.batch_size)
        if args.publish:
            immutable_write(args.publish / 'batch_plan.json', dump(result))
    else:
        if not args.publish:
            parser.error('--publish is required for execution')
        result = run_batches(args.source, args.root, args.publish, args.organ, args.batch_size, args.render)
    print(dump(result))


if __name__ == '__main__':
    main()
