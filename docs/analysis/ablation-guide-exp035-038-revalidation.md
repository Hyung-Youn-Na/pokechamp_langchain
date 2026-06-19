# EXP-035~038 재검증 ablation 가이드 (고정 팀 dynamic-resolve 매치업)

> EXP-035~038(simulation dynamic resolve fix 시리즈)의 fix1/fix2/fix3 각각의 **한계 효과(marginal effect)**를
> 고정 팀 `dynamic-v1` 매치업(동적 무브 밀집)에서 leave-one-out 제거 ablation으로 재검증하는 절차.
> 단일 진실 원본: [`experiment-context.md`](../../experiment-context.md) §9.

---

## 1. 배경: 왜 재검증인가

EXP-038 시리즈 종합은 **"fix1(priority/protosynthesis)만 승률 전이, fix2(protect/item) 역효과, fix3(tera/ivycudgel) 무효"**로 결론났다. 그러나 이 결론은 **랜덤 풀에서 dynamic resolve 발생 빈도가 너무 낮아서**(tera 언급 0.7%, Ogerpon 3배틀) fix2/fix3 효과가 애초에 측정 불가했기 때문이다.

고정 팀 `dynamic-v1.json`(dynamic score 상위 팀, 동적 무브 밀집) baseline을 3종 알고리즘으로 측정했다:

| 알고리즘 | dynamic 승률 (fix1+2+3) | random 승률 | 델타 |
|----------|--------------------------|-------------|------|
| io | 46.7% (14/30) | 53.3% | −6.6pp |
| react | 66.7% (20/30) | 76.7% | −10.0pp |
| minimax | 53.3% (16/30) | 80.0% | **−26.7pp** |

→ dynamic 매치업에서 **minimax가 가장 크게 흔들린다**(sim dynamic resolve 정확도에 최대 의존). 따라서 동일 dynamic 매치업에서 각 fix를 제거하면, 랜덤풀에서 불분명했던 fix2/fix3 효과가 — 특히 minimax에서 — 처음으로 제대로 측정된다.

**현행 코드 상태**: `poke_env/player/local_simulation.py` = **fix1+2+3 전부 적용**(commit `a1d03ab` = EXP-038 patch 결과물). 즉 위 dynamic baseline이 fix1+2+3 상태의 기준점이다.

---

## 2. ablation 매트릭스 (leave-one-out 제거, 3종)

baseline = 현행 dynamic(fix1+2+3, 이미 측정). 각 EXP는 **한 fix만 제거**한 코드로 동일 `dynamic-v1` 매치업 3 알고리즘(io/react/minimax) 측정.

| EXP | 제거 fix | 코드 상태 | 기대 (dynamic 한계 효과) |
|-----|----------|-----------|--------------------------|
| **EXP-039** | −fix3 (fix1+2) | tera/ivycudgel revert | 시리즈 처음으로 fix3 효과 의미 측정(랜덤풀에선 무효). minimax에서 양수 기여 기대 |
| **EXP-040** | −fix2 (fix1+3) | protect/item revert | fix2 한계 효과(랜덤풀 −13.3pp 역효과 재평가) |
| **EXP-041** | −fix1 (fix2+3) | priority/protosynthesis revert | fix1 한계 효과(시리즈 최대 전이 예상, 매 턴 영향) |

**해석 공식**: `baseline(fix1+2+3) 승률 − EXP-NNN(−fixX) 승률 = fixX의 한계 기여`
- 양수 = fixX가 승률에 도움 (제거하면 하락)
- 음수 = fixX가 해 (제거하면 상승 → 현행 코드에서 제거 고려)

---

## 3. 각 fix revert 지침

모두 `poke_env/player/local_simulation.py`의 **수동 편집**(`git apply -R`은 전체 revert만 가능 — 개별 fix는 patch base가 pre-fix 원본이라 현행에서 안 됨). 각 fix는 **서로 완전히 독립된 코드 영역**이라 충돌 없이 어떤 조합이든 revert 가능.

### 3.1 fix1 revert (−fix1, EXP-041) — 행동순서 priority/protosynthesis

**실패 테스트(_skip 대상)**: `tests/test_simulation_accuracy.py::TestActionOrder` (5개)

**① protosynthesis 복붙 버그로 복귀** (L1497):
```python
# 현行:        ) * self.apply_protosynthesis(p2, "spe")     # L1497
# revert:      ) * self.apply_protosynthesis(p1, "spe")     # ← p1 복붙 버그
```

**② priority 전 범위 비교 → `==1` 단일 체크로 복귀** (L1498-1517, 현행 20줄 → 원본 9줄):
```python
# 현行 (L1498-1517):
        p1_pri = m1.priority if m1 is not None else 0
        p2_pri = m2.priority if m2 is not None else 0
        if p1_pri != p2_pri:
            p1_first = p1_pri > p2_pri
        elif p1_speed != p2_speed:
            p1_first = p1_speed > p2_speed
        else:
            p1_first = (sum(map(ord, str(id1))) - sum(map(ord, str(id2)))) % 2 == 0
        if p1_first:
# revert:
        p1_priority = False
        if m1 is not None:
            if m1.priority == 1:
                p1_priority = True
                if m2 is not None:
                    if m1.priority == 1 and m2.priority == 1:
                        p1_priority = False
        if p1_speed > p2_speed or p1_priority:
```

**③ success 판정 복귀** (L1543-1544):
```python
# 현行:
        m1_success = (p1_first or hp1 > 0) and m1 != None
        m2_success = (not p1_first or hp2 > 0) and m2 != None
# revert:
        m1_success = ((p1_speed > p2_speed) or hp1 > 0) and m1 != None
        m2_success = ((p1_speed <= p2_speed) or hp2 > 0) and m2 != None
```

### 3.2 fix2 revert (−fix2, EXP-040) — protect/LifeOrb

**실패 테스트**: `TestProtectAndItem` (3개)

**편집 영역** (L2082-2104, 현行 23줄 → 원본 7줄):
```python
# 현行:
        # Items are stored lower-case ... so match accordingly.
        if pokemon.item == "lifeorb":                    # L2084
            baseDamage *= 1.3
        if target_move != None:
            _PROTECT_MOVES = {"protect","detect","kingsshield",...}   # L2093
            if target_move.id in _PROTECT_MOVES:
                if move.is_z or pokemon.is_dynamaxed:
                    baseDamage *= 0.25
                else:
                    return 0                             # protect 일반命中 0데미지
# revert:
        if pokemon.item == "LifeOrb":                    # ← 대문자 (구버전)
            baseDamage *= 1.3
        if target_move != None:
            if (move.is_z or pokemon.is_dynamaxed) and target_move.id == "protect":
                baseDamage *= 0.25                       # ← protect만, 일반 0처리 없음
```

### 3.3 fix3 revert (−fix3, EXP-039) — tera/ivycudgel (4개 하위 변경 + import)

**실패 테스트**: `TestTeraAndDynamicMoves` (4개). fix3는 5곳:

| # | 위치 | 내용 | revert |
|---|------|------|--------|
| import | L15 | `from poke_env.environment.pokemon_type import PokemonType` | 라인 삭제 |
| 3-a | L1592-1597 (`modify_base_power`) | ivycudgel + Ogerpon tera 시 100→120 | 6줄 블록 삭제 |
| 3-b | L1924-1938 (`modify_damage`) | `_IVYCUDGEL_OGERPON_TYPE` 폼별 타입 매핑 | 15줄 블록 삭제 |
| 3-c | L1982-1993 (`modify_damage`) | tera 공격자 STAB (attacker_types + tera) | `[type_1, type_2]` 단순 체크로 |
| 3-d | L1998-2019 (`modify_damage`) | tera defender 단일 타입 사용 | `opponent_type_list` 로직 + `type_1,type_2` 전달로 |

> fix3-c/d는 한 git hunk에 묶여있으나 코드적으로 독립 변수. **ablation에서는 fix3 전체(4개)를 한 단위로 revert 권장** — 모두 tera/ivycudgel 정확도라 한 덩어리로 측정이 의미 있음.

상세 before/after 코드는 `backups/code_state/EXP-038-sim-tera-ivycudgel/`의 dirty patch 참조(또는 조사 보고서).

---

## 4. 워크플로우 (각 EXP, 각 알고리즘)

```sh
# 1. EXP 스캐폴드 (동일 dynamic 매치업)
uv run python scripts/exp/new_experiment.py --name <fix>-revert-<algo> \
  --team_mode fixed \
  --team_manifest .temp/experiments/fixed-baselines/manifests/dynamic-v1.json \
  --baseline <io|react|minimax>
# → active/EXP-NNN/ + --team_mode fixed 안내 명령

# 2. fixX revert 코드 편집 (위 §3) + 해당 테스트 클래스 skip
#    revert 후 단위 테스트로 "의도한 revert" 확인 (해당 클래스만 FAIL, 나머지 PASS):
.venv/bin/pytest tests/test_simulation_accuracy.py -k "not <TestClass>" -q

# 3. 배틀 (사용자 실행 — §0-8): 안내 명령 사용
# 4. 검증: 같은 manifest → 팀 0 + 코드 1 = PASS
uv run python scripts/exp/verify_single_change.py EXP-NNN --baseline <algo> --zone fixed-baselines

# 5. ★원복 필수 (다음 케이스 오염 방지):
git checkout HEAD -- poke_env/player/local_simulation.py

# 6. 분석: exp_analysis/ANALYSIS_MANUAL.md 절차 + dynamic baseline 대비 델타
```

**EXP × 알고리즘 조합**: EXP-039/040/041 각각 io·react·minimax 3회 실행(스캐폴드 `--baseline`만 교체). 총 9 배틀 세트. revert 코드는 EXP 내에서 알고리즘 전환 시 동일(한 번 revert 후 3 알고리즘 모두 돌리고 원복).

---

## 5. 해석 가이드

- **같은 dynamic 매치업**이므로 `baseline − EXP` 델타 = 순수 fix 한계 효과(팀 노이즈 제거). 이게 고정 팀 모드의 핵심 가치.
- **minimax에서 가장 민감**(dynamic −26.7pp) → fix 효과가 minimax 승률에 가장 크게 반영. fix3 양수 기여가 minimax에서 뚜렷하면 "sim 정확도→승률 전이" 입증.
- **fix3(tera/ivycudgel)**: 랜덤풀 무효(0.7%)였으나 dynamic에선 tera 빈발 → **시리즈 처음으로 유의 효과 기대**. minimax에서 양수 = 현행 fix3 유지 정당화.
- **fix2(protect/item)**: 랜덤풀 −13.3pp 역효과. dynamic(protect 계열·Life Orb 빈발)에서 재평가. 여전히 음수면 fix2 본격 재검토.
- **fix1(priority/protosynthesis)**: 매 턴 영향 → 가장 큰 양수 기여 예상(시리즈 "fix1만 전이"와 일치 확인).
- **LLM 비결정성**(temp 0.3): 단회 실행(N=30). z-검정/p-값으로 유의성 판단, 중요 결론은 반복 측정 권장.

---

## 6. 안전 수칙 ★

1. **각 EXP 종료 후 반드시 원복**: `git checkout HEAD -- poke_env/player/local_simulation.py`. 안 하면 다음 ablation 케이스가 오염(여러 fix가 섞인 코드로 측정).
2. **revert 검증**: revert한 fix의 테스트 클래스만 FAIL, 다른 클래스는 PASS인지 확인 (`pytest -k "not <TestClass>"`가 전부 PASS). 이래야 "의도한 fix만 빠졌음"이 보장.
3. **같은 `dynamic-v1` manifest + 같은 seed 42** → 팀 통제. `--zone fixed-baselines`로 dynamic baseline과 비교.
4. **코드 커밋**: 각 EXP의 더티 patch는 배틀 로그 `meta`에 자동 기록(§8). `preserve_code_state.py`로 오프디스크 보존 권장.

---

## 7. 실행 지원

에이전트가 각 EXP의 **revert 코드를 준비**(`local_simulation.py` 편집 + 테스트 skip 안내)할 수 있다. 사용자는 §0-8에 따라 **배틀만 실행**. 첫 EXP(EXP-039, −fix3)부터 순차 진행 권장 — 시리즈에서 가장 불분명했던 fix3를 dynamic에서 먼저 검증.
