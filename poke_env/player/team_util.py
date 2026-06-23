from poke_env.data.download import download_teams
from poke_env.player.player import Player
from poke_env.player.baselines import AbyssalPlayer, MaxBasePowerPlayer, OneStepPlayer
from poke_env.player.random_player import RandomPlayer
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ShowdownServerConfiguration
from poke_env.teambuilder import Teambuilder
from numpy.random import randint
import hashlib
import importlib
import inspect
import json
import os
import random
import re

BANNED_MOVES_BY_FORMAT = {
    "gen9ou": {"Tera Blast", "Last Respects", "Shed Tail", "Baton Pass"},
    "gen9ubers": {"Last Respects", "Baton Pass"},
    "gen9uu": {"Tera Blast", "Last Respects", "Shed Tail", "Baton Pass"},
}


class TeamSet(Teambuilder):
    """Sample from a directory of Showdown team files.

    A simple wrapper around poke-env's Teambuilder that randomly samples a team from a
    directory of team files.

    Args:
        team_file_dir: The directory containing the team files (searched recursively).
            Team files are just text files in the standard Showdown export format. See
            https://pokepast.es/syntax.html for details.
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers",
            etc.). Note that we assume files have a matching extension (e.g.
            "any_name.gen1ou_team").
    """

    def __init__(self, team_file_dir: str, battle_format: str):
        super().__init__()
        self.team_file_dir = team_file_dir
        self.battle_format = battle_format
        self.team_files = self._find_team_files()

    def _find_team_files(self):
        team_files = []
        for root, _, files in os.walk(self.team_file_dir):
            for file in files:
                if file.endswith(f".{self.battle_format}_team"):
                    team_files.append(os.path.join(root, file))
        return sorted(team_files)

    def _has_banned_content(self, team_data: str) -> bool:
        banned_moves = BANNED_MOVES_BY_FORMAT.get(self.battle_format, set())
        if not banned_moves:
            return False
        normalized = team_data.lower().replace(" ", "").replace("-", "")
        for move in banned_moves:
            normalized_move = move.lower().replace(" ", "").replace("-", "")
            if normalized_move in normalized:
                return True
        return False

    def yield_team(self):
        if not self.team_files:
            raise ValueError(f"No team files found for format {self.battle_format}")
        attempts = 0
        max_attempts = len(self.team_files) + 1
        while attempts < max_attempts:
            file = random.choice(self.team_files)
            with open(file, "r") as f:
                team_data = f.read()
            if not self._has_banned_content(team_data):
                break
            attempts += 1
        team = self.parse_showdown_team(team_data)
        print(team)
        for mon in team:
            if mon.species is not None:
                mon.nickname = mon.species
        return self.join_team(team)


def get_metamon_teams(battle_format: str, set_name: str) -> TeamSet:
    """
    Download a set of teams from huggingface (if necessary) and return a TeamSet.

    Args:
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers", etc.).
        set_name: The name of the set of teams to download. See the README for options.
    """
    if set_name not in {
        "competitive",
        "paper_replays",
        "paper_variety",
        "modern_replays",
        "pokeagent_modern_replays",
    }:
        raise ValueError(
            f"Invalid set name: {set_name}. Must be one of: competitive, paper_replays, paper_variety, modern_replays"
        )
    path = download_teams(battle_format, set_name=set_name)
    if not os.path.exists(path):
        raise ValueError(
            f"Cannot locate valid team directory for format {battle_format} at path {path}"
        )
    return TeamSet(path, battle_format)


class TeamSet(Teambuilder):
    """Sample from a directory of Showdown team files.

    A simple wrapper around poke-env's Teambuilder that randomly samples a team from a
    directory of team files.

    Args:
        team_file_dir: The directory containing the team files (searched recursively).
            Team files are just text files in the standard Showdown export format. See
            https://pokepast.es/syntax.html for details.
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers",
            etc.). Note that we assume files have a matching extension (e.g.
            "any_name.gen1ou_team").
    """

    def __init__(self, team_file_dir: str, battle_format: str):
        super().__init__()
        self.team_file_dir = team_file_dir
        self.battle_format = battle_format
        self.team_files = self._find_team_files()

    def _find_team_files(self):
        team_files = []
        for root, _, files in os.walk(self.team_file_dir):
            for file in files:
                if file.endswith(f".{self.battle_format}_team"):
                    team_files.append(os.path.join(root, file))
        return sorted(team_files)

    def _has_banned_content(self, team_data: str) -> bool:
        banned_moves = BANNED_MOVES_BY_FORMAT.get(self.battle_format, set())
        if not banned_moves:
            return False
        normalized = team_data.lower().replace(" ", "").replace("-", "")
        for move in banned_moves:
            normalized_move = move.lower().replace(" ", "").replace("-", "")
            if normalized_move in normalized:
                return True
        return False

    def yield_team(self):
        if not self.team_files:
            raise ValueError(f"No team files found for format {self.battle_format}")
        attempts = 0
        max_attempts = len(self.team_files) + 1
        while attempts < max_attempts:
            file = random.choice(self.team_files)
            with open(file, "r") as f:
                team_data = f.read()
            if not self._has_banned_content(team_data):
                break
            attempts += 1
        team = self.parse_showdown_team(team_data)
        print(team)
        for mon in team:
            if mon.species is not None:
                mon.nickname = mon.species
        return self.join_team(team)


def get_metamon_teams(battle_format: str, set_name: str) -> TeamSet:
    """
    Download a set of teams from huggingface (if necessary) and return a TeamSet.

    Args:
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers", etc.).
        set_name: The name of the set of teams to download. See the README for options.
    """
    if set_name not in {
        "competitive",
        "paper_replays",
        "paper_variety",
        "modern_replays",
        "pokeagent_modern_replays",
    }:
        raise ValueError(
            f"Invalid set name: {set_name}. Must be one of: competitive, paper_replays, paper_variety, modern_replays"
        )
    if battle_format == "gen9vgc2025regi":
        path = "bayesian_dataset"
    else:
        path = download_teams(battle_format, set_name=set_name)
    if not os.path.exists(path):
        raise ValueError(
            f"Cannot locate valid team directory for format {battle_format} at path {path}"
        )

    # Check if team files exist for this format
    team_set = TeamSet(path, battle_format)
    if not team_set.team_files:
        raise ValueError(
            f"No team files found for format {battle_format} in {path}. "
            f"Expected files with extension '.{battle_format}_team'"
        )

    return team_set


# Allowed metamon set names — kept in sync with the inline set validated above.
METAMON_SET_NAMES = {
    "competitive",
    "paper_replays",
    "paper_variety",
    "modern_replays",
    "pokeagent_modern_replays",
}


def _numeric_team_sort(paths):
    """Re-sort metamon team files by their numeric index.

    ``TeamSet._find_team_files`` returns ``sorted(team_files)`` which is
    lexicographic, so ``team_10`` precedes ``team_2``. Manifest indices are
    meant to map to the numeric order, so we restore numeric ordering here.
    """
    def key(p):
        m = re.search(r"team_(\d+)\.", os.path.basename(p))
        return (int(m.group(1)) if m else 0, p)

    return sorted(paths, key=key)


class FixedTeamProvider:
    """Deterministic team provider that does NOT consume the global RNG.

    ``TeamSet.yield_team`` picks a team via ``random.choice``, consuming the
    global RNG state. Because ``--seed`` initializes the global RNG only once at
    process start, the second battle onward diverges depending on how many
    random draws the previous battle consumed (turn count, LLM nondeterminism)
    — so the same seed reproduces only the first battle. See the fixed-team
    mode design doc for the full diagnosis.

    This provider loads the metamon pool once, then selects teams by manifest
    index directly (no ``random.choice``), so the global RNG is unaffected.
    Returns packed Showdown teamstrings that ``Player.update_team`` wraps into
    ``ConstantTeambuilder`` automatically.
    """

    def __init__(self, battle_format, set_name, indices):
        if not indices:
            raise ValueError("FixedTeamProvider requires a non-empty indices list")
        self.battle_format = battle_format
        self.set_name = set_name
        self.indices = list(indices)
        team_set = get_metamon_teams(battle_format, set_name)
        self._team_set = team_set
        self._files = _numeric_team_sort(team_set.team_files)
        if not self._files:
            raise ValueError(
                f"No team files for format {battle_format}, set {set_name!r}"
            )
        for idx in self.indices:
            if not (0 <= idx < len(self._files)):
                raise ValueError(
                    f"team index {idx} out of range for set {set_name!r} "
                    f"(pool size={len(self._files)})"
                )
        # Pre-parse and cache packed teamstrings — minimizes loop I/O and
        # guarantees identical output across instantiations.
        self._teams = [self._load_packed(i) for i in self.indices]

    def _load_packed(self, idx):
        with open(self._files[idx], "r") as f:
            team_data = f.read()
        team = self._team_set.parse_showdown_team(team_data)
        for mon in team:
            if mon.species is not None:
                mon.nickname = mon.species
        return self._team_set.join_team(team)

    def at(self, position):
        """Packed teamstring for the ``position``-th (0-based) battle.

        Indices shorter than the battle count wrap around with modulo.
        """
        return self._teams[position % len(self._teams)]

    def index_at(self, position):
        return self.indices[position % len(self.indices)]

    def describe(self):
        return {
            "set": self.set_name,
            "pool_size": len(self._files),
            "matchup_count": len(self.indices),
            "indices": list(self.indices),
        }


class FixedTeamCombo:
    """Container pairing a fixed player team provider with a fixed opponent one.

    Battle scripts hold a single combo object and call ``player_at`` /
    ``opponent_at`` each iteration.
    """

    def __init__(self, player, opponent, manifest_hash, manifest_meta):
        self.player = player
        self.opponent = opponent
        self.manifest_hash = manifest_hash
        self.manifest_meta = manifest_meta

    def player_at(self, position):
        return self.player.at(position)

    def opponent_at(self, position):
        return self.opponent.at(position)

    def player_index(self, position):
        return self.player.index_at(position)

    def opponent_index(self, position):
        return self.opponent.index_at(position)

    def describe(self):
        return {
            "player": self.player.describe(),
            "opponent": self.opponent.describe(),
        }


def load_fixed_manifest(manifest_path):
    """Load a fixed-team manifest JSON and return a ``FixedTeamCombo``.

    Schema (fixed-team-manifest-v1)::

        {
          "version": 1, "mode": "fixed", "battle_format": "gen9ou",
          "player":   {"set": "competitive",    "indices": [...]},
          "opponent": {"set": "modern_replays", "indices": [...]},
          "n_battles": 30
        }
    """
    with open(manifest_path, "rb") as f:
        raw = f.read()
    manifest = json.loads(raw)
    manifest_hash = "sha256:" + hashlib.sha256(raw).hexdigest()

    version = manifest.get("version")
    mode = manifest.get("mode")
    battle_format = manifest.get("battle_format")
    # v1 = baseline fixed-team; v2 = same schema + player/opponent selection
    # metadata (selection/seed), which this loader ignores. Both share the
    # player/opponent {set, indices} contract.
    if version not in (1, 2):
        raise ValueError(
            f"Unsupported manifest version: {version!r} (expected 1 or 2)"
        )
    if mode != "fixed":
        raise ValueError(f"manifest mode must be 'fixed', got {mode!r}")
    if not battle_format:
        raise ValueError("manifest missing 'battle_format'")

    player_cfg = manifest.get("player") or {}
    opponent_cfg = manifest.get("opponent") or {}
    for label, cfg in (("player", player_cfg), ("opponent", opponent_cfg)):
        set_name = cfg.get("set")
        if set_name not in METAMON_SET_NAMES:
            raise ValueError(
                f"{label}.set {set_name!r} invalid; must be one of "
                f"{sorted(METAMON_SET_NAMES)}"
            )
        if not cfg.get("indices"):
            raise ValueError(f"{label}.indices missing or empty")

    player_provider = FixedTeamProvider(
        battle_format, player_cfg["set"], player_cfg["indices"]
    )
    opponent_provider = FixedTeamProvider(
        battle_format, opponent_cfg["set"], opponent_cfg["indices"]
    )
    return FixedTeamCombo(
        player_provider,
        opponent_provider,
        manifest_hash,
        {
            "version": version,
            "mode": mode,
            "battle_format": battle_format,
            "n_battles": manifest.get("n_battles"),
            "description": manifest.get("description"),
            "custom_purpose": manifest.get("custom_purpose"),
        },
    )


def load_random_team(id=None, vgc=False):
    if id == None:
        team_id = randint(1, 14)
    else:
        team_id = id
    if vgc is True:
        print(f"Loading VGC team {team_id}")
        with open(
            f"poke_env/data/static/teams/gen9vgc2025regi/gen9vgc2025regi{team_id}.txt",
            "r",
        ) as f:
            team = f.read()
    else:
        with open(f"poke_env/data/static/teams/gen9ou/gen9ou{team_id}.txt", "r") as f:
            team = f.read()
    return team


def get_custom_bot_class(bot_name: str):
    """
    Get a custom bot class by name from the bots folder.

    Args:
        bot_name: The name of the bot (without _bot suffix)

    Returns:
        The bot class if found, None otherwise
    """
    from pokechamp.llm_player import LLMPlayer

    try:
        # Import the bot module
        module_name = f"bots.{bot_name}_bot"
        module = importlib.import_module(module_name)

        # Find the bot class in the module
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, LLMPlayer) and obj != LLMPlayer:
                return obj

        return None
    except ImportError:
        return None


def get_llm_player(
    args,
    backend: str,
    prompt_algo: str,
    name: str,
    KEY: str = "",
    battle_format="gen9ou",
    llm_backend=None,
    device=0,
    PNUMBER1: str = "",
    USERNAME: str = "",
    PASSWORD: str = "",
    online: bool = False,
    use_timeout: bool = True,
    timeout_seconds: int = 90,
    enable_dynamic_flags: bool = False,
    enable_dynamic_calcs: bool = False,
    enable_showdown_oracle: bool = False,
    enable_llm_lead_selection: bool = False,
) -> Player:
    from pokechamp.llm_player import LLMPlayer
    from pokechamp.prompts import prompt_translate, state_translate2, state_translate3

    # Lazy imports to avoid circular dependency at module level
    from pokechamp.mcp_player import MCPPlayer
    from pokechamp.llm_vgc_player import LLMVGCPlayer

    server_config = None
    if online:
        server_config = ShowdownServerConfiguration
    if USERNAME == "":
        USERNAME = name

    if prompt_algo == "mcp":
        print(f"[DEBUG] Creating MCPPlayer")
        return MCPPlayer(
            battle_format=battle_format,
            api_key=KEY,
            backend=backend,
            temperature=args.temperature,
            prompt_algo=prompt_algo,
            log_dir=args.log_dir,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
            save_replays=args.log_dir,
            prompt_translate=(
                state_translate3 if "vgc" in battle_format.lower() else state_translate2
            ),
            device=device,
            llm_backend=llm_backend,
            enable_dynamic_flags=enable_dynamic_flags,
            enable_dynamic_calcs=enable_dynamic_calcs,
            enable_showdown_oracle=enable_showdown_oracle,
            enable_llm_lead_selection=enable_llm_lead_selection,
        )
    if name == "abyssal":
        return AbyssalPlayer(
            battle_format=battle_format,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
        )
    elif name == "max_power":
        return MaxBasePowerPlayer(
            battle_format=battle_format,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
        )
    elif name == "random":
        return RandomPlayer(
            battle_format=battle_format,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
        )
    elif name == "one_step":
        return OneStepPlayer(
            battle_format=battle_format,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
        )
    elif "pokellmon" in name:
        if use_timeout and online:
            from pokechamp.timeout_llm_player import PokellmonTimeoutLLMPlayer

            return PokellmonTimeoutLLMPlayer(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                prompt_algo=prompt_algo,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                device=device,
                llm_backend=llm_backend,
                timeout_seconds=timeout_seconds,
            )
        else:
            return LLMPlayer(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                prompt_algo=prompt_algo,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                device=device,
                llm_backend=llm_backend,
                enable_dynamic_flags=enable_dynamic_flags,
                enable_dynamic_calcs=enable_dynamic_calcs,
                enable_showdown_oracle=enable_showdown_oracle,
                enable_llm_lead_selection=enable_llm_lead_selection,
            )
    elif "pokechamp" in name:
        # Use VGC player for VGC formats, timeout player for online mode, regular player for others
        if "vgc" in battle_format:
            return LLMVGCPlayer(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                prompt_algo=prompt_algo,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                prompt_translate=state_translate3,
                device=device,
                llm_backend=llm_backend,
            )
        elif use_timeout and online:
            from pokechamp.timeout_llm_player import TimeoutLLMPlayer

            return TimeoutLLMPlayer(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                prompt_algo=prompt_algo,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                prompt_translate=state_translate2,
                device=device,
                llm_backend=llm_backend,
                timeout_seconds=timeout_seconds,
                enable_dynamic_flags=enable_dynamic_flags,
                enable_dynamic_calcs=enable_dynamic_calcs,
                enable_showdown_oracle=enable_showdown_oracle,
                enable_llm_lead_selection=enable_llm_lead_selection,
            )
        else:
            return LLMPlayer(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                prompt_algo=prompt_algo,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                prompt_translate=state_translate2,
                device=device,
                llm_backend=llm_backend,
                enable_dynamic_flags=enable_dynamic_flags,
                enable_dynamic_calcs=enable_dynamic_calcs,
                enable_showdown_oracle=enable_showdown_oracle,
                enable_llm_lead_selection=enable_llm_lead_selection,
            )
    elif "vgc" in name:
        return LLMVGCPlayer(
            battle_format=battle_format,
            api_key=KEY,
            backend=backend,
            temperature=args.temperature,
            prompt_algo=prompt_algo,
            log_dir=args.log_dir,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
            save_replays=args.log_dir,
            # Use state_translate3 for VGC formats, state_translate2 for others
            prompt_translate=(
                state_translate3 if "vgc" in battle_format.lower() else state_translate2
            ),
            device=device,
            llm_backend=llm_backend,
        )
    elif "pokechamp" in name:
        return LLMPlayer(
            battle_format=battle_format,
            api_key=KEY,
            backend=backend,
            temperature=args.temperature,
            prompt_algo=prompt_algo,
            #    prompt_algo="minimax",
            #    prompt_algo="io",
            log_dir=args.log_dir,
            account_configuration=AccountConfiguration(
                f"{USERNAME}{PNUMBER1}", PASSWORD
            ),
            server_configuration=server_config,
            save_replays=args.log_dir,
            #    prompt_translate=prompt_translate,
            prompt_translate=(
                state_translate3 if "vgc" in battle_format.lower() else state_translate2
            ),
            device=device,
            llm_backend=llm_backend,
            enable_dynamic_flags=enable_dynamic_flags,
            enable_dynamic_calcs=enable_dynamic_calcs,
            enable_showdown_oracle=enable_showdown_oracle,
        )
    else:
        # Try to find a custom bot in the bots folder
        custom_bot_class = get_custom_bot_class(name)
        if custom_bot_class:
            return custom_bot_class(
                battle_format=battle_format,
                api_key=KEY,
                backend=backend,
                temperature=args.temperature,
                log_dir=args.log_dir,
                account_configuration=AccountConfiguration(
                    f"{USERNAME}{PNUMBER1}", PASSWORD
                ),
                server_configuration=server_config,
                save_replays=args.log_dir,
                device=device,
                llm_backend=llm_backend,
            )
        else:
            raise ValueError(f"Bot not found: {name}")
