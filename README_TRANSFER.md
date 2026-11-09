# K-MELLODDY — 간독성 15,860편 작업 인계

작성 기준: 2026-11-09. 이 문서는 현재 작업을 다른 Windows PC로 옮겨 이어가기 위한 안내입니다. 사용자의 명시적 지시에 따라 현재 15,860편 작업과 무관한 과거 실행 자료를 정리합니다. 현재 작업의 검수는 추가 실행하지 않았습니다.

### 폴더 정리 진행 상태

최초 삭제 요청은 자동 승인 검토에서 거부됐으나, 사용자가 Collect 코드 보존·Collect 실행 기록 삭제·현재 15,860편 이외 Select 실행 기록 삭제를 명확하게 승인하여 정리를 완료했습니다. 123개 삭제 대상 경로가 모두 정리됐으며 `CLEANUP_20261109.json`은 `COMPLETED`, 삭제 오류는 0건입니다. 현재 작업·코드·설정·테스트의 보존 대상 6,486개 파일은 삭제 전 SHA-256과 모두 일치했고, SQLite 무결성과 11개 배치·110편 판정도 확인했습니다.

- 삭제 대상·처리 결과: `C:\dev\k-melloddy\CLEANUP_20261109.json`
- 현재 작업·코드·설정·테스트 보존 해시 목록: `C:\dev\k-melloddy\TRANSFER_PRESERVED_FILES_20261109.json`
- 현재 검수가 참조한 과거 요청·응답의 별도 보관: `C:\dev\k-melloddy\TRANSFER_PROVENANCE`
- 정리 후 보존 파일·배치·SQLite 검증: `C:\dev\k-melloddy\TRANSFER_CLEANUP_VERIFICATION_20261109.json`

이전 Collect 결과·PRISMA·SQLite와 과거 Select 시범 작업 결과는 정리 대상입니다. 기존 Collect 검색식·YAML 및 코드, 테스트 코드, 단계별 README는 남깁니다. 과거 결과를 가리키는 기존 문서의 예시 경로나 `collect_manifest.txt`는 더 이상 실제 산출물이 없을 수 있습니다. 현재 15,860편 CSV 작업 재개에는 이 과거 Collect manifest를 사용하지 않습니다.

별도 보관 자료는 현재 작업의 출처 확인용입니다. `manifest.json`에 원래 경로·보관 경로·실제 SHA-256이 있습니다. 일부 과거 참조 해시와 현재 남아 있는 과거 파일의 해시가 이미 달랐으며, 이 차이는 `preexisting_reference_issues`에 기록했습니다. 현재 검수 기록이나 해시를 그에 맞춰 수정하지 않았습니다. 이 보관 폴더도 이관 시 함께 보존합니다.

## 1. 현재 작업과 진행 상태

- 입력: 간독성 논문 15,860편 CSV
- 처리 단위: 원래 번호 순서로 1,500편씩, 총 11개 배치
- 현재 배치: 1~1,500번
- 최종 처리 저장: 1~110번, 확정 5편 / 제외 49편 / 보류 56편
- 다음 작업: 111번 원문·데이터 검수 응답 작성
- 현재 상태: `AWAITING_REVIEW`, 전체 작업은 `PARTIAL`
- 완료된 1,500편 배치: 0개
- 외부 LLM API: 미설정. 이 대화의 Codex가 실제 자료를 확인하고 검수 응답을 제출하는 방식

위 수치는 작성 시점의 기록입니다. 이후 진행 상태는 아래 파일을 기준으로 확인합니다. `processed_papers`는 현재 배치를 포함해 처리가 끝난 논문 수이고, `completed_papers`는 최종 발행까지 끝난 배치의 논문 수이므로 서로 다를 수 있습니다.

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\batch_progress.json
```

오래된 `execution_checkpoint_00063_20261108.json`은 63편 시점의 보존 기록이며 최신 진행 상태가 아닙니다.

## 2. 원본과 분할 입력의 전체 위치

원본:

```text
C:\dev\k-melloddy\간독성_논문목록화_15860.csv
```

원본 SHA-256:

```text
71df714e24f3977ba32651f27e7d455cda70523e1d34664594c2ae64fc329515
```

분할 입력은 이미 11개 모두 만들어져 있습니다. 첫 배치만 만들어진 것이 아닙니다. 원래 번호를 유지하며 배치마다 1번으로 다시 매기지 않습니다.

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\00001-01500\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\01501-03000\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\03001-04500\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\04501-06000\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\06001-07500\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\07501-09000\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\09001-10500\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\10501-12000\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\12001-13500\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\13501-15000\Input\selection.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\15001-15860\Input\selection.csv
```

마지막 배치는 860편입니다.

## 3. 이관 시 보존할 자료

코드·설정·테스트 코드·README를 보존합니다. 연구 작업은 원본과 함께 다음 폴더 전체를 보존합니다.

```text
C:\dev\k-melloddy\src
C:\dev\k-melloddy\config
C:\dev\k-melloddy\tests
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107
C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500
```

루트의 `pyproject.toml`, `AGENTS.md` 및 관련 문서도 함께 복사합니다. 위 목록은 현재 작업의 핵심 보존 대상이며, 다른 파일을 자동 삭제해도 된다는 뜻은 아닙니다. 과거 시범 실행 결과 정리는 별도 작업입니다.

각 배치 안의 다음 자료는 재개에 사용되므로 결과 Excel만 복사해서는 안 됩니다.

- `Input`: 분할 CSV, 정규화 입력, 원본 참조·해시, 검수 제출 내용
- `state.sqlite`: 판정·수정 이력·이벤트·현재 상태의 기준 원장
- `Runs`: 검수 요청과 응답, 원문 접근 증거, 캐시, 재검증 기록과 체크포인트
- `JSON`, `PRISMA`: 누적 결과 및 단계별 집계
- `Publication`, `Output` 등 이미 생성된 배치 내부 산출물
- 배치 상위의 `Input/batch_plan.json`, `batch_progress.json`, 실행 체크포인트

프로그램이 종료되고 SQLite 연결이 닫힌 상태에서 복사합니다. SQLite의 `-wal`·`-shm` 파일이 남아 있으면 임의 삭제하거나 DB 본체만 따로 가져가지 않습니다. 원본 PC와 새 PC에서 같은 작업을 동시에 실행하지 않습니다.

## 4. 판정 흐름 — 한 편을 끝낸 뒤 다음 편으로

1. Title과 Abstract 존재 여부 확인: 둘 중 하나라도 없으면 `TI/AB 부재`로 제외합니다.
2. TI/AB 관련성 평가: E01/E02는 제외하고, 관련성 있음·정보 부족은 원문 검증으로 이동합니다.
3. PMID 기준 공식 메타데이터 확인 후 원문, Methods, Data Availability, Supplementary, Repository와 실제 파일/API를 검증합니다. 입력 원본은 바꾸지 않고 공식 정보와 불일치를 별도 기록합니다.
4. 조건 충족 시 확정, 근거가 확인된 E03~E08은 제외, P01~P04는 코드별 심층 재검증을 수행합니다.
5. 재검증 후 확정·제외·최종 보류 중 하나로 마무리합니다. 같은 URL 재요청만으로 재검증을 완료했다고 하지 않습니다.
6. SQLite에 결과를 저장하고 누적 JSON·PRISMA·진행 Excel을 갱신한 뒤 다음 번호로 이동합니다.

키워드 일치만으로 확정·제외하지 않습니다. 실제 약물 노출, 간독성 관련성, 데이터 접근성과 구조를 확인합니다. 접근 실패나 증거 부족을 자동 제외로 바꾸지 않습니다. 판정 근거는 한국어로 기록하고, 실제 논문명·DB명·URL은 원문을 유지합니다.

## 5. JSON·PRISMA·Excel 역할

SQLite가 기준 원장이며, 누적 JSON은 SQLite의 저장 결과에서 생성됩니다.

| 파일 | 내용 |
|---|---|
| `screening_results.json` | 논문별 단계 판정, 최종 판정, 코드와 근거 |
| `evidence_log.json` | 공식 메타데이터, 원문·보충자료·Repository·파일 접근 증거 |
| `revalidation_history.json` | 최초 P코드, 재검증 시도와 판정 변경 이력 |
| 단계별 PRISMA JSON | 입력·전달·제외·보류·수집 오류 등 단계 집계 |

현재 배치의 누적 JSON 전체 경로:

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\00001-01500\JSON\screening_results.json
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\00001-01500\JSON\evidence_log.json
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\00001-01500\JSON\revalidation_history.json
```

현재 진행 Excel:

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500\In_Progress\DB_Select_00001-01500.xlsx
```

한 편의 최종 처리가 끝날 때마다 이 파일을 갱신합니다. 첫 시트에는 배치 입력 1,500편이 표시되며 아직 끝나지 않은 논문은 `미검수`입니다. 이 행들을 최종 보류 건수에 넣지 않습니다. 현재 진행 파일은 완성된 최종 결과가 아닙니다.

1,500편이 끝나면 SQLite·누적 JSON·PRISMA·Excel의 판정 수, 내부번호·PMID 및 DB 연결을 검증합니다. 최종 판정에서 `확정 + 제외 + 보류 = 배치 전체 논문 수`를 충족해야 최종 발행합니다. 최종 Excel은 PRISMA 통계만으로 생성하지 않습니다.

첫 배치가 완료되면 발행될 경로(작성 시점에는 미발행):

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500\DB_Select_00001-01500.xlsx
```

이후 파일명은 `DB_Select_01501-03000.xlsx` 등의 범위 형식입니다. 모든 Excel은 기존 열 구성과 다음 5개 시트를 유지합니다.

1. `01_논문스크리닝`
2. `02_확정DB`
3. `03_확정논문`
4. `04_제외논문`
5. `05_보류논문`

진행 Excel을 열어 두면 Windows가 갱신을 거부할 수 있습니다. 재시도 후에도 실패하면 다음 논문으로 넘어가지 않고, 저장된 판정과 재생성할 Excel을 유지합니다. Excel을 닫고 같은 명령으로 재개하면 Excel 반영부터 다시 수행합니다. 추적되지 않은 사용자 Excel 수정도 임의로 덮어쓰지 않습니다.

## 6. 새 PC 설치와 의존성

우선 새 PC에도 프로젝트를 **`C:\dev\k-melloddy`**에 배치합니다. 기존 기록에 절대 경로와 경로가 포함된 해시가 있으므로 다른 드라이브·폴더로의 무변경 재개는 보장하지 않습니다. 경로가 달라질 경우 별도의 이관 검증이 필요하며, 불변 기록을 일괄 치환하지 않습니다.

Python 요구사항은 `pyproject.toml`의 3.11 이상입니다. 현재 PC는 Python 3.13.14를 사용합니다. 기존 `.venv`는 PC 종속 경로와 시스템 패키지 참조가 있으므로 복사해서 재사용하지 않고 새 환경을 만듭니다.

```powershell
Set-Location -LiteralPath 'C:\dev\k-melloddy'
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

현재 확인된 주요 Python 버전은 PyYAML 6.0.3, openpyxl 3.1.5, xlrd 2.0.2, pytest 8.4.2, pypdf 6.14.2입니다. PDF 읽기 의존성 pypdf를 `pyproject.toml`에 포함했고 `requirements.txt`·`requirements-dev.txt`·`constraints.txt`로 설치하도록 정리했습니다. 주요 패키지 버전 제한이며 전체 전이 의존성 잠금 파일은 아닙니다. 새 PC 설치 검증은 별도로 필요합니다.

공개 보충자료의 PDF 표 셀을 명시적으로 검수하려면 추가로 `.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[review]"`를 실행합니다. 현재 검증된 선택 의존성은 PyMuPDF 1.27.2.3입니다. `public_form_captures`는 실제 공개 다운로드 양식의 응답을 출처·해시와 연결하여 보존하며 자동 로그인이나 양식 제출을 수행하지 않습니다. RAR 안의 선택한 PDF를 다시 검사하는 경우 RAR을 읽을 수 있는 `tar`/bsdtar가 필요합니다(현재 Windows 시스템 tar로 검증). 도구가 없거나 파일이 달라지면 미완료 검수를 멈추며 내용을 추정하지 않습니다. 확정된 이전 SQLite 기록은 이 기능 때문에 다시 판정하지 않습니다. 상세 계약은 `src/k_melloddy/db_select/form_material_capture.README.md`와 `pdf_grid_review.README.md`를 따릅니다.

Excel 생성은 Python 패키지만으로 되지 않습니다. Node.js와 `@oai/artifact-tool` 런타임이 필요합니다. 현재 코드의 기본 탐색 위치는 사용자 홈 아래 다음 경로입니다.

```text
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\@oai\artifact-tool
```

새 PC에서 실제 런타임 위치가 다르면 `KM_ARTIFACT_NODE`에 node.exe 전체 경로, `KM_ARTIFACT_MODULES`에 `@oai/artifact-tool`을 포함한 node_modules 폴더 전체 경로를 지정합니다. 설치되지 않은 경로를 입력하는 것으로 설치가 되지는 않습니다. Codex 런타임 제공 여부와 Excel 생성·읽기 검증을 새 PC에서 확인해야 합니다.

## 7. 기존 작업 재개 명령

PowerShell에서 프로젝트 루트로 이동한 뒤 실행합니다. 새 작업 폴더를 만들거나 날짜를 바꾸지 말고 기존 작업을 지정합니다.

```powershell
Set-Location -LiteralPath 'C:\dev\k-melloddy'
.\.venv\Scripts\python.exe -m k_melloddy.db_select.batch_workflow `
  --source 'C:\dev\k-melloddy\간독성_논문목록화_15860.csv' `
  --root 'C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107' `
  --publish 'C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500' `
  --organ Liver `
  --batch-size 1500
```

완료된 논문은 저장 기록을 검증하고 건너뜁니다. 미완료 논문은 저장된 요청·증거·단계에서 이어갑니다. SQLite에는 저장됐지만 Excel 반영이 미완료라면 Excel부터 갱신합니다. 확정된 과거 결과와 이벤트는 삭제하지 않습니다.

**이 명령은 수동 검수 답변을 자동 생성하지 않습니다.** 현재 111번의 요청은 아래 파일입니다.

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107\Batches\00001-01500\Runs\review\reviews\Liver-00111_r1.request.json
```

Codex가 해당 논문의 공식 정보와 실제 접근 증거를 읽고 요청 해시에 연결된 응답을 작성해야 다음 단계로 이동합니다. 증거가 추가되면 요청 파일명이 달라질 수 있으므로 최신 실행이 반환한 요청을 사용합니다. 응답을 임의 복사하거나 과거 요청의 답변으로 대체하지 않습니다.

중단 후 같은 명령으로 **재개하는 기능은 있지만**, 프로그램 종료 후 자동으로 다시 실행하는 감시 서비스는 없습니다. 대화가 끝난 뒤 Codex 검수가 백그라운드에서 계속되는 구조도 아닙니다. 미설정된 외부 LLM을 자동 활성화하지 않습니다.

## 8. 검증과 오류 대응

새 PC에서는 먼저 오프라인 회귀 테스트를 실행합니다. 이 테스트는 실제 논문 수집·검수를 시작하지 않습니다.

```powershell
Set-Location -LiteralPath 'C:\dev\k-melloddy'
.\.venv\Scripts\python.exe -m pytest tests/test_progress_excel.py tests/test_batch_workflow.py tests/test_full_workflow.py -q
```

현재 PC에서 위 테스트는 28개 통과했습니다. 이 결과가 새 PC 설치 성공이나 전체 15,860편의 검수 완료를 뜻하지 않습니다. 테스트 종료 시 Windows 임시 폴더 정리 권한 경고가 관찰됐으며 테스트 단언 실패와는 구분합니다.

| 상태·오류 | 처리 |
|---|---|
| `AWAITING_REVIEW` | 반환된 요청을 읽고 실제 검수 응답을 제출한 다음 재개 |
| Excel 잠금 | Excel·미리보기를 닫고 재개. 판정 중복 제출 불필요 |
| source/policy/hash 불일치 | 원본·설정·경로가 바뀌었는지 확인. 보호 검증을 우회하지 않음 |
| HTTP 403·접근 제한 | 공식 원문·PMC·출판사·자료 저장소 대체 경로 확인. 실패 이력을 보존 |
| 원문·자료 확인 불충분 | 적절한 P코드와 미해결 사유 기록. 자동 제외하지 않음 |
| Node/artifact-tool 없음 | 실제 런타임 설치·위치 확인 후 재개 |

보존된 판정 이력과 이벤트는 append-only입니다. 캐시에도 실제 증거가 들어 있으므로 현재 작업의 캐시·로그를 단순 임시 파일로 취급해 삭제하지 않습니다. DB_Download와 DB_Preprocessing은 인터페이스만 있으며 이 작업의 실행 대상이 아닙니다.
