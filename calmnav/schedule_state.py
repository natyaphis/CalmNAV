from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import requests

from calmnav.config import Settings

GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class ScheduleDecision:
    should_send: bool
    reason: str


def should_send_slot(settings: Settings, slot_key: str) -> ScheduleDecision:
    if not settings.github_repository or not settings.github_token:
        return ScheduleDecision(True, "GitHub state unavailable; sending without dedupe.")

    state = _read_state(settings)
    sent_slots = state.get("sent_slots", [])
    if slot_key in sent_slots:
        return ScheduleDecision(False, f"Slot {slot_key} already sent.")
    return ScheduleDecision(True, f"Slot {slot_key} not yet sent.")


def mark_slot_sent(settings: Settings, slot_key: str) -> None:
    if not settings.github_repository or not settings.github_token:
        return

    state, sha = _read_state(settings, include_sha=True)
    sent_slots = [slot for slot in state.get("sent_slots", []) if slot != slot_key]
    sent_slots.insert(0, slot_key)
    state["sent_slots"] = sent_slots[:20]
    _write_state(settings, state, sha)


def _read_state(settings: Settings, include_sha: bool = False) -> Any:
    _ensure_branch(settings)
    url = f"{GITHUB_API_BASE}/repos/{settings.github_repository}/contents/{settings.schedule_state_path}"
    response = requests.get(
        url,
        headers=_headers(settings),
        params={"ref": settings.schedule_state_branch},
        timeout=30,
    )
    if response.status_code == 404:
        state: dict[str, Any] = {"sent_slots": []}
        return (state, None) if include_sha else state

    response.raise_for_status()
    payload = response.json()
    content = payload.get("content", "")
    decoded = base64.b64decode(content).decode("utf-8") if content else "{}"
    state = json.loads(decoded)
    sha = payload.get("sha")
    return (state, sha) if include_sha else state


def _write_state(settings: Settings, state: dict[str, Any], sha: str | None) -> None:
    url = f"{GITHUB_API_BASE}/repos/{settings.github_repository}/contents/{settings.schedule_state_path}"
    payload: dict[str, Any] = {
        "message": f"Update CalmNAV schedule state for {state['sent_slots'][0]}",
        "content": base64.b64encode(json.dumps(state, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": settings.schedule_state_branch,
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=_headers(settings),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def _ensure_branch(settings: Settings) -> None:
    branch_ref = f"heads/{settings.schedule_state_branch}"
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{settings.github_repository}/git/ref/{branch_ref}",
        headers=_headers(settings),
        timeout=30,
    )
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    repo_response = requests.get(
        f"{GITHUB_API_BASE}/repos/{settings.github_repository}",
        headers=_headers(settings),
        timeout=30,
    )
    repo_response.raise_for_status()
    default_branch = repo_response.json()["default_branch"]

    default_ref_response = requests.get(
        f"{GITHUB_API_BASE}/repos/{settings.github_repository}/git/ref/heads/{default_branch}",
        headers=_headers(settings),
        timeout=30,
    )
    default_ref_response.raise_for_status()
    default_sha = default_ref_response.json()["object"]["sha"]

    create_response = requests.post(
        f"{GITHUB_API_BASE}/repos/{settings.github_repository}/git/refs",
        headers=_headers(settings),
        json={"ref": f"refs/{branch_ref}", "sha": default_sha},
        timeout=30,
    )
    if create_response.status_code not in (200, 201, 422):
        create_response.raise_for_status()


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
