# Git으로 설치하고 현재 작업 이어가기

## 공유 구성

Git에는 실행 코드, 설정, 테스트 코드, README 및 설치 의존성을 올립니다. 원본 논문 CSV, 검수 증거, SQLite, 누적 JSON, PRISMA, Excel은 별도의 체크포인트 압축본으로 배포합니다. 연구 데이터 약 4.3GB를 일반 Git 이력에 넣지 않도록 제외했습니다. 가상환경·Node 의존성·인증정보도 Git에 넣지 않습니다.

현재 저장소에는 외부 LLM 제공자가 설정되어 있지 않습니다. Codex가 실제 자료를 확인하고 검수 답변을 작성해야 진행됩니다. 단순히 clone하고 실행하는 것만으로 전체 논문의 판정이 자동 생성되지는 않습니다.

## 새 PC에서 설치

기존 작업은 절대 경로를 포함하므로 우선 같은 위치에 설치합니다. 비공개 저장소이므로 소유자가 초대한 GitHub 계정으로 인증해야 합니다.

```powershell
git clone https://github.com/peter04228/k-melloddy.git C:\dev\k-melloddy
Set-Location -LiteralPath 'C:\dev\k-melloddy'
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`pyproject.toml`이 프로젝트 의존성 선언의 기준이며 `constraints.txt`는 현재 환경에서 확인한 주요 패키지 버전을 제한합니다. 전체 전이 의존성을 고정하는 잠금 파일은 아닙니다. 기존 PC의 `.venv`는 복사하지 않습니다.

Excel 생성에는 별도로 Node.js와 `@oai/artifact-tool`을 제공하는 런타임이 필요합니다. 기본 위치 및 `KM_ARTIFACT_NODE`·`KM_ARTIFACT_MODULES` 설정은 `README_TRANSFER.md`를 따릅니다. 일반 Python 설치만으로 Excel 런타임까지 설치되지는 않습니다.

## 현재 110편 검수 상태 가져오기

코드 clone만으로 연구 데이터가 내려오지는 않습니다. [체크포인트 릴리스](https://github.com/peter04228/k-melloddy/releases/tag/checkpoint-20261109)에서 `k-melloddy-liver-15860-checkpoint-20261109.zip`과 `.zip.sha256`을 받아야 합니다. 비공개 릴리스이므로 저장소 접근 권한이 필요합니다. ZIP 해시를 확인한 다음 새로 clone한 프로젝트에 복원합니다. 기존 검수 폴더가 있는 PC에는 덮어쓰지 않습니다.

아래 명령은 ZIP을 현재 사용자의 Downloads 폴더에 받았다고 가정합니다.

```powershell
$checkpointZip = Join-Path $env:USERPROFILE 'Downloads\k-melloddy-liver-15860-checkpoint-20261109.zip'
$checkpointSha = (Get-Content -LiteralPath ($checkpointZip + '.sha256') -Raw).Split(' ')[0].Trim()
if ((Get-FileHash -LiteralPath $checkpointZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $checkpointSha) { throw 'Checkpoint SHA-256 mismatch' }
Expand-Archive -LiteralPath $checkpointZip -DestinationPath 'C:\dev\k-melloddy'
```

압축본 안의 `CHECKPOINT_MANIFEST_20261109.json`에는 원본·배치·현재 검수 상태와 각 파일의 해시가 있습니다. 원본 CSV와 불변 검수 기록을 수정하지 않습니다.

보존·복원할 핵심 경로:

```text
C:\dev\k-melloddy\간독성_논문목록화_15860.csv
C:\dev\k-melloddy\projects\Liver\DB_Select\Runs\csv-15860-batch1500-20261107
C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500
C:\dev\k-melloddy\TRANSFER_PROVENANCE
```

확정 5편·제외 49편·보류 56편, 총 110편을 저장한 상태이며 다음 검수는 111번입니다. 모든 11개 분할 입력과 현재 작업의 SQLite·요청/응답·증거·누적 JSON·PRISMA·진행 Excel을 함께 복원합니다. 단계별 처리는 논문 한 편을 끝내고 저장·Excel 반영 후 다음 논문으로 진행합니다.

진행 Excel 전체 경로:

```text
C:\dev\k-melloddy\projects\Liver\DB_Select\Output\2026-11-07\liver-15860-batch1500\In_Progress\DB_Select_00001-01500.xlsx
```

복원 후 실제 재개 명령과 오류 대응은 `README_TRANSFER.md`를 따릅니다. 기본 배치 명령은 미완료 배치부터 다음 배치로 순서대로 진행하며, 특정 배치만 실행하는 옵션이 있다고 가정하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_progress_excel.py tests/test_batch_workflow.py tests/test_full_workflow.py tests/test_pdf_material.py -q
```

오프라인 테스트는 실수집·실검수를 시작하지 않습니다. 새 PC에서 런타임 설치와 Excel 출력까지 확인해야 인계가 완료됩니다. 프로그램 자체의 중단 지점 재개는 지원하지만, 프로세스 자동 재시작이나 검수 답변의 무인 생성은 지원하지 않습니다.
