# EXP-035 (react / glm-5.1) 실험 분석

> 분석 일시: 2026-06-17
> EXP-035: 2026-06-17, glm-5.1 (ollama/glm-5.1:cloud), react (안 A + B-1), 30전 vs abyssal
> 비교: EXP-034 (안 A, 76.7%) · baseline `react-glm51` (76.7%) — 동일 조건(glm-5.1, temp 0.3, seed 42, N=30)

---

## 0. TL;DR

**안 B(B-1: 도구에 동적 타입/위력 리졸브 적용)은 기각.** 승률 76.7% → **56.7% (−20pp)**. 두 가지 결함이 확인됐다:

1. **기술 결함(코드 확정)**: `_apply_dynamic_resolution`이 동적 **위력**을 override하면, sim의 `modify_base_power`가 같은 무브를 **다시 보정(double-count)**. 특히 `acrobatics`(no item)는 B-1이 55→110으로 override → sim이 또 `×2` → **220 BP(실제 110) = 2× 과대평가**(`local_simulation.py:1576-1578`). `heavyslam`/`heatcrash`/`grassknot`/`lowkick`도 동일.
2. **근본 미해결**: 731의 Ivy Cudgel 거짓 OHKO는 **sim 본연의 위력 부풀림 버그**라 B-1(타입 리졸브)로 안 고쳐짐 — EXP-034에도 동일 존재.

> ⚠️ **통계 caveat**: −20pp는 n=30에서 **통계적으로 유의하지 않음**(z≈1.64, p≈0.10, 95% CI ±24pp). 두 실험이 비동일 매칭(다른 팀 시드)이라 paired 비교 불가. 즉 "B-1이 승률을 해쳤다"는 단정은 어렵지만, **승률 개선 증거도 없고 기술 결함도 확인**돼 기각이 합리적.

---

## 1. 결과 (정량)

| 메트릭 | baseline(031) | EXP-034(안 A) | **EXP-035(안 A + B-1)** |
|---|---|---|---|
| 승률 | 76.7% (23/30) | 76.7% (23/30) | **56.7% (17/30)** |
| 평균 턴(실측) | 24.4 | 22.6 | 23.0 |
| LLM 호출/판 | 119.1 | 73.3 | 75.8 (거의 동일) |
| prompt 토큰/판 | 357k | 208k | 211k (거의 동일) |
| 시간/판 | 426s | 242s | 293s |
| JSON 실패 | 4 | 1 | 0 |
| 거짓 OHKO(hp_lost=100%) | 25.7% | 25.7% | 21.7% (−4pp, 방향은 좋으나) |

- 비용은 안 A 수준 유지(75.8 LLM/211k 토큰). 거짓 OHKO는 −4pp 감소했으나 승률 하락이 압도적.
- 메트릭 fix(dc8cba3) 적용 → 이번 turns/won은 신뢰(battles won 합=17=summary).

---

## 2. §0-4 "변경 1개" 위반 — 런타임 무영향 확인

`verify_single_change.py`가 **4개 변경 FAIL**. 그 중 3개는 별개 세션용 **smogon 메타 통합 작업**(사용자 확인):
- `data_cache.py`(포맷 정리 + smogon 캐싱 메서드 추가), `smogon_roles_gen9ou.json`·`smogon_strategies_gen9ou.json`(신규)

**조사 결과 런타임 무영향 확정**: `get_cached_smogon_strategies/roles`의 소비처가 코드 전체에 **없음**(정의만 있고 호출 안 됨 = 미완성). 따라서 EXP-035의 56.7%는 **B-1(`battle_tools.py`)의 단독 효과로 해석 가능**. (사전 작업은 별도 stash로 분리 — §5)

---

## 3. 정성 분석 — B-1 역효과 메커니즘 (3각 검증)

### 3.1 🔴 기술 결함: 동적 위력 override 중복 보정 (코드 확정)

`_apply_dynamic_resolution`은 Move 복사본의 `base_power`를 override하지만, sim은 `modify_base_power`(`local_simulation.py:1540-1586`)에서 **`power = move.base_power`를 읽고 같은 무브를 다시 보정**:

| 무브 | B-1 override | sim 재보정 | 결과 |
|---|---|---|---|
| `acrobatics`(no item) | 55→**110** | L1576-78 `power *= 2` | **220 BP**(실제 110) ❌ |
| `heavyslam`/`heatcrash` | tier | L1545-57 tier 재산정 | 중복 ❌ |
| `grassknot`/`lowkick` | tier | L1559-72 tier 재산정 | 중복 ❌ |
| `facade`/`knockoff`/`hex`/`weatherball` | 동적 위력 | sim 분기 **없음** | OK ✅ |
| 동적 **타입**(ivycudgel 등) | type override | sim이 `move.type` 직접 사용 | OK ✅ |

→ B-1은 **타입 override는 안전**하지만, **위력 override는 sim과 충돌**. `acrobatics` 데미지가 EXP-034 34.2% → EXP-035 52.0%(+17.8pp)로 정확히 2×에 가까운 상승이 이를 뒷받침.

### 3.2 🔴 근본 미해결: Ivy Cudgel 거짓 OHKO

731의 "Ivy Cudgel 100% OHKO"는 **sim이 ivycudgel/Ogerpon 위력을 체계적으로 부풀리는 별개 버그**. B-1이 타입을 Grass→Water로 올바로 바꿔도 Water→Water 0.5×가 적용되지 않고 여전히 100%로 보고(EXP-035 battle-756에서 10회 연속). EXP-034에도 동일(Grass도 Water에 0.5×여야 하지만 100%). → **B-1은 표면적 불일치만 해소했을 뿐 calc의 근본 부정확은 미해결**. 이는 B2-B9 시리즈(sim 코어 버그) 영역.

### 3.3 🟡 보수화 패턴 (정성, 정량 지지)

정확해진(낮아진) 데미지 출력이 LLM에 "공격으로는 안 된다 → 세팅/회복이 유일한 경로"라는 보수적 판단을 유도한 정량 신호:
- 패배당 세팅 무브(Swords Dance/Calm Mind 등): 0.71 → **1.15**
- 패배당 회복 무브(Roost/Moonlight 등): 0.00 → **0.62**(EXP-034엔 0회)
- battle-774: 54턴 장기전, **414회 도구 호출**(Roost/Moonlight/Calm Mind 과다)

다만 공격/스위치 결정 비율은 불변(스위치율 39%→41%)이라, 이것만으로 −20pp를 온전히 설명하긴 어려움.

### 3.4 ⚠️ 표본 분산 경고

−20pp는 n=30에서 비유의(z≈1.64, p≈0.10). 비동일 매칭(다른 팀 시드)이라 paired 비교 불가. 동적 무브의 도구 호출 비중은 **4.4% only**라 B-1의 직접 영향 범위도 좁음. "거짓 OHKO 함정"(같은 defender에게 3회+ OHKO calc but 실제 KO 실패) 빈도도 50→51건으로 **불변**.

### 3.5 종합: B-1 역효과의 인과

- **확정**: B-1에 기술 결함(위력 중복 보정) 존재. ivycudgel 근본 미해결.
- **불확정**: −20pp가 (a) 중복 보정 과대평가→과신, (b) 보수화, (c) 표본 분산 중 어느 것인지 단정 불가.
- **결론**: 승률 **개선 증거 없음** + 기술 결함 확인 → **B-1 기각**이 합리적.

---

## 4. 이전 실험 대비 개선 현황

| 이슈 | EXP-034 | EXP-035 | 상태 |
|---|---|---|---|
| 731형 동적 무브 거짓 OHKO(표면) | 🔴 | 🟡 표면 해소(calc/get_move_details 일치) | 부분 |
| 동적 무브 calc 근본 정확도 | 🔴 | 🔴 (sim 본연 버그) | 미해결 |
| acrobatics/heavy-slam 중복 보정 | — | 🔴 B-1 신규 도입 | **신규 결함** |
| 속도/protect sim 버그(738/747) | 🔴 | 🔴 지속 | 미해결 |
| 비용(안 A 수준) | ✅ 208k | ✅ 211k | 유지 |

---

## 5. 권장 다음 방향

| 순위 | 방향 | 근거 | 비고 |
|---|---|---|---|
| 1 | **안 A(EXP-034) 확정 채택** | 승률 76.7% + 비용 −42%, 지금까지 최선 | 이미 달성 |
| 2 | B-1 **위력 override 중복 fix** 후 재실험 | acrobatics 중복은 코드 fix 가능(sim에 위임 또는 중복 무브 제외). −20pp가 비유의라 fix 후 재확인 가치 | 옵션 |
| 3 | **sim 코어 버그(B2-B9)** 별도 인프라 fix | ivycudgel 근본, 속도/protect — B-1과 무관 | B-2 영역 |
| 4 | smogon 메타 통합(별개 작업) | §0-4 위해 stash 분리, 다른 세션에서 진행 | 사용자 소관 |

> 모든 권고는 범용 gen9ou 관점. 단, −20pp가 비유의이므로 **B-1을 "해롭다"고 단정하지 말 것** — "이득 증거 없음 + 기술 결함"으로 기각.

---

## 6. 부록 — 패배 13판 (replay 역추론)

JSON 공식 13패: 755, 758, 759, 760, 761, 767, 770, 771, 772, 773, 774, 775, 781 (+ replay상 782 = 14번째 실패, JSON↔replay 불일치 1건).

분류(삼각검증): 속도/우선도 오판(759/769/770/780 — sim 버그 B3/B5), Protect 부재(782 — B6), 보수적 세팅/회복 함정(760/771/774/775/781 — B-1 간접), 측정불일치(755/758/767). 동적 무브 직접 패배는 0건(B-1 표면 효과).

정성 분석 산출: 본 보고서 §3 + EXP-034 분석(`docs/analysis/exp-034-react-glm51-analysis.md`) 부록 B.
