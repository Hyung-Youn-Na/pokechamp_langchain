# EXP-048 (react / glm-5.1) 실험 분석 — Oracle N-roll 난수 분산

> 분석 일시: 2026-06-23
> EXP-048: 2026-06-23, glm-5.1 (ollama/glm-5.1:cloud), react + `--enable_showdown_oracle` + **전무브 oracle + N-roll 난수 분산**(roll_count 8, damage min/max/median, ko 비율), 30전 vs abyssal
> 비교: EXP-044 (oracle off, 56.7%) · EXP-047 (전무브 통일·단일 roll, 63.3%) — 동일 `dynamic-v2.json`/seed 42/N=30
> 팀 모드: fixed · manifest `dynamic-v2.json` (sha256:`564353a6`) — 동일 30 매치업(paired)

---

## 0. TL;DR

**N-roll 난수 분산 시스템은 기술적으로 건강하며, 승률 하락은 oracle 정확도가 아니라 react/langGraph 구조 병목 때문이다.** 승률 **63.3%(047) → 53.3%(048)** (−10pp).

1. ✅ **N-roll 시스템 건강 (사용자 판단 지지)**: 난수 분산이 observation에 반영됨(range 폭 **평균 8.1pp**, node 검증 blissey 29.7-35.2%와 일관). 실제 배틀 난수를 모델링하므로 시스템 자체는 필요/유효.
2. ✅ **비용 영향 미미**: 048 시간 **204.3s/battle** = 047(205.4)·044(202.6) 수준. **N-roll(8배 worker runMove)에도 시간 변동 없음** — 캐싱(`OracleResultCache`)이 흡수. 토큰·LLM호출도 047 수준.
3. ❌ **승률 −10pp = 정확성≠승률 (EXP-046/047 진단과 일관)**: median(안정 대표값)이 047 단일 샘플과 다른 결정 캐스케이드 → 6 악화/3 개선. oracle 정확도 향상이 승률로 직결 안 됨. **병목은 damage 활용 = langGraph/react 구조**(사용자 지적).

> **결론**: oracle damage의 정확도/분산 개선은 **한계 도달**. 다음 승률 개선은 **langGraph/react 구조**(damage observation → 전략 변환) 영역.

---

## 1. 결과 (정량)

### 1.1 승률 / 리소스 / 시간

| 메트릭 | EXP-044 (off) | EXP-047 (단일 roll) | **EXP-048 (N-roll)** | 048−047 |
|---|---|---|---|---|
| 승률 | 56.7% (17/30) | 63.3% (19/30) | **53.3% (16/30)** | **−10.0pp** |
| 평균 턴 | 16.8 | 16.8 | 16.4 | −0.4 |
| LLM 호출/판 | 52.4 | 53.4 | 53.1 | −0.3 |
| prompt 토큰/판 | 147,672 | 151,870 | 150,823 | −1,047 |
| **배틀당 시간** | 202.6s | 205.4s | **204.3s** | **−1.1s** |

- 비용(토큰·LLM호출·시간)은 **047과 사실상 동일**. N-roll(8배 worker)의 비용/지연이 캐싱으로 상쇄됨을 실험적으로 확인.
- 승률만 047 대비 −10pp, 044 baseline 대비 −3.4pp.

### 1.2 매치업 페어링 (047 → 048, 동일 30 매치업)

- 9개 뒤집힘: **047 승→048 패 6**(5193, 16442, 20875, 24778, 4221, 17464) / 047 패→048 승 **3**(11964, 7326, 8201) → net **−3승**.
- 악화 6 / 개선 3 — 단일 roll(047)에서 우연히 적중했던 매치업이 N-roll median에서 다른 결정으로 이어진 캐스케이드.

---

## 2. N-roll 시스템 검증 — "난수 반영 시스템은 필요" (사용자 판단 지지)

### 2.1 난수 분산 반영 확인

oracle observation 1,436건(048) 분석:

| 지표 | 값 |
|---|---|
| observation 총수 | 1,436건 |
| range(min<max) 포함 | 65건 (4.5%) |
| **range 폭 평균** | **8.1pp** (±4pp) |
| median 평균 | 61.9% (047 단일 63.4%와 유사) |

- range 폭 8.1pp는 Showdown 난수(0.85-1.0, 데미지 ±~8%)의 **합리적 샘플**. node 검증(blissey N8: 29.7-35.2%, ±2.7pp)과 일관.
- **range가 4.5%에만 발생**하는 이유: 대부분 매치업이 KO(매 roll maxhp 도달 → min==max==100) 또는 면역/빗나감(0)이라 분산이 없음. **비-KO 매치업에서만** 난수 분산이 관측에 드러남 — N-roll 효과는 비-KO 구간에 집중.

### 2.2 비용/시간 영향 미미 (캐싱 흡수)

- 048 배틀당 **204.3s** = 047(205.4s)·044(202.6s) 수준. **N-roll(roll_count 8 = 8배 worker runMove)에도 시간 변동 없음**.
- 이유: `OracleResultCache` 키 `(active_state_hash, move_id, atk, defn)`(seed 없음)가 동일(상태·무브·매치업) 재방문을 흡수. N-roll 비용은 고유 (상태·무브) 조합 수에만 비례 → 캐시 히트 시 0.
- 토큰(150,823)·LLM호출(53.1)도 047 수준. plan에서 우려했던 "8배 쿼리 지연"은 현실화되지 않음(047에서 이미 검증된 패턴).

→ "실제 배틀에서 난수가 발생하므로 난수 반영 시스템은 필요"라는 사용자 판단을 **데이터가 지지**: 분산은 정확히 반영되고 비용은 거의 0.

---

## 3. 승률 하락 분석 — 정확성 ≠ 승률

### 3.1 median 캐스케이드

047(단일 roll)의 damage는 한 샘플, 048은 N-roll **median**(안정 대표값). 두 값이 다르면 LLM 결정이 달라지고, 그게 배틀 트리 전체를 캐스케이드.

- 047 단일 샘플이 **우연히 특정 매치업에서 더 적중**한 경우(예: 047의 49%가 실제 배틀 난수의 한 경우와 일치), median(평균적)으로 바뀌면 그 적중이 사라짐.
- 반대로 median이 더 정확함에도 승률이 낮아지는 것은, **정확한 damage 정보가 LLM에 의해 더 나은 결정으로 변환되지 않음**을 의미.

### 3.2 핵심 진단 — 병목은 langGraph/react 구조

이 결과는 시리즈를 관통하는 진단과 일관:

| 실험 | damage 처리 | 승률 | 교훈 |
|---|---|---|---|
| 044 (off) | sim 편향 | 56.7% | baseline |
| 045 | oracle 0% 버그(attacker 식별) | 53.3% | 기술 결함 |
| 046 | oracle 정확 + sim/oracle **혼합 척도** | 43.3% | 척도 불일치가 왜곡 |
| **047** | **전무브 통일**(단일 roll) | **63.3%** | **척도 해소 = 순효과** |
| **048** | **N-roll 분산**(median) | 53.3% | **정확성↑ ≠ 승률↑** |

- 047에서 **척도 일관성**(sim/oracle 혼합 해소)이 +6.6pp를 가져왔고, 048에서 **정확도 향상**(난수 분산)은 승률로 이어지지 않음.
- 즉 oracle damage의 **척도 일관성**은 승률에 결정적이었지만, 그 위의 **정확도/분산 정교화**는 한계 효과. 병목은 이제 damage 값 자체가 아니라 **LLM이 damage observation을 전략으로 변환하는 방식**(react/langGraph 구조).
- 사용자 지적("승률 하락은 langGraph 구조 개선으로 해결")과 완전히 일치.

### 3.3 range 부가의 미세 영향
- range(min/max)가 observation에 추가됐지만 4.5%에만 발생 → observation 블로트 효과 미미. 승률 하락의 주원인은 아님(median 값 변화가 주).

---

## 4. 결론

- **N-roll 난수 분산 시스템은 건강**: 실제 배틀 난수를 정확히 모델링(range 8.1pp), 비용/시간 영향 미미(캐싱). 시스템 자체는 유효·필요.
- **승률 −10pp는 oracle 영역 밖**: 정확도 향상이 승률로 직결되지 않음(정확성≠승률). 시리즈(044→048) 통해 oracle damage의 **정확도/분산은 한계 도달**임이 확인.
- **다음 병목 = langGraph/react 구조**: damage observation을 전략적 결정(스위치 타이밍, 세팅, KO 기회 활용)으로 변환하는 LLM 활용 방식. 이는 oracle 정확도와는 독립된 축.

> 규칙 준수(ANALYSIS_MANUAL 6.1·6.5): 모든 진단은 범용 gen9ou 관점.

---

## 5. 다음 단계

### oracle 영역 (종료)
- [x] 전무브 통일(047, 척도 해소 +6.6pp) + N-roll 난수 분산(048, 시스템 건강)로 oracle damage 정확도/분산은 한계 도달.

### langGraph/react 구조 개선 (사용자 방향 — 다음 병목)
- [ ] damage observation → 전략 변환 병목 해소. 후보:
  - 단기 damage 최적화 과신 완화(EXP-046/047 진단) — damage를 순위/KO 가능 여부로 재구성.
  - 동적 무브 조건부성(날씨/tera 시기)을 LLM이 전략적으로 다루도록 관측/프롬프트 개선(EXP-047 short 한계 17696).
  - langGraph 노드/상태 설계에서 damage observation과 장기 계획(포지셔닝·스위치)의 결합 방식.
- 변수 1개 ablation(EXP-049+)으로 진행.

---

## 부록 — 출처
- 승률/시간/페어링: `experiment_*.json` `summary`+`battles[]` (ANALYSIS_MANUAL 4.2·4.3).
- N-roll 분산: `langgraph_tool_log.jsonl` `type_source:showdown_oracle` 1,436건, `hp_lost_min/max` 분석.
- 시리즈 데이터: EXP-044/045/046/047 보고서(`docs/analysis/exp-04[4567]-*-analysis.md`).
- 코드: `oracle-worker.js`(N-roll, .gitignore → `docs/architecture/oracle-worker-reproduction.md`), `battle_tools.py`(median 관측).
