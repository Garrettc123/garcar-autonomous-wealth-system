#!/usr/bin/env python3
"""Open a P0 GitHub issue when a critical pipeline step fails.

Usage:
    python scripts/open_p0_issue.py "<title>"

Example:
    python scripts/open_p0_issue.py "Deploy failed on main"
"""
import os
import sys
import datetime
import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")


def open_p0_issue(title: str) -> None:
    if not GITHUB_TOKEN:
        print("⚠️  GITHUB_TOKEN not set — cannot open P0 issue")
        sys.exit(0)
    if not GITHUB_REPOSITORY:
        print("⚠️  GITHUB_REPOSITORY not set — cannot open P0 issue")
        sys.exit(0)

    sha = os.environ.get("GITHUB_SHA", "unknown")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    workflow = os.environ.get("GITHUB_WORKFLOW", "unknown workflow")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    run_url = (
        f"https://github.com/{GITHUB_REPOSITORY}/actions/runs/{run_id}"
        if run_id else "N/A"
    )

    body = (
        f"## 🚨 P0 Incident — {title}\n\n"
        f"| Field | Value |\n"
        f"|---|---|\n"
        f"| **Time** | {now} |\n"
        f"| **Workflow** | {workflow} |\n"
        f"| **Branch** | {ref} |\n"
        f"| **Commit** | `{sha[:7]}` |\n"
        f"| **Run** | [{run_id}]({run_url}) |\n\n"
        f"### Action required\n"
        f"- [ ] Investigate failure in the linked workflow run\n"
        f"- [ ] Verify Railway rollback completed successfully\n"
        f"- [ ] Update this issue with root cause and resolution\n"
    )

    headers = {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "title": f"[P0] {title}",
        "body": body,
        "labels": ["P0", "incident"],
    }

    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if response.status_code == 201:
        issue = response.json()
        print(f"✅ P0 issue opened: {issue.get('html_url')}")
    elif response.status_code == 422:
        # Labels may not exist yet; retry without labels
        payload.pop("labels", None)
        r2 = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if r2.status_code == 201:
            print(f"✅ P0 issue opened (no labels): {r2.json().get('html_url')}")
        else:
            print(f"⚠️  GitHub API error {r2.status_code}: {r2.text}")
    else:
        print(f"⚠️  GitHub API error {response.status_code}: {response.text}")

    # Always exit 0 — issue creation failure must not mask the real failure
    sys.exit(0)


if __name__ == "__main__":
    issue_title = sys.argv[1] if len(sys.argv) > 1 else "Unknown failure"
    open_p0_issue(issue_title)
