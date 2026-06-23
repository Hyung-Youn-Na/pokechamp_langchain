# Showdown Oracle Worker — 재현 가이드

> `oracle-worker.js`는 `pokemon-showdown/` 디렉토리(별도 clone, 자체 git repo) 안에 있어 **메인 PokéChamp repo에서 추적되지 않는다**(`.gitignore: pokemon-showdown/`). 이 문서는 새 환경에서 worker를 동일하게 재현하는 절차와 **전체 소스**를 제공한다.

## 역할

`oracle-worker.js`는 react 데미지 도구(`calculate_damage`/`simulate_turn`)가 **Showdown 엔진**으로 단일 무브의 정확한 damage/type/KO를 계산하기 위한 stdin/stdout JSON-line 워커다. `pokechamp/showdown_oracle.py`(`get_shared_oracle()`)가 이 worker를 subprocess로 띄워 payload를 보낸다.

- 동적 타입 무브(weatherball/terablast/ivycudgel 등): `onModifyType` 콜백 실행 → resolved type.
- 동적 위력 무브(facade/knockoff/hex 등): `runMove`로 정확 damage.
- side_conditions(Reflect/Light Screen/Aurora Veil): wall 보정.

## 전제

- **Node.js** v20+(이 프로젝트는 v24로 검증).
- **pokemon-showdown** 엔진 + 빌드된 `dist/`.

## 재현 절차

### 1. pokemon-showdown 확보 + 빌드

```sh
git clone https://github.com/smogon/pokemon-showdown.git
cd pokemon-showdown
npm install
node tools/build        # → dist/sim/index.js 생성 (worker가 require)
```

> 이미 `pokemon-showdown/` 이 repo 안에 있다면 이 단계는 생략. 단 `dist/sim/index.js`가 빌드돼 있어야 한다.

### 2. worker 파일 생성

`pokemon-showdown/scripts/oracle-worker.js` 를 아래 **전체 소스**로 생성:

```js
#!/usr/bin/env node
"use strict";
/**
 * Showdown Oracle Worker.
 *
 * stdin JSON-line payload → pokemon-showdown 실제 시뮬레이션으로 단일 무브의
 * resolved 결과(위력/타입상성/데미지/KO)를 계산 → stdout JSON-line 응답.
 *
 * 동적 무브(onModifyType/onBasePower 등)를 Showdown 콜백 그대로 실행하므로
 * sim(local_simulation.py)이 처리하지 못하는 동적 위력 71개·타입 13개를
 * 단일 진실 소스(gen9moves) 기반으로 정확 처리한다.
 *
 * Payload (pokechamp/battle_state_mapper.py: battle_to_oracle_payload):
 *   id, format, seed[4], actor_side, actor_slot, target_side, target_slot,
 *   move_id, weather, terrain, pseudoweather, team_p1, team_p2 (packed),
 *   active_state{p1:[...], p2:[...]}, side_conditions{p1:{}, p2:{}}
 *
 * Response:
 *   { ok, move_id,
 *     resolved{base_power, base_power_changed, base_power_reason, is_ohko,
 *              override_offensive_stat, effectiveness_multiplier, type},
 *     damage{min, max, min_pct, max_pct},
 *     ko_estimate{ohko_chance, twohko_chance} }
 *
 * 계약: tests/test_showdown_oracle.py (@pytest.mark.oracle)
 *   facade+burn→140, knockoff+item→97, fissure→OHKO, bodypress→def,
 *   freezedry/water→≥2.0
 */
const path = require("path");
const readline = require("readline");
const { Battle, Teams, Dex } = require(path.resolve(__dirname, "..", "dist", "sim", "index.js"));

const rl = readline.createInterface({ input: process.stdin, terminal: false });

function send(obj) {
	process.stdout.write(JSON.stringify(obj) + "\n");
}

function sideIdx(side) {
	return side === "p1" ? 0 : 1;
}

// payload.active_state[*]의 현재 포켓몬 상태를 Showdown Pokemon에 주입.
// (packed team엔 species/item/ability/nature/evs/ivs만 있고 HP/boosts/status/tera는 없다.)
function applyActiveState(pokemon, st) {
	if (!st) return;
	if (st.max_hp) {
		try { pokemon.maxhp = st.max_hp; } catch (e) {}
	}
	if (st.hp_pct != null && pokemon.maxhp) {
		pokemon.hp = Math.max(0, Math.round(pokemon.maxhp * st.hp_pct / 100));
	} else if (st.max_hp) {
		pokemon.hp = st.max_hp;
	}
	if (st.status) {
		try { pokemon.setStatus(st.status, null, false, false); } catch (e) {
			try { pokemon.status = st.status; } catch (e2) {}
		}
	}
	if (st.item) { try { pokemon.setItem(st.item); } catch (e) {} }
	if (st.ability) {
		try { pokemon.setAbility(st.ability); } catch (e) {
			pokemon.ability = st.ability;
			pokemon.baseAbility = st.ability;
		}
	}
	if (st.boosts) { try { pokemon.setBoost(st.boosts); } catch (e) {} }
	if (Array.isArray(st.volatiles)) {
		for (const v of st.volatiles) { try { pokemon.addVolatile(v); } catch (e) {} }
	}
	if (st.is_terastallized && st.tera_type) {
		try {
			// terablast reads pokemon.teraType; terastallized gates the callback.
			pokemon.terastallized = st.tera_type;
			pokemon.teraType = st.tera_type;
		} catch (e) {}
	}
}

function buildBattle(payload) {
	const battle = new Battle({
		formatid: payload.format || "gen9customgame",
		seed: (payload.seed && payload.seed.length === 4) ? payload.seed : [42, 1337, 256, 999],
		debug: true,
		forceRandomChance: true,
	});
	battle.setPlayer("p1", { name: "p1", team: Teams.unpack(payload.team_p1) });
	battle.setPlayer("p2", { name: "p2", team: Teams.unpack(payload.team_p2) });

	// weather/terrain durationCallback requires a source pokemon (5-turn weather
	// like raindance); use the active pokemon as the inducing source.
	const fieldSource = battle.sides[0] && battle.sides[0].active[0];
	if (payload.weather && fieldSource) { try { battle.field.setWeather(payload.weather, fieldSource); } catch (e) {} }
	if (payload.terrain && fieldSource) { try { battle.field.setTerrain(payload.terrain, fieldSource); } catch (e) {} }

	// singles: active_state.{p1,p2}[0]. actor/target slot은 0 고정(singles).
	const aState = payload.active_state && payload.active_state.p1 && payload.active_state.p1[0];
	const dState = payload.active_state && payload.active_state.p2 && payload.active_state.p2[0];
	if (aState) applyActiveState(battle.sides[0].active[0], aState);
	if (dState) applyActiveState(battle.sides[1].active[0], dState);

	return battle;
}

function resolve(battle, payload) {
	const actorIdx = sideIdx(payload.actor_side);
	const targetIdx = sideIdx(payload.target_side);
	const source = battle.sides[actorIdx].active[0];
	const target = battle.sides[targetIdx].active[0];
	const move = Dex.getActiveMove(payload.move_id);

	// resolved base power: move의 onBasePower + ability/item BasePower 이벤트.
	// compiled move(getActiveMove) 필수. raw Dex.moves.get는 콜백 미실행.
	const baseBP = move.basePower;
	let basePower = baseBP;
	try { basePower = battle.runEvent("BasePower", source, target, move, baseBP, true); } catch (e) {}
	if (typeof basePower !== "number") basePower = baseBP;
	basePower = Math.round(basePower);
	const base_power_changed = basePower !== baseBP;

	// effectiveness: move onEffectiveness 포함 (freezedry vs Water → 2×).
	let typeMod = 0;
	try { typeMod = target.runEffectiveness(move); } catch (e) {}
	const effectiveness_multiplier = Math.pow(2, typeMod);

	// resolved type: apply onModifyType (weatherball/terablast/ivycudgel/
	// revelationdance/terastarstorm/hiddenpower/terrainpulse) on a separate
	// compiled move BEFORE runMove (which mutates source/field state and can
	// suppress the ModifyType callback for some attackers). Showdown runs
	// singleEvent("ModifyType") for the move's own callback, then
	// runEvent("ModifyType") for ability/item modifiers. Base type otherwise.
	let moveType = move.type;
	try {
		let typeMove = Dex.getActiveMove(payload.move_id);
		battle.singleEvent("ModifyType", typeMove, null, source, target, typeMove, typeMove);
		const evMove = battle.runEvent("ModifyType", source, target, typeMove, typeMove);
		if (evMove && evMove.type) typeMove = evMove;
		moveType = typeMove.type || move.type;
	} catch (e) {}

	// damage via runMove (전체 파이프라인: ModifyType/ModifyMove→데미지).
	const beforeHP = target.hp;
	const targetLoc = (actorIdx === 0) ? 2 : 1; // singles opponent location
	let damage = 0;
	try { battle.actions.runMove(payload.move_id, source, targetLoc); } catch (e) {}
	damage = Math.max(0, beforeHP - target.hp);

	// Wall correction: Reflect (physical) / Light Screen (special) / Aurora
	// Veil (both) halve damage in singles. Showdown's side-condition
	// ModifyDamage event doesn't fire in this worker (the Battle is built by
	// hand without start()'s event wiring), so apply the screen multiplier
	// directly on the runMove HP-delta. (Crit ignores screens — not modeled
	// here; rare, and runMove's crit already rolled into the delta above.)
	const tSc = (payload.side_conditions && payload.side_conditions[payload.target_side]) || {};
	const cat = move.category;
	let wall = 1;
	if (cat === 'Special' && tSc.lightscreen) wall = 0.5;
	if (cat === 'Physical' && tSc.reflect) wall = 0.5;
	if (tSc.auroraveil && (cat === 'Physical' || cat === 'Special')) wall = Math.min(wall, 0.5);
	if (wall < 1) damage = Math.max(0, Math.round(damage * wall));

	const maxhp = target.maxhp || 1;
	const is_ohko = !!move.ohko || damage >= maxhp;

	const resolved = {
		base_power: basePower,
		base_power_changed: base_power_changed,
		base_power_reason: base_power_changed ? payload.move_id : null,
		is_ohko: is_ohko,
		override_offensive_stat: move.overrideOffensiveStat || null,
		effectiveness_multiplier: effectiveness_multiplier,
		type: String(moveType).toLowerCase(),
	};
	return {
		ok: true,
		move_id: payload.move_id,
		resolved: resolved,
		damage: {
			min: damage,
			max: damage,
			min_pct: +(damage / maxhp * 100).toFixed(1),
			max_pct: +(damage / maxhp * 100).toFixed(1),
		},
		// OHKO 무브(fissure 등)는 명중 시 즉사 → 1HKO/2HKO 모두 1.0.
		ko_estimate: {
			ohko_chance: is_ohko ? 1.0 : 0.0,
			twohko_chance: is_ohko ? 1.0 : ((2 * damage >= maxhp) ? 1.0 : 0.0),
		},
	};
}

rl.on("line", (line) => {
	if (!line.trim()) return;
	let payload;
	try {
		payload = JSON.parse(line);
	} catch (e) {
		send({ ok: false, error: "invalid json: " + e.message });
		return;
	}
	try {
		const battle = buildBattle(payload);
		send(resolve(battle, payload));
	} catch (e) {
		send({ ok: false, move_id: payload && payload.move_id, error: e.message });
	}
});

rl.on("close", () => process.exit(0));
```

### 3. 사전점검

```sh
node --check pokemon-showdown/scripts/oracle-worker.js   # 문법 OK
ls pokemon-showdown/dist/sim/index.js                     # 빌드产物 존재
```

### 4. 계약 테스트로 검증

```sh
uv run python -m pytest tests/test_showdown_oracle.py -m oracle -v
# 기대: 17 passed (facade→140, knockoff→97, fissure→OHKO, bodypress→def,
#                  freezedry→2x, weatherball/terablast type, lightscreen 절반, 일반 무브 damage 등)
```

전부 PASS면 worker + 빌드 + payload 매핑이 정상. 실패 시:
- `dist/sim/index.js` 빌드 확인.
- worker 경로: `pokechamp/showdown_oracle.py`의 worker 경로가 `pokemon-showdown/scripts/oracle-worker.js`인지.
- payload 스키마: `pokechamp/battle_state_mapper.py:battle_to_oracle_payload`(L350+) 참조.

## 핵심 수정 포인트 (재현 시 반드시 포함돼야 할 로직)

아래 항목이 누락되면 oracle이 틀린 결과를 낸다. 전체 소스에 이미 포함됨.

1. **resolved type (ModifyType, runMove 전)** — `resolve()` L132-139. weatherball/terablast/ivycudgel 등의 `onModifyType`을 `runMove` **전**에 `singleEvent`+`runEvent("ModifyType")`으로 실행. `typeMove`는 `let`(재할당). runMove 후엔 source/field 변형으로 콜백이 안 먹음.
2. **teraType 주입** — `applyActiveState()` L71-77. terablast가 `pokemon.teraType`를 읽으므로 `st.tera_type` 주입.
3. **weather/terrain source** — `buildBattle()` L92-94. `setWeather(weather, fieldSource)`에 source 전달(durationCallback 요구).
4. **active HP/status/boost 주입** — `applyActiveState()`. packed team엔 HP/boost/tera가 없으므로 payload `active_state`에서 주입.
5. **Wall 직접 보정** — `resolve()` L148-160. Showdown의 side-condition `ModifyDamage` 이벤트가 hand-built Battle(start 없음)에서 **발화하지 않으므로**, Reflect/Light Screen/Aurora Veil damage × 0.5를 runMove 결과에 직접 적용. (crit 무시는 미모델링 — 드물고 runMove의 crit가 delta에 이미 반영됨.)
6. **damage = runMove 전후 HP 차이** — L142-146. `runMove`가 `|cant|nopp|`로 조용히 return하면 0이 되며, 이 경우 `battle_tools.py`의 `damage_pct_max > 0` 가드가 sim fallback을 보존한다.

## 실험 검증 이력

- **EXP-045**: attacker 식별 버그(worker `active[0]`=team 첫째 + mapper active 정렬 누락) → damage 0%. mapper(`battle_state_mapper.py:_pack_team` lead)에서 해결(worker 수정 아님).
- **EXP-046**: 동적 무브 damage 정확화 후 sim/oracle 혼합 척도 편향.
- **EXP-047**: 전무브 oracle 통일 + 위 wall 직접 보정 → 승률 63.3% (+6.6pp vs baseline). 상세: `docs/analysis/exp-047-react-glm51-analysis.md`.

## 참조

- Python 호출부: `pokechamp/showdown_oracle.py`(`ShowdownOracle`, `get_shared_oracle`, `OracleResultCache`).
- payload 생성: `pokechamp/battle_state_mapper.py:battle_to_oracle_payload`(actor/target lead 정렬 포함).
- 도구 통합: `pokechamp/battle_tools.py`(`_resolve_move_outcome_via_oracle`, 게이트 제거·opp_m 통일).
- 테스트: `tests/test_showdown_oracle.py`(`@pytest.mark.oracle`).
