# Organ policies

Heart/Liver/Kidney v1은 약물·화합물 유발 장기 독성 평가의 보조 템플릿입니다. 임상 검증 자료가 아닙니다.
입력: organ_schema.json에 맞는 YAML. 출력: 실행 Criteria 스냅샷과 SHA-256. 코드가 공통 E/P 규칙 및 조사 완료 전제를 고정하고 장기 YAML은 표현·endpoint·예시를 제공합니다.
키워드가 없다는 이유로 자동 제외하지 않습니다. 정책 변경은 새 run에만 적용하며 기존 판정/이력은 보존합니다.
명령: `python -m k_melloddy select validate --organ Heart --manifest PATH`. 테스트: `python -m pytest -q tests/test_select.py`.
정책 검증 실패는 실행을 중단하고 수정 후 다시 검증합니다. 설정 자체는 PRISMA 문헌 수를 늘리지 않습니다.
