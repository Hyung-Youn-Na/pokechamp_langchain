# EXP-057 (react / glm-5.1) 데미지 백엔드 비교 분석 — calc vs Showdown oracle

> **정확도 + 편리성 비교** (승률은 metric에서 제외 — compare 모드는 의사결정=showdown).
> 계획: `/root/.claude/plans/transient-frolicking-petal.md` · 재현: `docs/architecture/damage-calc-worker-reproduction.md`.
> 코드 상태: HEAD `023e134`(damage-calc 통합) 위, **순수 측정(코드 변경 수반 ❌)** + worker 버그 수정 3종.

## 0. 실험 조건

| 항목 | 값 |
|------|------|
| 알고리즘 | react (glm-5.1:cloud) vs abyssal (gemini-2.5-pro, io) |
| oracle_backend | **compare** (양쪽 병렬, 의사결정=showdown, 차이 로그) |
| 팀 모드 | fixed — `dynamic-v2.json` (sha256 `564353a6…`, 050a 동일 매치업) |
| 비배틀 측정 | 제어 스위트 `scripts/exp/damage_compare_suite.py` (16 케이스, 결정론적) |
| 실배틀 compare | **사용자 실행 대기** (`--oracle_backend compare --N 30` → `.temp/oracle_compare.jsonl` ~1,500 레코드) |
| gate | 데미지 metric(승률 無) — EXP-056 비승률 게이트 선례 |

**EXP-057의 1차 산출(코드)**: worker(`damage-calc/scripts/damage-calc-worker.js`)의 **display-name 변환 버그 3종 발견·수정** — `toMoveName`/`toSpeciesName` 추가(기존 `toItemName`/`toAbilityName`에 합류). 제어 스위트가 이를 노출: weatherball 40.4→182.5%, ivycudgel 57.7→139.2%, **tb-lightball 108.8→215.1%**(Pikachu Light Ball species-specific 보정이 소문자 ID `pikachu`일 때 미적용되던 버그). **calc 자체는 정상**이었고 worker 변환 누락이었다.

## 1. 데미지 정확도 결과

### 1.1 제어 스위트 (16 케이스, 결정론적)

`scripts/exp/damage_compare_suite.py` — 카테고리별 대표 (attacker, defender, move, field)에 양 백엔드 동일 payload. `sd`=showdown oracle, `dc`=`@smogon/calc`, `Δ`=sd−dc. 결과 JSON: `.temp/experiments/active/EXP-057-damage-backend-compare/suite_results.json`.

| label | cat | move | sd% | dc% | Δ | type | tm |
|-------|-----|------|----:|----:|----:|------|:--:|
| eq-cb | normal | earthquake | 100.0 | 223.8 | −123.8 | ground | ✓ |
| tb-lightball | normal | thunderbolt | 100.0 | 215.1 | −115.1 | electric | ✓ |
| facade-burn | dyn-power | facade | 100.0 | 73.9 | +26.1 | normal | ✓ |
| knockoff-item | dyn-power | knock off | 85.3 | 56.1 | +29.2 | dark | ✓ |
| hex-status | dyn-power | hex | 44.0 | 58.1 | −14.1 | ghost | ✓ |
| acrobatics-noitem | dyn-power | acrobatics | 21.0 | 13.8 | +7.2 | flying | ✓ |
| terablast-water | dyn-type | terablast | **0.0** | 105.7 | −105.7 | water | ✓ |
| weatherball-rain | dyn-type | weatherball | 100.0 | 182.5 | −82.5 | water | ✓ |
| ivycudgel | dyn-type | ivycudgel | 100.0 | 139.2 | −39.2 | water | ✓ |
| tera-stab-dragon | tera | outrage | 77.5 | 51.2 | +26.3 | dragon | ✓ |
| fissure | ohko | fissure | 100.0 | 100.0 | +0.0 | ground | ✓ |
| rain-hydropump | weather | hydro pump | 100.0 | 110.6 | −10.6 | water | ✓ |
| burn-eq-halve | status | earthquake | 100.0 | 111.9 | −11.9 | ground | ✓ |
| reflect-eq | screen | earthquake | 50.0 | 111.9 | −61.9 | ground | ✓ |
| lightscreen-shadowball | screen | shadowball | 50.2 | 94.0 | −43.8 | ghost | ✓ |
| technician-pursuit | ability | pursuit | 45.4 | 30.0 | +15.4 | dark | ✓ |

**type 일치율: 16/16 = 100%** (동적 타입 Tera Blast→water/Weather Ball→water/Ivy Cudgel→water 포함). worker 변환 수정 후.

### 1.2 실배틀 compare (N=10, `.temp/oracle_compare.jsonl`, 527 레코드)

`scripts/exp/aggregate_oracle_compare.py` 출력 요약:

```
총 레코드: 527 | 양쪽 ok(가용): 527 (100.0%)
type 일치율: 525/527 = 99.62% (불일치 2)
delta_median_pct: mean=-24.47  median=-15.30  p90|Δ|=76.2  max|Δ|=434.6
방향성: oracle 과대(sd>dc) 177 | calc 과대(dc>sd) 333 | 동일 17

카테고리별: ko-clamp 90(avg|Δ|84.2) | dynamic-move 86(23.9) | normal 351(29.4)
```

**게이트 통과**: type 일치율 99.62% (≥99% ✅), 양쪽 백엔드 가용 100% (✅).

**★ 핵심 발견 — oracle 0-데미지 붕괴 (43.6%)**: 527레코드 중 **230건(43.6%)이 `showdown=0 & damagecalc>0`** — oracle이 정상 데미지여야 할 매치업에서 **0을 반환**했다. `|Δ|` top-15 전부 ko-clamp이며 대부분 sd=0(Headlong Rush vs Iron Moth 2×: sd 0 / dc 435; Close Combat vs Kingambit 2×: sd 0 / dc 244; Solar Beam vs Crawdaunt 2×: sd 0 / dc 231 …). calc는 동일 payload로 정상.

패턴(로그 정량화):
- **신무브/신종족 문제가 아님** — sd=0 move top: knockoff(22), closecombat(13), psyshock(8), nuzzle(7) 등 범용·구세대 무브가 다수; gen9 신무브는 31/230(13%)만.
- sd=0 defender top: hatterene(38, gen8), ironmoth(20), landorus-T(16), dondozo(10), toxapex(6) — 세대 무관.
- → oracle `runMove` 파이프라인이 특정 move×defender(ability/field/item 상호작용) 조합에서 **체계적 실패**해 damage=0. calc는 `@smogon/calc` mechanics로 견고.

**방향성**: calc 과대 333 vs oracle 과대 177 (≈2:1). 평균 Δ=−24.47(calc가 더 큼)은 (a) KO clamp(calc overkill) + (b) oracle 0-데미지가 합쳐진 결과.

### 1.3 승률 (보조 — 회귀 無)
compare 모드는 의사결정에 항상 showdown 결과를 반환. 다만 oracle sd=0일 때 `battle_tools.py`의 `damage_pct_median > 0` 가드가 LocalSim fallback을 트리거(EXP-050a fix 항목6)하므로, 050a(70%) 승률에 치명적 영향은 아니었을 것 — 다만 그만큼 oracle 결과가 **의사결정에 실제로 쓰이지 않고(sim으로 대체) 낭비**됐음. calc 전환 시 정확 데미지가 의사결정에 직접 쓰일 수 있어 개선 기대(승률 영향은 별도 ablation).

### 1.3 승률 (보조 — 회귀 無)
compare 모드는 의사결정에 항상 showdown 결과를 반환하므로 승률은 050a(70%)와 동일 예상. 본 metric 아님.

## 2. 차이 분석 — 두 종류

데미지 차이는 단일 원인이 아니라 **(A) 측정 방식 차이 + (B) 동적 무브/능력 처리 차이**로 나뉜다. "어느 백엔드가 더 정확"은 영역별로 다르다.

### (A) KO clamp — 측정 방식 차이 (자연스러움)
oracle은 `runMove` 후 **실제 HP 차감**(HP는 0 이하로 안 내려감) → KO 시 damage=maxhp=**100%**. calc는 damage formula의 **raw 출력(overkill 포함)** → 100% 초과(eq-cb 223.8%). screen 0.5×(reflect-eq: 양쪽 정확히 절반), burn halve(burn-eq-halve: 양쪽 111.9%)는 **양쪽 비율 일관** — 오직 KO 경계에서 overkill 표현 여부만 다르다. oracle이 실제 전투 동작에 가깝고, calc가 이론적 raw 데미지.

### (B) 동적 무브/능력/tera 처리 — 양쪽各有 실패 모드 (★핵심)
- **calc 우위**: Tera Blast(Tera-Water) — calc 105.7%(정상) vs **oracle 0%(tera 처리 실패)**. calc는 `teraType` 옵션으로 정확히.
- **oracle 과대/과소 혼재** (불안정): facade(+26.1)/knockoff(+29.2)/acrobatics(+7.2)/tera-stab(+26.3)/technician(+15.4)은 oracle 과대; **hex(−14.1)는 oracle 과소**. calc 직접 검증(desc)에서 calc는 140/97.5/130 BP 정확. 즉 oracle의 동적 위력 처리가 케이스별로 불안정.
- **weather/일반은 양쪽 근접**: rain-hydropump(Δ−10.6), KO clamp 보정하면 사실상 동등.

**판정**: 동적 무브 영역에서는 **calc가 mechanics로 일관적·견고**(Tera Blast 정상, 동적 위력 정확). oracle은 runMove 파이프라인 의존으로 특정 무브(Tera Blast)에서 완전 실패 + 동적 위력에서 과대/과소 분산. 단, oracle은 KO clamp로 비-KO 판정이 실제 전투에 가깝고 runMove 전체 이벤트를 타므로 일부 엣지케이스 유리 가능.

## 3. 편리성 비교 (정량 + 정성)

| metric | calc (`@smogon/calc`) | oracle (pokemon-showdown) | 비고 |
|--------|----------------------|---------------------------|------|
| 디스크(전체) | 180M | 474M | oracle 2.6× (대부분 node_modules) |
| **런타임 산물 dist** | **2.4M** | **101M** | **42× 차이** — calc는 데이터 내장 최소 산물 |
| 런타임 deps 선언 | `@types/node` 1개(사실상 0) | pokemon-showdown 자체 + deps | calc는 데이터 패키지 내장 |
| 빌드 | `tsc` clean compile **2.6s** | `npm install` + `node tools/build` (수십초~) | calc는 TS 1단계 |
| 재현 단계 | 복사 + 1 빌드 + worker | submodule clone + build + worker (3축) | oracle worker는 gitignored |
| 데이터 동기화 | 패키지 내장(smoketest로 Showdown과 지속 검증) | submodule HEAD 의존 (수동 pull) | calc가 자동 추적 |
| 결정론성 | 16-roll 고정(항상 동일) | 매-쿼리 seed 변동 N-roll | calc가 캐싱·디버깅 유리 |
| Node | v18+ (v24 검증) | v20+ | calc가 더 관대 |

정성: calc는 npm 패키지 1개로 의존 경량·CI 안정·재현성 압도. oracle은 gitignored submodule + 수동 worker 스크립트로 재현이 취약(조사보고서 "무겁고 취약" 평가). 다만 oracle은 Showdown 엔진 자체 구동이라 신메커니즘 선대응 가능(단 smoketest가 calc 동기화를 보장).

## 4. 결론 / 후속

**데미지 정확도 + 신뢰성**: 
- type 100%(제어)/99.62%(실배틀) 일치.
- 제어 스위트: (A) KO clamp(측정방식차) + (B) 동적 무브(영역별 — calc가 Tera Blast/동적위력 견고).
- **실배틀(★): oracle이 527레코드 중 230건(43.6%)에서 0-데미지 반환** — 정상 데미지여야 할 매치업에서. 신무브/신종족 문제가 아니라 oracle `runMove`의 체계적 실패(범용 무브·다세대 종족 포함). calc는 동일 payload로 정상. → **calc가 정확도뿐 아니라 신뢰성(0-데미지 無)에서도 압도**. 050a에서는 sd=0이 `damage_pct_median>0` 가드로 LocalSim fallback돼 승률(70%)에 치명적 영향은 아니었으나, oracle 결과가 의사결정에 안 쓰이고 낭비됨.

**편리성**: **calc 압도적 우위** — 런타임 산물 42배 작고, 빌드 1단계/2.6s, 의존성 경량, 결정론적, 재현성 양호.

**권고**: calc가 **정확도(동적 무브 견고) + 신뢰성(43.6% 0-데미지 無) + 편리성(의존 경량)** 3축에서 우위 → **calc 전환 강력 권고**. 단, oracle sd=0이 `damage_pct_median>0` 가드로 LocalSim fallback돼 050a 승률(70%)에 치명 영향은 아니었으므로, calc 전환의 승률 효과는 **별도 ablation**(`--oracle_backend damagecalc` 단독)에서 측정해야 — (a) KO clamp 차이, (b) 정확 데미지가 의사결정에 직접 쓰이는 효과가 승률에 어떻게 작용할지(EXP-054 "거짓 생존 유리" 역행 가능성 포함)가 열쇠. worker 변환 버그 3종(toMoveName/toSpeciesName)은 calc 전환과 무관하게 **즉시 수정**(현재 showdown/compare 모두에 영향).

**후속**:
1. 실배틀 compare(`--N 30`) 실행 → `aggregate_oracle_compare.py`로 1.2 보강(~1,500 레코드 분포).
2. calc 단독 ablation(EXP-058 가상)로 승률 영향 측정 — 본 계획 범위 밖.
3. oracle의 동적 위력 과대/과소 근본 원인(runMove 파이프라인)은 calc 우위 확정이므로 우선순위 낮음.

## 메타 교훈
"둘 다 Showdown 공식 → 정확도 동일" 가설(EXP-057 계획 단계)이 **다시 정정**: 같은 공식이어도 (a) 측정 방식(runMove HP 차감 vs formula raw), (b) 동적 처리 발동 경로(엔진 콜백 vs mechanics 하드코딩), (c) 구현 변환 누락(worker display-name)이 데미지를 의미 있게 갈랐다. **비교 인프라(compare 모드 + 제어 스위트) 자체가 숨은 버그 3종을 잡은 핵심 가치**였다. EXP-054 "정확성=승률 반례"에 이어 "정확성 비교 ≠ 단일 metric" 교훈 추가.
