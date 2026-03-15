# Codex Harness Week 4 체크리스트

## 문제 정의
- 목적: GitHub/Jira/PR/Approval UI를 최소 기능으로 연결해 end-to-end 운영 흐름을 완성한다.
- 범위: Integration Layer, PR Automation, Approval UI
- 성공 기준: GitHub Issue 또는 CLI 요청에서 시작해 PR 준비와 승인 재개 흐름까지 확인할 수 있어야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - GitHub/Jira MCP 사용 범위 정의
  - PR 자동 생성 규칙과 실패 처리 정의
  - approval interface와 audit 기록 연결
- 비기능 요구사항:
  - 외부 연동 실패 시 수동 fallback이 가능해야 한다.
  - 승인 없이 merge 또는 위험 실행은 허용하지 않는다.
- 우선순위:
  - 1순위: PR automation
  - 2순위: approval flow
  - 3순위: Jira/GitHub integration 세부 확장

## 제약 조건
- 일정/리소스:
  - Week 4는 최소 기능 완성을 목표로 하며 고도화는 후속 과제로 남긴다.
- 기술 스택/환경:
  - integration endpoint는 `config.toml`로 분리한다.
- 기타:
  - approval UI는 간단한 화면 또는 endpoint 수준으로 시작해도 된다.

## 아키텍처/설계 방향
- 핵심 설계:
  - READY_FOR_PR 상태를 외부 연동 시작점으로 사용한다.
  - approval 결과는 workflow state machine에 다시 연결한다.
- 대안 및 trade-off:
  - UI를 크게 만들기보다 endpoint 기반 승인부터 시작하는 편이 구현 속도에 유리하다.
- 리스크:
  - 외부 연동 실패 처리 기준이 없으면 workflow가 마지막 단계에서 멈출 수 있다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 4.1 Integration Layer
- [ ] GitHub MCP 사용 범위 정의
  - 설계 기준: issue 읽기, PR 생성, comment 작성 범위 한정
  - 산출물: GitHub integration scope
- [ ] Jira MCP 사용 범위 정의
  - 설계 기준: ticket 조회와 상태 반영 범위 한정
  - 산출물: Jira integration scope
- [ ] integration endpoint를 `config.toml`에 반영
  - 설계 기준: 환경별 주소 분리
  - 산출물: integration config
- [ ] 외부 연동 실패 fallback 정책 정의
  - 설계 기준: workflow 전체 실패 대신 수동 처리 전환 가능
  - 산출물: integration fallback rule

### 4.2 PR Automation
- [ ] PR 제목 생성 규칙 정의
  - 설계 기준: task summary + issue reference 결합
  - 산출물: PR title template
- [ ] PR 본문 생성 규칙 정의
  - 설계 기준: 변경 요약, 검증 결과, reviewer note 포함
  - 산출물: PR body template
- [ ] READY_FOR_PR 상태에서 자동 생성 연결
  - 설계 기준: 승인 없이 즉시 merge는 금지
  - 산출물: PR creation flow
- [ ] PR 생성 실패 시 재시도 또는 수동 전환 규칙 정의
  - 설계 기준: 운영 중단 최소화
  - 산출물: PR failure handling rule

### 4.3 Approval UI
- [ ] approval 대상 데이터 모델 정의
  - 설계 기준: request, action, reason, deadline 포함
  - 산출물: approval view model
- [ ] 최소 승인 화면 또는 endpoint 구현
  - 설계 기준: allow / reject / timeout 처리 가능
  - 산출물: approval interface
- [ ] 승인 결과를 workflow 상태에 반영
  - 설계 기준: 승인 시 재개, 거절 시 종료 또는 rollback
  - 산출물: approval result handler
- [ ] 감사 로그 남기기
  - 설계 기준: 누가 무엇을 승인했는지 추적 가능
  - 산출물: approval audit record

### 4.4 Week 4 검증
- [ ] GitHub Issue 또는 CLI 요청부터 PR 생성까지 end-to-end 확인
- [ ] approval required 시나리오에서 UI 승인 후 workflow 재개 확인
- [ ] 외부 연동 실패 시 수동 처리 fallback 확인
