# EXP-051 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-06-30
> EXP-051: 2026-06-30, glm-5.1:cloud, react, **N=10**전 vs abyssal (시간 제약)
> 팀 모드: fixed
> manifest: `.temp/experiments/fixed-baselines/manifests/dynamic-v2.json` (sha256:`564353a6`) — player/opponent `modern_replays`, 30 매치업 풀(중 10판 실행)
> 비교: EXP-050e (react, glm-5.1, 63.3%) — 직전 baseline(같은 코드 베이스 + plan resilience만 추가). 참조: EXP-050a (react, 70%, 시리즈 최고).

> ⚠️ **N=10 < 30 통계 유의성 낮음**. 시간 제약으로 10판만 진행. paired 비교는 동일 매치업으로 공정하나, 확정은 **N=30 본측정 필요**. 본 보고서는 N=10 결과 + 정성 분석이며, 완료 후 재분석 필요.

---

## 0. 실험 조건 (팀 구성 — 매치업 격리)

| 항목 | 값 |
|------|-----|
| team_mode | fixed |
| manifest | `.temp/experiments/fixed-baselines/manifests/dynamic-v2.json` (sha256:`564353a6`) |
| 매치업 | player/opponent `modern_replays`(25,192) 풀에서 30 매치업, **첫 10판 실행** |
| oracle | on (`--enable_showdown_oracle`) |
| lead selection | on (`--enable_llm_lead_selection`, `--max_tokens 65536`) — 050 시리즈 argv 일치 |
| 비교 기준 | EXP-050e (직전 baseline, 동일 manifest·oracle·lead selection) |

> **첫 smoke 교훈**: `--enable_llm_lead_selection`(+ `--max_tokens 65536`) 누락 시 teampreview가 random 폴백해 my_plan seed가 안 됨. 본 측정은 두 플래그 모두 ON(050 시리즈 일치)으로 재실행.

---

## 1. 실험 결과 비교

### 1.1 승률 (N=10 paired)

| 비교 | base (동일 10 매치업) | EXP-051 | 변화 |
|------|----------------------|---------|------|
| **vs EXP-050e (직전 baseline)** | 60% (6/10) | **90% (9/10)** | **+30pp** |
| vs EXP-050a post-fix (시리즈 최고) | 80% (8/10) | 90% (9/10) | +10pp |

> archive의 050a JSON(53.3%)은 oracle 버그 **수정 전(pre-fix)** 실행(`exp-050a...analysis.md:24` "버그 전 53.3% · 후 70%")이라 EXP-051(oracle 정상)과 비교 불공정 — 제외. 공식 050a(70%) = post-fix JSON(`20260626_033745`).

**paired net (discordant pairs)**:

| 비교 | 패→승 | 승→패 | net | McNemar z |
|------|-------|-------|-----|-----------|
| vs 050e | 4 (idx 2,5,6,8) | 1 (idx 0) | **+3** | 1.34 |
| vs 050a | 2 (idx 3,5) | 1 (idx 0) | +1 | 0.58 |

구간별(표본 작아 참고용): EXP-051 배틀 길이 8–21턴(평균 14.3). 짧은(<15턴) 6판 6승(100%), 긴(15+턴) 4판 3승(75%).

### 1.2 리소스 사용량 (vs 050e)

| 항목 | EXP-051 | 050e | 변화율 |
|------|---------|------|--------|
| 배틀당 LLM 호출 | 69.8 | 87.4 | −20% |
| 배틀당 prompt 토큰 | 228,420 | 281,319 | −19% |
| 배틀당 completion 토큰 | 8,217 | 10,892 | −25% |
| 배틀당 시간(초) | 224.7 | 319.8 | −30% |
| 평균 턴 | 14.3 | 17.6 | −19% |
| JSON 파싱 실패 | 1 | 1 | — |

> 리소스 감소는 주로 **배틀이 짧아진 탓**(14.3 vs 17.6턴) — 빠른 결찰. n=10 vs n=30 표본 차이도 있어 절대값보다 방향만 참고.

---

## 2. 핵심 발견

### 2.1 결정적 차이

EXP-051 = **90% (9/10)**, 직전 baseline(050e, 동일 10 매치업 60%) 대비 **+30pp, paired net +3**. 시리즈 최고(050a, 80%) 대비 +10pp, net +1. 단 n=10이라 통계 한계(McNemar z=1.34, 단측 p≈0.09).

### 2.2 가설 / 인과 추론 — ⚠️ **plan resilience의 인과는 불확실**

정성 분석(`langgraph_llm_log.jsonl`)에서 **plan resilience 메커니즘 자체에 결함** 발견:

1. **PLAN DISRUPTED 과발동 (설계 의도 이탈)**: `detect_plan_disruption`은 "내 active species 변화"를 보는데, 이게 **KO뿐 아니라 Volt Switch/pivot 자발 교체까지 잡음**. 배틀당 평균 ~40% 턴에서 발동(예: idx0 12턴 중 7턴, idx6 15턴 중 7턴). "내 KO만"이라는 설계 의도를 초과.
   - 검증: DISRUPTED 발동 53턴 중 **34%가 pivot/switch 키워드 동반**(나머지도 KO/강제교체와 잡히지 않은 자발교체 혼합). idx8 배틀에서 t3(Volt Switch)·t4·t5(switch) 발동 명확히 확인.
2. **my_plan 단기 재진술 퇴화 (050a 실패 모드 재현)**: 매턴 DISRUPTED 마커가 뜨면 LLM이 my_plan을 매번 다시 작성 → 내용이 **단기 행동으로 퇴화**. 예: `"OHKO Ogerpon with Hurricane"`, `"KO Crawdaunt with Solar Beam now"`, `"Volt Switch OHKOs Moltres and pivots"`. STRATEGY_SYSTEM_PROMPT가 금지한 "이번 턴 행동 ≠ my_plan" 원칙 위반. my_plan 기록 배틀당 16–37회(거의 매 호출).

**승률 90%의 인과 재해석**: plan resilience가 승률을 올렸다기보다, **oracle 정확도 + teampreview 풀 정보 + react pivot 전술 + LLM 단기 판단 정확도**가 지배적일 가능성. paired net +3은 이 결함(pivot 오탭 + my_plan 퇴화)에도 불구하고 나온 것으로, **순수 plan resilience 효과로 귀인 불가**. 역으로, 결함을 고치면 더 올라갈 수도 있고 노이즈일 수도 있음.

### 2.3 미해결 문제

- idx0 역퇴행(p17696/o20979, 050e/050a 모두 승·EXP-051 패): 12턴 패. my_plan `"OHKO Ogerpon with Hurricane"`(Hurricane 70% 명중 의존). 명중 의존 단기 plan + pivot 오탭 누적이 원인 후보. 단일 배틀이라 노이즈 가능성도.

---

## 3. 문제점 분석

### 🔴 P0-1: PLAN DISRUPTED 감지가 pivot 자발 교체를 오탭

| 항목 | EXP-051 |
|------|---------|
| DISRUPTED 발동 턴 비율 | ~40% (배틀당 평균) |
| 발동 53턴 중 pivot/switch 동반 | 34% (+ 잡히지 않은 자발교체) |

**근본 원인:** `detect_plan_disruption`(`battle_memory.py`)이 `active_pokemon.species` 변화만 보고, 그것이 **KO인지 자발 교체(switch/Volt Switch/pivot)인지 구분 안 함**. 설계는 "내 KO만"이었으나 구현은 "내 species 변화 전부". react agent가 pivot 전술을 자주 쓰므로 매턴 오탭 → 빈도 가드(층1 snapshot 비교)가 새 교체마다 매번 True.

**개선 방안:** KO 전용 감지로 좁히기 — 교체 직전 active가 `fainted`였는지(`memory`에 prev active의 fainted 상태 snapshot) 또는 `battle.active_pokemon`이 KO 후 강제 교체인지 판별. 자발 교체(switch 명령/pivot 무브 후)는 disruption에서 제외.

### 🔴 P0-2: my_plan 단기 재진술 퇴화 (050a 실패 모드 재현)

| 항목 | EXP-051 |
|------|---------|
| my_plan 단기 행동 퇴화 예시 | "OHKO Ogerpon with Hurricane", "KO Crawdaunt now", "Volt Switch OHKOs Moltres" |
| my_plan 기록 빈도 | 배틀당 16–37회 (거의 매 LLM 호출) |

**근본 원인:** P0-1의 과발동이 매턴 DISRUPTED 마커 → LLM이 매턴 my_plan 재작성 → STRATEGY_SYSTEM_PROMPT의 "LONG-TERM win path" 지시가 묻힘. 050a의 95.4% 단기 재진술 실패 모드가 plan resilience 마커에 의해 **재활성화**.

**개선 방안:** P0-1 해결(KO 전용 감지)로 마커 빈도 급감이 1차. 추가로 my_plan 갱신 쿨다운(같은 plan 유지 권장) 또는 단기 행동 감지 거부 로직.

### 🟢 P2-1: idx0 단일 배틀 역퇴행

**내용:** 단일 배틀(p17696/o20979) 노이즈 가능성. 본측정(N=30) 후 재확인.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-050e | EXP-051 | 상태 |
|------|----------|---------|------|
| plan disruption 대응 부재(KO 시 plan 갱신 없음) | 🔴 미구현 | 🟡 구현됐으나 오탭(pivot) | 🟡 완화(결함) |
| my_plan 단기 재진술(050a 모드) | 🟡 (strategy 노드로 완화) | 🔴 (마커 과발동으로 재활성화) | 🔴 악화 |
| teampreview 풀 정보 / oracle 정상 | ✅ | ✅ | ✅ 유지 |

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|------|------|------|--------|-----------|
| 1 | **KO 전용 감지** (pivot 자발 교체 제외) | DISRUPTED 40% 과발동 + my_plan 퇴화 근본 원인 | 중 | 마커 빈도 KO 수준으로 감소 → my_plan 안정화, 순수 plan resilience 효과 측정 가능 |
| 2 | 본측정 N=30 확정 | n=10 통계 한계(z=1.34, p≈0.09) | 낮 | 효과 유의성 확정 |
| 3 | idx0 역퇴행 정성 재확인 | 단일 배틀 노이즈 여부 | 낮 | 인과 명확화 |

> 모든 권고는 범용 gen9ou 전략 관점. KO 감지 정교화는 어떤 상대에게나 동일 적용.

---

## 6. 다음 단계

### 즉시
- [ ] **KO 전용 감지**로 `detect_plan_disruption` 수정(prev active `fainted` 상태로 KO/자발교체 구분) → 후속 실험(번호 자동 할당)
- [ ] smoke에서 PLAN DISRUPTED 발동 빈도가 "내 KO 횟수" 수준으로 떨어지는지 검증

### EXP-051 N=30 완료 후
- [ ] paired net(vs 050e) 유의성 재확인 (z ≥ 1.96 목표)
- [ ] my_plan 단기 재진술 비율 변화 측정
- [ ] idx0 역퇴행 지속 여부

### 후속 실험
- [ ] **KO 전용 감지 후속 실험**(pivot 오탭 제거) — baseline 대비 변수 1개만 변경. 목표: DISRUPTED 발동 빈도 ↓ + my_plan 장기화 + 승률 유지/향상.
- [ ] handoff 로드맵 후속 레버: 게임 phase 노드 / 자원 ledger / opp stats 추정 (plan resilience 안정화 후).
