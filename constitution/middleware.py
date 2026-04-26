"""
Phase 1 — FastAPI Middleware
Wires ConstitutionKernel as a mandatory pre-execution gate
for every agent action routed through the orchestrator.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from constitution.constitution_kernel import KERNEL, ConstitutionViolation, Verdict

logger = logging.getLogger("garcar.constitution")

# Paths that carry agent actions and must pass the critique gate
ACTION_PATHS = {
    "/api/agent/execute",
    "/api/agent/dispatch",
    "/api/revenue/trigger",
    "/api/stripe/charge",
    "/api/github/dispatch",
    "/api/zapier/trigger",
}


class ConstitutionMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that intercepts every incoming request on
    ACTION_PATHS, deserialises the body as an action dict, runs it
    through the ConstitutionKernel critique pass, and either
    forwards the request or returns a 403 / 202-escalate response.
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        if request.url.path not in ACTION_PATHS:
            return await call_next(request)

        # --- Read and parse body ---
        raw = await request.body()
        try:
            action: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON in action payload"},
            )

        # --- Critique pass ---
        result = KERNEL.critique(action)
        logger.info(
            "Constitution critique | action=%s verdict=%s hash=%s",
            action.get("action_id"),
            result.verdict.name,
            result.receipt_hash,
        )

        if result.verdict == Verdict.BLOCKED:
            logger.warning(
                "BLOCKED action=%s violations=%s",
                action.get("action_id"),
                result.violations,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error":          "Constitutional violation",
                    "verdict":        result.verdict.name,
                    "violations":     result.violations,
                    "critique":       result.critique_text,
                    "receipt_hash":   result.receipt_hash,
                },
            )

        if result.verdict == Verdict.ESCALATE:
            logger.warning(
                "ESCALATE action=%s violations=%s",
                action.get("action_id"),
                result.violations,
            )
            # Attach receipt headers; downstream handler decides
            request.state.constitution_result = result

        # --- Approved: rebuild request with receipt header ---
        # Re-inject body so call_next can read it
        async def receive():
            return {"type": "http.request", "body": raw}

        request._receive = receive  # type: ignore[attr-defined]
        response = await call_next(request)
        response.headers["X-Constitution-Receipt"] = result.receipt_hash
        response.headers["X-Constitution-Verdict"]  = result.verdict.name
        return response


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_constitution_middleware(app) -> None:
    """Call this in your FastAPI app factory."""
    app.add_middleware(ConstitutionMiddleware)
    logger.info("ConstitutionMiddleware registered on %d action paths",
                len(ACTION_PATHS))
