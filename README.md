# K-MELLODDY

> GitHub 비공개 저장소 설치와 현재 검수 상태 복원은 [README_GIT.md](README_GIT.md)를 참고하세요. 코드와 연구 데이터 압축본을 따로 배포합니다.

> 현재 15,860편 간독성 작업의 설치·인계·재개 안내는 [README_TRANSFER.md](README_TRANSFER.md)를 기준으로 확인합니다. 사용자의 요청으로 과거 Collect 실행 결과와 현재 작업 외 Select 시범 실행 기록을 정리했습니다. 아래 기존 설명에 있는 과거 결과 경로는 현재 존재하지 않을 수 있습니다. Collect 코드와 설정, 현재 CSV 및 11개 배치·검수 기록은 보존합니다.

명세 v1.0에 따른 Python PubMed 수집·선별 파이프라인입니다. **DB_Collect 1.1~1.12 및 DB_Select 2.1~2.12 엔진을 구현**했습니다. DB_Select의 실제 LLM은 사용자 선택 전까지 미설정이며 오프라인 fixture로 검증합니다. DB_Download / DB_Preprocessing은 인터페이스만 있습니다. 실제 연구 자료와 합성 테스트 자료를 혼용하지 않습니다.

## 설치 및 실행 (Windows PowerShell)

Python 3.11 이상이 필요합니다.

```powershell
python -m pip install -e ".[test]"
python -m k_melloddy collect init --organ Heart --reuse
```

`projects/Heart/DB_Collect/Input/query.txt`에 **사용할 원본 PubMed 검색식**을 입력합니다. 예시 검색식은 `config/query.example.txt`에만 있으며 자동으로 실제 검색에 적용하지 않습니다. `Input/config.yaml`은 날짜·페이지·출력 설정, `Input/fields.yaml`은 내보낼 필드 설정입니다. fields.yaml이 필드 선택의 기준입니다.

```powershell
python -m k_melloddy collect search --organ Heart
python -m k_melloddy collect status --organ Heart
python -m k_melloddy collect run --organ Heart --resume SEARCH_RUN_ID
# 새 검색 스냅샷 (기존 실행 및 ID 보존)
python -m k_melloddy collect run --organ Heart
# 저장된 체크포인트로 재내보내기 (네트워크 사용 안 함)
python -m k_melloddy collect export --organ Heart --resume SEARCH_RUN_ID
```

`search`와 `run`은 실제 NCBI 요청을 보냅니다. 검색 범위를 확정한 뒤 실행하세요. 본 구축 과정에서는 실제 PubMed 대량 수집을 수행하지 않았습니다. 실행 종료 코드는 성공 0, PARTIAL/BLOCKED 2, 오류 1, 사용자 중단 130입니다. 완료된 run을 재개하면 기존 완료 상태를 반환합니다.

다른 장기/프로젝트는 `--organ Kidney --project-name KidneyStudy --base projects`처럼 지정합니다. 이미 존재하는 프로젝트의 init에는 `--reuse`가 필요합니다. 경로 정규화 충돌을 검사하며 원래 명칭은 project.yaml에 남습니다.

## 오프라인 검증과 데모

```powershell
python -m pytest -q
python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12
```

데모는 명시적으로 합성 NCBI 응답을 사용하며 새 프로젝트에만 생성됩니다. Example이 이미 있으면 다른 프로젝트명을 사용합니다. 테스트에는 0/1/10000/10001/25000건, 날짜 경계·누락·중복, 실패 후 재개, XML 누락·오류, 고정 ID, 해시 변조, PRISMA 재생성, CSV/XLSX 처리가 포함됩니다.

## 디렉터리와 산출물

실행 코드는 `src/k_melloddy`, 입력·데이터는 `projects/<project>/DB_Collect`에 분리합니다. 모든 장기 프로젝트에 12개 단계 README를 생성합니다.

| 경로 | 내용 |
|---|---|
| Input/project.yaml, query.txt, config.yaml, fields.yaml | 편집 가능한 현재 입력; project.yaml 식별자는 변경하지 않음 |
| Input/runs/run_id/attempt_id | 불변 입력 스냅샷 |
| Raw/run_id/attempt_id | ESearch JSON, EFetch XML, PMID 출현 원본 |
| Intermediate/run_id/attempt_id | 검색·파티션·페이지·중복·메타데이터 manifest |
| Output/run_id/attempt_id | paper_id_map, 선택형식 마스터, 내부 마스터, 전달 manifest |
| Reports/run_id/attempt_id | QC, 의심 중복, PRISMA, 전이/집계 CSV, 요약 및 실패 보고 |
| state.sqlite | 프로젝트·검색·파티션·PMID·메타데이터·고정 ID·append-only ledger·체크포인트 |

경로는 의도적으로 run/attempt를 포함합니다. 과거의 확정 파일을 덮어쓰지 않기 위해 단일 Output/pubmed_master.csv 최신본을 자동 갱신하지 않습니다. CLI가 반환하는 manifest 경로를 다음 단계에 전달합니다. manifest에는 경로, SHA-256, run ID, 스키마 버전과 수집 상태가 있습니다. **downstream_ready=false인 결과는 완전 수집이 아닙니다.**

## 알고리즘·검증·PRISMA

원본 쿼리를 보존하고 Count를 먼저 얻습니다. Count>10000이면 날짜를 재귀 분할하여 기본 9000 이하로 나누며, 조회 페이지는 기본 500개, EFetch 배치는 200개입니다. 날짜를 지정하지 않은 검색의 분할 커버리지 기본값은 1800-01-01~2100-12-31이며 전체 Count와 대조하여 범위 밖/불완전 날짜를 조용히 누락하지 않습니다. 하루에 10000건을 넘으면 BLOCKED로 보고합니다.

PMID만 중복 제거 키로 사용합니다. ID는 최초로 등장한 실행에서 숫자 PMID 오름차순으로 배정하며 재배정하지 않습니다. DOI/제목 일치는 의심 중복 보고만 생성합니다. raw_occurrences = unique_pmids + duplicate_occurrences, unique_pmids = metadata_available + metadata_pending, metadata_available = abstract_present + abstract_absent를 검사합니다.

설정 1.1~1.4는 논문 0건으로 기록합니다. 1.5 검색 획득은 입력 0인 작업이며 공식 검색 건수는 별도의 observed 이벤트에 기록합니다. 1.6/1.7 이후 동일 단위 전환은 input = forwarded + removed + pending을 검증합니다. 시작/종료 이벤트에 집계 및 식별자 목록 해시가 있으며 실패/재시도는 논문 수에 더하지 않습니다. 학술 PRISMA는 Identification만 제공하고 Screening/Eligibility/Included는 미수행(null)입니다.

## 중단·재개·보존

성공 응답의 SHA-256을 검증한 뒤 체크포인트를 재사용합니다. 잘못된 응답은 원본으로 남기지만 체크포인트로 승인하지 않습니다. 재개는 저장된 검색식/설정을 사용하며 현재 Input 수정 내용을 적용하지 않습니다. 수정된 검색은 새 run으로 실행하세요. EFetch 누락·오류 배치는 전체 보류 후 재시도합니다. 초록 부재는 네트워크 실패가 아닙니다.

파일은 동일 디렉터리 임시 파일에 기록·fsync한 후 hard link로 원자적 공개하며 기존 파일은 덮어쓰지 않습니다. DB는 트랜잭션을 사용합니다. 파일 저장 직후 DB 커밋 전 종료 시 미등록 원본이 남을 수 있으며 재개 시 새 요청 결과를 별도 저장합니다. 프로젝트 단위 OS 잠금과 SQLite 고유 제약으로 동시 실행/ID 충돌을 막습니다. SQLite의 현재 상태는 갱신되지만 ledger와 모든 실행 산출물은 보존됩니다.

## 네트워크 정책·제한사항

NCBI transport는 timeout, 429/일시적 5xx 재시도, 지수 백오프, Retry-After, 기본 3req/s 미만(API key 사용 시 10req/s 미만)을 적용합니다. 최초 실행 email은 config.yaml, 재개 email은 NCBI_EMAIL 환경변수로 제공할 수 있습니다. API key는 NCBI_API_KEY 환경변수만 사용하며 보고서에 저장하지 않습니다. 사용자가 작성한 config.yaml 자체는 사용자 입력 파일입니다.

실제 API 정책 근거: [NCBI E-utilities reference](https://www.ncbi.nlm.nih.gov/books/NBK25499/), [NCBI usage guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/).

- 실시간 PubMed의 완전한 서버 스냅샷 동결을 보장하지 않습니다. Count/집합 불일치는 PARTIAL로 남습니다. 같은 수의 논문 교체는 Count 대조만으로 탐지할 수 없습니다.
- ELink 기반 Full Text 링크 조회는 아직 구현하지 않았으며 `not_requested` 및 별도 조회 필요 표시를 제공합니다. DOI/PMCID와 PubMed URL은 저장합니다.
- 하루 10000건 초과 시 대체 분할 자동 수행은 미구현입니다. BLOCKED 상태로 상세 원인을 기록합니다.
- DOI/URL은 형식 검사이며 주소 접근 가능성 검증이 아닙니다. XML은 원본을 보존하지만 모든 PubMed XML 확장 필드가 개별 열로 매핑되지는 않습니다.
- XLSX 32767자 초과/제어문자는 표시용 값을 조정하고 원문을 xlsx_overflow.json에 보존합니다. CSV는 원문을 유지하므로 스프레드시트에서 열 때 텍스트로 가져오세요.
- GUI, Windows EXE 패키징 및 3~4단계 처리는 미구현입니다. DB_Select는 아래 실행 안내를 참고하세요.
- 실제 NCBI 응답에 대한 온라인 smoke test는 별도 실행이 필요합니다. 이번 검증은 합성 fixture와 모의 HTTP에 한정됩니다.

세부 필드 매핑은 [config/field_mapping.md](config/field_mapping.md), 테스트 실행 결과는 [TEST_RESULTS.md](TEST_RESULTS.md)를 참고하세요.

## DB_Select — 한 편씩 순차 검수

DB_Collect의 manifest 경로를 입력합니다. 내부 마스터, 모든 참조 아티팩트의 SHA-256, 스키마와 run ID, PMID↔paper_id를 읽기 전용으로 검증합니다. 300편/50편 배치는 사용하지 않습니다. 새 장기 프로젝트는 `select init`으로 단계별 문서를 생성합니다.

```powershell
.\.venv\Scripts\python.exe -m k_melloddy select init --organ Heart
.\.venv\Scripts\python.exe -m k_melloddy select validate --organ Heart --manifest "실제_collect_output_manifest.json_경로"
# 또는 projects/Heart/DB_Select/Input/collect_manifest.txt에 manifest 경로 입력
.\.venv\Scripts\python.exe -m k_melloddy select run --organ Heart
.\.venv\Scripts\python.exe -m k_melloddy select run --organ Heart --resume SELECT_RUN_ID
.\.venv\Scripts\python.exe -m k_melloddy select revalidate --organ Heart --resume SELECT_RUN_ID
.\.venv\Scripts\python.exe -m k_melloddy select export --organ Heart --resume SELECT_RUN_ID
.\.venv\Scripts\python.exe -m k_melloddy select status --organ Heart
```

`config/db_select/common_rules.yaml`의 provider 기본값은 **unconfigured**입니다. 현재 사용자 선택에 따라 실제 외부 LLM을 연결하지 않았습니다. 미설정 상태의 run은 검수 결과를 만들지 않고 명시적 오류를 반환합니다. `validate`, `status`, 이미 저장된 실행의 `export`는 LLM을 호출하지 않습니다. 연결 계약은 [DB_Select 모듈 안내](src/k_melloddy/db_select/README.md)를 참고하세요.

Heart 정책은 [heart.yaml](config/db_select/organs/heart.yaml)이며 QT/QTc, hERG inhibition, cardiomyocyte viability, cardiac injury 등을 판단 보조 예시로 제공합니다. Liver/Kidney 예시도 있습니다. 키워드는 필수 문자열 규칙이 아니며 어느 장기 템플릿도 임상적으로 검증 완료된 기준이라고 주장하지 않습니다. 정책 파일 전체와 스키마·프로토콜의 해시를 실행마다 고정합니다.

최초 검수 전체가 끝난 후 보류 대상만 한 번 재검증합니다. 자동 재검증은 1회이며, 명시적 revalidate는 기본 최대 3회까지 한 순회씩 진행합니다. fetch_error가 남으면 초기 패스 미완료로 보고 재검증을 미룹니다. 재검증 실패는 기존의 근거 있는 보류를 유지하며 과거 사건을 삭제하지 않습니다. 논문 판정과 감사 이벤트를 SQLite에 즉시 commit하고 누적 JSON 3개를 갱신합니다. JSON/근거/이력 해시는 재내보내기 전에도 다시 검사합니다.

출력은 `DB_Select/JSON/`의 `screening_results.json`, `evidence_log.json`, `revalidation_history.json`과 `Output/DB_Select_Final.xlsx` 하나입니다. 시트는 `01_논문스크리닝`, `02_확정DB`, `03_확정논문`, `04_제외논문`, `05_보류논문` 순서입니다. 바탕화면 select_stage.xlsx의 16열/15열 헤더를 유지하며 열을 추가하지 않습니다. Excel 셀 한도를 넘는 원문은 누적 JSON에 보존하고 셀에 참조 위치를 표시합니다. `PRISMA/2.1.json`~`2.12.json`과 `final_summary.json`에서 단계 및 최종 집계를 검증합니다. 논문 수와 데이터셋 수는 별개이며 정당한 보류를 0으로 강제하지 않습니다.

기존 DB_Collect와 과거 검수 JSON/Excel은 보존합니다. 이전 파일 참조는 해시 검증 후 SQLite에 추가로 읽어들이며 기존 revision을 수정하지 않습니다. 새 공식 출력은 갱신 전에 SQLite에 보관합니다. 누적 JSON의 generation_id/해시가 어긋나면 재개·export에서 재생성합니다. 최신 검수 후 최종 Excel도 다시 export해야 합니다. [v1.3 검증 결과](DB_SELECT_V13_RESULTS.md).

Excel 생성은 Node `@oai/artifact-tool`로 수행하며 저장 검증은 openpyxl의 읽기 기능을 사용합니다. 현재 머신의 Codex runtime 경로를 자동 탐색합니다. 다른 환경에서는 `KM_ARTIFACT_NODE`(node 실행 파일), `KM_ARTIFACT_MODULES`(artifact-tool을 포함한 node_modules 경로)를 지정해야 합니다. 미설치 시 Excel 생성에 성공했다고 표시하지 않습니다. Windows Excel 앱 자체로 재계산한 검증은 아니며 표에는 수식을 생성하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m k_melloddy select demo --base demo_runs --project-name MySelectDemo --render
python -m pytest -q
```

실제 웹·LLM smoke test는 미실행입니다. 기본 공개 HTTP 수집기는 HTML/text/CSV 응답과 링크를 제한적으로 조사하며 PDF/JS 페이지 해석이나 부록·저장소 전체 조사 완료를 보장하지 않습니다. 기본 수집기로 확인하지 못한 근거는 fetch_error/유효한 pending으로 남습니다. 원문·근거 수집기와 LLM 모두 교체 가능한 계약이며 원본 파일 전체 수집은 DB_Download의 책임입니다.


## 2026-11-03 출력 형식 변경

사용자 마스터는 paper_id(내부 번호), PMID, fields.yaml에서 선택한 필드 순서입니다. Liver는 PMID/Title/Abstract를 선택해 총 4열입니다. 내부 마스터와 원본 XML은 검증용으로 유지합니다.
새 결과 경로는 Output/장기_YYYY-MM-DD/이며 한국 시간 기준입니다. 같은 날짜 폴더가 있으면 attempt ID를 붙여 보존합니다. 이전 Output/run/attempt 결과는 변경하지 않습니다. Reports/Raw 경로는 기존대로입니다.
`python -m k_melloddy collect export --organ Liver --resume RUN_ID --current-output`은 네트워크 없이 기존 체크포인트를 사용하고 현재 fields.yaml 및 formats/csv_bom만 반영합니다. 기본 재개는 고정된 설정을 사용합니다. 새 출력 설정은 attempt 입력 스냅샷에 기록되며 검증 상태는 그대로 유지됩니다.
테스트: tests/test_collection.py::test_compact_current_output_and_dated_folder. 기존 경로·출력 설명보다 이 변경 규칙이 우선합니다.
