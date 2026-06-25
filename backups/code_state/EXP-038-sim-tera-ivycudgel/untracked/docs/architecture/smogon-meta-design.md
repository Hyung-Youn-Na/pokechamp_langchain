# Smogon 커뮤니티 데이터 정제 — 설계 의도

> 정제 대상: `.temp/script/smogon_ou_strategies.json` (원시) + `.temp/script/gen9ou_role_compendium.md` (원시)
> 산출물: `poke_env/data/static/gen9/ou/smogon_strategies_gen9ou.json` · `smogon_roles_gen9ou.json`
> 정제 스크립트: `.temp/script/build_smogon_meta.py` (표준 라이브러리만 사용)
> 캐시: `pokechamp/data_cache.py` — `get_smogon_strategies()` / `get_smogon_roles()`
> 자매 문서(원본 스키마): `.temp/script/smogon_ou_strategies_schema.md`

이 문서는 **정제를 "왜" 이렇게 했는지**를 기록한다. 필드 단위 스키마는 스크립트의 docstring과 자매 문서에 이미 있으므로, 여기서는 각 정제 결정의 배경·취사 기준·기각한 대안에 집중한다.

---

## 1. 개요

`.temp/script/`에 gen9ou 커뮤니티 데이터 2종이 원시 형태로 있다. 이를 PokéChamp 코드베이스에서 즉시 소비 가능한 정제 JSON 2종으로 변환했다.

| 산출물 | 내용 | 규모 |
|--------|------|------|
| `smogon_strategies_gen9ou.json` | 포켓몬별 정제 전략 (추천 빌드 + overview/description 텍스트) | 108종 / 197 moveset |
| `smogon_roles_gen9ou.json` | 역할 인덱스 (정방향 role→포켓몬 + 역방향 포켓몬→role) | 11 카테고리 / 58 역할 / 114 포켓몬 |

두 산출물 모두 `species_key`(예: `greattusk`)를 키로 사용해 기존 `sets_*.json`(Smogon usage)과 곧바로 조인된다.

---

## 2. 배경: 왜 정제가 필요한가

원시 데이터를 그대로 쓸 수 없는 4가지 이유. 각각이 정제 로직의 대응 지점이 된다.

| 원시 데이터의 문제 | 그대로 쓰면 생기는 일 | 정제 대응 |
|---|---|---|
| `overview`/`comments`/`description`이 **HTML**(`<p>`, `<a href>`, `<h3>`) | LLM 프롬프트·검색·문자열 매칭에 태그가 끼어들어 노이즈 | 태그 제거 + 엔티티 디코딩 → plain text |
| 식별자가 **alias**(`samurott-hisui`)인데, 기존 데이터 키는 `samurotthisui` | 두 데이터를 조인하려면 매번 변환; 깨지면 조인 누락 | `alias → species_key` 매핑 레이어 |
| `moveslots`가 **4-슬롯 × 대안 조합** (`[[A],[B,C],[D,E,F],[G,H]]`) | "이 포켓몬이 쓸 수 있는 기술 집합"을 얻으려면 매번 평탄화 | 원본 슬롯 + 평탄화(`moves_flat`) 동시 제공 |
| role compendium은 **Markdown 표** | 코드에서 query 불가 | 표를 파싱해 정/역방향 인덱스로 구조화 |

---

## 3. 기존 데이터와의 역할 분담

프로젝트는 이미 `poke_env/data/static/gen9/ou/sets_*.json`을 베이지안 예측의 폴백 prior로 쓰고 있다. 이 정제가 **중복이 아니라 보완**이라는 점이 핵심이다.

| | 기존 `sets_1500.json` | 새 산출물 (strategies + roles) |
|---|---|---|
| 데이터 성격 | **양적** — 실제 사용 빈도(%) | **질적** — Smogon C&C 팀의 추천 + "왜"라는 설명 |
| 종 수 | 406종 | 108종 (C&C 가이드가 있는 종) |
| 핵심 필드 | abilities/items/moves/spreads/tera + `percentage` | moveslots(조합)/items/abilities/teratypes/EV + **overview/description 텍스트** + **role** |
| 질문 | "무엇이 자주 쓰이는가" | "왜 그 빌드인가, 어떤 역할인가" |

→ 빈도가 필요하면 기존 `sets_*.json`, 의미·역할이 필요하면 새 산출물. 정제는 기존 prior를 **대체하지 않고 보완**하도록 설계됐다. (`species_key`를 공유해 한 포켓몬에 대해 양쪽 데이터를 병합 가능.)

---

## 4. 설계 원칙: 활용처 중립성

정제 시점에 산출물의 **소비자가 미정**이었다(후보: LLM 프롬프트 주입 / 베이지안 prior 보강 / 역할 기반 팀 분석). 따라서 특정 소비자 형태에 편향되지 않도록 두 가지 원칙을 세웠다.

1. **원본 구조를 보존하되, 파생 뷰를 같이 제공한다.** — 한쪽을 택하면 다른쪽 소비자가 불편해지므로 둘 다 둔다. 대표 예: `moveslots`(조합 원본)와 `moves_flat`(평탄화 집합).
2. **가중치·해석은 소비자에게 맡긴다.** — 추천 순서는 보존하지만, 임의의 percentage/확률은 부여하지 않는다(빈도 데이터가 아니므로). prior 가중치·프롬프트용 요약 등은 활용처가 정해질 때 소비자 측에서 결정한다.

---

## 5. 정제 결정별 의도

각 결정을 **결정 / 이유 / 기각한 대안** 3단으로 정리.

### 5.1 HTML → plain text (`overview` / `other_options` / `description`)

- **결정**: `<p>`·`<a>`·`<h3>` 태그 제거, HTML 엔티티 디코딩(`&amp;` 등), 연속 공백 정리.
- **이유**: 텍스트는 LLM 프롬프트·검색·문자열 매칭에 쓰이므로 태그가 노이즈. 링크 안의 텍스트(포켓몬명 등)는 의미 정보라 **보존**.
- **기각한 대안**: `bs4` 사용. → 프로젝트가 아직 의존하지 않는 라이브러리라 불필요한 dep 추가 회피. 등장 태그가 `a/h3/p` 세 종류뿐이라 정규식으로 충분히 정확함(검증: 잔류 0).

### 5.2 `overview_links` 별도 추출

- **결정**: overview 안의 `<a href="/dex/sv/pokemon/<alias>/ou/">` 링크에서 alias를 뽑아 species_key 리스트로 별도 필드화. 링크 **텍스트**는 본문에 남김.
- **이유**: overview가 "Gholdengo는 Iron Valiant, Zamazenta, Kyurem을 체크한다" 식으로 **메타 체크 관계**를 서술. 이 연결 관계는 그래프적 메타 지식으로 독립 가치가 있음(역할 추론·매치업 분석 후보).
- **기각한 대안**: 본문 텍스트에만 남겨두기. → 구조적 query가 불가능해 활용이 텍스트 매칭에 국한됨.

### 5.3 `species_key` 매핑 규칙 (alias → 키)

- **결정**: `lower()` + `string.punctuation` 전체 제거 + 공백 제거. 기존 `poke_env/data/static/parse_sets.py`의 species 키 규칙과 **동일**.
- **이유**: 기존 `sets_*.json`과 조인하려면 키 규칙이 일치해야 한다. 이 규칙으로 108종 **전부** `sets_1500.json`(406종) 키와 매핑됨(누락 0, 검증 완료).
- **기각한 대안**: 별도 매핑 테이블(`alias → key`)을 손수 작성. → 규칙이 이미 존재하는데 중복 정의는 유지보수 부담. 규칙 하나로 100% 커버되므로 불필요.

> 예: `samurott-hisui` → `samurotthisui`, `great-tusk` → `greattusk`, `ogerpon-wellspring` → `ogerponwellspring`.

### 5.4 `moveslots` 원본 + `moves_flat` 동시 제공

- **결정**: 원본 4-슬롯 조합 구조(`List[List[str]]`)를 그대로 두고, 평탄화(모든 슬롯의 대안 합집합, 중복 제거, 순서 유지)한 `moves_flat`을 같이 제공.
- **이유**: 조합이 필요한 소비자(bayesian config 추정은 슬롯 단위 상호배타성이 의미)와 집합만 필요한 소비자(프롬프트 "가능한 기술 목록")가 다르다. 원칙 4.1(원본 + 파생 동시 제공)의 적용.
- **기각한 대안**: 한쪽만 제공. → 어느 한 소비자가 매번 재계산해야 함. 중복 저장 비용(수십 바이트/포켓몬)은 무시할 만함.

### 5.5 우선순위 배열 순서 보존, **가중치 미부여**

- **결정**: `abilities`/`items`/`teratypes`/`natures`/`evconfigs` 배열의 **순서**를 원본 그대로 보존. percentage나 확률 가중치는 부여하지 않음.
- **이유**: 원본 데이터의 배열 순서가 Smogon C&C의 **추천 우선순위**. 하지만 이것은 빈도가 아니라 전문가 정성적 순위이므로, 함부로 확률로 환산하면 오해의 소지. 가중치는 소비자가 결정(bayesian은 튜닝된 α로, 프롬프트는 "추천 순" 표현으로).
- **기각한 대안**: 순위 기반 감소 가중치(1.0, 0.5, ...) 부여. → 원칙 4.2 위반(해석을 정제 단계에서 끼워넣음).

### 5.6 `credits`·`type:null` 제거

- **결정**: `credits`(작성자/검수자 메타데이터)와 모든 `MoveOption.type`(항상 `null`) 제거.
- **이유**: 전투 추론에 무관한 노이즈. `type`은 스키마엔 있으나 모든 레코드에서 `null`이라 의미 없음(기술 타입은 `data_cache`의 move 데이터에서 조회).
- **기각한 대안**: 그대로 보존. → 산출물 크기만 키우고 소비 가치 없음.

### 5.7 산출물을 2개 파일로 분리 (strategies / roles)

- **결정**: 포켓몬별 전략(strategies)과 역할 인덱스(roles)를 별도 JSON으로.
- **이유**: 관심사가 다름. strategies는 "포켓몬 → 빌드", roles는 "역할 → 포켓몬" (역방향). 또한 roles는 role compendium이라 **별개 출처**에서 파생되므로 독립 갱신이 자연스움.
- **기각한 대안**: 단일 파일에 병합. → 역할 인덱스만 필요한 소비자가 969KB 전략 파일을 통째로 로드해야 함.

### 5.8 역할 인덱스의 2뷰: `by_role` + `by_pokemon`

- **결정**: 정방향(`by_role`: category → role → {main, niche} 포켓몬 리스트)과 역방향(`by_pokemon`: 포켓몬 → role 리스트)을 둘 다 제공.
- **이유**: lookup 패턴이 소비자마다 다름. 팀 분석은 "이 팀에 해저드 컨트롤이 있나"(by_role), 개별 포켓몬 설명은 "이 포켓몬의 역할은"(by_pokemon).
- **기각한 대안**: 한쪽만 저장하고 다른쪽은 런타임에 역산. → 114종×수 역할 역산은 매번 O(N) 순회; 인덱스 비용은 미미해 미리 구축이 합리적.

### 5.9 `main`/`niche` tier 보존 + `note` 분리

- **결정**: role compendium의 "주류(Main)/니치(Niche)" 구분을 `tier` 필드로 보존. 포켓몬명에 붙은 메모(예: `Samurott-Hisui (Ceaseless Edge)`)는 species_key 계산에서 **제외**하고 `note`로 별도 보존.
- **이유**: 주류/니치는 **신뢰도 신호**(니치 역할은 덜 자주). 메모는 같은 기술의 다른 맥락(`Ceaseless Edge` = 해저드+공격)이라 species 식별과 분리해야 함.
- **기각한 대안**: tier 무시하고 포켓몬을 평면 리스트로. → 니치 포켓몬이 주류처럼 비쳐 과신하는 추론 유발.

### 5.10 니치 `—` 셀 → 빈 리스트

- **결정**: compendium에서 니치 칸이 `—`(해당 없음)이면 빈 리스트로 저장.
- **이유**: "빈 집합"(니치 후보가 진짜 없음)과 "결측"(데이터 누락)을 구분. `—`는 명시적 부재이므로 빈 리스트가 정확한 의미.
- **기각한 대안**: `null`. → 결측과 혼동되어 소비자가 폴백 로직을 잘못 탈 수 있음.

---

## 6. 알려진 한계 / 데이터 품질 이슈

정제 파이프라인 자체는 정상이나, **입력 데이터 자체의 한계**가 산출물에 그대로 반영된다. 투명하게 기록한다.

| 이슈 | 내용 | 영향 |
|---|---|---|
| **`quaquaval` 오타** | role compendium 원본에서 Quaquaval이 "Quaquavel"로 오타. | roles 산출물에 `quaquavel` 키로 들어감. strategies(A)는 dex의 정확한 alias `quaquaval`. 이 때문에 A∩B = 107 (A=108, B=114). |
| **A(108) vs B(114) 차이** | strategies엔 있으나 compendium엔 없는 종 1종(`quaquavel` 오타 제외하면 0), compendium엔 있으나 C&C 가이드가 없는 종 6종(magnezone, polteageist, regieleki 등). | 자연스러운 차이. compendium이 더 넓은 메타를 커버. |
| **`home_tier ≠ OU`** | strategies 108종 중 다수가 실제 티어는 UU/RU/NU 등. | 모든 전략의 `format`은 "OU"지만, OU에서 자주 쓰여 가이드가 작성된 것. `home_tier` 필드로 실제 티어 보존. |
| **comments(Other Options) 대부분 비어있음** | 108종 중 96종이 `comments` 없음. | `other_options` 필드는 빈 문자열이 됨(정상). |
| **description 일부 비어있음** | 197 moveset 중 22개 description 없음. | `description` 필드 빈 문자열(정상). |

> 오타 보정(`quaquavel`→`quaquaval` 매핑)을 정제에 넣을지는 별도 결정 사항. 넣으면 A∩B = 108이 됨.

---

## 7. 재현성

- 정제 스크립트 `.temp/script/build_smogon_meta.py` 한 번 실행으로 두 산출물 재생성.
- **표준 라이브러리만 의존** (`json`, `re`, `html`, `string`). `bs4` 미사용 — 프로젝트 의존성 변경 없음.
- 스크립트는 자체 검증(매핑 완전성·HTML 잔류·`moves_flat` 일치)을 수행하고 결과를 콘솔에 출력.
- 로딩은 `pokechamp/data_cache.py`의 `get_smogon_strategies()` / `get_smogon_roles()` (`get_moves_set()`과 동일한 `lru_cache` + `orjson` 패턴).

---

## 8. 활용 가이드 (방향만)

산출물은 활용처无关적으로 구조화됐으므로, 결정 즉시 소비 가능. 구현은 별도 작업.

- **A. 프롬프트 메타 지식 주입** — `strategies[species].overview` / `.movesets[].description`을 `prompts.py`의 상대 포켓몬 블록에 추가. io/minimax/react 공통 적용 가능(state_translate 공유).
- **B. 역할 기반 팀 분석** — `roles.by_pokemon`으로 team preview에서 상대 팀의 역할 밸런스(해저드 컨트롤·스위퍼 유무) 파악.
- **C. 베이지안 prior 보강** — `strategies`의 추천 moveset을 `bayesian/team_predictor.py` 카운트 테이블에 pseudo-count로 주입. 단 기존 `sets_*.json`과 부분 중복이므로 한정적.

---

## 참고

- 정제 스크립트: `.temp/script/build_smogon_meta.py`
- 원본 데이터 스키마(자매 문서): `.temp/script/smogon_ou_strategies_schema.md`
- 비교 대상(양적 usage): `poke_env/data/static/gen9/ou/sets_1500.json`
- species 키 규칙 원본: `poke_env/data/static/parse_sets.py`
- 캐시 계층: `pokechamp/data_cache.py` (`GameDataCache.get_smogon_strategies` / `get_smogon_roles`)
