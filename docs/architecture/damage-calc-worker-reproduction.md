# Damage-Calc Worker — 재현 가이드 (`@smogon/calc` 백엔드)

> ``damage-calc/`` 디렉토리는 gitignored(``.gitignore: damage-calc/``)이므로, 이
> 문서가 새 환경에서 백엔드를 동일하게 재현하는 절차와 **전체 worker 소스**를 제공한다.
> ``oracle-worker-reproduction.md``(Showdown oracle)과 대칭 구조.

## 역할

`damage-calc-worker.js`는 react 데미지 도구(`calculate_damage`/`simulate_turn`)가
**Smogon `@smogon/calc` 라이브러리**로 단일 무브의 damage/type/KO를 계산하기 위한
stdin/stdout JSON-line 워커다. `pokechamp/damage_calc_oracle.py`(`get_shared_damage_calc_oracle()`)가
subprocess로 띄워 payload를 보낸다.

기존 `oracle-worker.js`(Showdown 엔진 서브프로세스)와 **동일 payload + 동일 응답 스키마**
(`ok/resolved/damage/ko_estimate`)를 공유하므로, `battle_tools.py`·`battle_state_mapper.py`
·`showdown_oracle.py` 수정 없이 백엔드 교체/병렬 비교가 가능하다(`pokechamp/oracle_backend.py`).

## 전제

- **Node.js** v18+(이 프로젝트는 v24로 검증).
- **`@smogon/calc`** 빌드(`damage-calc/calc/dist/index.js`).

## 재현 절차

### 1. damage-calc 패키지 확보 + 빌드

```sh
# Smogon damage-calc 의 calc/ 서브패키지(= @smogon/calc npm 패키지)를 workspace 로 복사.
# calc/tsconfig.json 이 "../tsconfig.json" 을 extends 하므로 루트 tsconfig.json 도 함께.
mkdir -p damage-calc
cp -r /path/to/damage-calc-repo/calc damage-calc/calc
cp /path/to/damage-calc-repo/tsconfig.json damage-calc/tsconfig.json
# bundle(bundler.js)은 브라우저용 production.min.js 라 불필요 → prepare 훅을 건너뛰고 compile 만.
cd damage-calc/calc && npm install --ignore-scripts && npm run compile
ls calc/dist/index.js   # 빌드产物 확인
```

> `.gitignore`에 `damage-calc/` 추가(`pokemon-showdown/` 패턴과 대칭).

### 2. worker 파일 생성

`damage-calc/scripts/damage-calc-worker.js`를 아래 **부록(전체 소스)**로 생성.

### 3. 사전점검

```sh
node --check damage-calc/scripts/damage-calc-worker.js
node -e "console.log(typeof require('./damage-calc/calc/dist/index.js').calculate)"  # 'function'
```

### 4. 백엔드 선택 + compare 검증

```sh
# compare 모드: 양쪽 동시 호출, 차이는 .temp/oracle_compare.jsonl, 의사결정은 showdown.
.venv/bin/python scripts/battles/local_1v1_langchain.py \
  --player_name pokechamp --player_prompt_algo react --player_backend <glm> \
  --opponent_name abyssal --enable_showdown_oracle --oracle_backend compare --N 3
```

`--oracle_backend {showdown(기존, 기본) | damagecalc | compare}`.

## 핵심 구현 포인트 (재현 시 반드시 포함돼야 할 로직)

1. **item/ability display-name 변환 (★비자명)** — `toItemName`/`toAbilityName`.
   `calc.Pokemon`의 item/ability 옵션은 **display name**("Choice Band")으로 받아야 효과가
   적용된다. **ID**("choiceband")를 주면 lookup 없이 그대로 저장해 **효과가 무시된다**
   (species/move/nature는 ID OK — 이 비대칭이 함정). Showdown packed은 item/ability를
   ID로 주므로 `GEN.items.get(id).name` / `GEN.abilities.get(id).name`으로 변환.
   검증: Choice Band 미적용 시 데미지가 ~1/1.5(494 vs 740)로 나온다.
2. **curHP = rawStats.hp × hp_pct/100** — calc는 `rawStats.hp`(=maxhp) 산출 후
   `originalCurHP` 설정. `max_hp`는 payload에서 오지 않는다(EXP-050a 방어 규칙, oracle과 동일).
3. **16-roll → min/max/median** — `result.damage`(16배열)를 정렬해 산출. calc는 내부적으로
   결정론적 16-roll(0.85–1.0 × 16단계)을 계산하므로 별도 seed 샘플링 불필요(oracle의
   매-쿼리 seed 변동 N-roll과 다름).
4. **OHKO 무브 ID 감지** — calc는 fissure/guillotine/horn-drill/sheer-cold를 `damage: 0`
   (미구현)으로 반환하고 `move.ohko` 속성도 없다. 4개 ID를 하드코딩해 oracle의
   `move.ohko` 계약(명중 시 즉사, ohko_chance 1.0)으로 정렬.
5. **R4(Screen) — wall 보정 불필요** — calc의 `Field`/`Side` 객체가 Reflect/Light Screen/
   Aurora Veil ×0.5를 **자동 적용**한다. oracle은 hand-built Battle이라 직접 곱했지만,
   본 워커는 곱하면 **이중 적용**이 되므로 절대 곱하지 않는다. (검증: Reflect 시
   baseline의 정확히 절반 — oracle과 동일 결과.)
6. **resolved 블록은 report-only** — calc `Result`가 `base_power`/`effectiveness`를
   직접 노출하지 않는다. `result.move.type`/`.bp`에서 best-effort 추출(type은 동적
   타입 Tera Blast 등을 정확히 잡음). **데미지 median이 핵심 판정 기준**.

## 핵심 검증 결과: Showdown oracle vs damage-calc (compare 모드)

동일 payload로 양쪽 호출(`pokechamp/oracle_compare.py`). type 일치율 **100%**(동적 타입
Tera Blast→water 포함). 하지만 **데미지 median은 상당히 다르다** — plan의 "같은 공식 →
정확도 동일" 가설이 **틀렸음**이 드러났다:

| move | showdown | damagecalc | 해석 |
|------|---------|-----------|------|
| earthquake (CB) | 100% | 223.8% | KO clamp (아래) |
| thunderbolt (Light Ball) | 100% | 108.8% | KO clamp |
| freezedry vs Water | 100% | 226.8% | KO clamp |
| **knockoff (item)** | **85.3%** | **56.1%** | calc=97.5 BP 정상; **oracle 과대** |
| **facade (burn+Guts)** | **100%** | **73.9%** | calc=140 BP 정상; **oracle 과대** |
| **terablast (Tera Water)** | **0%** | **105.7%** | **oracle=0(tera 처리 실패)**; calc 정상 |

### 차이의 두 가지 종류

**(A) KO clamp — 측정 방식 차이(자연스러움).** oracle은 `runMove` 후 **실제 HP 차감**을
재므로 KO 시 damage = maxhp(=100%). calc는 damage formula의 **raw 출력(overkill 포함)**을
낸다(223.8%). 둘 다 valid하지만 다른 것을 측정: oracle이 실제 전투 동작(HP는 0 이하로 안
내려감)에 더 가깝고, calc가 이론적 raw 데미지. → KO/비KO 경계 판정에 영향.

**(B) 동적 무브/능력 처리 — calc가 더 정확(★핵심).** calc 직접 검증:
- Knock Off vs Snorlax+item: desc에 **"97.5 BP"** 명시, 51-60% → smoke dc=56.1% 정합.
  **calc는 item boost 정상 적용.** oracle 85.3%는 과대(원인: oracle의 runMove 파이프라인에서
  Leftovers 회복 타이밍 / ability 보정 해석 추정).
- Facade burn+Guts: desc **"140 BP"**, 67-79% → dc=73.9% 정합. **calc 정상.** oracle 100% 과대.
- **Tera Blast(Tera Water): calc=105.7%(정상), oracle=0%(tera 처리 실패)**. calc는
  `teraType` 옵션으로 동적 타입을 정확히 잡지만 oracle은 `is_terastallized`+`tera_type`
  payload에서 Tera Blast의 ModifyType을 실행하지 못한다.

### 결론

- **type(동적 타입 포함)은 양쪽 100% 일치.**
- **데미지는 (A) KO clamp로 인한 측정 차이 + (B) 동적 무브/능력/tera에서 calc가 더
  견고**하다. plan이 세운 "같은 공식 → 정확도 동일 → 의존성만 경량화" 가설은 부정확;
  오히려 **calc가 동적 무브 영역에서 oracle보다 정확한 케이스가 많다**.
- oracle의 남은 강점: KO clamp로 실제 전투 동작에 가까운 비-KO 판정, runMove 전체
  이벤트 파이프라인(일부 엣지케이스). calc의 강점: 동적 위력/타입/tera 견고성,
  결정론적 16-roll, 의존성 경량(npm 1개).

## Python 통합 (additive)

- `pokechamp/damage_calc_oracle.py` — `DamageCalcOracle(ShowdownOracle)`: 상속해
  `_verify_dist`만 override(`showdown_oracle.py` 0행 수정). 별도 캐시
  `get_damage_calc_cache()`(compare 시 결과 혼합 방지).
- `pokechamp/oracle_backend.py` — `get_oracle(backend)`/`get_cache(backend)` 팩토리 +
  `set_default_backend()`. `battle_tools.py:_resolve_move_outcome_via_oracle`는
  `get_oracle()`/`get_cache()`로 교체(기본 showdown → 기존 동작 유지).
- `pokechamp/oracle_compare.py` — `CompareOracle`: 양쪽 query, **의사결정은 showdown**,
  차이는 `ORACLE_COMPARE_LOG`(기본 `.temp/oracle_compare.jsonl`)에 JSONL append.

## 한계 / 후속

- **KO clamp 차이**는 battle_tools의 median 사용 방식에 영향. 실제 배틀 N=smoke에서
  compare 로그의 delta 분포를 측정해야 전환 영향 정량화(사용자 실행).
- oracle의 knockoff/facade 과대 산출 근본 원인(runMove 파이프라인 해석)은 미해명 —
  calc가 Showdown 공식에 더 부합하므로 우선순위 낮음.
- 교체(`--oracle_backend damagecalc` 단독)는 compare 검증 후 **별도 ablation**으로
  측정(one-change-per-ablation 원칙). plan 참조.

## 부록: worker 전체 소스 (`damage-calc/scripts/damage-calc-worker.js`)

```js
#!/usr/bin/env node
"use strict";
/** Damage-Calc Worker — Smogon @smogon/calc 백엔드. oracle-worker.js 와 동일
 *  payload/응답 스키마. 자세한 주석은 소스 파일 참조. */
const path = require("path");
const readline = require("readline");
const calc = require(path.resolve(__dirname, "..", "calc", "dist", "index.js"));
const GEN = calc.Generations.get(9);
const rl = readline.createInterface({ input: process.stdin, terminal: false });
function send(obj) { process.stdout.write(JSON.stringify(obj) + "\n"); }
const OHKO_MOVES = new Set(["fissure", "guillotine", "horndrill", "sheercold"]);
function sideIdx(side) { return side === "p1" ? 0 : 1; }
const STAT_KEYS = ["hp", "atk", "def", "spa", "spd", "spe"];
function parseStatList(s, dflt) {
  if (!s) return null;
  const v = String(s).split(","), o = {};
  for (let i = 0; i < 6; i++) o[STAT_KEYS[i]] = parseInt(v[i], 10);
  if (isNaN(o.hp)) return null;
  for (const k of STAT_KEYS) if (isNaN(o[k])) o[k] = dflt;
  return o;
}
function toItemName(id) { if (!id) return undefined; const it = GEN.items.get(id); return it ? it.name : id; }
function toAbilityName(id) { if (!id) return undefined; const ab = GEN.abilities.get(id); return ab ? ab.name : id; }
function parsePackedMon(seg) {
  const f = String(seg).split("|");
  const clean = (x) => (x && x !== "none" ? x : undefined);
  return {
    species: f[1] || "",
    item: toItemName(clean(f[2])), ability: toAbilityName(clean(f[3])),
    moves: (f[4] || "").split(",").filter(Boolean),
    nature: f[5] || "serious",
    evs: parseStatList(f[6], 0) || { hp:0,atk:0,def:0,spa:0,spd:0,spe:0 },
    gender: f[7] || undefined,
    ivs: parseStatList(f[8], 31) || { hp:31,atk:31,def:31,spa:31,spd:31,spe:31 },
    level: parseInt(f[10], 10) || 100,
  };
}
function parsePackedTeam(packed) { if (!packed) return []; return String(packed).split("]").filter(Boolean).map(parsePackedMon); }
const WEATHER_MAP = { raindance:"Rain", rain:"Rain", primordialsea:"Heavy Rain", sunnyday:"Sun", sundance:"Sun", desolateland:"Harsh Sunshine", sandstorm:"Sandstorm", sand:"Sandstorm", hail:"Hail", snow:"Snow", snowscape:"Snow", chillyreception:"Snow", winds:"Strong Winds", deltastream:"Strong Winds" };
const TERRAIN_MAP = { electric:"Electric", electricterrain:"Electric", grassy:"Grassy", grassyterrain:"Grassy", misty:"Misty", mistyterrain:"Misty", psychic:"Psychic", psychicterrain:"Psychic" };
function mapWeather(id) { return id ? WEATHER_MAP[String(id).toLowerCase()] : undefined; }
function mapTerrain(id) { return id ? TERRAIN_MAP[String(id).toLowerCase()] : undefined; }
function makeCalcPokemon(mon, st) {
  const opts = { level: mon.level || 100, ability: mon.ability, item: mon.item, nature: mon.nature || "serious", evs: mon.evs, ivs: mon.ivs, gender: mon.gender };
  if (st) {
    if (st.status) opts.status = st.status;
    if (st.boosts) opts.boosts = st.boosts;
    if (st.is_terastallized && st.tera_type) opts.teraType = st.tera_type;
    if (st.ability) opts.ability = toAbilityName(st.ability);
    if (st.item) opts.item = toItemName(st.item);
  }
  const poke = new calc.Pokemon(GEN, mon.species, opts);
  if (st && st.hp_pct != null) {
    const maxhp = (poke.rawStats && poke.rawStats.hp) || 1;
    poke.originalCurHP = Math.max(1, Math.round((maxhp * st.hp_pct) / 100));
  }
  return poke;
}
function makeCalcSide(sc) {
  return new calc.Side({
    isReflect: !!(sc && sc.reflect), isLightScreen: !!(sc && sc.lightscreen),
    isAuroraVeil: !!(sc && sc.auroraveil), spikes: sc && sc.spikes ? sc.spikes : undefined,
    isSR: !!(sc && sc.stealthrock), isTailwind: !!(sc && sc.tailwind),
    isProtected: !!(sc && sc.protect), isHelpingHand: !!(sc && sc.helpinghand),
  });
}
function makeCalcField(payload) {
  const aSc = (payload.side_conditions && payload.side_conditions[payload.actor_side]) || {};
  const tSc = (payload.side_conditions && payload.side_conditions[payload.target_side]) || {};
  return new calc.Field({ gameType:"Singles", weather: mapWeather(payload.weather), terrain: mapTerrain(payload.terrain), attackerSide: makeCalcSide(aSc), defenderSide: makeCalcSide(tSc) });
}
function resolve(payload) {
  const actorIdx = sideIdx(payload.actor_side), targetIdx = sideIdx(payload.target_side);
  const teams = [parsePackedTeam(payload.team_p1), parsePackedTeam(payload.team_p2)];
  const aMon = teams[actorIdx][0], dMon = teams[targetIdx][0];
  if (!aMon || !dMon || !aMon.species || !dMon.species) return { ok:false, move_id:payload.move_id, error:"missing active pokemon" };
  const aSt = payload.active_state && payload.active_state[payload.actor_side];
  const dSt = payload.active_state && payload.active_state[payload.target_side];
  let attacker, defender, field, move;
  try { attacker = makeCalcPokemon(aMon, aSt && aSt[0]); defender = makeCalcPokemon(dMon, dSt && dSt[0]); field = makeCalcField(payload); move = new calc.Move(GEN, payload.move_id, { isCrit:false, hits:1 }); }
  catch (e) { return { ok:false, move_id:payload.move_id, error:"build failed: " + e.message }; }
  let result;
  try { result = calc.calculate(GEN, attacker, defender, move, field); }
  catch (e) { return { ok:false, move_id:payload.move_id, error:"calculate failed: " + e.message }; }
  const d = result.damage;
  let dmgArr;
  if (typeof d === "number") dmgArr = [d, d];
  else if (Array.isArray(d) && Array.isArray(d[0])) { const r = result.range(); dmgArr = [r[0], r[1]]; }
  else if (Array.isArray(d)) dmgArr = d.slice();
  else dmgArr = [0, 0];
  const sorted = dmgArr.slice().sort((a, b) => a - b);
  const maxhp = (defender.rawStats && defender.rawStats.hp) || 1;
  const pct = (x) => +((x / maxhp) * 100).toFixed(1);
  const ohkoMove = OHKO_MOVES.has(String(payload.move_id || "").toLowerCase());
  const min = ohkoMove ? maxhp : sorted[0];
  const max = ohkoMove ? maxhp : sorted[sorted.length - 1];
  const median = ohkoMove ? maxhp : sorted[Math.floor(sorted.length / 2)];
  let ko = { chance:0, n:0 };
  try { ko = result.kochance() || ko; } catch (e) {}
  const ohko_chance = ohkoMove ? 1.0 : ko.n === 1 ? +Number(ko.chance).toFixed(3) : 0;
  const twohko_chance = ohkoMove ? 1.0 : ko.n <= 2 ? +Number(ko.chance).toFixed(3) : 0;
  const is_ohko = ohkoMove ? true : min >= maxhp || ohko_chance >= 0.5;
  let moveType = null, basePower = null;
  try { if (result.move && result.move.type) moveType = String(result.move.type).toLowerCase(); } catch (e) {}
  try { if (result.move && typeof result.move.bp === "number") basePower = result.move.bp; } catch (e) {}
  const resolved = { base_power:basePower, base_power_changed:null, base_power_reason:null, is_ohko:is_ohko, override_offensive_stat:(result.move && result.move.overrideOffensiveStat) || null, effectiveness_multiplier:null, type:moveType };
  return { ok:true, move_id:payload.move_id, resolved:resolved, damage:{ min:min, max:max, min_pct:pct(min), max_pct:pct(max), median:median, median_pct:pct(median) }, ko_estimate:{ ohko_chance:ohko_chance, twohko_chance:twohko_chance } };
}
rl.on("line", (line) => {
  if (!line.trim()) return;
  let payload;
  try { payload = JSON.parse(line); } catch (e) { send({ ok:false, error:"invalid json: " + e.message }); return; }
  try { send(resolve(payload)); } catch (e) { send({ ok:false, move_id:payload && payload.move_id, error:e.message }); }
});
rl.on("close", () => process.exit(0));
```

## 참조

- Python 호출부: `pokechamp/damage_calc_oracle.py`(`DamageCalcOracle`, `get_shared_damage_calc_oracle`).
- 백엔드 팩토리/compare: `pokechamp/oracle_backend.py`, `pokechamp/oracle_compare.py`.
- payload 생성: `pokechamp/battle_state_mapper.py:battle_to_oracle_payload`(백엔드 공유).
- 도구 통합: `pokechamp/battle_tools.py:_resolve_move_outcome_via_oracle`.
- 원본 oracle: `docs/architecture/oracle-worker-reproduction.md`.
- 원본 계획: `/root/.claude/plans/transient-frolicking-petal.md`.
