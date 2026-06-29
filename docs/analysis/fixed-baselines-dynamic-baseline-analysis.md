# 고정 팀 dynamic-resolve baseline 분석 (io / react / minimax)

> ⚠️ **오염 경고 (2026-06-29 갱신)**: 본 분석은 2026-06-19, oracle 통합(EXP-045+) **이전**에 작성되었습니다.
> sim-only 측정이라 oracle 데미지 버그와는 무관할 수 있으나, 후속 시리즈(EXP-045~049c)가 모두
> oracle 버그 하 오염 측정으로 끝났습니다. 따라서 본문의 "fix2/fix3 진짜 효과 측정 기대" 등 전망은
> EXP-050a(oracle 수정 후) 정상 측정으로 재검증이 필요합니다. 본문 정량(react 66.7% / minimax 53.3%)은
> 이력 보존. **최신 결론: [`exp-050a`](exp-050a-react-glm51-analysis.md).**

> 분석 일시: 2026-06-19
> 고정 팀 dynamic baseline: glm-5.1 (ollama/glm-5.1:cloud), temp 0.3, seed 42, N=30 vs abyssal
> 팀 모드: **fixed** (manifest `dynamic-v1.json`, sha256:5bf6bf05…)
> 비교: 랜덤 팀 baseline `baselines/{io,react,minimax}-glm51` (동일 조건, 랜덤 매치업)

---

## 0. 실험 조건 (팀 구성 — 매치업 격리)

| 항목 | 값 |
|------|-----|
| team_mode | fixed |
| manifest | `fixed-baselines/manifests/dynamic-v1.json` (sha256:5bf6bf05bf787063…) |
| 매치업 | player modern_replays rank1-30 × opponent modern_replays rank31-60 (disjoint) |
| 선별 기준 | dynamic score 상위 (Tera 다양성 + 동적 타입/위력/priority/어빌리티/아이템 균형) |
| 비교 기준 | `baselines/{algo}-glm51` (랜덤 매치업) / `fixed-baselines/{algo}-glm51-dynamic` (동일 dynamic 매치업) |

> 세 알고리즘 모두 **동일 manifest hash** 확인 → 같은 30 매치업. 알고리즘 간 승률 차이 = 알고리즘 자체 차이.
> dynamic 풀은 동적 무브(tera blast/ivycudgel/acrobatics/hex/knockoff/…)·Tera 다양성·protosynthesis 등이 밀집. 랜덤풀 대비 dynamic resolve 빈발(EXP-038 "tera 0.7%" 문제 해소).

---

## 1. 실험 결과 비교

### 1.1 dynamic baseline 3종 + 랜덤 baseline 대비

| 알고리즘 | dynamic 승률 | random 승률 | 델타 | dynamic 턴 | random 턴 | LLM/판 (dyn) |
|----------|--------------|-------------|------|------------|-----------|--------------|
| io | 46.7% (14/30) | 53.3% (16/30) | −6.6pp | 17.6 | 39.0 | 21.6 |
| react | 66.7% (20/30) | 76.7% (23/30) | −10.0pp | 15.5 | 24.4 | 47.6 |
| minimax | 53.3% (16/30) | 80.0% (24/30) | **−26.7pp** | 15.6 | 28.9 | 52.2 |

### 1.2 리소스 사용량 (dynamic)

| 항목 | io | react | minimax |
|------|----|-------|---------|
| 배틀당 LLM 호출 | 21.6 | 47.6 | 52.2 |
| 배틀당 prompt 토큰 | 40,097 | 131,713 | 88,862 |
| 배틀당 completion 토큰 | 1,855 | 4,889 | 7,711 |
| JSON 파싱 실패 | 0 | 2 | 0 |

### 1.3 구간별 승률 (dynamic)

| 구간 | io | react | minimax |
|------|----|-------|---------|
| 짧은 (<15턴) | 4/8 (50%) | **9/11 (82%)** | 7/12 (58%) |
| 중간 (15-24턴) | 10/21 (48%) | 11/19 (58%) | 9/17 (53%) |
| 긴 (25+턴) | 0/1 | — (n=0) | 0/1 |

> dynamic 매치업은 **대부분 <25턴**에 결착 (25+ 배틀이 io 1·react 0·minimax 1). 랜덤풀의 장기전 패턴(react 24.4턴 avg)과 대조적으로 동적 위력 무브의 빠른 KO가 지배적.

---

## 2. 핵심 발견

### 2.1 dynamic 매치업 = 빠른 결착 + 비용 절감

모든 알고리즘에서 턴 수가 대폭 단축됐다(io 39.0→17.6, react 24.4→15.5, minimax 28.9→15.6). 동적 위력 무브(acrobatics/facade/hex/knockoff/heavyslam)와 Tera 강화 공격이 밀집한 팀이라 **초반 KO**가 빈번. 결과적으로 LLM 호출·토큰도 절감(react 119.1→47.6 calls/판). 이는 비용 효율 측면에선 긍정적.

### 2.2 승률 하락 = opponent 강팀 효과

세 알고리즘 모두 승률이 하락했다. 이는 player 풀뿐 아니라 **opponent 풀도 modern_replays dynamic 상위(rank31-60, 강팀)**이기 때문이다 — abyssal(휴리스틱)이 더 강력한 팀을 구동하므로 pokechamp 입장에서 더 어려운 상대. 동일 매치업이므로 알고리즘 간 **상대적** 비교는 공정.

### 2.3 결정적 차이: minimax −26.7pp = sim dynamic resolve 의존도 노출 ★

가장 큰 발견. dynamic 매치업에서 알고리즘별 하락 폭이 io(−6.6) < react(−10.0) ≪ **minimax(−26.7)**로 벌어진다.

- **minimax**는 `LocalSim` 시뮬레이션 트리의 리프를 LLM이 평가하는 구조 → sim의 dynamic resolve 정확도(동적 타입/위력/priority 리졸브)가 의사결정에 직결. dynamic 밀집 팀에서 sim 오류(동적 위력 중복 보정 EXP-035, tera/ivycudgel fix3 영역)가 빈번히 발현되어 타격.
- **react**는 LLM이 도구 호출로 상황을 직접 추론(sim에 덜 의존) → sim 오류에 완충. 짧은 배틀(<15) 82% 승률로 견고.
- **io**는 단순 I/O로 sim 의존 최소 → 가장 작은 하락.

### 2.4 가설 / 인과 추론

이 결과는 **EXP-038 시리즈 종합 결론("fix1만 전이, fix2/3 비전이")이 매치업 빈도에 의해 가려졌을 가능성**을 시사한다. 랜덤풀에선 tera/ivycudgel 발동이 0.7%라 fix3 효과가 측정 불가였으나, dynamic 매치업에서는 dynamic resolve가 빈발하므로 fix2(protect/item)·fix3(tera/ivycudgel)의 진짜 효과가 승률로 드러날 수 있다. 특히 minimax에서 가장 민감하게 측정될 것.

---

## 3. 다음 단계: EXP-035~038 fix 재검증 (dynamic 매치업 + minimax)

dynamic baseline이 확보됐으므로, 이제 동일 dynamic 매치업에서 fix 변경점을 ablation 한다.

### 권장 ablation (변수 1개, 동일 dynamic-v1 manifest)

1. **EXP-039: dynamic baseline 대비 fix1 (priority/protosynthesis)** — 시리즈에서 유일 전이됐던 fix. dynamic 매치업에서 효과 크기 재측정.
2. **EXP-040: fix2 (protect/item)** — 랜덤풀에선 −13.3pp(역효과 의심)였으나, dynamic 매치업에서 재평가.
3. **EXP-041: fix3 (tera/ivycudgel)** — 랜덤풀에선 무효(발동 0.7%)였으나, dynamic 매치업(tera/ivycudgel 빈발)에서 진짜 효과 첫 측정 기대.

```sh
# 예: EXP-039 (fix1), 동일 dynamic 매치업, minimax
uv run python scripts/exp/new_experiment.py --name <change> --team_mode fixed \
  --team_manifest .temp/experiments/fixed-baselines/manifests/dynamic-v1.json --baseline minimax
# 코드 1개 변경 → 안내 명령으로 배틀 → verify_single_change.py EXP-039 --baseline minimax --zone fixed-baselines
```

> 검증: `--zone fixed-baselines` 로 `minimax-glm51-dynamic` baseline과 비교. 같은 manifest → 팀 키 0 + 코드 1 = PASS.

### 즉시
- [ ] dynamic 매치업 기반 ablation 설계 (위 3개 fix 각각)
- [ ] 특히 **minimax**에서 fix3(tera/ivycudgel) 효과 측정 — 시리즈 처음으로 의미있는 데이터 기대

---

## 4. 한계

- **LLM 비결정성**(temp 0.3): 동일 알고리즘 2회 실행이 완전 일치하지 않음. 본 baseline은 단회 실행(N=30). 중요 결론은 반복 측정으로 보강 권장.
- **opponent 강도 혼입**: random↔dynamic 승률 델타는 "opponent 풀 강도 + dynamic resolve 영향" 혼합. 순수 dynamic resolve 효과는 **동일 dynamic 매치업 내 코드 변경(fix) 전후**로만 분리 가능(위 ablation).
- **abyssal tera 한도**: abyssal은 휴리스틱이라 tera 능동 사용 안 함. fix3(tera) 효과는 player 팀 tera 사용에 의존 — player 풀이 dynamic 밀집팀(tera 다수)이라 부분 보장.
