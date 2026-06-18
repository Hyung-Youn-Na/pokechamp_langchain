# 고정 팀 모드 (Fixed-Team Mode) — 설계 의도

> ablation 간 **팀 매치업을 격리**해 승률 변화가 "코드 변경 때문인지 팀 구성 때문인지"
> 분리 불가능한 문제를 해결하는 실험 인프라.
> 단일 진실 원본은 [`experiment-context.md`](../../experiment-context.md) §9. 본 문서는 설계 의도·결정 근거.

---

## 1. 개요

- **문제**: `--seed 42` 는 첫 배틀만 재현하고, 2번째 배틀부터 팀 구성이 매번 달라진다.
- **해결**: 미리 선별한 player/opponent 팀 매치업 N개를 manifest 로 고정해, ablation 간
  **동일 매치업**을 겪도록 한다. 전역 RNG를 소비하지 않는 결정적 로딩.
- **산출물**:
  - `poke_env/player/team_util.py`: `FixedTeamProvider`, `FixedTeamCombo`, `load_fixed_manifest`
  - `scripts/battles/local_1v1_langchain.py`·`local_1v1.py`: `--team_mode`/`--team_manifest` 분기
  - `.temp/experiments/fixed-baselines/manifests/v1.json`: 공통 canonical 팀 세트
  - `scripts/exp/verify_single_change.py`: `--zone fixed-baselines`
- **비교 체계 2종 병존**: `baselines/`(랜덤 팀, 최종 평균 성능) + `fixed-baselines/`(고정 팀, ablation 격리).

---

## 2. 배경: 왜 `--seed`가 실패하는가

`--seed 42`는 프로세스 시작 시 전역 RNG를 **단 한 번** 초기화한다(`local_1v1_langchain.py:135-145`,
루프 밖). 이후 매 배틀마다:

1. `TeamSet.yield_team()`(`team_util.py:147-164`)이 `random.choice(self.team_files)`(`:153`)로
   팀을 뽑아 전역 RNG를 소비.
2. 배틀 진행 중 `random.shuffle`(팀프리뷰)·`random.random`(무브)·`np.random.randint`(선공 분기,
   매 iteration)이 **가변 개수**로 난수를 소비.

→ 첫 배틀은 seed 직후라 재현되지만, 2번째부터는 **직전 배틀이 소비한 난수량(턴 수·LLM 응답에
따라 가변)** 에 의존해 팀이 달라진다. ablation A와 B가 같은 seed를 써도 서로 다른 매치업 시퀀스를
겪으므로, 승률 차이의 인과를 코드에서 분리할 수 없다.

---

## 3. 설계 결정

### 3.1 인덱스 기반 직접 선택 (`random.choice` 대신)

`FixedTeamProvider`는 metamon 풀의 정렬된 파일 목록에서 manifest가 지정한 **인덱스로 직접
선택**한다. `random.choice`를 호출하지 않으므로 전역 RNG에 영향을 주지 않는다. 이것이 시드
결함을 우회하는 핵심 메커니즘이다.

파일명의 숫자 인덱스와 manifest 인덱스가 일치하도록, `TeamSet._find_team_files()`의 사전순
`sorted()`(`team_10`이 `team_2` 앞에 옴)를 `_numeric_team_sort`로 숫자순 복원한다.

### 3.2 manifest JSON 포맷

player/opponent 매치업을 한 파일에 정의하고, 파일 SHA-256(`team_manifest_hash`)으로 무결성을
보장한다. 같은 manifest면 같은 매치업 → verify가 "변경 0"으로 처리(팀=통제 조건). manifest가
바뀌면 hash가 변해 "변경 1"로 잡힘(manifest 자체가 ablation 변수).

```json
{
  "version": 1, "mode": "fixed", "battle_format": "gen9ou",
  "player":   {"set": "competitive",    "indices": [...]},
  "opponent": {"set": "modern_replays", "indices": [...]},
  "n_battles": 30
}
```

공통 세트(`v1.json`): player competitive(16) modulo 순환 + opponent modern_replays(25192)에서
30개 균등 간격 유일 추출 → 매치업 쌍 30개 모두 유일.

### 3.3 `FixedTeamProvider` (기존 `TeamSet` 서브클래싱 대신 별도 클래스)

기존 `TeamSet.yield_team()`(random)은 **수정하지 않는다**. 랜덤 팀 baseline(`baselines/`)과
기존 워크플로우를 100% 보존하기 위해서다. `FixedTeamProvider`는 내부에 `TeamSet` 인스턴스를
두고 `parse_showdown_team`/`join_team` 인스턴스 메서드만 재사용한다. default `--team_mode`는
여전히 `random`이다.

### 3.4 `update_team` + `ConstantTeambuilder` 재사용

`FixedTeamProvider.at(i)`는 packed Showdown teamstring을 반환한다.
`Player.update_team(str)`(`player.py:308-318`)은 문자열을 자동으로 `ConstantTeambuilder`
(17줄, 항상 같은 팀 반환)로 wrap한다. 새 직렬화 코드 없이 기존 빌딩 블록 위에서 동작한다.

---

## 4. 기각한 대안

- **루프마다 `random.seed(42+i)` 재설정**: 배틀 *도중* 난수 소비가 가변이라 여전히 불안정.
  턴 수·LLM 응답이 달라지면 다음 배틀 팀 선택 시점의 RNG state가 흔들린다. 근본 원인(전역
  RNG 공유)을 해결하지 못한다.
- **전역 `random` monkey-patch**: 영향 범위가 넓고, 라이브러리 코드(poke_env)와 배틀 로직이
  공유하는 RNG를 건드려 예측 불가능한 부작용 위험.
- **CLI 인덱스 나열**(`--player_teams 0,1,2,...`): player/opponent 매치업 쌍의 재현성·무결성
  검증이 어렵고, manifest hash 기반 verify와 연동 불가.
- **`TeamSet` 서브클래싱으로 yield_team override**: 기존 랜덤 경로를 건드려 baseline 호환성 위험.

---

## 5. 한계

1. **LLM 응답 비결정성(temp 0.3)**: 팀을 고정해도 동일 ablation의 2회 실행이 완전히 일치하지
   않는다. 고정 팀 모드가 보장하는 것은 **ablation 간 매치업 공정성**이지, **실행 간 완전 재현성**이
   아니다. 분석은 N판 평균 ± 표준편차로 보고.
2. **competitive 풀 16개 vs N=30**: player 팀이 modulo 순환한다. 단 opponent 30개가 유일해
   **매치업 쌍**은 30개 모두 유일하다(player 팀 반복은 opponent가 다르면 다른 배틀). 매치업
   다양성이 더 필요하면 N=16 또는 player 풀 확장(modern_replays 등)을 검토.
3. **archive(EXP-001~038)와의 단절**: 과거 실험은 랜덤 팀이라 fixed-baseline과 직접 비교 불가.
   `baselines/`(랜덤)는 과거 archive 비교 기준으로 보존, `fixed-baselines/`는 신규 비교 기준 —
   두 체계 병존. 중요한 과거 결론은 고정 팀 모드로 재검증(신규 EXP 번호) 가능.
4. **banned-move 팀**: metamon 풀은 경쟁용으로 큐레이션되어 banned move가 거의 없으나, 만약
   manifest 인덱스가 banned 팀을 가리키면 Showdown 서버가 거부하고 `Player._handle_team_rejection`
   이 static fallback(`(n-1)%13+1`)으로 처리한다. 이 경로는 RNG를 쓰지 않으나 매치업이 의도와
   달라질 수 있음 — manifest 작성 시 해당 풀의 banned 여부 사전 점검 권장.

---

## 6. 재현성

- 같은 manifest + 같은 코드 → 같은 30개 매치업 시퀀스(전역 RNG 비소비로 보장).
- experiment JSON `config`에 `team_mode`/`team_manifest`/`team_manifest_hash`/`teams` 가,
  per-battle에 `player_team_idx`/`opponent_team_idx` 가 기록된다. hash 불일치로 manifest 변경 detect.
- manifest는 git 추적 권장 — 디스크 장애 후에도 hash로 무결성 검증 가능.

---

## 7. 활용 가이드 (요약)

상세 워크플로우·명령어는 [`experiment-context.md`](../../experiment-context.md) §9.3.

```
0. fixed-baselines/{io,react,minimax}-glm51 1회 측정 (--team_mode fixed)
1. new_experiment.py --name <change> --team_mode fixed   # 스캐폴드 + 안내 명령
2. 코드 1개 변경
3. 안내 명령으로 배틀 (사용자 실행)
4. verify_single_change.py EXP-NNN --baseline <algo> --zone fixed-baselines
   # 같은 manifest → 팀 0 + 코드 1 = PASS
5. ANALYSIS_MANUAL.md 절차 + template.md "0. 실험 조건"
```
