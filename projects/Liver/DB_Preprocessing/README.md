# DB_Preprocessing

상태: **미구현, 인터페이스만 제공**.

PreprocessingRequest: 원본 파일 manifest와 변환 정책 ArtifactRef. 원본 보존, compound/measurement provenance, 결측/단위/QC는 향후 구현.

출력 계약: 경로·SHA-256·run_id·schema_version을 포함한 ArtifactRef. 실행 함수는 NotImplementedError를 발생시킨다. PRISMA/데이터셋 집계 및 상태 전이는 실행하지 않는다. 재시도·재개도 미구현이다. 테스트: `python -m pytest -q`. src/k_melloddy/core/contracts.py 참조.
