from k_melloddy.db_select.spreadsheet_workflow import publish_outputs


def test_publication_keeps_round_prisma_and_is_idempotent(tmp_path):
    root, output = tmp_path / 'run', tmp_path / 'dated'
    files = {
        'Input/source_reference.json': '{"sha256":"source"}',
        'JSON/screening_results.json': '{"total_count":3}',
        'PRISMA/qc.json': '{"checks":"passed"}',
        'Runs/review/PRISMA/round_1/2.4.json': '{"round":1}',
        'Runs/review/PRISMA/round_2/3.json': '{"round":2}',
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf8')
    publish_outputs(root, output)
    publish_outputs(root, output)
    assert (output / 'PRISMA/round_1/2.4.json').read_text() == '{"round":1}'
    assert (output / 'PRISMA/round_2/3.json').read_text() == '{"round":2}'
    assert (output / 'JSON/screening_results.json').read_text() == '{"total_count":3}'
    assert all((root / name).read_text() == text for name, text in files.items())
