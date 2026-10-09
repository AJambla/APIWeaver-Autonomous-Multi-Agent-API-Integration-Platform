"""Terminal instrumentation and high-visibility logger for LangGraph agents.

Provides live terminal visibility into:
- Real-time agent status (ACTIVE, COMPLETED, FAILED, FALLBACK, IDLE)
- Execution speed (duration, throughput in tokens/second)
- Idle time between agent nodes and approval gates
- Detailed inputs, outputs, errors, and fallback triggers
"""

from __future__ import annotations

import sys
import time
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# ANSI Color Codes for terminal formatting
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
MAGENTA = "\033[1;35m"
BLUE = "\033[1;34m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class LangGraphAgentLogger:
    """Tracks execution time, throughput, idle states, and fallbacks for graph nodes."""

    def __init__(self) -> None:
        self._node_start_times: dict[str, float] = {}
        self._last_node_end_time: float | None = None

    def _emit(self, text: str) -> None:
        """Prints directly to terminal with flush for immediate live feedback."""
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except (OSError, UnicodeEncodeError) as err:
            logger.debug("terminal_stdout_write_failed", error=str(err))

    def log_start(
        self,
        node_name: str,
        run_id: str,
        details: str = "",
        extra_meta: dict[str, Any] | None = None,
    ) -> float:
        """Logs when an agent begins execution, calculating idle time since previous stage."""
        now = time.perf_counter()
        self._node_start_times[node_name] = now

        idle_str = "None (first stage)"
        idle_seconds = 0.0
        if self._last_node_end_time is not None:
            idle_seconds = now - self._last_node_end_time
            idle_str = f"{idle_seconds:.3f}s"

        run_tag = run_id[:8] if run_id else "unknown"
        display_name = node_name.replace("_", " ").title()

        msg = (
            f"\n{BLUE}[LANGGRAPH]{RESET} {BOLD}▶ [{display_name}]{RESET} {CYAN}STARTED{RESET} "
            f"| Run: {BOLD}{run_tag}{RESET} | State: {GREEN}ACTIVE{RESET} | Idle before node: {idle_str}\n"
            f"          {DIM}Details:{RESET} {details}"
        )
        self._emit(msg)

        logger.info(
            "langgraph_node_started",
            node=node_name,
            run_id=run_id,
            state="ACTIVE",
            idle_seconds=round(idle_seconds, 3),
            details=details,
            **(extra_meta or {}),
        )
        return now

    def log_complete(
        self,
        node_name: str,
        run_id: str,
        tokens_before: int = 0,
        tokens_after: int = 0,
        details: str = "",
        extra_meta: dict[str, Any] | None = None,
    ) -> float:
        """Logs successful node completion with duration and throughput (tokens/sec)."""
        now = time.perf_counter()
        start = self._node_start_times.get(node_name, now)
        duration = max(now - start, 0.001)
        self._last_node_end_time = now

        tokens_delta = max(tokens_after - tokens_before, 0)
        speed_tps = (tokens_delta / duration) if (duration > 0 and tokens_delta > 0) else 0.0
        speed_str = f"{speed_tps:.1f} tokens/s" if speed_tps > 0 else f"{1.0/duration:.1f} ops/s"

        display_name = node_name.replace("_", " ").title()

        msg = (
            f"{GREEN}[LANGGRAPH]{RESET} {BOLD}✔ [{display_name}]{RESET} {GREEN}COMPLETED{RESET} "
            f"| Duration: {BOLD}{duration:.2f}s{RESET} | Speed: {CYAN}{speed_str}{RESET} "
            f"| Tokens: +{tokens_delta}\n"
            f"          {DIM}Result:{RESET} {details}"
        )
        self._emit(msg)

        logger.info(
            "langgraph_node_completed",
            node=node_name,
            run_id=run_id,
            state="COMPLETED",
            duration_seconds=round(duration, 3),
            tokens_used=tokens_delta,
            speed_tokens_per_second=round(speed_tps, 1),
            details=details,
            **(extra_meta or {}),
        )
        return duration

    def log_fallback(
        self,
        node_name: str,
        run_id: str,
        reason: str,
        fallback_action: str = "",
    ) -> None:
        """Logs when an agent activates a fallback due to model error or format issue."""
        run_tag = run_id[:8] if run_id else "unknown"
        display_name = node_name.replace("_", " ").title()

        msg = (
            f"{YELLOW}[LANGGRAPH]{RESET} {BOLD}⚠ [{display_name}]{RESET} {YELLOW}FALLBACK ACTIVATED{RESET} "
            f"| Run: {run_tag}\n"
            f"          {DIM}Reason:{RESET} {reason}\n"
            f"          {DIM}Action:{RESET} {fallback_action or 'Using deterministic schema/template defaults'}"
        )
        self._emit(msg)

        logger.warning(
            "langgraph_node_fallback",
            node=node_name,
            run_id=run_id,
            state="FALLBACK",
            reason=reason,
            fallback_action=fallback_action,
        )

    def log_failure(
        self,
        node_name: str,
        run_id: str,
        error: Exception | str,
        details: str = "",
    ) -> float:
        """Logs when an agent fails with duration and error description."""
        now = time.perf_counter()
        start = self._node_start_times.get(node_name, now)
        duration = max(now - start, 0.001)
        self._last_node_end_time = now

        run_tag = run_id[:8] if run_id else "unknown"
        display_name = node_name.replace("_", " ").title()

        msg = (
            f"{RED}[LANGGRAPH]{RESET} {BOLD}✖ [{display_name}]{RESET} {RED}FAILED{RESET} "
            f"| Duration: {duration:.2f}s | Run: {run_tag}\n"
            f"          {DIM}Error:{RESET} {str(error)}\n"
            f"          {DIM}Details:{RESET} {details or 'Execution halted'}"
        )
        self._emit(msg)

        logger.error(
            "langgraph_node_failed",
            node=node_name,
            run_id=run_id,
            state="FAILED",
            duration_seconds=round(duration, 3),
            error=str(error),
            details=details,
        )
        return duration

    def log_idle(
        self,
        node_name: str,
        run_id: str,
        reason: str,
    ) -> None:
        """Logs when the workflow enters an idle or waiting state (e.g. human approval gate)."""
        now = time.perf_counter()
        self._last_node_end_time = now

        run_tag = run_id[:8] if run_id else "unknown"
        display_name = node_name.replace("_", " ").title()

        msg = (
            f"{MAGENTA}[LANGGRAPH]{RESET} {BOLD}⏸ [{display_name}]{RESET} {MAGENTA}STATE: IDLE / WAITING{RESET} "
            f"| Run: {run_tag}\n"
            f"          {DIM}Reason:{RESET} {reason}"
        )
        self._emit(msg)

        logger.info(
            "langgraph_node_idle",
            node=node_name,
            run_id=run_id,
            state="IDLE",
            reason=reason,
        )

    def log_thought(
        self,
        node_name: str,
        run_id: str,
        message: str,
        action: str | None = None,
    ) -> None:
        """Logs real-time agent thoughts and granular actions to terminal."""
        run_id[:8] if run_id else "unknown"
        display_name = node_name.replace("_", " ").title()
        time_str = time.strftime("%H:%M:%S")
        action_tag = f" {CYAN}({action}){RESET}" if action else ""
        msg = f"  {DIM}[{time_str}]{RESET} {BLUE}▶{RESET} {BOLD}[{display_name}]{RESET}{action_tag} {message}"
        self._emit(msg)

