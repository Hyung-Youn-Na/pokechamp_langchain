"""
Tests for python-dotenv integration.

Verifies:
1. python-dotenv can be imported
2. common.py calls load_dotenv() (.env values appear in os.environ)
3. .env file values are loaded into os.environ after importing common
4. Existing shell env vars take precedence over .env values
5. Missing .env file does not cause import errors
6. .env.example exists and contains all required variable names
7. Backend player files are unchanged
"""

import os
import sys
import subprocess
import textwrap

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "FEATHERLESS_API_KEY",
]

BACKEND_PLAYER_FILES = [
    "pokechamp/gpt_player.py",
    "pokechamp/openrouter_player.py",
    "pokechamp/gemini_player.py",
    "pokechamp/featherless_player.py",
]


class TestDotenvImportable:
    """VAL-DOTENV-001: python-dotenv is an explicit dependency."""

    def test_dotenv_importable(self):
        """python-dotenv package can be imported."""
        import dotenv

        assert hasattr(dotenv, "load_dotenv")


class TestLoadDotenvInCommon:
    """VAL-DOTENV-002: load_dotenv called in common.py."""

    def test_common_calls_load_dotenv(self, tmp_path):
        """Importing common.py triggers load_dotenv, so .env values appear in os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_KEY_12345=loaded_value\n")

        # Run in a subprocess to avoid polluting this process's env
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""\
                    import os, sys
                    os.chdir({str(tmp_path)!r})
                    sys.path.insert(0, {PROJECT_ROOT!r})
                    import common
                    print(os.getenv("TEST_DOTENV_KEY_12345", "NOT_FOUND"))
                """),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "loaded_value" in result.stdout.strip()


class TestEnvFileLoaded:
    """VAL-DOTENV-003: .env file loads keys into os.environ."""

    def test_env_file_loaded(self, tmp_path):
        """Values from .env file appear in os.environ after importing common."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=test-key-123\n")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""\
                    import os, sys
                    os.chdir({str(tmp_path)!r})
                    sys.path.insert(0, {PROJECT_ROOT!r})
                    import common
                    print(os.getenv("OPENAI_API_KEY", "NOT_FOUND"))
                """),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        # common.py prints PNUMBER1 on import, so check last line
        last_line = result.stdout.strip().split("\n")[-1]
        assert last_line == "test-key-123"


class TestEnvVarPrecedence:
    """VAL-DOTENV-004: Existing env vars take precedence over .env."""

    def test_env_var_precedence(self, tmp_path):
        """Shell env vars take precedence over .env values."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENROUTER_API_KEY=dotenv-value\n")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""\
                    import os, sys
                    os.chdir({str(tmp_path)!r})
                    sys.path.insert(0, {PROJECT_ROOT!r})
                    import common
                    print(os.getenv("OPENROUTER_API_KEY", "NOT_FOUND"))
                """),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={
                **os.environ,
                "OPENROUTER_API_KEY": "shell-value",
            },
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        # common.py prints PNUMBER1 on import, so check last line
        last_line = result.stdout.strip().split("\n")[-1]
        assert last_line == "shell-value"


class TestMissingEnvFile:
    """VAL-DOTENV-005: Missing .env file does not cause errors."""

    def test_missing_env_file_no_error(self, tmp_path):
        """Missing .env file does not cause import errors."""
        # tmp_path has no .env file
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""\
                    import os, sys
                    os.chdir({str(tmp_path)!r})
                    sys.path.insert(0, {PROJECT_ROOT!r})
                    import common
                    print("import succeeded")
                """),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "import succeeded" in result.stdout


class TestEnvExample:
    """VAL-DOTENV-006: .env.example exists with all required variables."""

    def test_env_example_exists(self):
        """.env.example file exists in the project root."""
        env_example_path = os.path.join(PROJECT_ROOT, ".env.example")
        assert os.path.isfile(env_example_path), ".env.example must exist in project root"

    def test_env_example_contains_all_required_vars(self):
        """.env.example contains all required API key variable names."""
        env_example_path = os.path.join(PROJECT_ROOT, ".env.example")
        with open(env_example_path) as f:
            content = f.read()

        for var_name in REQUIRED_ENV_VARS:
            assert var_name in content, (
                f".env.example must contain {var_name}"
            )


class TestEnvGitignored:
    """VAL-DOTENV-007: .env is gitignored."""

    def test_env_is_gitignored(self):
        """.env files are listed in .gitignore and will not be tracked."""
        result = subprocess.run(
            ["git", "check-ignore", ".env"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, ".env must be gitignored"


class TestBackendPlayersUnchanged:
    """VAL-DOTENV-008: Backend players unchanged."""

    def test_backend_players_unchanged(self):
        """No modifications to backend player files (checked against git HEAD)."""
        result = subprocess.run(
            ["git", "diff", "HEAD"] + BACKEND_PLAYER_FILES,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.stdout.strip() == "", (
            f"Backend player files must not be modified. Diff:\n{result.stdout}"
        )


class TestEndToEndKeyLoading:
    """VAL-CROSS-001: End-to-end key loading works for all providers."""

    def test_all_provider_keys_loaded(self, tmp_path):
        """Creating .env with test keys for all providers, import common, verify all accessible."""
        env_file = tmp_path / ".env"
        env_file.write_text(textwrap.dedent("""\
            OPENAI_API_KEY=test-openai-key
            OPENROUTER_API_KEY=test-openrouter-key
            GEMINI_API_KEY=test-gemini-key
            FEATHERLESS_API_KEY=test-featherless-key
        """))

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""\
                    import os, sys
                    os.chdir({str(tmp_path)!r})
                    sys.path.insert(0, {PROJECT_ROOT!r})
                    import common
                    keys = {{
                        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
                        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY"),
                        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
                        "FEATHERLESS_API_KEY": os.getenv("FEATHERLESS_API_KEY"),
                    }}
                    for k, v in keys.items():
                        print(f"{{k}}={{v}}")
                """),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        output = result.stdout.strip()
        assert "OPENAI_API_KEY=test-openai-key" in output
        assert "OPENROUTER_API_KEY=test-openrouter-key" in output
        assert "GEMINI_API_KEY=test-gemini-key" in output
        assert "FEATHERLESS_API_KEY=test-featherless-key" in output
