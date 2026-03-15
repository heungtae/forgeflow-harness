# Codex Harness 주차별 개발 체크리스트

## 문제 정의
- 목적: [codex_harness_architecture_design.md](/home/heungtae/develop/ai-agent/forgeflow/docs/codex_harness_architecture_design.md)를 실제 개발 작업으로 옮기기 위해 주차별 문서를 분리하고, 설계와 진행 현황을 함께 추적한다.
- 범위: 전체 구현 로드맵을 Week 1~4 문서로 나누고, 각 문서가 독립적으로 개발 체크리스트 역할을 하게 한다.
- 성공 기준: 각 주차 문서를 단독으로 열어도 목표, 세부 task, 검증 항목, 진행 상태를 확인할 수 있어야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - 주차별 상세 checklist를 별도 파일로 분리한다.
  - 공통 문서는 전체 흐름과 파일 링크만 담당한다.
  - 각 주차 문서는 `[ ]`, `[/]`, `[x]` 상태 표기를 유지한다.
- 비기능 요구사항:
  - 기존 아키텍처 문서의 용어와 계층을 유지한다.
  - 각 task는 구현 이슈로 바로 옮길 수 있을 만큼 작아야 한다.
- 우선순위:
  - 1순위: Week별 실행 문서 분리
  - 2순위: 선행 관계와 검증 포인트 명확화

## 제약 조건
- 일정/리소스:
  - 4주를 기준으로 분리하되, 각 주차는 독립 milestone이어야 한다.
- 기술 스택/환경:
  - `config.toml`, Codex App Server, git worktree, MCP 연동 방향을 유지한다.
- 기타:
  - 구현 세부사항보다 작업 순서, 산출물, 검증 포인트를 우선 기록한다.

## 아키텍처/설계 방향
- 핵심 설계:
  - 이 문서는 주차별 문서의 index 역할만 수행한다.
  - 실제 개발 진행 관리는 각 Week 문서에서 체크한다.
- 대안 및 trade-off:
  - 문서를 하나로 유지하면 검색은 쉽지만, 진행 관리가 길어지고 충돌 가능성이 커진다.
  - 주차별 분리는 탐색성과 병렬 작업에 유리하다.
- 리스크:
  - 아키텍처 문서가 바뀌면 Week 문서들과 함께 동기화해야 한다.

## 작업 계획
1. [Week 1 체크리스트](/home/heungtae/develop/ai-agent/forgeflow/docs/plans/20260315-codex-harness-week1.md)
2. [Week 2 체크리스트](/home/heungtae/develop/ai-agent/forgeflow/docs/plans/20260315-codex-harness-week2.md)
3. [Week 3 체크리스트](/home/heungtae/develop/ai-agent/forgeflow/docs/plans/20260315-codex-harness-week3.md)
4. [Week 4 체크리스트](/home/heungtae/develop/ai-agent/forgeflow/docs/plans/20260315-codex-harness-week4.md)

공통 상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

공통 운영 규칙:
- [ ] 각 Week 시작 전에 선행 Week 완료 여부 확인
- [ ] 각 Week 종료 시 데모 시나리오 1개 이상 수행
- [ ] 완료 task에는 산출물 링크 추가
- [ ] block 상태 task에는 원인과 다음 액션 기록
- [ ] 아키텍처 문서 변경 시 관련 Week 문서 동기화
