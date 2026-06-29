# EXP-045 (react / glm-5.1) 실험 분석 — Showdown Oracle 동적 무브 통합 (마일스톤 1+2)

> ⚠️ **오염 경고 (2026-06-29 갱신)**: 본 분석은 oracle 데미지 버그(`_pack_pokemon` 빈 pack 랜덤
> 폴백 + `active_state.max_hp`=opp 퍼센트(100) 덮어쓰기) **하의 측정**입니다. 본문이 attacker 식별
> 버그를 잡았다고 진단하나, **진짜 치명 버그(빈 pack → Pelipper/Swanna 등 랜덤 폴백, max_hp=100
> → 거짓 100% OHKO)는 인지하지 못했습니다**. baseline EXP-044(56.7%) 자체도 동일 오염. EXP-050a
> (commit `c9ac112`+`dd9b040`)에서 수정되어 EXP-044~049c 전체가 폐기. 정량·결론은 신뢰 불가(이력 보존).
> **정상 측정 최신 결론: [`exp-050a-react-glm51-analysis.md`](exp-050a-react-glm51-analysis.md).**

> 분석 일시: 2026-06-22
> EXP-045: 2026-06-22, glm-5.1 (ollama/glm-5.1:cloud), react + **`--enable_showdown_oracle`**, 30전 vs abyssal
> 비교: EXP-044 (react, 동일 manifest, **oracle off**) — 동일 `dynamic-v2.json`, 동일 seed 42, 변수 1개(`enable_showdown_oracle`)
> 팀 모드: fixed · manifest: `.temp/experiments/fixed-baselines/manifests/dynamic-v2.json` (sha256:`564353a6`) — player `modern_replays`(25,192) × opponent `modern_replays`(25,192), 30 매치업

---

## 0. TL;DR

**Oracle 동적 무브 통합은 기대 효과를 내지 못했고, 오히려 관측(observation) 품질을 악화시켰다.** 승률 **56.7% → 53.3% (−3.4pp)**, 도구 호출 +7.4%, prompt 토큰 +8.4%. 두 가지 결함이 확인됐다:

1. **🔴 동적 *위력* 무브의 oracle damage가 전부 0** — `knockoff`(107건)·`acrobatics`(18건)·`hex`(2건)·`ivycudgel`(9건)의 `hp_lost`가 **모두 0%**. 같은 매치업에서 sim(EXP-044)은 정상(`knockoff quaquaval→ogerpon` 32% / `weatherball` nonzero율 97%)이었는데, oracle(EXP-045)이 이를 0으로 **덮어쓰기**했다.
2. **🔴 관측 보정 결함** — `battle_tools.py:406-413`이 `damage_pct_max==0`을 받으면 `hp_lost="0%"`로 덮어쓰되 `turns_to_ko`는 sim 원값을 그대로 남겨, **"데미지 0%인데 4턴 KO"**라는 자기모순 observation을 LLM에 주입.

**결론**: 마일스톤 1(동적 *타입*, weatherball/terablast `effective_type`)은 부분 유효, 마일스톤 2(동적 *위력*)은 **완전 실패** — `damage` 통합이 깨져 핵심 동적 무브를 0 데미지로 오판시켜, 특히 짧은 결판 매치업(short <15턴)에서 승률 72.7%→44.4% 급락을 유도. **oracle의 damage 통합은 비활성화하고 type만 유지**하는 것이 즉시 시행 가능한 복구안.

> ⚠️ **통계 caveat**: −3.4pp는 N=30에서 비유의(z≈0.36, p≈0.72). 단, 본 비교는 **동일 매치업 paired**(EXP-035와 달리 팀 시드 동일)이며, (b) 0% 관측이라는 체계적 결함, (c) 짧은 배틀 −28pp의 방향성 신호가 동반됨. "oracle이 승률을 올렸다"는 증거는 **전혀 없고**, 관측 결함은 코드로 확정.

---

## 0.5 정정 (2026-06-22) — 원인 재조사: "못 쓰는 무브" 가설 기각, attacker 식별 버그가 진짜 원인

> 본 보고서 초안(§3.1)은 damage=0의 원인을 "attacker가 실제로 못 쓰는 무브를 쿼리"한 것으로 추정했다. **이 가설은 기각**되었고, 정정한다.

**재조사 계기**: "sim과 동일한 턴 상태를 구현 후 쿼리할 텐데 어째서 못 쓰는 move가 쿼리되는가"라는 질문. 3개 경로(코드 추적 · 로그 전수조사 · worker node 직접 실행)로 검증:

1. **로그 전수조사**: `hp_lost=0%` oracle observation 214건 중 **85.5%(183건)는 player active의 실제 moveset에 있는 무브**. "못 쓰는 무브"(가설적 쿼리)는 14.5%(31건)에 불과. knockoff quaquaval도 실제 moveset에 knockoff가 **있었음**. → "못 쓰는 무브"가 주원인이 **아님**.
2. **근본 원인 = attacker 식별 버그**:
   - `oracle-worker.js:108` — `source = battle.sides[actorIdx].active[0]` = **packed team의 첫 번째 포켓몬**을 무조건 attacker로 사용.
   - `battle_state_mapper.py` `_pack_team`은 `team.values()` **삽입 순서**를 그대로 pack. active를 첫째로 정렬하지 않음.
   - → 스위치인 후 실제 active(quaquaval, knockoff 보유)가 team 첫째(lead)가 아니면, worker가 **lead**를 attacker로 `runMove('knockoff')` → lead moveset에 없어 Showdown이 `|cant|nopp|`로 **조용히 return**(예외 아님 → worker catch 못 잡음) → `damage = 0`.
   - 즉 oracle payload가 **"실제 active를 attacker로 반영"하지 못한 것**. 사용자 전제("동일 턴 상태 구현")가 구현되지 않았다.
3. **node 직접 검증 (결정적)**: 같은 active_state(quaquaval active)·같은 move(knockoff)에서 — attacker를 **첫째(quaquaval)**로 pack → `damage 100%` ✅; attacker를 **둘째**(knockoff 없는 kingambit 첫째)로 pack → `damage 0%` ❌(EXP-045 버그 정확 재현).
4. learnset 보충: quaquaval/pelipper는 knockoff **학습 가능**(초안의 "학습하지 못하는 포켓몬" 서술은 틀림). ironmoth+ivycudgel만 시그니처라 진짜 불가(14.5% 가설적 케이스).

**적용된 fix** (worker 수정 없이 mapper만으로 — worker는 `.gitignore` 로컬):
- **근본**: `_pack_team(team, lead=...)` 추가(`battle_state_mapper.py`) — `battle_to_oracle_payload`가 `user`(player active)를 team_p1 첫째로, `target`(opp active)를 team_p2 첫째로 pack → worker `active[0]`가 정확한 attacker/target.
- **방어**: `battle_tools.py:406`(calculate_damage)·`:736`(simulate_turn) — 보정 조건을 `damage_pct_max > 0`로 가드. 0이면 sim 관측 유지 → "hp_lost 0% & turns 4" 자기모순 제거 + 잔여 엣지(미러 등) 방어.

**검증**: `_pack_team` lead 단위 3(첫째/None보존/매칭실패) + 기존 `test_showdown_oracle.py` 72 + `test_react_oracle_dynamic_type.py` 57 **전부 PASS**. node 회귀로 damage 0→100% 회복 확인.

→ §3.1·§3.4의 "못 쓰는 무브 / 학습하지 못하는 포켓몬" 서술은 **기각**. EXP-045의 0% observation은 attacker 식별 버그가 원인이었고, 이제 fix됐다. 마일스톤 2(동적 위력)는 이 fix로 **처음 제대로 작동**하게 됨. 다음은 EXP-046(동일 dynamic-v2/seed 42) 재실험으로 실제 효과 측정.

---

## 1. 결과 (정량)

### 1.1 승률 / 리소스

| 메트릭 | EXP-044 (oracle off) | EXP-045 (oracle on) | 변화 |
|---|---|---|---|
| 승률 | 56.7% (17/30) | **53.3% (16/30)** | −3.4pp |
| 평균 턴 | 16.8 | 17.7 | +0.9 |
| LLM 호출/판 | 52.4 | 56.1 | +3.7 (+7.1%) |
| prompt 토큰/판 | 147,672 | 160,050 | +12,378 (+8.4%) |
| completion 토큰/판 | 5,336 | 5,669 | +333 |
| 도구 호출 합계 | 1,862 | 2,000 | +138 (+7.4%) |
| 도구 에러율 | 2.5% (46/1,862) | 2.8% (55/2,000) | +0.3pp |

- 비용이 **일률적으로 +7~8% 상승** — oracle observation이 도구 결과를 풍부하게 만들어 LLM이 더 많이 탐색(`simulate_turn` +49%, `check_type_effectiveness` +24%, `get_move_details` +64%).
- 승률 하락폭(−3.4pp) 자체는 비유의이나, **비용 증가 + 짧은 배틀 급락**(아래)이 방향성을 뒷받침.

### 1.2 턴 구간별 승률

| 구간 | EXP-044 | EXP-045 | 변화 |
|---|---|---|---|
| **짧은 배틀 (<15턴)** | 72.7% (8/11) | **44.4% (4/9)** | **−28.3pp ❌** |
| 중간 배틀 (15-24턴) | 50.0% (9/18) | 61.1% (11/18) | +11.1pp ✅ |
| 긴 배틀 (25+턴) | 0.0% (0/1) | 33.3% (1/3) | (표본 작음) |

- **짧은 결판 매치업에서만 명확한 악화**. 빠르게 주도권을 잡고 끝내야 할 매치업(보통 우위 STAB/커버리지 동적 무브가 결정타)에서 oracle의 0% 관측이 주력 무브 기피를 유도한 정량 신호.
- mid 배틀은 오히려 개선 — 정적 무브 중심이거나 weatherball type 정확도(날씨 팀)가 도움된 매치업.

### 1.3 매치업별 승패 페어링 (paired — 동일 30 매치업)

변수가 oracle 1개뿐이므로 **같은 매치업을 paired 비교**할 수 있다(EXP-035의 비동일 매칭 한계와 다름).

- 30 매치업 중 **11개 뒤집힘**: 044 승→045 패 **6건(악화)** / 044 패→045 승 **5건(개선)** → net **−1승**
- **악화 6**: idx 4221, 8201, 11082, 19519, 20875, 24778
- **개선 5**: idx 4851, 11964, 14007, 17464, 19343

악화가 개선보다 1건 많은 것 자체는 노이즈 범주지만, 짧은 배틀 집중 하락과 관측 결함이 이 방향을 뒷받침한다.

### 1.4 도구 사용 분포

| 도구 | EXP-044 | % | EXP-045 | % | 변화 |
|---|---|---|---|---|---|
| `calculate_damage` | 1,511 | 81.1% | 1,571 | 78.5% | +60 |
| `simulate_turn` | 88 | 4.7% | 131 | 6.5% | **+43 (+49%)** |
| `check_type_effectiveness` | 87 | 4.7% | 108 | 5.4% | +21 |
| `get_move_details` | 36 | 1.9% | 59 | 3.0% | **+23 (+64%)** |
| `evaluate_position` | 44 | 2.4% | 45 | 2.2% | +1 |
| `analyze_matchup` | 36 | 1.9% | 43 | 2.1% | +7 |
| `predict_opponent_moves` | 54 | 2.9% | 40 | 2.0% | −14 |
| 합계 | 1,862 | | 2,000 | | +138 |

---

## 2. Oracle 동작 검증 — "개선점이 적용됐는가?"

> 사용자 핵심 질문: *개선점이 원하는 방향대로 적용됐는지 검토.*

### 2.1 ✅ Oracle은 실제로 동작했다 (마일스톤 인프라는 정상)

- EXP-045 tool_result에서 `type_source: "showdown_oracle"` observation **297건** 탑재 (EXP-044는 **0건**).
- `_logger.debug("oracle outcome move=...")` 경로가 동적 무브마다 실행됨 — `get_shared_oracle` 싱글톤·`OracleResultCache`·`Move.type` setter 파이프라인은 설계대로 작동.
- `effective_type`은 **정확**: weatherball→`Rock`, knockoff→`Dark`, terablast→`Normal`(tera 전)/`Fire`, ivycudgel→`Grass`, hex→`Ghost`, acrobatics→`Flying`.

### 2.2 ❌ 하지만 동적 *위력* 무브의 damage는 전부 0 (마일스톤 2 결함)

oracle이 resolve한 무브별 `hp_lost` 분포 (총 279건):

| 무브 | 건수 | 평균 hp_lost | 비고 |
|---|---|---|---|
| `weatherball` | 123 | 40.2% | nonzero **51%** (날씨 팀에서만 정상) |
| `knockoff` | 107 | **0.0%** | **전부 0%** ❌ |
| `terablast` | 20 | 10.0% | 부분 (tera 시만) |
| `acrobatics` | 18 | **0.0%** | **전부 0%** ❌ |
| `ivycudgel` | 9 | **0.0%** | **전부 0%** ❌ |
| `hex` | 2 | **0.0%** | **전부 0%** ❌ |

동적 **위력** 무브(knockoff/acrobatics/hex) **127건이 전부 0%**.

### 2.3 🔴 결정적 비교 — 같은 매치업, sim vs oracle

| 무브 / 매치업 | EXP-044 (sim) | EXP-045 (oracle) |
|---|---|---|
| `knockoff` quaquaval→ogerponwellspring | `hp_lost 32%, turns 4` ✅ | `hp_lost 0%, turns 4` ❌ |
| `knockoff` pelipper→landorustherian | `hp_lost 12%, turns 9` ✅ | `hp_lost 0%` ❌ |
| `weatherball` nonzero율 | **97%** (114/117) ✅ | **51%** (63/123) ❌ |

→ sim이 정확히 계산하던 데미지를 **oracle이 0으로 덮어쓰기**했다. EXP-045의 `hp_lost=0%`는 시스템 오프셋이 아니라 oracle damage 결함의 직접 결과.

---

## 3. 결함 메커니즘 (정성 + 코드)

### 3.1 🔴 P0-1: Oracle 동적 위력 무브 damage=0 (근본)

> ⚠️ **초안 원인 서술("attacker가 못 쓰는 무브")은 기각** — §0.5 정정 참조. 진짜 원인은 **attacker 식별 버그**(worker가 team 첫째를 attacker로 사용하는데 `_pack_team`이 active를 첫째로 정렬하지 않음). 아래 표(0% 데이터)는 유효하나, 원인 해석은 §0.5로 대체.

| 항목 | 값 |
|---|---|
| 동적 위력 무브 oracle `hp_lost` | knockoff 107/107 = 0%, acrobatics 18/18 = 0%, hex 2/2 = 0% |
| 동일 매치업 sim(EXP-044) | 32% / 12% / 8% … (정상 분포) |

**근본 원인** — `oracle-worker.js:142-146`:
```js
const beforeHP = target.hp;
try { battle.actions.runMove(payload.move_id, source, targetLoc); } catch (e) {}
damage = Math.max(0, beforeHP - target.hp);
```
oracle은 **"이 attacker가 실제로 이 무브를 runMove했을 때"**의 HP 차이를 잰다. 샘플 attacker(`quaquaval`·`pelipper`·`ragingbolt`·`pecharunt`·`ironmoth`)들은 해당 동적 무브를 **학습하지 못하는 포켓몬**(예: ivycudgel은 Ogerpon 전용, Iron Moth 사용 불가). Showdown이 무효 무브로 거부 → 데미지 0.

반면 sim(`battle_tools` 경로)은 attacker의 무브셋을 검증하지 않고 **무브 자체의 위력·상성·STAB**으로 계산 → 정상값(32%). 두 경로의 의미가 다른데, oracle damage를 우선시하도록 `battle_tools.py:406-413`이 **sim값을 0으로 덮어쓴 것**이 관측 품질 악화의 직결 원인.

**weatherball nonzero 51%**도 같은 뿌리: 날씨가 세팅된 매치업(날씨 팀 idx 17696 등)에서는 정상이나, 날씨 미세팅/조건 미충족 매치업에서는 runMove가 낮은 위력·잘못된 타입으로 떨어져 절반이 0.

### 3.2 🔴 P0-2: 자기모순 observation (보정 결함)

`battle_tools.py:406-413`:
```python
if outcome and outcome.get("damage_pct_max") is not None:
    hp2 = max(0, round(100 - outcome["damage_pct_max"]))  # 0 → hp2=100
    ko = outcome.get("ko") or {}
    if ko["ohko_chance"] >= 0.5:      turns = 1
    elif ko["twohko_chance"] >= 0.5:  turns = 2
    # damage 0 → ohko=0, twohko=0 → turns 는 sim 원값 유지(4, 9, …)
```
`damage_pct_max==0`이면 `hp_lost="0%"`로 덮어쓰지만 `turns_to_ko`는 sim 원값(4 등)을 남긴다 → **`{"hp_lost":"0%", "defender_hp_after":"100%", "turns_to_ko":4}`** 라는 자기모순. fallback 가드(`damage_pct_max > 0`)가 없다.

### 3.3 인과: 왜 짧은 배틀에서 급락했나

- player 풀(`dynamic-v2` player = dynamic score 상위)은 동적 무브 **빈발 팀**. 핵심 STAB/커버리지가 knockoff·acrobatics·hex 등.
- oracle이 이들을 0%로 보고 → LLM "주력 무브로 데미지 0" 오판 → 약한 무브 선택 / 불필요한 스위칭 / 패시브 세팅.
- 짧은 결판 매치업(short)은 초반 주도권이 곧 승리인 매치업이라 주력 무브 기피가 치명적 → 72.7%→44.4%.
- mid 배틀 개선은 정적 무브 중심 매치업 + weatherball type 정확도(날씨 팀)의 부분 기여가 0% 노이즈를 상회한 결과.

### 3.4 EXP-035와의 대조 — 정반대 실패 모드

| | EXP-035 (마일스톤 0) | EXP-045 (마일스톤 1+2) |
|---|---|---|
| 통합 방식 | 동적 위력을 **move override** | 위력은 override 안 하고 **oracle damage 관측 반영** |
| 실패 모드 | **과대평가** (acrobatics 55→110→sim ×2 = 220 BP) | **과소평가** (knockoff 32% → 0%) |
| 원인 | sim `modify_base_power` 중복 보정 | oracle `runMove` damage=0 + 보정 덮어쓰기 |
| 승률 | 76.7%→56.7% (−20pp, 비유의) | 56.7%→53.3% (−3.4pp, 비유의) |

→ **동적 *위력* 통합은 두 접근 모두에서 깨진다**. 안정적인 것은 **동적 *타입* 통합(마일스톤 1)** 뿐. EXP-035 교훈("위력 override 금지")을 지키려 damage 경로를 우회했으나, 우회 경로 자체(oracle runMove damage)가 깨져 있었다.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-044 (oracle off) | EXP-045 (oracle on) | 상태 |
|---|---|---|---|
| 동적 *타입* 정확한 관측 | 🔴 sim 미처리 | 🟡 weatherball/terablast `effective_type` 정확 | **부분 성공** |
| 동적 *위력* 정확한 관측 | 🔴 sim 5개만 | 🔴 **oracle damage=0** (knockoff/acrobatics/hex 전부) | **신규 결함** |
| 관측 자기모순(hp_lost 0% & turns≥1) | — | 🔴 보정 fallback 부재 | **신규 결함** |
| EXP-035 중복 보정(acrobatics 220 BP) | 🔴 (EXP-035) | ✅ 위력 override 안 함 | **회피 성공** |
| 비용(토큰/도구) | 기준 | +7~8% | 악화 |

---

## 5. 권장 개선 우선순위

| 순위 | 문제 | 근거 | 난이도 | 예상 효과 |
|---|---|---|---|---|
| 1 | **damage=0 fallback 가드**: `damage_pct_max > 0`일 때만 관측 덮어쓰기, 아니면 sim값 유지 | knockoff/acrobatics/hex 127건 0% → sim 정상값 복원 | 낮 | 짧은 배틀 −28pp 회복 1차 |
| 2 | **oracle damage 통합 비활성화, type만 유지** (마일스톤 1로 회귀) | weatherball nonzero율조차 51%(sim 97%보다 열위) → damage 경로 신뢰 불가 | 낮 | 0% 노이즈 원천 제거 |
| 3 | oracle worker 디버그: attacker가 못 쓰는 무브 runMove 거부 → 0 문제 (runMove 전 무브셋 검증, 또는 dex 기반 위력 직산) | 근본 원인. 수정 전까지 damage 통합 불가 | 높 | 마일스톤 2 재활성화 전제 |
| 4 | weatherball 날씨 미세팅 매치업 처리 | nonzero 51% → type 정확해도 damage 노이즈 | 중 | 날씨 팀 외 매치업 정확도 |

> 모든 권고는 범용 gen9ou 관점 (ANALYSIS_MANUAL 6.1·6.5). abyssal 특화 아님. 우선순위 1·2는 **코드 1~2줄 가드**로 즉시 시행 가능하며 oracle 인프라는 그대로.

---

## 6. 다음 단계

### 완료 (2026-06-22) — attacker 식별 버그 fix + 방어 가드
- [x] **근본 fix**: `battle_state_mapper.py` `_pack_team(team, lead=...)` 추가 → `battle_to_oracle_payload`가 `user`(player active)를 team_p1 첫째, `target`을 team_p2 첫째로 pack. worker `active[0]`가 정확한 attacker/target이 됨. **worker 수정 불필요**.
- [x] **방어 가드**: `battle_tools.py:406`·`:736` — `damage_pct_max > 0` 가드. 0이면 sim 관측 유지(hp_lost 0% & turns≥1 자기모순 제거 + 잔여 엣지 방어).
- [x] 검증: 단위 60 + 통합 15 + node 회귀(quaquaval/knockoff 0→100%) PASS.

### EXP-046 (fix 적용 후 재실험 — 사용자 실행)
- [ ] 동일 `dynamic-v2.json`·seed 42·N=30, `--enable_showdown_oracle` 유지. oracle 동적 타입(마일스톤 1)+위력(마일스톤 2, **이제 처음 정상 작동**) 통합의 실제 효과 측정.
- [ ] 사후검증: oracle observation `hp_lost=0%` 비율 급감(214건 → 수십 건 이하) + knockoff/acrobatics nonzero율 sim 수준 회복. 목표: EXP-044 baseline(56.7%) 대비 손실 없음 + 짧은 배틀 72.7% 회복.

### 후속
- [ ] 보고서: EXP-035(과대평가, 중복보정)·EXP-045(과소평가, attacker 식별 버그) 교차 분석으로 "동적 위력 통합" 접근법 전수 검토 문서화.

---

## 부록 — 검증 스니펫 출처

- 승률/구간: `experiment_*.json` `summary` + `battles[]` (ANALYSIS_MANUAL 4.2·4.3)
- 도구 분포/에러: `langgraph_tool_log.jsonl` `tool_call`/`tool_result` (4.5)
- oracle 관측: `tool_result` 내 `type_source: "showdown_oracle"` + `hp_lost` 분포 (무브별 279건)
- paired 비교: `battles[].player_team_idx` 기반 30 매치업 페어링 (동일 manifest)
- 코드: `battle_tools.py:246-319`(`_resolve_move_outcome_via_oracle`), `:406-413`(보정), `oracle-worker.js:142-146`(damage 측정)
