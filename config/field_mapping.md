# PubMed 필드 매핑

| 필드 | XML 경로/처리 |
|---|---|
| PMID | MedlineCitation/PMID 또는 BookDocument/PMID |
| Title | Article/ArticleTitle, itertext로 혼합 마크업 텍스트 보존 |
| Abstract | Article/Abstract/AbstractText + OtherAbstract/AbstractText; Label, NlmCategory 별도 보존 |
| DOI/PMCID/PII | ArticleIdList/ArticleId; DOI/PII는 ELocationID 보완 |
| Keywords | KeywordList 전체 반복 구조 |
| MeSH | MeshHeadingList/MeshHeading 구조와 속성 |
| Authors | AuthorList/Author 반복 구조와 속성 |
| Journal | Journal/Title |
| Publication Date | JournalIssue/PubDate와 ArticleDate 구조 |
| Publication Type | PublicationTypeList/PublicationType |
| Language | Language 반복 값 |
| Volume/Issue/Pages | JournalIssue/Volume, Issue, Pagination |
| Affiliation | Article 하위 모든 Affiliation 텍스트 |
| Grant | GrantList/Grant 구조 |
| PubMed URL | https://pubmed.ncbi.nlm.nih.gov/{PMID}/ |
| Full Text | 별도 ELink 조회 미구현; not_requested |

반복 구조는 tag/attributes/text/tail/children으로 저장합니다. CSV는 키 정렬 JSON으로 직렬화하며 csv 모듈로 따옴표·줄바꿈을 보존합니다. 원본 XML이 손실 없는 최종 근거입니다. 선택하지 않은 선택 필드는 not_requested, 필수 필드는 선택과 관계없이 보존합니다. 실패 배치의 PMID는 available, 나머지는 fetch_failed이며 fetch_state=pending_retry입니다.
