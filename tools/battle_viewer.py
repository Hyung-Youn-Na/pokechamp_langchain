#!/usr/bin/env python3
"""
Battle Replay + LLM Log Viewer Generator

Parses Pokemon battle HTML replays and run.log files from experiments,
matches LLM reasoning entries to battle turns, and generates enhanced
HTML viewer files with side-by-side replay + LLM reasoning display.

Also supports LangGraph ReAct agent logs (langgraph_llm_log.jsonl +
langgraph_tool_log.jsonl), rendering tool-use chains alongside battle state.

Usage:
    python tools/battle_viewer.py .temp/experiments/EXP-011-io-baseline-glm51
    python tools/battle_viewer.py .temp/experiments/EXP-011 --battle battle-gen9ou-310 --open
    python tools/battle_viewer.py .temp/experiments/EXP-021-react-glm51
"""

import argparse
import json
import os
import re
import sys
import webbrowser
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LLMEntry:
    """A single LLM call entry parsed from run.log or llm_log.jsonl."""

    battle_tag: str  # e.g. "battle-gen9ou-310"
    reasoning: str  # LLM reasoning text (before JSON action)
    action: dict  # {"move": "earthquake"} or {"switch": "toxapex"}
    thinking: str = ""  # === THINKING === block content (Ollama thinking mode)
    raw_message: str = ""  # Full raw message content
    system_prompt: str = ""  # System prompt (from llm_log.jsonl)
    user_prompt: str = ""  # User prompt / battle state (from llm_log.jsonl)


@dataclass
class TurnInfo:
    """Battle turn information parsed from HTML replay."""

    turn: int
    player_action: str  # e.g. "earthquake", "switch toxapex"
    player_action_type: str  # "move" or "switch"
    events: list = field(default_factory=list)  # Showdown protocol lines for this turn


@dataclass
class BattleData:
    """Combined data for a single battle."""

    battle_tag: str
    html_path: str
    winner: str = ""
    format: str = ""
    player_name: str = ""
    opponent_name: str = ""
    turns: list = field(default_factory=list)  # list[TurnInfo]
    llm_entries: list = field(default_factory=list)  # list[LLMEntry]
    matched_turns: list = field(default_factory=list)  # list[dict]


# ---------------------------------------------------------------------------
# LangGraph / ReAct data structures
# ---------------------------------------------------------------------------


@dataclass
class ToolCallInfo:
    """A single tool invocation within a ReAct step."""

    tool_name: str
    args: dict
    call_id: str = ""
    result: str = ""  # Result text (filled from tool_log)
    is_error: bool = False


@dataclass
class ReActStep:
    """A single LLM call within a ReAct turn (one 'step' in the chain)."""

    call_index: int  # llm_call_in_turn (1-based)
    reasoning: str  # LLM text response
    tool_calls: list = field(default_factory=list)  # list[ToolCallInfo]
    is_final: bool = False  # True if tool_calls is None (final decision)
    final_action: dict = field(default_factory=dict)  # Parsed final JSON action
    token_usage: dict = field(default_factory=dict)
    timestamp: str = ""
    duration_ms: float = 0.0


@dataclass
class ReActTurn:
    """All ReAct steps for a single battle turn."""

    turn: int
    battle_tag: str
    steps: list = field(default_factory=list)  # list[ReActStep]
    battle_state: str = ""  # Extracted battle state from first step's user_prompt
    historical_summary: str = ""  # Extracted historical turns from user_prompt
    system_prompt: str = ""


@dataclass
class LangGraphBattle:
    """Combined data for a single LangGraph ReAct battle."""

    battle_tag: str
    turns: list = field(default_factory=list)  # list[ReActTurn]
    tool_stats: dict = field(default_factory=dict)  # tool_name -> count
    total_llm_calls: int = 0
    total_tokens: dict = field(default_factory=dict)  # prompt/completion/total
    winner: str = ""
    player_name: str = ""
    opponent_name: str = ""


# ---------------------------------------------------------------------------
# run.log parser
# ---------------------------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BATTLE_TAG_RE = re.compile(r"All thinking sent to (battle-[\w]+-\d+)")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_RE.sub("", text)


def parse_run_log(log_path: str) -> dict[str, list[LLMEntry]]:
    """Parse run.log and return LLM entries grouped by battle_tag.

    Returns:
        dict mapping battle_tag -> list[LLMEntry] (in order)
    """
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    lines = [strip_ansi(line.rstrip("\n")) for line in raw_lines]

    entries_by_battle: dict[str, list[LLMEntry]] = defaultdict(list)

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect "Message content:" start of an LLM entry
        if line.startswith("Message content:"):
            entry_lines = [line]
            i += 1

            # Collect lines until we find "All thinking sent to battle-"
            battle_tag = ""
            while i < len(lines):
                current = lines[i]
                entry_lines.append(current)

                match = BATTLE_TAG_RE.search(current)
                if match:
                    battle_tag = match.group(1)
                    i += 1
                    break
                i += 1

            if battle_tag:
                entry = _parse_entry_block(entry_lines, battle_tag)
                if entry:
                    entries_by_battle[battle_tag].append(entry)
        else:
            i += 1

    return dict(entries_by_battle)


def _parse_entry_block(lines: list[str], battle_tag: str) -> Optional[LLMEntry]:
    """Parse a single LLM entry block (from Message content: to All thinking sent)."""
    full_text = "\n".join(lines)

    # Extract message content between first "Message content: " and "output:"
    # Use greedy match to handle content with embedded quotes
    msg_match = re.search(
        r'Message content: "(.+)"\noutput:', full_text, re.DOTALL
    )
    if not msg_match:
        # Try without opening quote (message may not be wrapped in quotes)
        msg_match = re.search(
            r"Message content: ?(.+?)\noutput:", full_text, re.DOTALL
        )

    if not msg_match:
        return None

    message_content = msg_match.group(1)
    # Strip trailing quote if the message was wrapped in quotes
    if message_content.endswith('"'):
        message_content = message_content[:-1]

    # Extract thinking block if present
    thinking = ""
    thinking_match = re.search(
        r"=== THINKING ===\n(.*?)\n={40}", full_text, re.DOTALL
    )
    if thinking_match:
        thinking = thinking_match.group(1).strip()

    # Extract output JSON (handle nested objects like {"move": "eq", "tera": {"type": "fire"}})
    output_json_str = ""
    output_match = re.search(r"output: (\{.+\})", full_text, re.DOTALL)
    if output_match:
        output_json_str = output_match.group(1)
        # Try parsing; if it fails, try finding the last complete JSON object
        try:
            action = json.loads(output_json_str)
        except json.JSONDecodeError:
            json_objects = _find_json_objects(output_json_str)
            if json_objects:
                for obj in reversed(json_objects):
                    try:
                        action = json.loads(obj)
                        output_json_str = obj
                        break
                    except json.JSONDecodeError:
                        continue
                else:
                    action = {"raw": output_json_str}
            else:
                action = {"raw": output_json_str}
    else:
        return None

    # Separate reasoning from the message content
    # The reasoning is everything before the JSON action in the message
    reasoning = _extract_reasoning(message_content)

    return LLMEntry(
        battle_tag=battle_tag,
        reasoning=reasoning,
        action=action,
        thinking=thinking,
        raw_message=message_content,
    )


def parse_llm_log_jsonl(jsonl_path: str) -> dict[str, list[LLMEntry]]:
    """Parse structured llm_log.jsonl (from _log_llm_call).

    Returns:
        dict mapping battle_tag -> list[LLMEntry] (in order)
    """
    entries_by_battle: dict[str, list[LLMEntry]] = defaultdict(list)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            battle_tag = entry.get("battle_tag", "")
            if not battle_tag:
                continue

            raw_response = entry.get("llm_response", "")
            reasoning = _extract_reasoning(raw_response)

            # Parse action from parsed_action (already JSON)
            action = {}
            parsed = entry.get("parsed_action", "")
            if parsed:
                try:
                    action = json.loads(parsed)
                except (json.JSONDecodeError, TypeError):
                    action = {"raw": parsed}

            llm_entry = LLMEntry(
                battle_tag=battle_tag,
                reasoning=reasoning,
                action=action,
                raw_message=raw_response,
                system_prompt=entry.get("system_prompt", ""),
                user_prompt=entry.get("user_prompt", ""),
            )
            entries_by_battle[battle_tag].append(llm_entry)

    return dict(entries_by_battle)


def _extract_reasoning(message_content: str) -> str:
    """Extract reasoning text from LLM message (everything before JSON action)."""
    # Find the last JSON object in the message using bracket-aware parsing
    json_objects = _find_json_objects(message_content)
    if json_objects:
        last_json = json_objects[-1]
        json_start = message_content.rfind(last_json)
        reasoning = message_content[:json_start].strip()
    else:
        reasoning = message_content.strip()

    # Clean up: remove trailing quotes, newlines
    reasoning = reasoning.rstrip('"').strip()

    return reasoning


# ---------------------------------------------------------------------------
# LangGraph ReAct parser
# ---------------------------------------------------------------------------


def parse_langgraph_logs(
    llm_log_path: str, tool_log_path: Optional[str] = None
) -> dict[str, LangGraphBattle]:
    """Parse langgraph_llm_log.jsonl and optionally langgraph_tool_log.jsonl.

    Returns:
        dict mapping battle_tag -> LangGraphBattle
    """
    # --- 1. Parse tool log (index by battle_tag + turn + tool name) ---
    tool_results: dict[str, list[dict]] = defaultdict(list)  # key -> list of results
    tool_stats: dict[str, Counter] = defaultdict(Counter)  # battle_tag -> Counter

    if tool_log_path and os.path.exists(tool_log_path):
        with open(tool_log_path, "r", encoding="utf-8") as f:
            tool_entries = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    tool_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # Pair tool_call + tool_result entries
        i = 0
        while i < len(tool_entries):
            entry = tool_entries[i]
            btag = entry.get("battle_tag", "")
            turn = entry.get("turn", 0)
            key = f"{btag}|{turn}"

            if "tool_call" in entry:
                tool_stats[btag][entry["tool_call"]["tool"]] += 1
                call_info = {
                    "tool": entry["tool_call"]["tool"],
                    "input": entry["tool_call"].get("input", ""),
                }
                # Next entry should be the result
                result_text = ""
                is_error = False
                if i + 1 < len(tool_entries) and "tool_result" in tool_entries[i + 1]:
                    result_text = tool_entries[i + 1].get("tool_result", "")
                    if isinstance(result_text, str):
                        try:
                            parsed = json.loads(result_text)
                            is_error = "error" in parsed
                        except json.JSONDecodeError:
                            pass
                    i += 1  # Skip the result entry
                call_info["result"] = result_text
                call_info["is_error"] = is_error
                tool_results[key].append(call_info)
            i += 1

    # --- 2. Parse LLM log ---
    # Group entries by (battle_tag, turn)
    raw_entries: dict[tuple[str, int], list[dict]] = defaultdict(list)
    total_tokens: dict[str, dict] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

    with open(llm_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            btag = entry.get("battle_tag", "")
            turn = entry.get("turn", 0)
            if not btag:
                continue
            raw_entries[(btag, turn)].append(entry)

            # Accumulate tokens
            tu = entry.get("token_usage", {})
            bt = total_tokens[btag]
            bt["prompt_tokens"] += tu.get("prompt_tokens", 0)
            bt["completion_tokens"] += tu.get("completion_tokens", 0)
            bt["total_tokens"] += tu.get("total_tokens", 0)

    # --- 3. Build LangGraphBattle objects ---
    battles: dict[str, LangGraphBattle] = {}

    for (btag, turn), entries in sorted(raw_entries.items()):
        if btag not in battles:
            battles[btag] = LangGraphBattle(
                battle_tag=btag,
                tool_stats=dict(tool_stats.get(btag, {})),
                total_tokens=total_tokens[btag],
            )

        battle = battles[btag]
        react_turn = ReActTurn(turn=turn, battle_tag=btag)

        # Sort entries by llm_call_in_turn
        entries.sort(key=lambda e: e.get("llm_call_in_turn", 0))

        # Tool result iterator for this turn
        tool_key = f"{btag}|{turn}"
        turn_tool_results = list(tool_results.get(tool_key, []))
        tool_result_idx = 0

        for entry in entries:
            call_idx = entry.get("llm_call_in_turn", 0)
            raw_response = entry.get("llm_response", "")
            tool_calls_raw = entry.get("tool_calls")  # list or None
            is_final = tool_calls_raw is None
            timestamp = entry.get("timestamp", "")
            start_time = entry.get("start_time", "")
            duration_ms = 0.0
            if start_time and timestamp:
                try:
                    from datetime import datetime

                    t0 = datetime.fromisoformat(start_time)
                    t1 = datetime.fromisoformat(timestamp)
                    duration_ms = (t1 - t0).total_seconds() * 1000
                except (ValueError, TypeError):
                    pass

            # Extract first step's battle state
            if call_idx == 1:
                user_prompt = entry.get("user_prompt", "")
                react_turn.battle_state = _extract_battle_state(user_prompt)
                react_turn.historical_summary = _extract_historical_turns(user_prompt)
                react_turn.system_prompt = entry.get("system_prompt", "")

            # Build tool calls
            tool_calls = []
            if tool_calls_raw:
                for tc in tool_calls_raw:
                    tc_info = ToolCallInfo(
                        tool_name=tc.get("name", ""),
                        args=tc.get("args", {}),
                        call_id=tc.get("id", ""),
                    )
                    # Match with tool_results by tool name
                    if tool_result_idx < len(turn_tool_results):
                        tr = turn_tool_results[tool_result_idx]
                        if (
                            tr["tool"] == tc_info.tool_name
                            or not tr.get("tool")
                        ):
                            tc_info.result = tr.get("result", "")
                            tc_info.is_error = tr.get("is_error", False)
                            tool_result_idx += 1
                    tool_calls.append(tc_info)

            # Parse final action
            final_action = {}
            if is_final:
                final_action = _extract_final_action(raw_response)

            step = ReActStep(
                call_index=call_idx,
                reasoning=raw_response,
                tool_calls=tool_calls,
                is_final=is_final,
                final_action=final_action,
                token_usage=entry.get("token_usage", {}),
                timestamp=timestamp,
                duration_ms=duration_ms,
            )
            react_turn.steps.append(step)

        battle.turns.append(react_turn)
        battle.total_llm_calls += len(react_turn.steps)

    return battles


def _extract_battle_state(user_prompt: str) -> str:
    """Extract the 'Current battle state:' section from user_prompt."""
    # Try to find "Turn N: Current battle state:" section with flexible end marker
    match = re.search(
        r"Turn \d+: (Current battle state:.+?)(?:\n\n(?:Your current pokemon|Choose|Available)|$)",
        user_prompt,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # Fallback 1: find "Current battle state:" with "Choose only from" end marker
    match = re.search(
        r"(Current battle state:.+?)(?:Choose only from|$)", user_prompt, re.DOTALL
    )
    if match:
        return match.group(1).strip()

    # Fallback 2: find "Current battle state:" to end of substantial content
    match = re.search(
        r"(Current battle state:.{50,})", user_prompt, re.DOTALL
    )
    if match:
        return match.group(1).strip()

    return ""


def _extract_historical_turns(user_prompt: str) -> str:
    """Extract the 'Historical turns:' section from user_prompt."""
    # Primary pattern: "Historical turns:" to "Turn N: Current battle state:"
    match = re.search(
        r"Historical turns:\n(.+?)(?:Turn \d+: Current battle state:|$)",
        user_prompt,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # Fallback: "Historical turns:" to next double-newline section break
    match = re.search(
        r"Historical turns:\n(.+?)(?:\n{3,}|$)",
        user_prompt,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    return ""


def _extract_final_action(response: str) -> dict:
    """Extract the final JSON action from LLM response."""
    # Try to find JSON in code block first (handle nested objects)
    code_block_match = re.search(r"```(?:json)?\s*(\{.+\})\s*```", response, re.DOTALL)
    if code_block_match:
        json_objects = _find_json_objects(code_block_match.group(1))
        for obj in reversed(json_objects):
            try:
                return json.loads(obj)
            except json.JSONDecodeError:
                continue

    # Try last JSON object in response using bracket-aware parsing
    json_objects = _find_json_objects(response)
    if json_objects:
        for obj in reversed(json_objects):
            try:
                return json.loads(obj)
            except json.JSONDecodeError:
                continue

    # Fallback: try to find any key-value patterns
    for pattern in [
        r'"move"\s*:\s*"([^"]+)"',
        r'"switch"\s*:\s*"([^"]+)"',
    ]:
        match = re.search(pattern, response)
        if match:
            if '"move"' in pattern:
                return {"move": match.group(1)}
            elif '"switch"' in pattern:
                return {"switch": match.group(1)}

    return {}


# ---------------------------------------------------------------------------
# HTML replay parser
# ---------------------------------------------------------------------------


def parse_html_replay(
    html_path: str, llm_player_name: str = ""
) -> tuple[list[TurnInfo], str, str, str]:
    """Parse an HTML replay file.

    Args:
        html_path: Path to HTML replay file
        llm_player_name: Username of the LLM player (to determine p1/p2)

    Returns:
        (turns, winner, llm_player_name, opponent_name)
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Extract battle-log-data
    data_match = re.search(
        r'<script type="text/plain" class="battle-log-data">(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    if not data_match:
        return [], "", "", ""

    log_data = data_match.group(1)
    lines = log_data.strip().split("\n")

    # Extract player names and determine which is the LLM player
    p1_name = ""
    p2_name = ""
    for line in lines:
        if line.startswith("|player|p1|"):
            parts = line.split("|")
            if len(parts) >= 4:
                p1_name = parts[3]
        elif line.startswith("|player|p2|"):
            parts = line.split("|")
            if len(parts) >= 4:
                p2_name = parts[3]

    # Determine LLM player number (p1 or p2)
    llm_player_num = ""
    if llm_player_name:
        if llm_player_name == p1_name:
            llm_player_num = "p1"
        elif llm_player_name == p2_name:
            llm_player_num = "p2"
    if not llm_player_num:
        # Default: try to match by username prefix "pokechamp"
        if "pokechamp" in p1_name.lower():
            llm_player_num = "p1"
        elif "pokechamp" in p2_name.lower():
            llm_player_num = "p2"
        else:
            llm_player_num = "p1"  # Fallback

    llm_name = p1_name if llm_player_num == "p1" else p2_name
    opponent_name = p2_name if llm_player_num == "p1" else p1_name
    llm_team = llm_player_num  # "p1" or "p2"
    opponent_team = "p2" if llm_team == "p1" else "p1"

    # Extract winner (from |win| or infer from last |faint|)
    winner = ""
    for line in lines:
        if line.startswith("|win|"):
            winner = line.split("|")[2]

    if not winner:
        # Infer from last faint: if opponent's last mon faints, LLM player wins
        last_faint = ""
        for line in reversed(lines):
            if line.startswith("|faint|"):
                last_faint = line
                break
        if last_faint:
            parts = last_faint.split("|")
            if len(parts) >= 3:
                faint_pos = parts[2]  # e.g. "p1a: Garganacl" or "p2a: Blissey"
                faint_team = faint_pos[:2]  # "p1" or "p2"
                if faint_team == opponent_team:
                    winner = llm_name
                elif faint_team == llm_team:
                    winner = opponent_name

    # Parse turns
    turns = []
    current_turn = None
    current_events = []

    for line in lines:
        if line.startswith("|turn|"):
            # Save previous turn
            if current_turn is not None:
                turns.append(
                    _build_turn_info(current_turn, current_events, llm_player_num)
                )
            current_turn = int(line.split("|")[2])
            current_events = [line]
        elif current_turn is not None:
            current_events.append(line)

    # Save last turn
    if current_turn is not None:
        turns.append(_build_turn_info(current_turn, current_events, llm_player_num))

    return turns, winner, llm_name, opponent_name


def _build_turn_info(
    turn: int, events: list[str], player_num: str
) -> TurnInfo:
    """Build TurnInfo from raw events for a turn.

    Args:
        player_num: "p1" or "p2" — which player is the LLM player
    """
    player_action = ""
    player_action_type = ""

    move_prefix = f"{player_num}a:"  # e.g. "p1a:"
    switch_prefix = f"{player_num}a:"  # e.g. "p1a:" (switches also use pNa: format)

    for event in events:
        parts = event.split("|")
        if len(parts) < 3:
            continue

        cmd = parts[1]

        # Once we have a player action, stop looking (ignore replacement
        # switches after faints, Sleep Talk sub-moves, etc.)
        if player_action:
            break

        # Look for LLM player's moves/switches
        if cmd == "move" and move_prefix in parts[2]:
            move_name = parts[3] if len(parts) > 3 else ""
            player_action = move_name.lower().replace(" ", "").replace("-", "")
            player_action_type = "move"
        elif cmd == "switch" and switch_prefix in parts[2]:
            # |switch|pNa: Name|Species, details|HP
            pokemon_detail = parts[3] if len(parts) > 3 else ""
            # Extract species name (before comma)
            species = (
                pokemon_detail.split(",")[0].strip().lower().replace(" ", "").replace("-", "")
            )
            player_action = f"switch {species}"
            player_action_type = "switch"
        elif cmd == "drag" and switch_prefix in parts[2]:
            pokemon_detail = parts[3] if len(parts) > 3 else ""
            species = (
                pokemon_detail.split(",")[0].strip().lower().replace(" ", "").replace("-", "")
            )
            player_action = f"drag {species}"
            player_action_type = "switch"

    # Filter events to only show meaningful ones (not raw protocol noise)
    display_events = []
    for event in events:
        if event.startswith("|turn|") or event.startswith("|upkeep|"):
            continue
        if event.startswith("|j|") or event.startswith("|l|"):
            continue
        display_events.append(event)

    return TurnInfo(
        turn=turn,
        player_action=player_action,
        player_action_type=player_action_type,
        events=display_events,
    )


# ---------------------------------------------------------------------------
# Turn matching
# ---------------------------------------------------------------------------


def match_entries_to_turns(
    turns: list[TurnInfo], entries: list[LLMEntry]
) -> list[dict]:
    """Match LLM entries to battle turns using action verification.

    Uses a global walk-through approach: process entries one by one,
    advancing the turn pointer when an entry matches the current turn's
    expected action. Unmatched entries between matches are retries.

    Returns list of dicts:
        {
            "turn": int,
            "reasoning": str,
            "action": dict,
            "thinking": str,
            "retries": [{"reasoning": ..., "action": ...}, ...],
            "events": [str, ...],
            "matched": bool,
        }
    """
    # Initialize result for each turn
    matched = []
    for turn_info in turns:
        matched.append(
            {
                "turn": turn_info.turn,
                "reasoning": "",
                "action": {},
                "thinking": "",
                "system_prompt": "",
                "user_prompt": "",
                "retries": [],
                "events": turn_info.events,
                "matched": False,
            }
        )

    if not turns or not entries:
        return matched

    # Global walk: assign each entry to the current turn.
    # When an entry matches the current turn's action, mark it as accepted
    # and advance to the next turn. Otherwise, mark it as a retry.
    turn_idx = 0
    for entry in entries:
        if turn_idx >= len(turns):
            # Extra entries after all turns — append to last turn as retries
            matched[-1]["retries"].append(
                {"reasoning": entry.reasoning, "action": entry.action}
            )
            continue

        turn_info = turns[turn_idx]

        if _action_matches(entry.action, turn_info):
            # This entry matches the current turn — accept it
            matched[turn_idx]["reasoning"] = entry.reasoning
            matched[turn_idx]["action"] = entry.action
            matched[turn_idx]["thinking"] = entry.thinking
            matched[turn_idx]["system_prompt"] = entry.system_prompt
            matched[turn_idx]["user_prompt"] = entry.user_prompt
            matched[turn_idx]["matched"] = True
            turn_idx += 1
        else:
            # This entry doesn't match — it's a retry for the current turn
            # But first, check if it matches a FUTURE turn (skip unmatched turns).
            # NOTE: Only looks ahead up to 3 turns. Entries matching 4+ turns ahead
            # will be treated as retries for the current turn.
            future_match = False
            for ahead in range(turn_idx + 1, min(turn_idx + 4, len(turns))):
                if _action_matches(entry.action, turns[ahead]):
                    future_match = True
                    break

            if future_match:
                # This entry actually belongs to a future turn.
                # The current turn had no LLM entry (opponent forced switch, etc.)
                # Add as retry to current turn and let future matching handle it
                matched[turn_idx]["retries"].append(
                    {"reasoning": entry.reasoning, "action": entry.action}
                )
            else:
                # Likely a genuine retry for the current turn
                matched[turn_idx]["retries"].append(
                    {"reasoning": entry.reasoning, "action": entry.action}
                )

    return matched


def _action_matches(action: dict, turn_info: TurnInfo) -> bool:
    """Check if an LLM action matches the actual player action in a turn."""
    if not turn_info.player_action:
        return True  # No player_action recorded (forced switch, post-faint, etc.) — assume match

    if turn_info.player_action_type == "move":
        for key in ["move", "dynamax", "terastallize"]:
            if key in action:
                move_id = action[key].lower().replace(" ", "").replace("-", "")
                expected = turn_info.player_action.lower().replace("-", "")
                return move_id == expected
    elif turn_info.player_action_type in ("switch", "drag"):
        if "switch" in action:
            switch_target = action["switch"].lower().replace(" ", "").replace("-", "")
            expected = turn_info.player_action.lower().replace("-", "")
            # Extract species from "switch speciesname"
            species = expected.replace("switch ", "").replace("drag ", "")
            return species in switch_target or switch_target in species

    return False


# ---------------------------------------------------------------------------
# HTML generator
# ---------------------------------------------------------------------------

VIEWER_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; }
  .header { background: #16213e; padding: 12px 20px; border-bottom: 2px solid #0f3460; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .header h1 { font-size: 16px; color: #e94560; }
  .header .meta { font-size: 13px; color: #a0a0b0; }
  .header .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
  .badge-win { background: #27ae60; color: #fff; }
  .badge-loss { background: #e74c3c; color: #fff; }
  .badge-tie { background: #f39c12; color: #fff; }
  .container { display: flex; height: calc(100vh - 48px); }
  .replay-panel { width: 55%; min-width: 400px; border-right: 1px solid #0f3460; overflow: auto; position: relative; }
  .replay-panel iframe { width: 100%; height: 100%; border: none; }
  .log-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .turn-nav { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 12px; background: #16213e; border-bottom: 1px solid #0f3460; max-height: 120px; overflow-y: auto; scrollbar-width: thin; }
  .turn-btn { padding: 3px 8px; border: 1px solid #333; border-radius: 4px; background: #1a1a2e; color: #a0a0b0; cursor: pointer; font-size: 12px; transition: all 0.15s; }
  .turn-btn:hover { background: #0f3460; color: #fff; }
  .turn-btn.active { background: #e94560; color: #fff; border-color: #e94560; }
  .turn-btn.has-retry { border-color: #f39c12; }
  .turn-btn.unmatched { border-color: #555; opacity: 0.5; }
  .log-scroll { flex: 1; overflow-y: auto; padding: 12px; }
  .turn-card { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
  .turn-card-header { padding: 8px 12px; background: #0f3460; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
  .turn-card-header h3 { font-size: 14px; color: #e94560; }
  .turn-card-header .action-tag { font-size: 12px; color: #fff; background: #27ae60; padding: 2px 8px; border-radius: 4px; }
  .turn-card-header .action-tag.switch { background: #3498db; }
  .turn-card-body { padding: 12px; }
  .reasoning { font-size: 13px; line-height: 1.6; color: #c0c0d0; white-space: pre-wrap; margin-bottom: 8px; }
  .thinking-block { background: #1a1a2e; border-left: 3px solid #f39c12; padding: 8px 12px; margin-bottom: 8px; font-size: 12px; color: #d4a017; white-space: pre-wrap; }
  .retry-section { margin-top: 8px; border-top: 1px dashed #333; padding-top: 8px; }
  .retry-label { font-size: 11px; color: #f39c12; margin-bottom: 4px; }
  .retry-item { background: #1a1a2e; padding: 6px 10px; border-radius: 4px; margin-bottom: 4px; font-size: 12px; color: #a0a0b0; }
  .events-section { margin-top: 8px; border-top: 1px dashed #333; padding-top: 8px; }
  .events-label { font-size: 11px; color: #7f8c8d; margin-bottom: 4px; }
  .event-line { font-size: 11px; color: #666; font-family: monospace; padding: 1px 0; }
  .prompt-section { margin-top: 8px; border-top: 1px dashed #333; padding-top: 8px; }
  .prompt-label { font-size: 11px; color: #3498db; margin-bottom: 4px; cursor: pointer; }
  .prompt-content { font-size: 11px; color: #888; font-family: monospace; white-space: pre-wrap; max-height: 300px; overflow-y: auto; background: #111; padding: 6px 8px; border-radius: 4px; display: none; margin-top: 4px; }
  .prompt-content.expanded { display: block; }
  .no-data { text-align: center; padding: 40px; color: #555; font-style: italic; }
  @media (max-width: 900px) {
    .container { flex-direction: column; height: auto; }
    .replay-panel { width: 100%; height: 50vh; min-width: auto; border-right: none; border-bottom: 1px solid #0f3460; }
    .log-panel { height: 50vh; }
  }
</style>
"""

INDEX_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1 { color: #e94560; margin-bottom: 8px; font-size: 22px; }
  .summary { color: #a0a0b0; font-size: 14px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 12px; background: #0f3460; color: #e94560; font-size: 13px; border-bottom: 2px solid #e94560; }
  td { padding: 8px 12px; border-bottom: 1px solid #1a1a2e; font-size: 13px; }
  tr:hover td { background: #16213e; }
  a { color: #3498db; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-win { background: #27ae60; color: #fff; }
  .badge-loss { background: #e74c3c; color: #fff; }
  .badge-tie { background: #f39c12; color: #fff; }
  .back-link { margin-bottom: 16px; display: inline-block; }
</style>
"""


def generate_battle_viewer(
    battle: BattleData, output_dir: str, replay_relative_path: str
) -> str:
    """Generate the combined viewer HTML for a single battle."""
    output_path = os.path.join(output_dir, f"{battle.battle_tag}.html")

    # Build turn data as JSON
    # NOTE: This JSON is currently NOT inserted into a <script> tag context.
    # If this changes in the future, ensure </script> is escaped to <\/script>
    # to prevent XSS via LLM-generated content containing script-closing tags.
    turn_data_json = json.dumps(battle.matched_turns, ensure_ascii=False)

    # Build turn navigation buttons
    turn_buttons = ""
    for t in battle.matched_turns:
        classes = ["turn-btn"]
        if not t["matched"]:
            classes.append("unmatched")
        if t.get("retries"):
            classes.append("has-retry")
        cls = " ".join(classes)
        turn_buttons += f'<button class="{cls}" data-turn="{t["turn"]}">{t["turn"]}</button>\n'

    # Build turn cards
    turn_cards = ""
    for t in battle.matched_turns:
        # Action tag
        action_str = ""
        if "move" in t.get("action", {}):
            action_str = t["action"]["move"]
        elif "switch" in t.get("action", {}):
            action_str = f"→ {t['action']['switch']}"
        elif t.get("action"):
            action_str = json.dumps(t["action"])

        action_cls = "switch" if "switch" in t.get("action", {}) else ""

        # Thinking block
        thinking_html = ""
        if t.get("thinking"):
            thinking_html = (
                f'<div class="thinking-block">{_html_escape(t["thinking"])}</div>'
            )

        # Retry section
        retry_html = ""
        if t.get("retries"):
            retry_items = ""
            for r in t["retries"]:
                retry_items += f'<div class="retry-item">{_html_escape(r.get("reasoning", ""))} → <code>{json.dumps(r.get("action", {}))}</code></div>'
            retry_html = f"""
            <div class="retry-section">
              <div class="retry-label">⚠ Retries ({len(t["retries"])})</div>
              {retry_items}
            </div>"""

        # Events section
        events_html = ""
        if t.get("events"):
            event_lines = ""
            for e in t["events"][:50]:  # Limit to 50 events per turn
                event_lines += f'<div class="event-line">{_html_escape(e)}</div>'
            extra = ""
            if len(t["events"]) > 50:
                extra = f'<div class="event-line">... and {len(t["events"]) - 20} more</div>'
            events_html = f"""
            <div class="events-section">
              <div class="events-label">Battle Events</div>
              {event_lines}{extra}
            </div>"""

        # Prompt section (only if system_prompt or user_prompt is available)
        prompt_html = ""
        if t.get("system_prompt") or t.get("user_prompt"):
            prompt_sections = ""
            if t.get("system_prompt"):
                prompt_sections += f"""<div style="margin-bottom:6px">
                  <div class="prompt-label" onclick="togglePrompt(this)">▶ System Prompt</div>
                  <div class="prompt-content">{_html_escape(t['system_prompt'])}</div>
                </div>"""
            if t.get("user_prompt"):
                prompt_sections += f"""<div>
                  <div class="prompt-label" onclick="togglePrompt(this)">▶ User Prompt (Battle State)</div>
                  <div class="prompt-content">{_html_escape(t['user_prompt'])}</div>
                </div>"""
            prompt_html = f"""
            <div class="prompt-section">
              {prompt_sections}
            </div>"""

        reasoning_html = (
            f'<div class="reasoning">{_html_escape(t.get("reasoning", ""))}</div>'
            if t.get("reasoning")
            else '<div class="reasoning" style="color:#555;font-style:italic">No reasoning captured</div>'
        )

        turn_cards += f"""
        <div class="turn-card" id="turn-{t['turn']}">
          <div class="turn-card-header" onclick="toggleCard(this)">
            <h3>Turn {t["turn"]}</h3>
            <span class="action-tag {action_cls}">{_html_escape(action_str)}</span>
          </div>
          <div class="turn-card-body">
            {thinking_html}
            {reasoning_html}
            {retry_html}
            {events_html}
            {prompt_html}
          </div>
        </div>"""

    # Winner badge
    winner_badge = ""
    if battle.winner:
        is_win = battle.winner == battle.player_name
        is_loss = battle.winner == battle.opponent_name
        if is_win:
            winner_badge = f'<span class="badge badge-win">WIN</span>'
        elif is_loss:
            winner_badge = f'<span class="badge badge-loss">LOSS</span>'
        else:
            winner_badge = f'<span class="badge badge-tie">{_html_escape(battle.winner)}</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{battle.battle_tag} — Battle Viewer</title>
  {VIEWER_CSS}
</head>
<body>
  <div class="header">
    <h1>{battle.battle_tag}</h1>
    <span class="meta">{_html_escape(battle.player_name)} vs {_html_escape(battle.opponent_name)}</span>
    {winner_badge}
    <span class="meta">{len(battle.turns)} turns · {len(battle.llm_entries)} LLM calls</span>
    <a href="index.html" style="color:#3498db;font-size:12px;margin-left:auto;">← All Battles</a>
  </div>
  <div class="container">
    <div class="replay-panel">
      <iframe src="{replay_relative_path}"></iframe>
    </div>
    <div class="log-panel">
      <div class="turn-nav">
        {turn_buttons}
      </div>
      <div class="log-scroll" id="logScroll">
        {turn_cards}
      </div>
    </div>
  </div>
  <script>
    // Turn navigation
    document.querySelectorAll('.turn-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const turn = btn.dataset.turn;
        const card = document.getElementById('turn-' + turn);
        if (card) {{
          card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          // Highlight active button
          document.querySelectorAll('.turn-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
        }}
      }});
    }});

    // Toggle card body
    function toggleCard(header) {{
      const body = header.nextElementSibling;
      if (body.style.display === 'none') {{
        body.style.display = 'block';
      }} else {{
        body.style.display = 'none';
      }}
    }}

    // Toggle prompt section
    function togglePrompt(label) {{
      const content = label.nextElementSibling;
      content.classList.toggle('expanded');
      label.textContent = content.classList.contains('expanded')
        ? label.textContent.replace('▶', '▼')
        : label.textContent.replace('▼', '▶');
    }}

    // Keyboard navigation
    document.addEventListener('keydown', (e) => {{
      const buttons = [...document.querySelectorAll('.turn-btn')];
      const activeIdx = buttons.findIndex(b => b.classList.contains('active'));
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
        e.preventDefault();
        const next = Math.min(activeIdx + 1, buttons.length - 1);
        buttons[next]?.click();
      }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
        e.preventDefault();
        const prev = Math.max(activeIdx - 1, 0);
        buttons[prev]?.click();
      }}
    }});
  </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_index(
    battles: list[BattleData],
    output_dir: str,
    experiment_name: str,
    model_info: str = "",
) -> str:
    """Generate the index.html with all battles listed."""
    output_path = os.path.join(output_dir, "index.html")

    # Compute stats
    wins = sum(1 for b in battles if b.winner == b.player_name)
    losses = sum(1 for b in battles if b.winner == b.opponent_name)
    ties = len(battles) - wins - losses

    # Build table rows
    rows = ""
    for b in sorted(battles, key=lambda x: x.battle_tag):
        is_win = b.winner == b.player_name
        is_loss = b.winner == b.opponent_name
        if is_win:
            result = '<span class="badge badge-win">WIN</span>'
        elif is_loss:
            result = '<span class="badge badge-loss">LOSS</span>'
        elif b.winner:
            result = f'<span class="badge badge-tie">{_html_escape(b.winner)}</span>'
        else:
            result = '<span class="badge badge-tie">?</span>'

        llm_count = len(b.llm_entries)
        turn_count = len(b.turns)
        retry_count = max(0, llm_count - turn_count)

        rows += f"""
        <tr>
          <td><a href="{b.battle_tag}.html">{b.battle_tag}</a></td>
          <td>{turn_count}</td>
          <td>{llm_count} ({retry_count} retries)</td>
          <td>{result}</td>
          <td>{_html_escape(b.opponent_name)}</td>
        </tr>"""

    win_rate = f"{wins/len(battles)*100:.1f}" if battles else "0"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_html_escape(experiment_name)} — Battle Viewer</title>
  {INDEX_CSS}
</head>
<body>
  <h1>{_html_escape(experiment_name)}</h1>
  <div class="summary">
    {_html_escape(model_info)} |
    {len(battles)} battles: {wins}W / {losses}L / {ties}T ({win_rate}%)
  </div>
  <table>
    <thead>
      <tr>
        <th>Battle</th>
        <th>Turns</th>
        <th>LLM Calls</th>
        <th>Result</th>
        <th>Opponent</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _find_json_objects(text: str) -> list[str]:
    """Find all top-level JSON object strings in text, handling nesting.

    Uses bracket counting instead of simple regex to correctly handle
    nested objects like {"move": "earthquake", "tera": {"type": "fire"}}.
    """
    results = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape_next = False
            while i < len(text):
                ch = text[i]
                if escape_next:
                    escape_next = False
                elif ch == '\\' and in_string:
                    escape_next = True
                elif ch == '"' and not escape_next:
                    in_string = not in_string
                elif not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            results.append(text[start:i + 1])
                            break
                i += 1
        i += 1
    return results


# ---------------------------------------------------------------------------
# LangGraph ReAct viewer HTML generator
# ---------------------------------------------------------------------------

REACT_VIEWER_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; }
  .header { background: #16213e; padding: 12px 20px; border-bottom: 2px solid #0f3460; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .header h1 { font-size: 16px; color: #e94560; }
  .header .meta { font-size: 13px; color: #a0a0b0; }
  .header .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
  .badge-win { background: #27ae60; color: #fff; }
  .badge-loss { background: #e74c3c; color: #fff; }
  .badge-tie { background: #f39c12; color: #fff; }
  .container { display: flex; height: calc(100vh - 48px); }
  .battle-panel { width: 45%; min-width: 350px; border-right: 1px solid #0f3460; overflow-y: auto; padding: 12px; }
  .replay-panel { width: 55%; min-width: 400px; border-right: 1px solid #0f3460; overflow: auto; position: relative; }
  .replay-panel iframe { width: 100%; height: 100%; border: none; }
  .agent-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .turn-nav { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 12px; background: #16213e; border-bottom: 1px solid #0f3460; max-height: 120px; overflow-y: auto; scrollbar-width: thin; }
  .turn-btn { padding: 3px 8px; border: 1px solid #333; border-radius: 4px; background: #1a1a2e; color: #a0a0b0; cursor: pointer; font-size: 12px; transition: all 0.15s; }
  .turn-btn:hover { background: #0f3460; color: #fff; }
  .turn-btn.active { background: #e94560; color: #fff; border-color: #e94560; }
  .turn-btn.has-tools { border-color: #3498db; }
  .turn-btn.has-error { border-color: #e74c3c; }
  .agent-scroll { flex: 1; overflow-y: auto; padding: 12px; }

  /* Battle state panel */
  .battle-section { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
  .battle-section-header { padding: 8px 12px; background: #0f3460; display: flex; justify-content: space-between; align-items: center; }
  .battle-section-header h3 { font-size: 14px; color: #e94560; }
  .battle-section-body { padding: 12px; font-size: 12px; line-height: 1.6; color: #c0c0d0; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }

  /* Agent step cards */
  .step-card { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; margin-bottom: 8px; overflow: hidden; }
  .step-card.final { border-color: #27ae60; }
  .step-card-header { padding: 6px 12px; background: #1a1a2e; display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
  .step-card-header .step-num { color: #e94560; font-weight: 600; }
  .step-card-header .step-time { color: #666; font-size: 11px; }
  .step-card-header .step-tokens { color: #f39c12; font-size: 11px; }
  .step-card-body { padding: 10px 12px; }

  .reasoning-text { font-size: 12px; line-height: 1.6; color: #c0c0d0; white-space: pre-wrap; margin-bottom: 8px; }

  /* Tool calls */
  .tool-section { margin-top: 6px; }
  .tool-call { background: #1a1a2e; border-left: 3px solid #3498db; padding: 6px 10px; margin-bottom: 4px; border-radius: 0 4px 4px 0; font-size: 12px; }
  .tool-call.error { border-left-color: #e74c3c; }
  .tool-call.success { border-left-color: #27ae60; }
  .tool-name { color: #3498db; font-weight: 600; }
  .tool-name.error { color: #e74c3c; }
  .tool-args { color: #888; font-family: monospace; font-size: 11px; }
  .tool-result { color: #a0a0b0; font-family: monospace; font-size: 11px; margin-top: 4px; max-height: 250px; overflow-y: auto; white-space: pre-wrap; }
  .tool-result.error { color: #e74c3c; }
  .tool-result.success { color: #27ae60; }

  /* Final action */
  .final-action { background: #1a3a1a; border: 1px solid #27ae60; border-radius: 6px; padding: 8px 12px; margin-top: 8px; }
  .final-action-label { font-size: 11px; color: #27ae60; font-weight: 600; margin-bottom: 4px; }
  .final-action-json { font-family: monospace; font-size: 13px; color: #fff; }

  /* No final action */
  .no-final { background: #3a1a1a; border: 1px solid #e74c3c; border-radius: 6px; padding: 8px 12px; margin-top: 8px; font-size: 11px; color: #e74c3c; }

  /* Stats bar */
  .stats-bar { display: flex; gap: 12px; padding: 8px 12px; background: #0f3460; font-size: 11px; color: #a0a0b0; }
  .stats-bar .stat { display: flex; align-items: center; gap: 4px; }
  .stats-bar .stat-val { color: #fff; font-weight: 600; }

  @media (max-width: 900px) {
    .container { flex-direction: column; height: auto; }
    .battle-panel { width: 100%; height: 40vh; min-width: auto; border-right: none; border-bottom: 1px solid #0f3460; }
    .replay-panel { width: 100%; height: 50vh; min-width: auto; border-right: none; border-bottom: 1px solid #0f3460; }
    .agent-panel { height: 60vh; }
  }

  /* Collapsible text sections */
  .collapsible-wrapper { position: relative; }
  .collapsible-toggle {
    display: inline-block; margin-top: 4px; padding: 2px 8px; border: 1px solid #3498db;
    border-radius: 3px; background: transparent; color: #3498db; font-size: 11px;
    cursor: pointer; transition: background 0.15s;
  }
  .collapsible-toggle:hover { background: #0f3460; }
  .collapsible-toggle.expanded { border-color: #e94560; color: #e94560; }
</style>
"""

REACT_INDEX_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1 { color: #e94560; margin-bottom: 8px; font-size: 22px; }
  .summary { color: #a0a0b0; font-size: 14px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 12px; background: #0f3460; color: #e94560; font-size: 13px; border-bottom: 2px solid #e94560; }
  td { padding: 8px 12px; border-bottom: 1px solid #1a1a2e; font-size: 13px; }
  tr:hover td { background: #16213e; }
  a { color: #3498db; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-win { background: #27ae60; color: #fff; }
  .badge-loss { background: #e74c3c; color: #fff; }
  .badge-tie { background: #f39c12; color: #fff; }
  .tool-stats { margin-top: 20px; }
  .tool-stats h2 { color: #3498db; font-size: 16px; margin-bottom: 8px; }
  .tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 8px; }
  .tool-stat-card { background: #16213e; border: 1px solid #0f3460; border-radius: 6px; padding: 8px 12px; }
  .tool-stat-card .name { color: #3498db; font-weight: 600; font-size: 13px; }
  .tool-stat-card .count { color: #f39c12; font-size: 18px; font-weight: 700; }
</style>
"""


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _collapsible_text(text: str, preview_len: int = 500, css_class: str = "") -> str:
    """Generate HTML for collapsible text with a 'Show more' toggle.

    Shows the first `preview_len` characters by default. If the text is
    longer, a clickable toggle reveals the full content.
    """
    if not text:
        return ""
    escaped = _html_escape(text)
    if len(text) <= preview_len:
        return f'<div class="{css_class}">{escaped}</div>'

    preview = _html_escape(text[:preview_len])
    return f"""<div class="{css_class} collapsible-wrapper">
      <div class="collapsible-preview">{preview}...</div>
      <div class="collapsible-full" style="display:none">{escaped}</div>
      <button class="collapsible-toggle" onclick="toggleCollapsible(this)">▸ 더 보기 ({len(text) - preview_len}자)</button>
    </div>"""


def generate_react_viewer(
    battle: LangGraphBattle,
    output_dir: str,
    experiment_name: str = "",
    replay_relative_path: Optional[str] = None,
) -> str:
    """Generate the HTML viewer for a LangGraph ReAct battle."""
    output_path = os.path.join(output_dir, f"{battle.battle_tag}.html")

    # Build turn navigation buttons
    turn_buttons = ""
    for turn_data in battle.turns:
        classes = ["turn-btn"]
        has_error = any(
            tc.is_error for step in turn_data.steps for tc in step.tool_calls
        )
        has_tools = any(step.tool_calls for step in turn_data.steps)
        if has_error:
            classes.append("has-error")
        elif has_tools:
            classes.append("has-tools")
        cls = " ".join(classes)
        turn_buttons += f'<button class="{cls}" data-turn="{turn_data.turn}">{turn_data.turn}</button>\n'

    # Build battle state panel (left side)
    battle_sections = ""
    for turn_data in battle.turns:
        # System prompt (collapsible)
        sys_html = ""
        if turn_data.system_prompt:
            sys_html = f"""<div class="battle-section" id="sys-{turn_data.turn}">
              <div class="battle-section-header" style="cursor:pointer" onclick="toggleBattleSection(this)">
                <h3>🤖 Turn {turn_data.turn} — System Prompt</h3>
                <span style="font-size:11px;color:#888">▶ click to expand</span>
              </div>
              <div class="battle-section-body" style="display:none">{_html_escape(turn_data.system_prompt)}</div>
            </div>"""

        # Historical summary
        hist_html = ""
        if turn_data.historical_summary:
            hist_html = f"""<div class="battle-section" id="hist-{turn_data.turn}">
              <div class="battle-section-header">
                <h3>📜 Turn {turn_data.turn} — History</h3>
              </div>
              <div class="battle-section-body">{_html_escape(turn_data.historical_summary)}</div>
            </div>"""

        # Current battle state
        state_html = ""
        if turn_data.battle_state:
            state_html = f"""<div class="battle-section" id="state-{turn_data.turn}">
              <div class="battle-section-header">
                <h3>⚔️ Turn {turn_data.turn} — Battle State</h3>
              </div>
              <div class="battle-section-body">{_html_escape(turn_data.battle_state)}</div>
            </div>"""

        battle_sections += f"""
        <div class="turn-battle-group" id="battle-group-{turn_data.turn}" style="display:none">
          {sys_html}
          {hist_html}
          {state_html}
        </div>"""

    # Build agent step cards (right side)
    step_cards = ""
    for turn_data in battle.turns:
        turn_steps_html = ""
        for step in turn_data.steps:
            # Tool calls HTML
            tools_html = ""
            for tc in step.tool_calls:
                result_cls = "error" if tc.is_error else "success"
                args_str = json.dumps(tc.args, ensure_ascii=False) if tc.args else ""
                result_html = _collapsible_text(tc.result, 200, f"tool-result {result_cls}") if tc.result else ""

                tools_html += f"""
              <div class="tool-call {result_cls}">
                <span class="tool-name {result_cls}">🔧 {tc.tool_name}</span>
                <span class="tool-args">{_html_escape(args_str)}</span>
                {result_html}
              </div>"""

            # Final action HTML
            final_html = ""
            if step.is_final:
                if step.final_action:
                    action_json = json.dumps(step.final_action, ensure_ascii=False)
                    final_html = f"""
              <div class="final-action">
                <div class="final-action-label">✅ Final Decision</div>
                <div class="final-action-json">{_html_escape(action_json)}</div>
              </div>"""
                else:
                    final_html = """
              <div class="no-final">⚠️ No valid JSON action found in response</div>"""

            # Duration string
            duration_str = ""
            if step.duration_ms > 0:
                if step.duration_ms > 1000:
                    duration_str = f"{step.duration_ms/1000:.1f}s"
                else:
                    duration_str = f"{step.duration_ms:.0f}ms"

            # Token string
            token_str = ""
            if step.token_usage:
                total = step.token_usage.get("total_tokens", 0)
                if total:
                    token_str = f"{total:,} tokens"

            card_cls = "step-card final" if step.is_final else "step-card"
            step_label = "🏁 Final" if step.is_final else f"Step {step.call_index}"

            turn_steps_html += f"""
          <div class="{card_cls}">
            <div class="step-card-header">
              <span class="step-num">{step_label}</span>
              <span class="step-tokens">{token_str}</span>
              <span class="step-time">{duration_str}</span>
            </div>
            <div class="step-card-body">
              {_collapsible_text(step.reasoning, 500, "reasoning-text")}
              {f'<div class="tool-section">{tools_html}</div>' if tools_html else ''}
              {final_html}
            </div>
          </div>"""

        # Summary stats for this turn
        tool_count = sum(len(s.tool_calls) for s in turn_data.steps)
        error_count = sum(
            1 for s in turn_data.steps for tc in s.tool_calls if tc.is_error
        )
        step_count = len(turn_data.steps)
        total_tokens_turn = sum(
            s.token_usage.get("total_tokens", 0) for s in turn_data.steps
        )

        step_cards += f"""
        <div class="turn-steps-group" id="steps-{turn_data.turn}" style="display:none">
          <div class="stats-bar">
            <div class="stat">📋 <span class="stat-val">{step_count}</span> steps</div>
            <div class="stat">🔧 <span class="stat-val">{tool_count}</span> tool calls</div>
            <div class="stat">❌ <span class="stat-val">{error_count}</span> errors</div>
            <div class="stat">🪙 <span class="stat-val">{total_tokens_turn:,}</span> tokens</div>
          </div>
          {turn_steps_html}
        </div>"""

    # Tool stats
    tool_stats_html = ""
    if battle.tool_stats:
        cards = ""
        for name, count in sorted(
            battle.tool_stats.items(), key=lambda x: -x[1]
        ):
            cards += f"""<div class="tool-stat-card">
              <div class="name">{_html_escape(name)}</div>
              <div class="count">{count}</div>
            </div>"""
        tool_stats_html = f"""
      <div class="tool-stats">
        <h2>🔧 Tool Usage</h2>
        <div class="tool-grid">{cards}</div>
      </div>"""

    replay_indicator = " · Replay" if replay_relative_path else ""
    # Build left panel: iframe replay if available, otherwise text battle state
    if replay_relative_path:
        left_panel_html = f"""
    <div class="replay-panel" id="replayPanel">
      <iframe src="{replay_relative_path}"></iframe>
    </div>"""
    else:
        left_panel_html = f"""
    <div class="battle-panel" id="battlePanel">
      {battle_sections}
      <div id="battlePlaceholder" style="text-align:center;padding:40px;color:#555;font-style:italic;">
        Click a turn number to view battle state
      </div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{battle.battle_tag} — ReAct Agent Viewer</title>
  {REACT_VIEWER_CSS}
</head>
<body>
  <div class="header">
    <h1>{battle.battle_tag}</h1>
    <span class="meta">ReAct Agent{replay_indicator} · {experiment_name}</span>
    {f'<span class="badge badge-win">WIN</span>' if battle.winner and battle.winner == battle.player_name else f'<span class="badge badge-loss">LOSS</span>' if battle.winner and battle.winner == battle.opponent_name else f'<span class="badge badge-tie">{_html_escape(battle.winner)}</span>' if battle.winner else ''}
    <span class="meta">{len(battle.turns)} turns · {battle.total_llm_calls} LLM calls · {battle.total_tokens.get('total_tokens', 0):,} tokens</span>
    <a href="index.html" style="color:#3498db;font-size:12px;margin-left:auto;">← All Battles</a>
  </div>
  <div class="container">
    {left_panel_html}
    <div class="agent-panel">
      <div class="turn-nav">
        {turn_buttons}
      </div>
      <div class="agent-scroll" id="agentScroll">
        {step_cards}
        <div id="agentPlaceholder" style="text-align:center;padding:40px;color:#555;font-style:italic;">
          Click a turn number to view agent reasoning chain
        </div>
      </div>
    </div>
  </div>
  <script>
    let activeTurn = null;

    function toggleCollapsible(btn) {{
      const wrapper = btn.parentElement;
      const preview = wrapper.querySelector('.collapsible-preview');
      const full = wrapper.querySelector('.collapsible-full');
      if (full.style.display === 'none') {{
        preview.style.display = 'none';
        full.style.display = 'block';
        btn.textContent = '▴ 접기';
        btn.classList.add('expanded');
      }} else {{
        preview.style.display = 'block';
        full.style.display = 'none';
        btn.textContent = btn.dataset.originalText || '▸ 더 보기';
        btn.classList.remove('expanded');
      }}
    }}
    // Store original button text
    document.querySelectorAll('.collapsible-toggle').forEach(b => {{
      b.dataset.originalText = b.textContent;
    }});

    function toggleBattleSection(header) {{
      const body = header.nextElementSibling;
      const hint = header.querySelector('span');
      if (body.style.display === 'none') {{
        body.style.display = 'block';
        if (hint) hint.textContent = '▼ click to collapse';
      }} else {{
        body.style.display = 'none';
        if (hint) hint.textContent = '▶ click to expand';
      }}
    }}

    function showTurn(turnNum) {{
      // Hide all turn groups
      document.querySelectorAll('.turn-battle-group, .turn-steps-group').forEach(el => el.style.display = 'none');
      // Show selected turn
      var battleGroup = document.getElementById('battle-group-' + turnNum);
      if (battleGroup) battleGroup.style.display = 'block';
      document.getElementById('steps-' + turnNum).style.display = 'block';
      // Hide placeholders
      var battlePlaceholder = document.getElementById('battlePlaceholder');
      if (battlePlaceholder) battlePlaceholder.style.display = 'none';
      document.getElementById('agentPlaceholder').style.display = 'none';
      // Update active button
      document.querySelectorAll('.turn-btn').forEach(b => b.classList.remove('active'));
      document.querySelector(`.turn-btn[data-turn="${{turnNum}}"]`).classList.add('active');
      activeTurn = turnNum;
    }}

    // Turn navigation
    document.querySelectorAll('.turn-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        showTurn(btn.dataset.turn);
      }});
    }});

    // Keyboard navigation
    document.addEventListener('keydown', (e) => {{
      const buttons = [...document.querySelectorAll('.turn-btn')];
      const activeIdx = buttons.findIndex(b => b.classList.contains('active'));
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
        e.preventDefault();
        const next = Math.min(activeIdx + 1, buttons.length - 1);
        buttons[next]?.click();
      }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
        e.preventDefault();
        const prev = Math.max(activeIdx - 1, 0);
        buttons[prev]?.click();
      }}
    }});

    // Show first turn by default
    if (document.querySelectorAll('.turn-btn').length > 0) {{
      showTurn(document.querySelectorAll('.turn-btn')[0].dataset.turn);
    }}
  </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_react_index(
    battles: list[LangGraphBattle],
    output_dir: str,
    experiment_name: str,
) -> str:
    """Generate the index.html for LangGraph ReAct battles."""
    output_path = os.path.join(output_dir, "index.html")

    # Aggregate stats
    total_turns = sum(len(b.turns) for b in battles)
    total_calls = sum(b.total_llm_calls for b in battles)
    total_tokens = sum(b.total_tokens.get("total_tokens", 0) for b in battles)
    wins = sum(1 for b in battles if b.winner and b.winner == b.player_name)
    losses = sum(1 for b in battles if b.winner and b.winner == b.opponent_name)
    ties = len(battles) - wins - losses
    agg_tool_stats: Counter = Counter()
    for b in battles:
        agg_tool_stats.update(b.tool_stats)

    # Tool stats section
    tool_stats_html = ""
    if agg_tool_stats:
        cards = ""
        for name, count in agg_tool_stats.most_common():
            cards += f"""<div class="tool-stat-card">
              <div class="name">{_html_escape(name)}</div>
              <div class="count">{count}</div>
            </div>"""
        tool_stats_html = f"""
    <div class="tool-stats">
      <h2>🔧 Tool Usage Across All Battles</h2>
      <div class="tool-grid">{cards}</div>
    </div>"""

    # Build table rows
    rows = ""
    for b in sorted(battles, key=lambda x: x.battle_tag):
        tool_errors = sum(
            1
            for t in b.turns
            for s in t.steps
            for tc in s.tool_calls
            if tc.is_error
        )
        avg_steps = (
            f"{b.total_llm_calls / len(b.turns):.1f}" if b.turns else "0"
        )
        total_tool_calls = sum(b.tool_stats.values())

        # Result badge
        if b.winner and b.winner == b.player_name:
            result = '<span class="badge badge-win">WIN</span>'
        elif b.winner and b.winner == b.opponent_name:
            result = '<span class="badge badge-loss">LOSS</span>'
        elif b.winner:
            result = f'<span class="badge badge-tie">{_html_escape(b.winner)}</span>'
        else:
            result = '<span class="badge badge-tie">?</span>'

        rows += f"""
      <tr>
        <td><a href="{b.battle_tag}.html">{b.battle_tag}</a></td>
        <td>{len(b.turns)}</td>
        <td>{b.total_llm_calls} (avg {avg_steps}/turn)</td>
        <td>{total_tool_calls} ({tool_errors} errors)</td>
        <td>{b.total_tokens.get('total_tokens', 0):,}</td>
        <td>{result}</td>
      </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_html_escape(experiment_name)} — ReAct Agent Viewer</title>
  {REACT_INDEX_CSS}
</head>
<body>
  <h1>{_html_escape(experiment_name)}</h1>
  <div class="summary">
    ReAct Agent (LangGraph) |
    {len(battles)} battles · {total_turns} turns · {total_calls} LLM calls · {total_tokens:,} tokens
    {f' · {wins}W / {losses}L / {ties}T ({wins/len(battles)*100:.1f}%)' if battles and wins + losses + ties > 0 else ''}
  </div>
  <table>
    <thead>
      <tr>
        <th>Battle</th>
        <th>Turns</th>
        <th>LLM Calls</th>
        <th>Tool Calls</th>
        <th>Tokens</th>
        <th>Result</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  {tool_stats_html}
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def process_experiment(
    exp_dir: str, battle_filter: Optional[str] = None
) -> str:
    """Process an experiment directory and generate viewer files.

    Auto-detects the experiment format:
    - LangGraph ReAct: langgraph_llm_log.jsonl present
    - Standard: HTML replays + llm_log.jsonl or run.log

    Args:
        exp_dir: Path to experiment directory
        battle_filter: Optional battle tag to process only one battle

    Returns:
        Path to the output directory
    """
    exp_path = Path(exp_dir).resolve()
    if not exp_path.exists():
        print(f"Error: directory not found: {exp_path}")
        sys.exit(1)

    battle_log_dir = exp_path / "battle_log"
    output_dir = exp_path / "viewer"

    # --- Auto-detect LangGraph format ---
    langgraph_llm = exp_path / "langgraph_llm_log.jsonl"
    if not langgraph_llm.exists():
        langgraph_llm = battle_log_dir / "langgraph_llm_log.jsonl"

    if langgraph_llm.exists():
        return _process_langgraph_experiment(
            exp_path, langgraph_llm, battle_log_dir, output_dir, battle_filter
        )

    # --- Standard format (HTML replays) ---
    if not battle_log_dir.exists():
        print(f"Error: battle_log/ directory not found in {exp_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    log_path = exp_path / "run.log"

    # Parse LLM logs (prefer structured llm_log.jsonl over run.log)
    entries_by_battle: dict[str, list[LLMEntry]] = {}
    model_info = ""
    llm_player_name = ""
    has_prompts = False

    jsonl_path = exp_path / "llm_log.jsonl"
    if not jsonl_path.exists():
        # Also check battle_log/ subdirectory (where --log_dir points)
        jsonl_path = battle_log_dir / "llm_log.jsonl"
    if jsonl_path.exists():
        print(f"Parsing llm_log.jsonl (structured, with prompts)...")
        entries_by_battle = parse_llm_log_jsonl(str(jsonl_path))
        has_prompts = True
        # Still extract model info from run.log if available
        if log_path.exists():
            model_info, llm_player_name = _extract_model_info(str(log_path))
        print(f"  Found entries for {len(entries_by_battle)} battles")
    elif log_path.exists():
        print(f"Parsing run.log (stdout capture, responses only)...")
        entries_by_battle = parse_run_log(str(log_path))
        model_info, llm_player_name = _extract_model_info(str(log_path))
        print(f"  Found entries for {len(entries_by_battle)} battles")
    else:
        print(f"No LLM logs found — generating replay-only viewer")

    # Find HTML replay files
    html_files = sorted(battle_log_dir.glob("*.html"))
    if not html_files:
        print(f"Error: no HTML replay files found in {battle_log_dir}")
        sys.exit(1)

    print(f"  Found {len(html_files)} replay files")

    # Process each battle
    battles = []
    for html_file in html_files:
        # Extract battle tag from filename
        tag_match = re.search(r"(battle-[\w]+-\d+)", html_file.name)
        if not tag_match:
            continue

        battle_tag = tag_match.group(1)

        # Filter if specific battle requested
        if battle_filter and battle_tag != battle_filter:
            continue

        # Parse replay with LLM player name for correct p1/p2 detection
        turns, winner, llm_name, opponent_name = parse_html_replay(
            str(html_file), llm_player_name=llm_player_name
        )

        # Get LLM entries for this battle
        llm_entries = entries_by_battle.get(battle_tag, [])

        # Match entries to turns
        matched = match_entries_to_turns(turns, llm_entries)

        battle = BattleData(
            battle_tag=battle_tag,
            html_path=str(html_file),
            winner=winner,
            player_name=llm_name,
            opponent_name=opponent_name,
            turns=turns,
            llm_entries=llm_entries,
            matched_turns=matched,
        )
        battles.append(battle)

        # Generate viewer HTML
        replay_rel = os.path.relpath(str(html_file), str(output_dir))
        viewer_path = generate_battle_viewer(battle, str(output_dir), replay_rel)
        print(f"  Generated: {os.path.basename(viewer_path)} ({len(turns)} turns, {len(llm_entries)} LLM calls, matched={sum(1 for m in matched if m['matched'])})")

    if not battles:
        print("No battles processed.")
        sys.exit(1)

    # Generate index
    experiment_name = exp_path.name
    index_path = generate_index(battles, str(output_dir), experiment_name, model_info)
    print(f"\nGenerated index: {index_path}")
    print(f"Output directory: {output_dir}")

    return str(output_dir)


def _process_langgraph_experiment(
    exp_path: Path,
    langgraph_llm: Path,
    battle_log_dir: Path,
    output_dir: Path,
    battle_filter: Optional[str],
) -> str:
    """Process a LangGraph ReAct experiment."""
    os.makedirs(output_dir, exist_ok=True)

    print(f"Detected LangGraph ReAct format")
    print(f"  Parsing {langgraph_llm.name}...")

    # Find tool log
    tool_log_path = exp_path / "langgraph_tool_log.jsonl"
    if not tool_log_path.exists():
        tool_log_path = battle_log_dir / "langgraph_tool_log.jsonl"
    tool_log_str = str(tool_log_path) if tool_log_path.exists() else None

    if tool_log_str:
        print(f"  Parsing {tool_log_path.name}...")

    # Parse logs
    battles = parse_langgraph_logs(str(langgraph_llm), tool_log_str)
    print(f"  Found {len(battles)} battles")

    # --- Discover HTML replay files ---
    replay_map: dict[str, str] = {}  # battle_tag -> relative path from output_dir
    replay_abs_map: dict[str, str] = {}  # battle_tag -> absolute path for parsing
    if battle_log_dir.exists():
        html_files = sorted(battle_log_dir.glob("*.html"))
        for html_file in html_files:
            if html_file.name == "index.html":
                continue
            tag_match = re.search(r"(battle-[\w]+-\d+)", html_file.name)
            if tag_match:
                replay_map[tag_match.group(1)] = os.path.relpath(
                    str(html_file), str(output_dir)
                )
                replay_abs_map[tag_match.group(1)] = str(html_file)
        if replay_map:
            print(f"  Found {len(replay_map)} HTML replay file(s)")

    # Extract win/loss info from HTML replays
    for btag, battle in battles.items():
        abs_path = replay_abs_map.get(btag)
        if abs_path:
            _, winner, llm_name, opponent_name = parse_html_replay(
                abs_path, llm_player_name=""
            )
            battle.winner = winner
            battle.player_name = llm_name
            battle.opponent_name = opponent_name

    # Process each battle
    processed = []
    for btag, battle in sorted(battles.items()):
        if battle_filter and btag != battle_filter:
            continue

        replay_rel_path = replay_map.get(btag)
        viewer_path = generate_react_viewer(
            battle,
            str(output_dir),
            experiment_name=exp_path.name,
            replay_relative_path=replay_rel_path,
        )
        processed.append(battle)

        tool_errors = sum(
            1
            for t in battle.turns
            for s in t.steps
            for tc in s.tool_calls
            if tc.is_error
        )
        replay_indicator = " [with replay]" if replay_rel_path else ""
        print(
            f"  Generated: {os.path.basename(viewer_path)}{replay_indicator} "
            f"({len(battle.turns)} turns, {battle.total_llm_calls} LLM calls, "
            f"{sum(battle.tool_stats.values())} tool calls, {tool_errors} errors)"
        )

    if not processed:
        print("No battles processed.")
        sys.exit(1)

    # Generate index
    index_path = generate_react_index(
        processed, str(output_dir), exp_path.name
    )
    print(f"\nGenerated index: {index_path}")
    print(f"Output directory: {output_dir}")

    return str(output_dir)


def _extract_model_info(log_path: str) -> tuple[str, str]:
    """Extract model/opponent info and LLM player name from run.log header.

    Returns:
        (model_info_str, llm_player_name)
    """
    model = ""
    opponent = ""
    llm_player_name = ""

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = strip_ansi(line)
                if line.startswith("Player: "):
                    model = line.replace("Player: ", "").strip()
                elif line.startswith("Opponent: "):
                    opponent = line.replace("Opponent: ", "").strip()
                elif "LLM [" in line:
                    # Extract from first LLM log line: "LLM [pokechamp4150]: ..."
                    match = re.search(r"LLM \[(\w+)\]", line)
                    if match:
                        llm_player_name = match.group(1)
                if model and opponent and llm_player_name:
                    break
    except Exception:
        pass

    parts = [p for p in [model, opponent] if p]
    model_info = " vs ".join(parts) if parts else "Unknown"
    return model_info, llm_player_name


def main():
    parser = argparse.ArgumentParser(
        description="Generate battle replay + LLM log viewer"
    )
    parser.add_argument(
        "experiment_dir",
        help="Path to experiment directory (e.g. .temp/experiments/EXP-011)",
    )
    parser.add_argument(
        "--battle",
        help="Only process a specific battle (e.g. battle-gen9ou-310)",
        default=None,
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the viewer in a browser after generation",
    )

    args = parser.parse_args()
    output_dir = process_experiment(args.experiment_dir, args.battle)

    if args.open:
        index_path = os.path.join(output_dir, "index.html")
        webbrowser.open(f"file://{os.path.abspath(index_path)}")


if __name__ == "__main__":
    main()
