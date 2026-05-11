import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from experimental.graph.battle_state import BattleDecisionState


# ---------------------------------------------------------------------------
# Node 1 — Battlefield Analysis
# ---------------------------------------------------------------------------

BATTLEFIELD_SYSTEM = """\
You are an expert Pokemon battle battlefield analyst. Your job is to produce a \
concise, structured report on the current battlefield conditions.

Analyze the following categories and respond in bullet points:

**Weather & Terrain:**
- Current weather (sun/rain/sand/hail) and remaining turns, if any.
- Active terrain (electric/psychic/grassy/misty) and remaining turns, if any.
- How weather/terrain modifies move power (e.g. Fire 1.5x in sun, Water 0.5x).

**Hazards:**
- Entry hazards on each side: Stealth Rock, Spikes, Toxic Spikes, Sticky Web.
- Estimated hazard damage on each Pokemon if it switches in.

**Status Conditions:**
- Active status on each side's Pokemon (burn/paralysis/poison/bad poison/sleep/freeze/confusion).
- How each status affects performance (e.g. burn halves physical attack, paralysis 25% chance to skip turn).

**Stat Changes:**
- Current stat stage changes (+/-) for both active Pokemon.

**Residual Damage:**
- Ongoing damage sources: Leech Seed, Curse, weather chip, binding moves, etc.
- Rough estimate of HP lost per turn from residual effects.

**Turn-Sensitive Effects:**
- Trick Room, Tailwind, Reflect, Light Screen, Aurora Veil — active? How many turns remaining?
- Any one-time effects like Destiny Bond, Grudge, Beak Blast charging.

Be precise and factual. Do NOT suggest moves. Only report what is known."""


# ---------------------------------------------------------------------------
# Node 2 — Role Analysis
# ---------------------------------------------------------------------------

ROLE_SYSTEM = """\
You are an expert Pokemon battle team analyst. Identify the combat role of each \
Pokemon based on its stats, typing, moveset, and item.

For EACH active Pokemon and all benched Pokemon you can see, classify into one \
or more of these roles:

**Attacker Roles:**
- Physical Attacker (high Attack investment, physical moves)
- Special Attacker (high SpAtk investment, special moves)
- Mixed Attacker (uses both physical and special moves)
- Sweeper (has setup moves like Dragon Dance, Swords Dance, Quiver Dance, Nasty Plot)
- Wallbreaker (high power, meant to break through defensive Pokemon)

**Defensive Roles:**
- Physical Wall (high Def/HP, absorbs physical hits)
- Special Wall (high SpDef/HP, absorbs special hits)
- Mixed Wall (balanced defenses)
- Tank (decent offenses + good bulk, can attack while taking hits)
- Speed Control / Stopper (can paralyze, burn, or outspeed sweepers)

**Support Roles:**
- Screen Setter (Reflect/Light Screen/Aurora Veil)
- Hazard Setter (Stealth Rock/Spikes/Toxic Spikes/Sticky Web)
- Weather/Terrain Setter
- Pivot (U-turn/Volt Switch/Flip Turn for safe switching)
- Stall (Toxic/Will-O-Wisp + Protect/Substitute)

For each Pokemon, provide:
1. Its most likely role (primary)
2. A secondary role if applicable
3. Key moves that indicate this role
4. Whether this Pokemon is currently in a position to fulfill its role

Also flag any Pokemon that might be running an **unexpected/trick set** (role disruption) \
based on unusual moves or items.

Format your response as structured text with clear headers per Pokemon."""


# ---------------------------------------------------------------------------
# Node 3 — Matchup Assessment
# ---------------------------------------------------------------------------

MATCHUP_SYSTEM = """\
You are an expert Pokemon type-matchup analyst. Assess the current head-to-head \
matchup and overall team matchup.

**Current Active Matchup:**
- Type effectiveness: List our moves vs opponent's types (2x super effective, 1x neutral, 0.5x resisted, 0x immune).
- Opponent's moves vs our types (same analysis).
- STAB (Same Type Attack Bonus): Which of our moves get the 1.5x STAB bonus? Which of theirs do?
- Can we hit the opponent's weakness? Which moves exploit it?
- Can the opponent hit our weakness? Which of their moves exploit it?

**Immunity & Resistance:**
- Any type immunities from abilities (Levitate, Flash Fire, Lightning Rod, etc.)?
- Any type resistances from abilities (Thick Fat, Dry Skin, Water Absorb, etc.)?
- Any item-based resistances (Air Balloon, Occa Berry, etc.)?

**Team-Wide Matchup:**
- Do we have a counter (a benched Pokemon that can safely switch in and threaten the opponent)?
- Does the opponent have a counter to our active Pokemon waiting on their bench?
- **Sweep potential**: Do we have a Pokemon that, if it sets up, can sweep the opponent's \
  remaining team (consistency check)?
- **Type overlap weakness**: Do multiple Pokemon on our team share a common weakness?

**Switch Advantage:**
- If we switch, which benched Pokemon gains the best immediate matchup?
- If the opponent switches, what are they most likely to switch to?

Be specific about type names and move names. Use 2x, 0.5x, 0x notation."""


# ---------------------------------------------------------------------------
# Node 4 — Damage Evaluation
# ---------------------------------------------------------------------------

DAMAGE_SYSTEM = """\
You are an expert Pokemon damage calculator. Estimate damage ranges for the \
current matchup to inform tactical decisions.

For each available move our active Pokemon can use against the opponent's active Pokemon:

**Per-Move Analysis:**
- Base power after STAB (1.5x if same type as user)
- Type effectiveness multiplier (2x, 1x, 0.5x, 0x)
- Any relevant ability modifiers (e.g. Technician, Sheer Force, Adaptability, Huge Power)
- Any relevant item modifiers (e.g. Choice Band/Specs, Life Orb, Expert Belt)
- Weather/terrain modifier if applicable
- Estimated damage range as % of opponent's remaining HP (min 85% to max 100% of calculated damage)

**KO Assessment:**
- Can this move KO in one hit? (current HP <= max damage)
- Is it a guaranteed 2HKO? (2x min damage >= remaining HP)
- Is it a possible 2HKO with good roll? (2x max damage >= remaining HP, but 2x min damage < remaining HP)
- How many hits to KO (NHKO)?

**Survivability Check:**
- Can our Pokemon survive the opponent's strongest move?
- Are we in KO range from any of the opponent's moves?
- After hazards damage (if we switch out and back in later), can we still survive?

**Residual Kill:**
- If we chip the opponent now, will residual damage (burn, poison, Leech Seed, hazards, weather) \
  KO them within 1-2 turns?

Respond with a structured summary per move. Use approximate percentages. \
Prioritize identifying OHKO, guaranteed 2HKO, and whether we are in danger of being KO'd."""


# ---------------------------------------------------------------------------
# Node 5 — Tactical Plan Generation
# ---------------------------------------------------------------------------

TACTICAL_SYSTEM = """\
You are an expert Pokemon battle tactician. Based on the battlefield conditions, \
role analysis, matchup assessment, and damage evaluation, generate tactical plans \
organized by category.

Generate 2-3 candidate actions TOTAL, selecting from the most promising categories below. \
Each candidate must be realistic given the current state.

**Categories:**

1. **ATTACK** — Direct attack for maximum impact.
   - Best damage move (considering KO potential, STAB, type effectiveness).
   - Pick move to secure a KO if possible, or to chip for a future KO.
   - Consider: Is there a move that OHKOs? Is there a guaranteed 2HKO?

2. **SETUP / MOMENTUM** — Invest now for future payoff.
   - Stat-boosting moves (Dragon Dance, Swords Dance, Nasty Plot, Quiver Dance) \
     only if we can survive a hit or opponent is likely to switch.
   - Screen/hazard setting if safe.
   - Substituting on a predicted switch.

3. **SWITCH** — Bring in a better matchup.
   - Switch to a counter that walls the opponent and threatens back.
   - Pivot switch (U-turn/Volt Switch) for momentum.
   - Sac switch (let current Pokemon faint to bring in a sweeper safely) if \
     current Pokemon is heavily damaged and cannot contribute.
   - Consider hazard damage on the incoming Pokemon.

4. **MIND GAME** — Play around opponent's likely response.
   - Predict opponent will switch → hit the incoming Pokemon with a super-effective move.
   - Predict opponent will protect/set up → use that turn to set up ourselves.
   - Aggressive play (use a high-risk high-reward move when opponent expects defensive play).

For each candidate, provide:
- action: "move <move_name>" or "switch <pokemon_name>"
- category: one of [attack, setup, switch, mind_game]
- reason: 1-2 sentences explaining why
- risk: LOW / MEDIUM / HIGH
- reward: LOW / MEDIUM / HIGH

Format as JSON array:
[{"action": "...", "category": "...", "reason": "...", "risk": "...", "reward": "..."}]"""


# ---------------------------------------------------------------------------
# Node 6 — Opponent Prediction
# ---------------------------------------------------------------------------

PREDICT_SYSTEM = """\
You are an expert Pokemon battle mind-game analyst. Predict the opponent's most \
likely actions for each of our candidate plans.

For each candidate action we are considering, predict 3 opponent scenarios:

**Scenario A — Best Response (opponent plays optimally against us):**
- What would the opponent's best counter-play be?
- What move or switch would they choose?
- What is the worst outcome for us?

**Scenario B — Neutral Response (opponent continues their plan):**
- What would the opponent do if they ignore our action?
- E.g., they attack with their strongest move, or set up.
- What is the expected outcome?

**Scenario C — Passive Response (opponent switches or defends):**
- Opponent predicts our attack and switches to a counter.
- Opponent uses Protect to scout.
- What is the best outcome for us?

**Overall Assessment:**
- Which of our candidates has the best worst-case (minimax)?
- Which candidate is most robust against different opponent responses?
- Is there a candidate that is good regardless of what the opponent does?

Format as structured text, one section per candidate."""


# ---------------------------------------------------------------------------
# Node 7 — Plan Evaluation
# ---------------------------------------------------------------------------

EVALUATE_SYSTEM = """\
You are an expert Pokemon battle evaluator. Produce a final evaluation matrix \
for each tactical plan, incorporating the opponent prediction analysis.

For each candidate, score on these criteria (1-10 scale):

**Expected Utility (EU):**
- Weighted average outcome across opponent scenarios.
- Higher = better average result.

**Downside Risk (DR):**
- How bad is the worst-case scenario?
- Lower score = less risky (1 = very safe, 10 = very risky).

**Consistency (CON):**
- Does this move fit into a long-term winning strategy?
- Does it maintain or improve our win condition?
- Higher = more aligned with winning plan.

**Opportunity Cost (OC):**
- What do we give up by choosing this over alternatives?
- Lower score = less sacrifice (1 = nothing lost, 10 = passing up a great opportunity).

**Damage Efficiency (DE):**
- Are we getting good damage value? Or risking a "damage loss" (dealing insufficient damage)?
- Higher = better damage efficiency.

Then compute a **Composite Score**:
  Composite = EU*3 - DR*2 + CON*2 - OC*1 + DE*2

Output a ranked list with the composite score, and 1-sentence justification per candidate.

Format as JSON array (highest composite first):
[{"action": "...", "EU": N, "DR": N, "CON": N, "OC": N, "DE": N, "composite": N, "justification": "..."}]"""


# ---------------------------------------------------------------------------
# Node 8 — Final Action Selection
# ---------------------------------------------------------------------------

SELECT_SYSTEM = """\
You are the final decision-maker for a Pokemon battle AI. Based on all the \
analysis, tactical plans, opponent predictions, and evaluation scores, choose \
the single best action.

You MUST respond with ONLY a JSON object:
- To use a move: {"move": "<move_name>"}
- To switch Pokemon: {"switch": "<pokemon_name>"}

No other text. No explanation. Just the JSON object."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_llm(state: BattleDecisionState, node_name: str):
    node_llms = state.get("node_llms") or {}
    return node_llms.get(node_name, state["llm"])


def _call_llm(
    llm,
    system_prompt: str,
    user_prompt: str,
    config: RunnableConfig,
    track_fn=None,
    max_tokens=None,
) -> str:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    if max_tokens is not None:
        llm = llm.bind(max_tokens=max_tokens)
    resp = llm.invoke(messages, config=config)
    if track_fn:
        track_fn(resp)
    return resp.content


def _build_context(state: BattleDecisionState, *fields: str) -> str:
    parts: list[str] = []
    for field in fields:
        value = state.get(field)
        if value:
            label = field.replace("_", " ").title()
            if isinstance(value, list):
                parts.append(f"**{label}:**\n{json.dumps(value, ensure_ascii=False)}")
            else:
                parts.append(f"**{label}:**\n{value}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

def analyze_battlefield(state: BattleDecisionState, config: RunnableConfig) -> dict:
    analysis = _call_llm(
        _get_llm(state, "analyze_battlefield"),
        BATTLEFIELD_SYSTEM,
        state["user_prompt"],
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {"battlefield_report": analysis, "raw_outputs": raw + [analysis]}


def analyze_roles(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(state, "battlefield_report")
    user_prompt = f"{context}\n\n---\n\nBattle state:\n{state['user_prompt']}"
    analysis = _call_llm(
        _get_llm(state, "analyze_roles"),
        ROLE_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {"role_analysis": analysis, "raw_outputs": raw + [analysis]}


def assess_matchups(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(state, "battlefield_report", "role_analysis")
    user_prompt = f"{context}\n\n---\n\nBattle state:\n{state['user_prompt']}"
    analysis = _call_llm(
        _get_llm(state, "assess_matchups"),
        MATCHUP_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {"matchup_assessment": analysis, "raw_outputs": raw + [analysis]}


def evaluate_damage(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(
        state, "battlefield_report", "role_analysis", "matchup_assessment",
    )
    user_prompt = f"{context}\n\n---\n\nBattle state:\n{state['user_prompt']}"
    analysis = _call_llm(
        _get_llm(state, "evaluate_damage"),
        DAMAGE_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {"damage_evaluation": analysis, "raw_outputs": raw + [analysis]}


def generate_tactical_plans(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(
        state,
        "battlefield_report",
        "role_analysis",
        "matchup_assessment",
        "damage_evaluation",
    )
    user_prompt = f"{context}\n\n---\n\nAvailable actions:\n{state.get('actions', 'see battle state')}\n\nBattle state:\n{state['user_prompt']}"
    plans_text = _call_llm(
        _get_llm(state, "generate_tactical_plans"),
        TACTICAL_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])

    plans = plans_text
    try:
        start = plans_text.find("[")
        end = plans_text.rfind("]")
        if start != -1 and end != -1:
            plans = json.loads(plans_text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    return {
        "tactical_plans": plans,
        "candidate_moves": plans_text,
        "raw_outputs": raw + [plans_text],
    }


def predict_opponent(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(
        state,
        "battlefield_report",
        "role_analysis",
        "matchup_assessment",
        "damage_evaluation",
    )
    plans_str = (
        json.dumps(state["tactical_plans"], ensure_ascii=False)
        if isinstance(state.get("tactical_plans"), list)
        else str(state.get("tactical_plans", ""))
    )
    user_prompt = (
        f"{context}\n\n---\n\n"
        f"Our candidate plans:\n{plans_str}\n\n"
        f"Battle state:\n{state['user_prompt']}"
    )
    analysis = _call_llm(
        _get_llm(state, "predict_opponent"),
        PREDICT_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {"opponent_prediction": analysis, "raw_outputs": raw + [analysis]}


def evaluate_plans(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(
        state,
        "battlefield_report",
        "role_analysis",
        "matchup_assessment",
        "damage_evaluation",
    )
    plans_str = (
        json.dumps(state["tactical_plans"], ensure_ascii=False)
        if isinstance(state.get("tactical_plans"), list)
        else str(state.get("tactical_plans", ""))
    )
    user_prompt = (
        f"{context}\n\n---\n\n"
        f"Our candidate plans:\n{plans_str}\n\n"
        f"Opponent prediction:\n{state.get('opponent_prediction', '')}\n\n"
        f"Battle state:\n{state['user_prompt']}"
    )
    eval_text = _call_llm(
        _get_llm(state, "evaluate_plans"),
        EVALUATE_SYSTEM,
        user_prompt,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])
    return {
        "plan_evaluation": eval_text,
        "evaluation_notes": eval_text,
        "raw_outputs": raw + [eval_text],
    }


def select_action(state: BattleDecisionState, config: RunnableConfig) -> dict:
    context = _build_context(
        state,
        "battlefield_report",
        "role_analysis",
        "matchup_assessment",
        "damage_evaluation",
    )
    plans_str = (
        json.dumps(state["tactical_plans"], ensure_ascii=False)
        if isinstance(state.get("tactical_plans"), list)
        else str(state.get("tactical_plans", ""))
    )
    combined = (
        f"{context}\n\n---\n\n"
        f"Our candidate plans:\n{plans_str}\n\n"
        f"Opponent prediction:\n{state.get('opponent_prediction', '')}\n\n"
        f"Evaluation:\n{state.get('plan_evaluation', '')}\n\n"
        f"Battle state:\n{state['user_prompt']}"
    )
    action = _call_llm(
        _get_llm(state, "select_action"),
        SELECT_SYSTEM,
        combined,
        config,
        state.get("_track_tokens_fn"),
        max_tokens=state.get("max_tokens"),
    )
    raw = state.get("raw_outputs", [])

    needs_revision = True
    try:
        parsed = json.loads(action)
        if "move" in parsed or "switch" in parsed:
            needs_revision = False
    except json.JSONDecodeError:
        start = action.find("{")
        end = action.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                json.loads(action[start : end + 1])
                needs_revision = False
            except json.JSONDecodeError:
                pass

    return {
        "final_action": action,
        "raw_outputs": raw + [action],
        "needs_revision": needs_revision,
    }


def revise_decision(state: BattleDecisionState, config: RunnableConfig) -> dict:
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "needs_revision": False,
    }
