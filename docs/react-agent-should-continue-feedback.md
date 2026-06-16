구조 자체는 LangGraph ReAct 패턴의 정석에 가깝게 잘 잡혀 있어요. "LLM의 tool_calls 유무 → 라우터가 해석"하는 방식은 LangGraph 공식 tools_condition과 동일한 철학이고, 문서에서 "LLM이 직접 판단하지 않는다"고 정리한 것도 정확한 이해입니다. 다만 실전(배틀) 관점에서 몇 가지 짚을 부분이 보입니다.
1. Rule 3의 pending 초과 처리가 도구 호출을 통째로 버림
tool_call_count + pending > max_tool_calls일 때 바로 "parse"로 가면, LLM이 방금 요청한 tool_calls가 실행도 안 되고 버려집니다. 두 가지 문제가 생겨요. 첫째, 응답받지 못한 tool_calls가 달린 AIMessage가 히스토리에 남는데, 이후 그 히스토리로 LLM을 다시 호출하면 OpenAI 호환 API들은 "tool_calls에 대응하는 tool 메시지가 없다"며 400 에러를 내는 경우가 많습니다(강제 종료 시 2-message로 재구성한다면 그 경로에선 회피되지만, parse_action이 기존 히스토리를 쓰면 터집니다). 둘째, 예산이 1개 남았는데 LLM이 2개를 병렬 요청하면 전부 버리는 것보다 앞에서부터 잘라서 1개라도 실행하는 게 정보량 측면에서 낫습니다. tool_calls[:remaining]으로 truncate하는 걸 추천해요.
2. LLM이 자기 예산을 모름
지금 구조에서 LLM은 max_tool_calls 한도에 도달할 때까지 자기가 몇 번 남았는지 모르고, 한도 도달 시 "STOP" 프롬프트로 갑자기 차단당합니다. 매 agent_loop 진입 시 시스템/휴먼 메시지에 "남은 도구 호출: N회"를 주입하면 LLM이 마지막 호출을 더 가치 있는 조회에 쓰도록 유도할 수 있습니다. 특히 GLM이나 Haiku급 모델은 이런 명시적 신호 없으면 같은 도구를 반복 호출하는 degenerate loop에 빠지기 쉬운데(이전에 겪으셨던 반복 문제와 같은 계열), 예산 주입 + 동일 (tool, args) 호출 dedup(캐시된 결과를 ToolMessage로 즉시 반환하고 카운트에서 제외하거나 경고 주입)을 같이 넣으면 체감이 꽤 다릅니다.
3. 에러도 카운트되는 문제
ToolMessage 개수로 카운트하면 도구 실행 실패(크롤러 타임아웃, Smogon RPC 에러 등)도 예산을 소모합니다. 배틀 중 네트워크 이슈로 5회가 전부 에러로 날아가면 LLM은 정보 0으로 강제 JSON 출력을 해야 해요. 에러 ToolMessage는 카운트에서 빼거나, 별도의 error budget을 두는 게 안전합니다.
4. 최종 parse 실패 시 fallback
강제 종료 경로에서 JSON mode를 써도 파싱이 깨질 수 있습니다(특히 작은 모델은 JSON 안에 주석을 넣거나 필드명을 틀림). parse_action에서 파싱 실패 시 재질의 1회 → 그래도 실패면 휴리스틱 fallback(최대 위력기 선택 같은)으로 떨어지는 경로가 있는지 확인해보세요. 배틀에서는 invalid action = 타임아웃/랜덤 행동이라 파싱 실패가 그대로 패배 요인이 됩니다.
5. 턴 간 상태 재사용 시 카운트 버그 가능성
sum(ToolMessage in state["messages"])는 매 턴 그래프를 새로 invoke한다는 전제에서만 맞습니다. 만약 나중에 턴 간 메시지 히스토리를 이어가는 구조(상대 정보 누적 등)로 바꾸면 이전 턴의 ToolMessage까지 세서 첫 루프부터 강제 종료됩니다. 카운트를 메시지 스캔이 아니라 state의 별도 카운터 필드로 빼두면 이 함정을 미리 피할 수 있어요.
6. 강제 종료 시 컨텍스트 재구성의 정보 손실
2-message로 재구성하면서 "Tool Results Summary"로 압축하는 건 토큰 절약엔 좋은데, LLM이 중간에 했던 추론(왜 그 도구를 불렀는지)이 날아갑니다. 요약에 tool 결과뿐 아니라 마지막 AIMessage의 텍스트 추론도 한두 줄 포함시키면 최종 결정 품질이 올라가는 경우가 많습니다.
전체적으로 무한 루프 방지 safety net까지 갖춘 견고한 설계고, 위 항목들은 대부분 "작은 모델 + 실시간 배틀"이라는 조건에서 터지는 엣지 케이스들입니다. 우선순위를 매기면 4번(fallback) > 1번(dangling tool_calls) > 2번(예산 주입/dedup) 순으로 손보는 걸 권합니다.