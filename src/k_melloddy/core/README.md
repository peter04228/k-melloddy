# core

Implemented collection infrastructure.

Inputs and outputs: see root README, core/contracts.py and project step READMEs. Algorithms and metric units: DB_Collect uses search_result, pmid_occurrence, unique_pmid and paper; later stages will use dataset/file/compound/measurement separately. State transitions: started/completed/partial/failed/retried in append-only audit events for collection. Later stages have no runtime events. Validation: input = forwarded + removed + pending; SHA-256 and schema/ID invariants. Retry/resume: run-scoped validated checkpoints and immutable attempt artifacts, no retries for unimplemented stages.

Run: `python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12`. Test: `python -m pytest -q`. Limitations: no GUI, no ELink, no implementation of stages 2-4.


## Liver 내부 번호 (2026-11-03 변경)

새 Liver 논문은 Liver-00001 형식으로 P 없이 최소 5자리 숫자를 사용합니다. 10,000번은 Liver-10000입니다. 99,999를 초과하면 자릿수를 늘리며 중복·순환하지 않습니다. 이미 발급된 ID는 수정하지 않으며 다른 장기 형식은 유지합니다. DB_Select는 새 형식과 기존 LIVER-P000001 형식을 모두 숫자 순서로 인식합니다. 재개/재내보내기는 기존 매핑을 유지합니다. 오프라인 테스트: tests/test_collection.py::test_liver_five_digit_ids_and_select_handoff.
