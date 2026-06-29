# PokéChamp 문서 지도

> 실험·개발 관련 문서의 네비게이션 인덱스. 배틀 데이터 자체는 `.temp/experiments/` (3분할: `baselines/`/`active/`/`archive/`)에, 핵심 규칙은 루트의 `experiment-context.md`에 있다.

## 핵심 (루트)
- [`experiment-context.md`](../experiment-context.md) — ★ 실험 규칙·행동 규칙·baseline 인덱스. **모든 작업의 출발점** (섹션 0 행동 규칙, 섹션 5 baseline 전경표, 섹션 7 baseline 백업).
- [`exp_analysis/`](../exp_analysis/) — 분석 절차 매뉴얼([`ANALYSIS_MANUAL.md`](../exp_analysis/ANALYSIS_MANUAL.md)) + 보고서 템플릿([`template.md`](../exp_analysis/template.md)). 새 분석은 이 절차를 따른다.

## 백업 (`backups/`)
- [`backups/baselines/RESTORE.md`](../backups/baselines/RESTORE.md) — 공식 baseline 3종의 git-tracked 백업·복원 안내. 도구는 [`scripts/backup/backup_baselines.py`](../scripts/backup/backup_baselines.py). 디스크 장애 시 `git clone` 으로 baseline 전체 복원.

## 실험 분석 보고서 (`analysis/`)
동일 조건(glm-5.1, temp 0.3, seed 42, N=30, 상대 abyssal)의 baseline 3종 + 비교 분석.

| 문서 | 요약 |
|------|------|
| [EXP-030/031 — ReAct](analysis/exp-030-react-glm51-analysis.md) | stopping-criteria 개선 전후 비교 (EXP-031 baseline의 비교 근거) |
| [EXP-031 — ReAct baseline ★](analysis/exp-031-react-glm51-analysis.md) | 76.7%, 도구 호출량 60% 감소 후 장기전 안정 |
| [EXP-032 — IO baseline ★](analysis/exp-032-io-glm51-analysis.md) | 53.3%, 장기전 붕괴 |
| [EXP-033 — Minimax baseline ★](analysis/exp-033-minimax-glm51-analysis.md) | 80.0%, 알고리즘이 지배적 요인 |

> ★ = 공식 baseline (`experiment-context.md` §5 baseline 전경표 참조).

## 아키텍처 (`architecture/`)
- [LangGraph ReAct 에이전트 아키텍처](architecture/langgraph-architecture.md)
- [LangGraph Tool 아키텍처](architecture/langgraph-tools-architecture.md)
- [ReAct 구조 재설계 roadmap](architecture/react-architecture-redesign.md) — B(5노드) + D(턴 메모리) + Smogon 결합 (EXP-049+)
- [Minimax Prompt Algorithm 작동 방식](architecture/minimax-algorithm.md)
- [Smogon 커뮤니티 데이터 정제 — 설계 의도](architecture/smogon-meta-design.md) — 정제 산출물(strategies/roles JSON)의 구조와 각 정제 결정의 why
- [Showdown Oracle Worker 재현 가이드](architecture/oracle-worker-reproduction.md) — `oracle-worker.js` 재현 절차 + 전체 소스 + mapper fix 주의
- [고정 팀 모드](architecture/fixed-team-mode.md) — manifest 기반 매치업 고정 (ablation 격리)

## ReAct Agent 노트 (`agent-notes/`)
- [LLM 기반 도구 호출 종료 판단 설계](agent-notes/react-agent-llm-based-stopping-criteria.md)
- ["should_continue" 결정 방식 분석](agent-notes/react-agent-should-continue-analysis.md)

## 도구 (`tools/`)
- [Battle Viewer (`tools/battle_viewer.py`) 문제점 분석서](tools/battle_viewer_issues.md)

## 아카이브 (`archive/`)
해결된 과거 이슈·비정형 노트. 참고용 (활성 참조 대상 아님).
- [EXP-027 — ReAct JSON 파싱 실패 근본 원인](archive/exp-027-react-glm51-analysis.md)
- [ReAct final-step valid action 반환 fix](archive/react-agent-final-step-fix.md)
- [ReAct JSON 파싱 오류 분석/해결](archive/react-agent-json-parsing-fix.md)
- [ReAct should-continue 피드백](archive/react-agent-should-continue-feedback.md)
