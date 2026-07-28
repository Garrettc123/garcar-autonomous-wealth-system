#!/usr/bin/env python3
"""Update Notion deployment status database.

Usage:
    python scripts/notion_update_deploy.py <status>

Example:
    python scripts/notion_update_deploy.py live
"""
import os
import sys
import datetime
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DEPLOY_DB_ID = os.environ.get("NOTION_DEPLOY_DB_ID")


def update_deploy_status(status: str) -> None:
    if not NOTION_TOKEN:
        print("⚠️  NOTION_TOKEN not set — skipping Notion update")
        return
    if not NOTION_DEPLOY_DB_ID:
        print("⚠️  NOTION_DEPLOY_DB_ID not set — skipping Notion update")
        return

    headers = {
        "Authorization": "Bearer " + NOTION_TOKEN,
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    repo = os.environ.get("GITHUB_REPOSITORY", "unknown/repo")
    sha = os.environ.get("GITHUB_SHA", "unknown")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    now = datetime.datetime.utcnow().isoformat() + "Z"

    payload = {
        "parent": {"database_id": NOTION_DEPLOY_DB_ID},
        "properties": {
            "Name": {
                "title": [{"text": {"content": f"Deploy {sha[:7]} → {status}"}}]
            },
            "Status": {
                "select": {"name": status}
            },
            "Repository": {
                "rich_text": [{"text": {"content": repo}}]
            },
            "Branch": {
                "rich_text": [{"text": {"content": ref}}]
            },
            "Commit SHA": {
                "rich_text": [{"text": {"content": sha}}]
            },
            "Deployed At": {
                "date": {"start": now}
            },
        },
    }

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if response.status_code in (200, 201):
        print(f"✅ Notion deploy record created — status: {status}")
    else:
        print(f"⚠️  Notion API error {response.status_code}: {response.text}")
        # Non-fatal — do not fail the pipeline
        sys.exit(0)


if __name__ == "__main__":
    status_arg = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    update_deploy_status(status_arg)
