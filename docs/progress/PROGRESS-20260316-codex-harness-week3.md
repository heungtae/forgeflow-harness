# 작업 내용
- Week 3 구현 범위를 기준으로 `src/forgeflow_harness/models.py`, `src/forgeflow_harness/config.py`, `src/forgeflow_harness/orchestrator.py`를 확장해 reviewer/fixer loop, guardrail 정책, trace correlation 필드를 추가했다.
- `src/forgeflow_harness/guardrails.py`를 추가해 command/file policy를 `allow | approval_required | deny`로 평가하는 전용 엔진을 분리했다.
- `src/forgeflow_harness/workspace.py`에 changed file 조회를 추가해 validation 전 file guardrail preflight에 연결했다.
- `config.toml`에 review/guardrail 기본 설정을 반영했다.
- `tests/test_harness.py`를 확장해 reviewer pass, fixer 재실행, approval pause, guardrail deny, trace correlation 시나리오를 검증하도록 바꿨다.
- `docs/plans/20260315-codex-harness-week3.md`를 체크리스트 수준에서 구현 가능한 설계/완료 기준 문서로 구체화했다.
- hardening 단계에서 `src/forgeflow_harness/normalizer.py`를 추가해 raw Codex event 정규화 책임을 분리했다.
- `src/forgeflow_harness/orchestrator.py`에 reviewer terminal payload 필수 필드 검증과 `decision_parse_failed` trace 기록을 추가했다.
- `src/forgeflow_harness/models.py`, `src/forgeflow_harness/trace.py`, `src/forgeflow_harness/approvals.py`를 확장해 `ApprovalRecord`, `approval_resolved`, `TraceReplay`, 내부 `resume()` 계약을 추가했다.
- `config.toml`과 `src/forgeflow_harness/config.py`에 `review.required_reviewer_decision_fields`, `guardrail.approval_timeout_seconds` 설정을 추가했다.
- `tests/test_harness.py`에 nested reviewer payload, role fallback, summary 누락 실패, approval resolve, trace replay 시나리오를 추가했다.

## 검증
- `python3 -m unittest -v tests.test_harness`
- 결과: 27개 테스트 통과

## 다음 할일
- 실제 Codex App Server event payload와 reviewer/fixer terminal event 규칙이 맞는지 통합 검증한다.
- 내부 `resume()` 계약을 실제 approval resume API/UI에 연결한다.
- approval 승인 후 중단된 phase를 다시 실행하는 orchestrator 재진입 경로를 구현한다.

## 주의사항
- reviewer/fixer terminal event 판정은 normalizer로 분리됐지만 실제 운영 payload 변형은 아직 통합 검증이 필요하다.
- file guardrail은 현재 worktree 변경 결과와 runtime observed action 기준이므로 tool 내부 세분화 정책은 후속 강화 여지가 있다.
- approval resume은 trace 기록과 내부 계약까지만 구현되어 있고 실제 재개 endpoint/UI는 아직 없다.
