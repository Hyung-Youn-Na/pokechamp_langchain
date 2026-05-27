"""Showdown Oracle — Python wrapper for the Node.js oracle worker subprocess.

This module provides :class:`ShowdownOracle`, which manages a long-running
Node.js subprocess running ``oracle-worker.js``.  Communication uses a
stdin/stdout JSON-line protocol: one JSON object per newline-terminated line.

Key design constraints:
- **Never raises to callers**: ``query()`` returns ``None`` on any failure.
- **Auto-restart**: if the worker subprocess dies, it is restarted up to
  ``max_restarts`` times per ``query()`` call.
- **Timeout**: each query has a configurable timeout (default 5 s).
- **Cleanup**: ``atexit`` handler, ``__del__``, and ``__exit__`` all ensure
  the subprocess is terminated.
- **Logging**: uses ``logging.getLogger("showdown_oracle")``, never ``print()``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("showdown_oracle")


class ShowdownOracle:
    """Manage a Node oracle-worker subprocess for move-outcome prediction.

    Parameters
    ----------
    worker_path : str
        Path to the ``oracle-worker.js`` script.
    node_path : str
        Path to the Node.js binary.
    timeout_seconds : float
        Maximum time (in seconds) to wait for a worker response.
    max_restarts : int
        Maximum number of auto-restart attempts when the worker dies.
    """

    def __init__(
        self,
        worker_path: str = "pokemon-showdown/scripts/oracle-worker.js",
        node_path: str = "node",
        timeout_seconds: float = 5.0,
        max_restarts: int = 3,
    ) -> None:
        self._worker_path = worker_path
        self._node_path = node_path
        self._timeout_seconds = timeout_seconds
        self._max_restarts = max_restarts
        self._process: Optional[subprocess.Popen] = None
        self._closed = False

        # Verify that the Showdown dist build exists before spawning.
        self._verify_dist()

        # Spawn the worker subprocess.
        self._spawn()

        # Register atexit cleanup so the subprocess is killed on interpreter
        # exit even if close() is never called explicitly.
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send a request to the worker and return the parsed response.

        Returns ``None`` on *any* failure (timeout, crash, bad JSON, etc.).
        Never raises an exception to the caller.

        Parameters
        ----------
        payload : dict
            A JSON-serializable request dict (see oracle-worker protocol).

        Returns
        -------
        dict | None
            The parsed JSON response, or ``None`` on failure.
        """
        if self._closed:
            logger.warning("query() called after close(); returning None")
            return None

        for attempt in range(self._max_restarts + 1):
            # Check / restart the subprocess if needed.
            if not self._is_alive():
                if attempt >= self._max_restarts:
                    logger.error(
                        "Worker dead and max_restarts (%d) exhausted",
                        self._max_restarts,
                    )
                    return None
                logger.info(
                    "Worker dead (attempt %d/%d), restarting",
                    attempt + 1,
                    self._max_restarts,
                )
                try:
                    self._spawn()
                except Exception as exc:
                    logger.error("Failed to restart worker: %s", exc)
                    return None

            # Send the request.
            try:
                line = json.dumps(payload, separators=(",", ":")) + "\n"
                assert self._process is not None
                assert self._process.stdin is not None
                self._process.stdin.write(line.encode("utf-8"))
                self._process.stdin.flush()
            except Exception as exc:
                logger.warning("Failed to write to worker stdin: %s", exc)
                self._kill_worker()
                continue

            # Read the response with timeout.
            try:
                response_line = self._read_line_with_timeout()
                if response_line is None:
                    logger.warning(
                        "Worker read timed out after %.1fs", self._timeout_seconds
                    )
                    self._kill_worker()
                    continue
                result = json.loads(response_line)
                return result
            except json.JSONDecodeError as exc:
                logger.warning("Worker returned invalid JSON: %s", exc)
                return None
            except Exception as exc:
                logger.warning("Error reading worker response: %s", exc)
                self._kill_worker()
                continue

        # Exhausted all restart attempts.
        return None

    def close(self) -> None:
        """Terminate the worker subprocess cleanly."""
        if self._closed:
            return
        self._closed = True
        self._kill_worker()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> ShowdownOracle:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Destructor (backup cleanup)
    # ------------------------------------------------------------------

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _verify_dist(self) -> None:
        """Raise FileNotFoundError if the Showdown dist build is missing."""
        # Derive the dist path relative to the worker script.
        # worker_path is like "pokemon-showdown/scripts/oracle-worker.js"
        # dist is at "pokemon-showdown/dist/sim/battle.js"
        worker_dir = os.path.dirname(os.path.abspath(self._worker_path))
        showdown_root = os.path.dirname(worker_dir)  # pokemon-showdown/
        battle_js = os.path.join(showdown_root, "dist", "sim", "battle.js")

        if not os.path.isfile(battle_js):
            raise FileNotFoundError(
                f"Showdown dist not found at {battle_js}. "
                "Run 'cd pokemon-showdown && npm install && npm run build' first."
            )

    def _spawn(self) -> None:
        """Spawn (or re-spawn) the worker subprocess."""
        # Kill any existing process first.
        self._kill_worker()

        abs_worker = os.path.abspath(self._worker_path)
        logger.info("Spawning oracle worker: %s %s", self._node_path, abs_worker)

        self._process = subprocess.Popen(
            [self._node_path, abs_worker],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._closed = False

    def _is_alive(self) -> bool:
        """Return True if the worker subprocess is running."""
        return self._process is not None and self._process.poll() is None

    def _kill_worker(self) -> None:
        """Terminate the worker subprocess (SIGTERM then SIGKILL)."""
        if self._process is None:
            return
        try:
            if self._process.poll() is None:
                # Try SIGTERM first.
                self._process.terminate()
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    # Force kill.
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        except Exception as exc:
            logger.debug("Error killing worker: %s", exc)
        finally:
            self._process = None

    def _read_line_with_timeout(self) -> Optional[str]:
        """Read one newline-terminated line from stdout with timeout.

        Returns ``None`` on timeout.
        """
        assert self._process is not None
        assert self._process.stdout is not None

        deadline = time.monotonic() + self._timeout_seconds
        buf = bytearray()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            # Use a small poll interval so we don't block past the deadline.
            chunk = self._process.stdout.read(1)
            if chunk is None:
                return None
            if not chunk:
                # EOF — worker probably died.
                return None

            buf.extend(chunk)
            if chunk == b"\n":
                return buf.decode("utf-8").strip()
