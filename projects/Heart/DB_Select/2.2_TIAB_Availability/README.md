# 2.2 TIAB_Availability

목적·알고리즘: Title/Abstract와 fetch_state를 구분한다. 원본 abstract_absent만 ABSTRACT_ABSENT로 제외하고 수집 실패는 fetch_error로 둔다.

입력: 문헌 마스터

출력: TIAB availability 및 단계 이벤트

## 상태·집계·저장

논문 단위: `input = forwarded + excluded + pending + fetch_error`.
최종 검수 완료 논문만 `N_all = N_confirmed + N_excluded + N_pending`이고,
미검수·수집 오류는 incomplete_count다. 데이터셋 수는 별도로 집계한다.
후보와 pending_relevance는 2.3의 전달 상태이며 P01~P04와 중복 집계하지 않는다.
초기 보류와 재검증 이벤트는 append-only SQLite에 보존한다. PRISMA는 JSON만 생성한다.

판정에는 source_record, 정책 버전/해시, prompt_version, 모델 제공자/이름, UTC 검수 시각,
실제 자료 evidence_ref를 보존한다. 연구 근거가 없는 값을 채우지 않는다.
논문별 JSON 파일은 새로 생성하지 않는다. 최신 포인터는 SQLite current_records, 불변 이력은 revisions/events/documents이다.
1편 결과·고정 DB 연결·최종 전이 이벤트를 한 트랜잭션으로 commit한 후 누적 JSON 3개를 갱신한다.
`JSON/screening_results.json`은 모든 입력 논문의 최신 상태(미검수 포함), `JSON/evidence_log.json`은 실제 조사 근거,
`JSON/revalidation_history.json`은 재검증 시도·판정 변경이다. 모두 내부 번호 숫자 오름차순 papers 배열과 paper_id/pmid index를 갖는다.
3개 파일의 schema_version/run_id/generation_id가 일치해야 한다. 파일별 임시 저장→원자적 교체 후 SQLite checkpoint를 확정한다.
중간 중단으로 세대가 섞이면 검증에서 거부하고 재개/export에서 SQLite로 모두 복원한다. 현재 선택한 run 전체를 보여주며 다른 run의 판단을 섞지 않는다.
PRISMA/2.1.json~2.12.json 및 final_summary.json은 최신 단계별 JSON이다. 이전의 개별 파일/스냅샷은 삭제하지 않는다.
최종 Excel은 Output/DB_Select_Final.xlsx 하나, 시트는 01_논문스크리닝/02_확정DB/03_확정논문/04_제외논문/05_보류논문 순서다.
01/03/04/05는 4행 헤더 16열, 02는 2행 헤더 15열이다. 추가 기술 열이나 긴 셀용 연속 열을 만들지 않는다.
공유 데이터셋은 02에 한 행으로 표시하고 원래논문순번·PMID를 세미콜론으로 함께 연결한다. 영구 DB 번호는 재번호하지 않는다.
완료 Excel/manifest와 누적 JSON의 과거 확정 스냅샷은 SQLite published_exports에 보존한다. 공식 파일 갱신 전 기존 파일 바이트도 preserved_outputs에 보존한다.

## 실행·재시도

`python -m k_melloddy select validate --organ Heart --project-name Heart --manifest COLLECT_MANIFEST`

`python -m k_melloddy select run --organ Heart --project-name Heart --manifest COLLECT_MANIFEST`

중단 재개: 위 run 명령에 `--resume SELECT_RUN_ID`를 사용한다.
`python -m k_melloddy select revalidate --organ Heart --project-name Heart --resume SELECT_RUN_ID`
`python -m k_melloddy select export --organ Heart --project-name Heart --resume SELECT_RUN_ID`
`python -m k_melloddy select status --organ Heart --project-name Heart`

manifest 경로는 Input/collect_manifest.txt에도 지정할 수 있다. 사용자 입력은 참조만 저장한다.
모델 미설정이면 실제 검수를 시작하지 않는다. 개별 오류는 fetch_error로 저장하고 다음 논문을 진행한다.
fetch_error가 있으면 보류 재검증 전체 패스를 시작하지 않는다. 재개 시 오류 논문부터 다시 처리한다.
이미 유효하게 저장한 논문은 건너뛴다. 정책 수정은 새 run으로 실행하며 기존 run은 고정 정책을 사용한다.
네트워크 오류의 반복 자동 접근은 하지 않고 재개 또는 제한된 재검증에서 다시 확인한다.
OS 잠금과 SQLite 트랜잭션을 사용하며 DB를 먼저 commit하고 파생 파일을 원자적으로 교체한다.
Windows에서 일시적 파일 잠금은 최대 6회 재시도한다. 계속 잠겨 있으면 오류로 중단하며 이미 commit한 검수는 보존한다.
기존 v1 논문별 JSON은 검증 후 SQLite에 추가로 읽어 들이고 원본 파일·판정·내부 번호는 변경하지 않는다. 같은 run의 export는 LLM 재검수 없이 누적 구조를 만든다.

## 검증·한계

`python -m pytest -q tests/test_select.py` 및 전체 `python -m pytest -q`.
합성 데모: `python -m k_melloddy select demo --base demo_runs --project-name SelectDemo --render`.
데모 경로는 신규 이름이어야 한다. LLM/웹은 fixture이며 실측 근거가 아니다.
실제 제공자는 python:module:factory 플러그인 계약으로 연결한다. Codex/GPT/로컬 제공자의
제품별 어댑터는 미연결이며 자동 호출하지 않는다. 기본 HTTP 수집기는 공개 HTML/text/CSV만
제한적으로 해석하고 PDF/JS/인증/대규모 원본 다운로드·완전한 저장소 조사는 수행하지 않는다.
따라서 접근 확인 불충분/판정 후보 검증 오류는 완료로 숨기지 않는다. DB_Download/Preprocessing은 미구현이다.
