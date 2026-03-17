# Codex Harness Week 3 체크리스트

## 문제 정의
- 목적: Week 2의 coding/validation 루프 위에 reviewer/fixer 자동 반복, guardrail preflight, trace 상관관계를 추가해 운영 안전성과 추적성을 높인다.
- 범위: Reviewer Agent, Fixer loop, Guardrail Engine, Execution Trace
- 성공 기준:
  - reviewer가 `fix_required`를 반환하면 fixer가 자동 재실행된다.
  - 위험한 command와 정책 대상 파일 변경은 실행 전 또는 다음 단계 진입 전에 통제된다.
  - 요청 1건의 workflow를 trace만으로 복원할 수 있다.

## 요구사항 구조화
- 기능 요구사항:
  - `REVIEWING`, `FIXING`, `AWAITING_APPROVAL` 상태 추가
  - reviewer 결과를 `pass | fix_required | blocked`로 표준화
  - `config.toml` 기반 command/file guardrail 정책 로딩
  - trace event에 `session_id`, `run_id`, `workflow_state`, `correlation_id` 저장
- 비기능 요구사항:
  - trace 저장소는 append-only JSONL을 유지한다.
  - approval required는 실패가 아니라 pause 상태로 남긴다.
  - Week 2의 `unittest` 스타일을 유지한다.
- 우선순위:
  - 1순위: guardrail과 approval pause
  - 2순위: reviewer/fixer 자동 반복
  - 3순위: trace 상관관계 강화

## 제약 조건
- 일정/리소스:
  - Week 3 종료 시 운영 기본선은 확보하되 UI/외부 approval 연동은 제외한다.
- 기술 스택/환경:
  - Python 3.11+, 현재 `src/forgeflow_harness/*` 구조, `config.toml`, `unittest` 기반 테스트 유지
- 기타:
  - approval resume endpoint/UI는 Week 4 범위로 미룬다.
  - trace 저장소는 조회 최적화보다 복원 가능성을 우선한다.

## 아키텍처/설계 방향
- 핵심 설계:
  - validation 진입 전 changed file과 validation command를 guardrail로 평가한다.
  - reviewer는 validation 결과와 changed file을 받아 fix 필요 여부를 결정한다.
  - fixer는 reviewer findings를 입력으로 받아 수정 후 validation/review loop를 다시 돈다.
  - approval required는 `AWAITING_APPROVAL` 상태와 `approval_pending` trace로 남긴다.
  - hardening 단계에서는 raw event 해석을 전용 normalizer로 분리하고 reviewer terminal payload 필수 필드를 강제한다.
  - approval pending은 trace payload 안에 구조화된 approval record를 남기고, resume 계약은 `approve | reject | expire`로 고정한다.
  - trace replay는 append-only JSONL 전체 스캔으로 request timeline을 복원한다.
- 대안 및 trade-off:
  - 별도 DB trace 저장소 대신 JSONL append-only 저장을 유지해 구현을 단순화한다.
  - 실제 human approval 재개 기능은 미루고, Week 3에서는 pending state와 trace만 보장한다.
- 리스크:
  - Codex event payload가 실제 운영 환경에서 더 다양한 shape를 가지면 normalizer alias를 추가로 보강해야 한다.
  - 현재 approval resume은 내부 계약과 trace 기록까지만 구현되어 있고, 실제 workflow 재실행 endpoint는 아직 없다.
  - 파일 guardrail은 현재 worktree 결과와 runtime observed action 기준이라 tool 내부 세부 동작 차단은 후속 강화가 필요하다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 3.1 Reviewer / Fixer Loop
- [x] reviewer input schema 정의
  - 설계 기준: changed file, validation result, task graph, request context 포함
  - 산출물: reviewer run payload
- [x] review 결과 분류 규칙 정의
  - 설계 기준: `pass | fix_required | blocked`
  - 산출물: `ReviewDecision`
- [x] fixer 재실행 조건 정의
  - 설계 기준: reviewer findings 기반 재진입
  - 산출물: fixer run payload 및 loop 규칙
- [x] review-fix 반복 횟수 제한 추가
  - 설계 기준: `review.max_rounds` 기반 무한 루프 방지
  - 산출물: retry cap rule

### 3.2 Guardrail Engine
- [x] 파일 정책 schema 정의
  - 설계 기준: `allow | approval_required | deny`
  - 산출물: `FilePolicyRule`
- [x] 명령 정책 schema 정의
  - 설계 기준: `allow | approval_required | deny`
  - 산출물: `CommandPolicyRule`
- [x] `config.toml`에서 policy 로딩 구현
  - 설계 기준: 코드 수정 없이 정책 조정 가능
  - 산출물: guardrail config loader
- [x] command/file 접근 시 policy 검사 연결
  - 설계 기준: validation 시작 전 preflight
  - 산출물: guardrail preflight check
- [x] approval required 흐름 정의
  - 설계 기준: 즉시 실패 대신 `AWAITING_APPROVAL`
  - 산출물: approval pending state rule

### 3.3 Execution Trace
- [x] trace event schema 확장
  - 설계 기준: `session_id`, `run_id`, `workflow_state`, `correlation_id` 추가
  - 산출물: 확장된 `TraceEvent`
- [x] trace 상관관계 규칙 정의
  - 설계 기준: request, task, run 연결
  - 산출물: correlation id 생성 규칙
- [x] 주요 workflow 이벤트 발행 연결
  - 설계 기준: review/fix/guardrail/approval 이벤트 포함
  - 산출물: trace publisher 확장
- [x] append-only 저장 유지
  - 설계 기준: 조회 최적화보다 timeline 복원 우선
  - 산출물: 기존 `TraceRepository` 유지

### 3.5 Week 3 Hardening
- [x] event normalizer 분리
  - 설계 기준: orchestrator 내부의 raw event shape 해석 책임 분리
  - 산출물: `EventNormalizer`
- [x] reviewer terminal payload 필수 필드 검증 추가
  - 설계 기준: `review_decision|decision|result`, `summary` 누락 시 명시적 실패
  - 산출물: reviewer decision parsing hardening
- [x] approval record와 resolve trace 계약 추가
  - 설계 기준: pending approval을 resume 가능한 구조로 남김
  - 산출물: `ApprovalRecord`, `approval_resolved`
- [x] trace replay 유틸 추가
  - 설계 기준: request 단위 state/run/approval/validation timeline 복원
  - 산출물: `TraceReplay`
- [x] hardening 회귀 테스트 추가
  - 설계 기준: nested payload, role fallback, summary 누락, approval resolve 검증
  - 산출물: `unittest` 시나리오 확장

### 3.4 Week 3 검증
- [x] 금지 command가 실행 전에 차단되는지 확인
- [x] approval required 파일 접근이 대기 상태로 바뀌는지 확인
- [x] reviewer가 `fix_required`를 반환하면 fixer가 자동 실행되는지 확인
- [x] request 1건에 대한 trace timeline 복원이 가능한지 확인
