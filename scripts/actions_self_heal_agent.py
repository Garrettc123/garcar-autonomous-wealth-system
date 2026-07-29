#!/usr/bin/env python3
"""Self-healing agent for failed/stalled GitHub Actions runs."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error, parse, request


FAIL_CONCLUSIONS = {
    "failure",
    "timed_out",
    "startup_failure",
    "stale",
    "action_required",
}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


class GitHubApi:
    def __init__(self, token: str, repository: str) -> None:
        self.token = token
        self.repository = repository
        self.base = f"https://api.github.com/repos/{repository}"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base}{path}",
            data=data,
            method=method.upper(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "garcar-actions-self-heal-agent",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body) if body else {}
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8") if exc.fp else ""
            return exc.code, text
        except Exception as exc:  # pragma: no cover
            return 0, str(exc)

    def list_recent_runs(self, per_page: int = 100) -> list[dict[str, Any]]:
        q = parse.urlencode({"per_page": max(1, min(100, per_page)), "exclude_pull_requests": "true"})
        status, body = self._request("GET", f"/actions/runs?{q}")
        if status != 200 or not isinstance(body, dict):
            return []
        return body.get("workflow_runs", []) or []

    def cancel_run(self, run_id: int) -> bool:
        status, _ = self._request("POST", f"/actions/runs/{run_id}/cancel")
        return status in (202, 409)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        status, body = self._request("GET", f"/actions/runs/{run_id}")
        if status == 200 and isinstance(body, dict):
            return body
        return None

    def rerun_failed_jobs(self, run_id: int) -> bool:
        status, _ = self._request("POST", f"/actions/runs/{run_id}/rerun-failed-jobs")
        return status in (201, 202)

    def rerun(self, run_id: int) -> bool:
        status, _ = self._request("POST", f"/actions/runs/{run_id}/rerun")
        return status in (201, 202)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        print("⚠️ GITHUB_TOKEN or GITHUB_REPOSITORY missing; skipping self-heal.")
        return 0

    lookback_hours = _env_int("LOOKBACK_HOURS", 24)
    stall_threshold_minutes = _env_int("STALL_THRESHOLD_MINUTES", 60)
    max_retry_attempts = _env_int("MAX_RETRY_ATTEMPTS", 3)
    max_runs = _env_int("MAX_RUNS", 100)
    self_workflow_path = os.environ.get(
        "SELF_WORKFLOW_PATH",
        ".github/workflows/actions-self-heal-agent.yml",
    )

    oldest = _now_utc() - timedelta(hours=max(1, lookback_hours))
    api = GitHubApi(token, repository)
    runs = api.list_recent_runs(per_page=max_runs)

    healed: list[str] = []
    unresolved: list[str] = []

    for run in runs:
        run_id = int(run.get("id") or 0)
        if not run_id:
            continue
        run_path = str(run.get("path") or "")
        if run_path == self_workflow_path:
            continue

        name = str(run.get("name") or "unknown")
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        attempt = int(run.get("run_attempt") or 1)
        created_at = _parse_ts(run.get("created_at"))
        updated_at = _parse_ts(run.get("updated_at")) or created_at

        if created_at and created_at < oldest:
            continue
        if attempt >= max_retry_attempts:
            continue

        if status == "in_progress":
            if updated_at:
                age_minutes = (_now_utc() - updated_at).total_seconds() / 60.0
                if age_minutes > stall_threshold_minutes:
                    cancelled = api.cancel_run(run_id)
                    if not cancelled:
                        unresolved.append(f"{name}#{run_id}: stalled, cancel request failed")
                        continue

                    run_completed = False
                    for poll_index in range(6):
                        latest = api.get_run(run_id)
                        latest_status = str((latest or {}).get("status") or "")
                        if latest_status == "completed":
                            run_completed = True
                            break
                        if poll_index < 5:
                            time.sleep(10)

                    if not run_completed:
                        unresolved.append(
                            f"{name}#{run_id}: cancelled stalled run, timed out waiting to rerun"
                        )
                        continue

                    reran = api.rerun(run_id)
                    if reran:
                        healed.append(f"{name}#{run_id}: cancelled stalled run and reran")
                    else:
                        unresolved.append(
                            f"{name}#{run_id}: cancelled stalled run, rerun request failed"
                        )
            continue

        if status == "completed" and conclusion in FAIL_CONCLUSIONS:
            retried = api.rerun_failed_jobs(run_id)
            if not retried:
                retried = api.rerun(run_id)
            if retried:
                healed.append(f"{name}#{run_id}: failure auto-rerun requested")
            else:
                unresolved.append(f"{name}#{run_id}: failure rerun request failed")

    print("\n=== Actions Self-Heal Summary ===")
    print(f"Scanned runs: {len(runs)}")
    print(f"Healed actions: {len(healed)}")
    print(f"Unresolved actions: {len(unresolved)}")
    if healed:
        print("\nHealed:")
        for item in healed:
            print(f"  ✅ {item}")
    if unresolved:
        print("\nUnresolved:")
        for item in unresolved:
            print(f"  ❌ {item}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## 🤖 Actions Self-Heal Agent\n\n")
            f.write(f"- Scanned runs: **{len(runs)}**\n")
            f.write(f"- Healed actions: **{len(healed)}**\n")
            f.write(f"- Unresolved actions: **{len(unresolved)}**\n\n")
            if healed:
                f.write("### Healed\n")
                for item in healed:
                    f.write(f"- ✅ {item}\n")
                f.write("\n")
            if unresolved:
                f.write("### Unresolved\n")
                for item in unresolved:
                    f.write(f"- ❌ {item}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
