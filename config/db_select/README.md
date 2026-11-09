# DB_Select policy configuration

common_rules.yaml: 공통 버전, prompt_version, 최대 재검증 횟수, HTTP 조사 범위 및 provider.
exclusion_codes.yaml / pending_codes.yaml: 고정된 E01~E08 / P01~P04의 역할. 이 파일의 의미를 변경하면 validation이 거부합니다.
organs/*.yaml: 편집 가능한 장기별 독성 범위, 키워드·동의어·endpoint, 적용/비적용/모호 사례, 후보/E01/E02/자료 예시.
fulltext_protocol.md: 실제 원문·부록·저장소 탐색 절차와 한계.
output_schema.json: LLM Full Text 판정 후보의 JSON Schema.
tiab_schema.json / record_schema.json / organ_schema.json: TIAB 후보, 저장 문헌 JSON, 장기 입력 계약.

`python -m k_melloddy select validate --organ Heart --manifest PATH`로 읽기 전용 검증합니다.
코드의 schema.py는 이 파일들에서 사용하는 type/required/properties/additionalProperties/enum/items/minItems/minLength/pattern/minimum/maximum 부분집합만 검증합니다. 자유로운 JSON Schema 확장을 지원한다고 주장하지 않습니다. 임의 스키마 변경은 거부하며 의미·근거 전제는 decision.py가 추가 검증합니다.

정책 수정은 새 run에 반영하고, 재개는 고정된 Criteria 스냅샷을 사용합니다. 모든 결정에 정책 버전/해시와 모델/프롬프트 버전을 저장합니다. 설정 작업은 문헌 수를 생성하지 않습니다. 검증 실패는 run 시작 전 오류이며 자동 재시도하지 않습니다.

Heart는 기본 템플릿, Liver/Kidney는 예시입니다. 임상적 기준의 타당성은 별도 검토가 필요하며 clinically_validated=false를 고정합니다. keyword의 포함 여부만으로 포함/제외하지 않습니다.

LLM 연결 전 provider=unconfigured를 유지합니다. 이후 `python:module:factory`로 사용자 설치 어댑터를 명시적으로 지정합니다. 모듈 로딩은 사용자가 신뢰하는 코드에만 설정하세요. 테스트: `python -m pytest -q tests/test_select.py`.

excel_template.json: 바탕화면 select_stage.xlsx의 헤더·열 너비·헤더 행과 원본 SHA-256만 추출한 레이아웃 계약입니다. 연구 데이터 행은 가져오지 않습니다. 16열/15열 고정이며 추가 열은 허용하지 않습니다. export는 입력 건수·판정·연결·PRISMA와 Excel을 검증합니다.


## liver-v3 및 시범 검수 표시

liver-v3의 확장 예시·재검증·포함 요건·decision_notes는 스키마 검증 후 정책 스냅샷에 포함합니다. 기존 v1/v2 필수 필드는 유지합니다. ReviewIncomplete는 검수자가 제출한 구체적인 미완료 사유를 final.reason에 저장하고 기술 예외 유형은 이벤트로 분리합니다. fetch_error의 Excel 표시는 미확정입니다. P02 보류는 최종 포함/제외가 아니며 미완료 원문 조사와 구분합니다. 테스트: test_extended_liver_policy_and_incomplete_display 및 전체 pytest. 이번 결과/한계/재검증 대기는 Output/pilot20_liverv3_report.md에 기록했습니다.
