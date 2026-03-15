# Codex Harness Week 2 체크리스트

## 문제 정의
- 목적: 요청을 작은 task graph로 분해하고 coder loop와 quality gate를 연결해 자동 실행 흐름을 만든다.
- 범위: Decomposition Agent, Workflow State Machine, Coding Loop, Quality Gate
- 성공 기준: 샘플 요청이 task graph 생성부터 validation까지 자동 진행돼야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - decomposition schema와 validation 정의
  - workflow 상태 전이 규칙 구현
  - coder run orchestration 연결
  - build/test/lint 기반 quality gate 연결
- 비기능 요구사항:
  - 상태 전이와 side effect를 분리한다.
  - validation artifact를 추적 가능하게 남긴다.
- 우선순위:
  - 1순위: task graph와 상태 머신
  - 2순위: coder run 연결
  - 3순위: validation 자동화

## 제약 조건
- 일정/리소스:
  - Week 2 종료 시 한 번의 coding loop와 validation loop가 자동으로 이어져야 한다.
- 기술 스택/환경:
  - 상태는 아키텍처 문서의 전이 순서를 유지한다.
- 기타:
  - decomposition 품질보다 schema 안정성과 실행 가능성을 먼저 확보한다.

## 아키텍처/설계 방향
- 핵심 설계:
  - decomposition output은 task graph schema로 강제한다.
  - validation은 workspace harness를 통해서만 실행한다.
- 대안 및 trade-off:
  - 복잡한 planner보다 단순한 3-step decomposition부터 시작하는 것이 안정적이다.
- 리스크:
  - task graph와 state machine이 어긋나면 loop가 중간 상태에서 멈출 수 있다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 2.1 Decomposition Agent
- [ ] decomposition input schema 정의
  - 설계 기준: goal, constraints, repo context 포함
  - 산출물: decomposition request model
- [ ] task graph output schema 정의
  - 설계 기준: `id`, `goal`, `depends_on` 유지
  - 산출물: decomposition response model
- [ ] task graph 생성 프롬프트/정책 초안 작성
  - 설계 기준: root cause, implementation, regression test 단계 분리
  - 산출물: decomposition prompt template
- [ ] task graph validation 추가
  - 설계 기준: 순환 의존, 빈 goal 방지
  - 산출물: validation logic

### 2.2 Workflow State Machine
- [ ] 상태 enum 정의
  - 설계 기준: `NEW -> DECOMPOSED -> CODING -> VALIDATING -> REVIEWING -> NEEDS_FIX -> READY_FOR_PR -> DONE`
  - 산출물: workflow states
- [ ] 상태 전이 규칙 표 작성
  - 설계 기준: 성공/실패/승인 필요 분기 명시
  - 산출물: transition map
- [ ] 전이 실행기 구현
  - 설계 기준: side effect와 상태 변경 분리
  - 산출물: state transition service
- [ ] 예외 시 복구 가능한 상태 정의
  - 설계 기준: RETRY 대상과 terminal failure 구분
  - 산출물: error handling rule

### 2.3 Coding Loop
- [ ] coder agent 실행 요청 포맷 정의
  - 설계 기준: 현재 task, repo path, constraints 포함
  - 산출물: coder input model
- [ ] coder session run 연결
  - 설계 기준: task 단위 run 시작
  - 산출물: run orchestration
- [ ] agent 응답 이벤트를 내부 상태에 반영
  - 설계 기준: command/result/event를 workflow와 연결
  - 산출물: event mapper
- [ ] task 완료 판정 기준 정의
  - 설계 기준: 구현 완료와 검증 대기 상태 분리
  - 산출물: task completion rule

### 2.4 Quality Gate
- [ ] build/test/lint 실행 명령 매핑 정의
  - 설계 기준: repo별 기본 명령 세트 준비
  - 산출물: validation command config
- [ ] command 실행기 연결
  - 설계 기준: workspace harness를 통해서만 실행
  - 산출물: validation runner
- [ ] 성공/실패 결과를 상태 전이에 반영
  - 설계 기준: `VALIDATING` 성공 시 `REVIEWING`, 실패 시 `NEEDS_FIX`
  - 산출물: validation result handler
- [ ] validation artifact 수집
  - 설계 기준: stdout/stderr/exit code 저장
  - 산출물: artifact collector

### 2.5 Week 2 검증
- [ ] 샘플 요청을 3개 task graph로 분해되는지 확인
- [ ] coder run 후 validation까지 자동 진행되는지 확인
- [ ] validation 실패 시 fix 대기 상태로 이동하는지 확인
