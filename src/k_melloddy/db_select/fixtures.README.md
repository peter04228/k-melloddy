# Offline synthetic fixtures

Inputs: requested synthetic verdict/code and paper count. Outputs: source papers, provider proposals and evidence records explicitly marked SYNTHETIC. They must never be used as research results. `scenario` creates combinations of TIAB, full-text and material evidence; P03 cites its repository and P04 its file. Tests also inject invalid evidence. Units are synthetic papers/datasets; the engine emits synthetic audit events and PRISMA.

No network calls or scientific inference occur here. Retry and resume behavior belongs to the engine tested with these fixtures. Run `python -m pytest -q tests/test_select.py tests/test_verified_select.py tests/test_revalidation_campaign.py`. Validation rejects unsupported quotations and wrong evidence types. Limitations: deterministic payloads cannot establish actual provider quality, publisher access or dataset availability.
