# Configuration

실행 입력은 프로젝트 Input/config.yaml 및 fields.yaml입니다. config.example.yaml은 기본값 예시, config.schema.json은 도구용 JSON Schema입니다. 런타임 검증은 db_collect/config.py의 validate가 수행합니다. 원본 query.txt를 편집하면 다음 새 실행부터 적용합니다. 재개 시 기존 실행 설정을 사용합니다.

초기화 명령: `python -m k_melloddy collect init --organ Heart --reuse`.
검증: `python -m pytest -q`. 잘못된 형식/범위/필드/날짜는 새 검색 전에 오류로 중단합니다.
설정 단계의 PRISMA 문헌 수는 0이며 실행 시작 후 1.1~1.4 이벤트에 기록됩니다.
상태/집계/재시도/보존 규칙은 루트 README와 각 단계 README를 따릅니다.
