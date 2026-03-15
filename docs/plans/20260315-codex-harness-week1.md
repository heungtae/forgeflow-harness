# Codex Harness Week 1 체크리스트

## 문제 정의
- 목적: 요청 1건을 받아 세션과 워크스페이스를 할당하고, Codex App Server 호출까지 연결되는 최소 실행 기반을 만든다.
- 범위: 프로젝트 골격, `config.toml`, ingress 최소 진입점, Codex Adapter, Session Manager, Workspace Harness
- 성공 기준: 샘플 요청 1건이 intake부터 session/worktree 준비까지 통과해야 한다.

## 요구사항 구조화
- 기능 요구사항:
  - 오케스트레이터 모듈 경계 확정
  - 설정 로더 연결
  - ingress 최소 채널 구현
  - session/workspace lifecycle 시작점 구현
- 비기능 요구사항:
  - 하드코딩 대신 설정 주입 우선
  - 요청별 독립 workspace 보장
- 우선순위:
  - 1순위: 설정과 모듈 구조
  - 2순위: ingress와 session 생성
  - 3순위: worktree 생성과 cleanup

## 제약 조건
- 일정/리소스:
  - Week 1 종료 시 end-to-end 완성보다 실행 골격 확보가 목표다.
- 기술 스택/환경:
  - `config.toml`, Codex session API, git worktree 사용 방향 유지
- 기타:
  - ingress는 CLI 또는 REST 중 하나만 먼저 구현해도 된다.

## 아키텍처/설계 방향
- 핵심 설계:
  - Ingress는 최소 채널 1개만 두고, 나머지 채널은 이후 주차로 미룬다.
  - Session lifecycle과 Workspace lifecycle은 분리된 서비스로 둔다.
- 대안 및 trade-off:
  - REST를 먼저 만들면 외부 연동 확장이 쉽고, CLI를 먼저 만들면 검증 속도가 빠르다.
- 리스크:
  - cleanup이 없으면 실패 요청이 workspace를 누적시킬 수 있다.

## 작업 계획
상태 규칙:
- `[ ]` 미착수
- `[/]` 진행 중
- `[x]` 완료

### 1.1 프로젝트 골격
- [ ] 오케스트레이터 모듈 디렉터리 구조 확정
  - 설계 기준: Ingress, Orchestrator, Adapter, Workspace 계층 분리
  - 산출물: 패키지/모듈 초안
- [ ] `config.toml` 초안 생성
  - 설계 기준: guardrail default, session policy, workspace limit, integration endpoint 분리
  - 산출물: 기본 설정 파일
- [ ] 애플리케이션 시작 시 설정 로더 연결
  - 설계 기준: 하드코딩 대신 설정 주입
  - 산출물: config parser + bootstrap wiring

### 1.2 Ingress 최소 진입점
- [ ] CLI 또는 REST 중 하나를 1차 ingress로 선택
  - 설계 기준: 초기 검증은 채널 1개면 충분
  - 산출물: 선택 근거 기록
- [ ] request payload DTO 정의
  - 설계 기준: `request_id`, `repo`, `goal`, `constraints` 유지
  - 산출물: request schema
- [ ] intake endpoint/command 구현
  - 설계 기준: 요청 수신 후 내부 workflow 시작 이벤트 발생
  - 산출물: ingress handler
- [ ] 잘못된 request에 대한 validation 추가
  - 설계 기준: 필수 필드 누락 방지
  - 산출물: validation rule + 실패 응답

### 1.3 Codex Adapter / Session Manager
- [ ] Codex session client interface 정의
  - 설계 기준: `/sessions`, `/run`, `/reply`, `/approve`, `/events`, `/terminate` 캡슐화
  - 산출물: adapter interface
- [ ] session 생성 API 연결
  - 설계 기준: 요청 단위 session lifecycle 시작
  - 산출물: create session flow
- [ ] session event polling 또는 subscription 방식 결정
  - 설계 기준: trace/event 수집 가능한 방식 선택
  - 산출물: event fetch design note
- [ ] session 종료 처리 구현
  - 설계 기준: 정상 종료와 실패 종료 분리
  - 산출물: terminate flow

### 1.4 Workspace Harness
- [ ] repo checkout 책임 경계 정의
  - 설계 기준: clone/checkout/worktree 생성 책임을 workspace 계층에 고정
  - 산출물: workspace manager interface
- [ ] git worktree 생성 구현
  - 설계 기준: 요청별 독립 작업 공간 확보
  - 산출물: worktree creation flow
- [ ] branch naming 규칙 정의
  - 설계 기준: request_id 기반 충돌 방지
  - 산출물: branch naming helper
- [ ] 작업 디렉터리 정리 정책 추가
  - 설계 기준: 실패 시에도 orphan workspace 최소화
  - 산출물: cleanup hook

### 1.5 Week 1 검증
- [ ] 샘플 request로 session 생성까지 확인
- [ ] 샘플 request로 worktree 생성까지 확인
- [ ] 실패 시 session/workspace 정리 여부 확인
