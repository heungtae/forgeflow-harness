# Codex Harness Week 2 체크리스트

## 문제 정의
- 목적: Week 1에서 확보한 session/workspace 실행 골격 위에 요청 분해, task별 coder 실행, validation을 묶은 1회 자동 workflow를 완성한다.
- 범위: Decomposition Agent, Workflow State Machine, Coding Loop, Quality Gate, validation artifact 추적
- 성공 기준: 샘플 요청 1건이 task graph 생성, task별 Codex run, validation 실행을 거쳐 `DONE`, `NEEDS_FIX`, `FAILED` 중 하나의 최종 상태로 종료돼야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - decomposition input/output schema와 validation 정의
  - workflow 상태 enum과 상태 전이 규칙 구현
  - task 단위 coder run orchestration 연결
  - ordered validation command 실행과 artifact 저장
- 비기능 요구사항:
  - 상태 전이와 side effect를 분리한다.
  - trace만으로 task별 실행과 validation 결과를 복원할 수 있어야 한다.
  - 기존 `unittest` 기반 테스트 스타일을 유지한다.
- 우선순위:
  - 1순위: task graph와 상태 머신
  - 2순위: coder run 연결
  - 3순위: validation artifact 저장

## 제약 조건
- 일정/리소스:
  - Week 2 종료 시 reviewer/fixer/PR 없이도 decomposition부터 validation까지 1회 자동 루프가 성립해야 한다.
- 기술 스택/환경:
  - Python 3.11+, 현재 `src/forgeflow_harness/*` 구조, `unittest` 기반 테스트를 유지한다.
  - Codex App Server 연동은 기존 `CodexAdapter`를 확장하는 방식으로 진행한다.
- 기타:
  - decomposition 품질보다 schema 안정성과 실행 가능성을 먼저 확보한다.
  - 병렬 task 실행과 repo별 validation 자동 추론은 Week 2 범위에서 제외한다.

## 아키텍처/설계 방향
- 핵심 설계:
  - decomposition output은 `TaskNode`, `TaskGraph` 모델로 강제한다.
  - workflow 엔진은 상태 계산과 외부 실행기를 분리한다.
  - validation은 workspace harness 내부 실행기로만 수행한다.
- 대안 및 trade-off:
  - 복잡한 planner 대신 고정 3-step decomposition 기본형으로 시작해 schema와 orchestration 안정성을 먼저 확보한다.
  - 최종 상태를 단순화해 `DONE`, `NEEDS_FIX`, `FAILED`만 실제 종료 상태로 사용하고 reviewer/approval 전이는 Week 3~4로 미룬다.
- 리스크:
  - task graph와 state machine이 어긋나면 loop가 중간 상태에서 멈출 수 있다.
  - validation command가 workspace 외부에서 실행되면 요청별 격리가 깨질 수 있다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 2.1 Decomposition Agent
- [x] decomposition input schema 정의
  - 설계 기준: `request_id`, `goal`, `constraints`, `repo`, `workspace_path` 포함
  - 산출물: decomposition request model
  - 진행 현황: `HarnessRequest`와 task run payload 조합으로 입력 경계 반영
- [x] task graph output schema 정의
  - 설계 기준: `TaskNode(id, goal, depends_on, status)`와 `TaskGraph(request_id, tasks)` 유지
  - 산출물: task graph model
  - 진행 현황: `TaskNode`, `TaskGraph` 모델 추가 및 기본 3-step 구조 구현 완료
- [x] task graph 생성 프롬프트/정책 초안 작성
  - 설계 기준: 기본 출력은 `T1 root cause/context`, `T2 implementation`, `T3 regression test/verification` 3단계로 고정
  - 산출물: decomposition prompt template 또는 기본 decomposition policy
  - 진행 현황: 로컬 고정 3-step decomposition policy 구현 완료
- [x] task graph validation 추가
  - 설계 기준: 중복 `id`, 빈 `goal`, 존재하지 않는 dependency, 순환 의존 방지
  - 산출물: validation logic

### 2.2 Workflow State Machine
- [x] 상태 enum 정의
  - 설계 기준: `NEW -> DECOMPOSING -> DECOMPOSED -> CODING -> VALIDATING -> DONE | NEEDS_FIX | FAILED`
  - 산출물: workflow states
  - 진행 현황: `WorkflowState` 추가 완료
- [x] 상태 전이 규칙 표 작성
  - 설계 기준: decomposition 성공 시 `DECOMPOSED`, task run 시작 시 `CODING`, validation 시작 시 `VALIDATING`, validation 실패 시 `NEEDS_FIX`, adapter/graph 오류 시 `FAILED`
  - 산출물: transition map
  - 진행 현황: 오케스트레이터 내부 상태 전이 이벤트로 구현 완료
- [x] 전이 실행기 구현
  - 설계 기준: 순수 상태 계산 함수와 Codex/validation 실행기를 분리
  - 산출물: state transition service
- [x] 예외 시 복구 가능한 상태 정의
  - 설계 기준: validation 실패만 `NEEDS_FIX`로 복구 가능, decomposition 실패와 adapter 통신 실패는 terminal failure로 구분
  - 산출물: error handling rule

### 2.3 Coding Loop
- [x] coder agent 실행 요청 포맷 정의
  - 설계 기준: `task_id`, `task_goal`, `repo`, `workspace_path`, `constraints` 포함
  - 산출물: coder input model
  - 진행 현황: task run payload로 입력 필드 반영 완료
- [x] adapter run API 일반화
  - 설계 기준: decomposition run과 coder run이 모두 동일한 payload entrypoint를 사용할 수 있어야 한다.
  - 산출물: generic `start_run(session_id, input_payload)` 형태의 adapter API
  - 진행 현황: generic payload 기반 `start_run()`으로 변경 완료
- [x] coder session run 연결
  - 설계 기준: task graph 순서대로 task 단위 run 시작
  - 산출물: task run orchestration
- [x] agent 응답 이벤트를 내부 상태에 반영
  - 설계 기준: run 시작, task 완료, task 실패 이벤트를 workflow/task status와 연결
  - 산출물: event mapper
  - 진행 현황: `task_started`, `task_finished` trace 이벤트 반영 완료
- [x] task 완료 판정 기준 정의
  - 설계 기준: 마지막 task 완료 후 `VALIDATING`로 전이하고, 중간 task 완료는 다음 task 시작 조건으로만 사용
  - 산출물: task completion rule
  - 진행 현황: 마지막 task 후 validation 전이 로직 구현 완료

### 2.4 Quality Gate
- [x] validation command 설정 추가
  - 설계 기준: `HarnessConfig`에서 ordered command list를 주입하고 Week 2 기본값은 `python3 -m unittest discover -s tests -v`로 시작
  - 산출물: validation command config
  - 진행 현황: `config.toml`, config loader, 기본값 반영 완료
- [x] command 실행기 연결
  - 설계 기준: worktree path 내부에서만 subprocess 실행
  - 산출물: validation runner
- [x] 성공/실패 결과를 상태 전이에 반영
  - 설계 기준: `VALIDATING` 성공 시 `DONE`, 실패 시 `NEEDS_FIX`
  - 산출물: validation result handler
- [x] validation artifact 수집
  - 설계 기준: `ValidationResult(command, exit_code, stdout, stderr, status)` 구조로 stdout/stderr/exit code 저장
  - 산출물: artifact collector 및 trace payload 확장

### 2.5 Week 2 검증
- [x] 샘플 요청이 기본 3개 task graph로 분해되는지 확인
  - 검증: happy path decomposition 테스트
- [x] task graph validation이 cycle/빈 goal/중복 id를 차단하는지 확인
  - 검증: invalid graph 테스트
- [x] coder run 후 validation까지 자동 진행되어 최종 `DONE`으로 종료되는지 확인
  - 검증: success orchestration 테스트
- [x] validation 실패 시 최종 상태가 `NEEDS_FIX`로 이동하는지 확인
  - 검증: failing validation command 테스트
- [x] decomposition 또는 adapter run 실패 시 최종 상태가 `FAILED`로 종료되는지 확인
  - 검증: decomposition failure 테스트
- [x] validation artifact가 trace output에 저장되는지 확인
  - 검증: trace payload assertion 테스트

## 현재 진행 요약
- 완료:
  - Week 2 설계 문서 상세화 완료
  - decomposition/task graph/workflow/validation 경계와 기본 정책 구현 완료
  - Week 1 session/workspace 준비 및 run 시작 골격 구현
  - append-only trace 저장과 CLI ingress 연결
  - 고정 3-step decomposition, task graph validation, workflow 상태 전이 구현
  - generic adapter run payload, worktree 내부 validation runner, validation artifact trace 저장 구현
  - Codex event stream polling 기반 task 완료/실패/timeout 판정 구현
  - validation profile 설정, repo 매핑, request constraint 우선순위 선택 로직 구현
  - `unittest` 기반 success / validation failure / task failure / timeout / profile selection / trace artifact 시나리오 검증
- 진행 중:
  - decomposition은 아직 Codex 기반 planner가 아니라 로컬 고정 3-step 정책이다.
  - event terminal 판정은 현재 느슨한 heuristic(`type`/`status`/`event`)에 의존하며 실제 Codex payload shape 검증이 더 필요하다.
- 다음 액션:
  - 실제 Codex App Server `/sessions/{id}/events` payload shape에 맞춰 terminal event classifier를 고정
  - repo별 validation profile 자동 선택 규칙을 repo 이름 매핑 외 방식으로 확장할지 결정
  - Week 3 reviewer/fixer/guardrail 설계와 상태 전이 연결
