# Offline tests

`python -m pytest -q`를 저장소 루트에서 실행합니다. 임시 프로젝트에 합성 응답만 사용하며 네트워크는 호출하지 않습니다. tests/fixtures는 XML 구조 fixture, db_collect/fake.py는 수량/날짜/중복/오류를 제어하는 모의 NCBI입니다.

검증 범위: 0/1/10000/10001/25000, 날짜 경계/커버리지/겹친 PMID, 실패 재개, 고정 ID, append-only ledger, 원본 해시, CSV/XLSX, PRISMA 재내보내기, NCBI 재시도. 입력=전달+제거+보류를 검사하며 API 재시도는 문헌 수로 세지 않습니다. 테스트 실패는 구현 결함을 나타내며 실제 PubMed 라이브 상태를 보증하지 않습니다. 테스트 재실행은 새 임시 폴더를 사용합니다.

DB_Select 테스트는 tests/test_select.py입니다. E01~E08, P01~P04, 초록 부재/수집 오류, 전체 최초 패스 후 유한 재검증, 단일 논문 다중 DB/공유 DB, DOI 실패 후 PMC 성공, landing/code-only 거부, 근거 변조, 정책 고정·변경, r01 무효화, JSON 공개 직후 DB 커밋 전 중단·재개, XLSX 4종/빈 Pending/긴 내용/날짜·수식형 원문 보존을 검증합니다. 웹/LLM은 모의 객체만 사용합니다. XLSX 통합 테스트는 artifact-tool Node runtime이 필요하며 저장 검증에는 openpyxl 읽기를 사용합니다.
