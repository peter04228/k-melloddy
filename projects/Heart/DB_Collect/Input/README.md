# Input

사용자 입력과 실행별 입력 스냅샷.

## 실행·상태·추적

전체 파이프라인 실행: `python -m k_melloddy collect run --organ "Heart" --project-name "Heart"`. 개별 세부 스텝 CLI는 제공하지 않는다.
검색만 실행: `python -m k_melloddy collect search --organ "Heart" --project-name "Heart"`.
중단 후 상태 조회: `python -m k_melloddy collect status --organ "Heart" --project-name "Heart"`.
재개: `python -m k_melloddy collect run --organ "Heart" --project-name "Heart" --resume RUN_ID` (저장된 입력 스냅샷 사용).
다른 저장 위치는 모든 명령에 `--base PATH`를 지정한다.

상태는 started → completed/partial/failed이며 재개 시 retried 이벤트를 추가한다.
각 단계 시작·종료 시 집계와 식별자 목록 해시를 append-only SQLite ledger에 기록한다.
설정 단계의 논문 수는 0이다. 검색/출현 수는 observed 이벤트에서 별도 단위로 기록하며
단위 전환을 동일 단위의 보존식과 섞지 않는다. 같은 단위 전환은
`input = forwarded + removed + pending`을 검증한다.

## 오류·재시도·재실행

네트워크 timeout 및 429/5xx에 지수 백오프와 Retry-After를 적용한다.
새 실행은 새 run ID, 재개는 같은 run ID와 새 attempt ID를 사용한다.
원본 및 보고서는 `분류/run_id/attempt_id/`에 저장하여 이전 결과를 덮어쓰지 않는다.
성공 응답 체크포인트는 SHA-256 검증 후 재사용한다. 응답 검증 실패는 체크포인트로 승인하지 않는다.
원본 저장 후 DB 커밋 전에 종료되면 해당 파일은 남고 요청을 재시도할 수 있다.
각 파일은 같은 디렉터리 임시 파일을 fsync한 뒤 원자적으로 공개한다.
OS 프로젝트 잠금은 프로세스 종료 시 해제된다. state.sqlite는 현재 상태,
ledger와 버전별 산출물은 과거 이력의 근거다.

## 테스트·제한

저장소 루트에서 `python -m pytest -q`.
오프라인 데모: `python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12`.
Example 경로가 이미 있으면 새 이름을 사용한다. 데모 데이터는 합성 테스트 자료다.
실제 PubMed는 실행 도중 변경될 수 있어 완전히 동결된 서버 스냅샷을 보장하지 않는다.
ELink Full Text 별도 조회는 미구현이며 not_requested로 표시한다.
날짜 커버리지 불일치/하루 10000건 초과는 대체 전략을 자동 추정하지 않는다.
2~4단계는 인터페이스만 제공한다. CSV의 긴 셀은 보존하며 XLSX 제한 초과/제어문자는
별도 xlsx_overflow.json에 원문을 보존하고 경고한다. DOI 검증은 형식 검사다.
