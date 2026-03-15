# Codex Harness Week 3 체크리스트

## 문제 정의
- 목적: reviewer/fixer loop, guardrail, trace storage를 붙여 운영 안정성과 추적성을 높인다.
- 범위: Reviewer Agent, Fixer loop, Guardrail Engine, Execution Trace
- 성공 기준: 위험 작업은 실행 전에 통제되고, 요청 1건의 trace를 복원할 수 있어야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - reviewer/fixer loop 정의
  - 파일/명령 정책 기반 guardrail 구현
  - trace event 저장과 상관관계 관리
- 비기능 요구사항:
  - 정책은 `config.toml`로 조정 가능해야 한다.
  - trace는 append-only로 시작해도 되지만 복원 가능해야 한다.
- 우선순위:
  - 1순위: guardrail
  - 2순위: trace
  - 3순위: reviewer/fixer 반복 제어

## 제약 조건
- 일정/리소스:
  - Week 3 종료 시 통제와 관측이 가능한 운영 기본선을 확보한다.
- 기술 스택/환경:
  - 기존 workflow 상태와 연결 가능한 형태로 구현한다.
- 기타:
  - approval required는 즉시 거부가 아니라 대기 상태 전이를 지원해야 한다.

## 아키텍처/설계 방향
- 핵심 설계:
  - 모든 위험 command/file 접근은 실행 전에 preflight 검사한다.
  - trace는 request, task, session을 함께 묶어 조회 가능하게 설계한다.
- 대안 및 trade-off:
  - trace 저장소를 초기에 단순화하면 구현은 빠르지만 조회 최적화는 이후 과제가 된다.
- 리스크:
  - guardrail 연결 지점이 늦거나 누락되면 우회 실행이 발생할 수 있다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 3.1 Reviewer / Fixer Loop
- [ ] reviewer input schema 정의
  - 설계 기준: diff, validation result, architecture rule 포함
  - 산출물: reviewer request model
- [ ] review 결과 분류 규칙 정의
  - 설계 기준: pass / fix-required / blocked 구분
  - 산출물: review decision model
- [ ] fixer 재실행 조건 정의
  - 설계 기준: reviewer finding 기반 재진입
  - 산출물: fix loop policy
- [ ] review-fix 반복 횟수 제한 추가
  - 설계 기준: 무한 루프 방지
  - 산출물: retry cap rule

### 3.2 Guardrail Engine
- [ ] 파일 정책 schema 정의
  - 설계 기준: allow / approval required / deny 규칙 지원
  - 산출물: file policy model
- [ ] 명령 정책 schema 정의
  - 설계 기준: allow / deny 패턴 지원
  - 산출물: command policy model
- [ ] `config.toml`에서 policy 로딩 구현
  - 설계 기준: 코드 수정 없이 정책 조정 가능
  - 산출물: policy loader
- [ ] command/file 접근 시 policy 검사 연결
  - 설계 기준: 실행 전 차단
  - 산출물: preflight guardrail check
- [ ] approval required 흐름 정의
  - 설계 기준: 즉시 거부가 아니라 human approval 대기 가능
  - 산출물: approval pending state rule

### 3.3 Execution Trace
- [ ] trace event schema 정의
  - 설계 기준: `workflow_started`, `task_decomposed`, `command_started`, `command_finished` 등 유지
  - 산출물: trace event model
- [ ] trace_id 상관관계 규칙 정의
  - 설계 기준: request, task, session 연결
  - 산출물: correlation rule
- [ ] 이벤트 저장소 구현
  - 설계 기준: 최소 append-only 저장부터 시작
  - 산출물: trace repository
- [ ] 주요 workflow 이벤트 발행 연결
  - 설계 기준: 상태 전이와 외부 실행 이벤트 모두 기록
  - 산출물: trace publisher

### 3.4 Week 3 검증
- [ ] 금지 command가 실행 전에 차단되는지 확인
- [ ] approval required 파일 접근이 대기 상태로 바뀌는지 확인
- [ ] request 1건에 대한 trace timeline 복원이 가능한지 확인
