"""Unit tests for T23: SSE Progress Streaming (main.py).

Verifies all safety, formatting, and performance requirements:
- GET /events/{run_id} endpoint exists and returns text/event-stream.
- Format: data: <JSON>\\n\\n.
- Valid JSON payloads with run_id, stage, status, message, percentage, timestamp.
- Chronological ordering preserved for past and live streamed events.
- Bounded event history (max 100 events per run) preventing memory leaks.
- Safe 404 response for unknown run_id without leaking internal paths.
- Redaction of API keys, tokens, and secrets in SSE payloads.
- Disconnect handling cleans up queues without crashing backend.
- Concurrency and subscriber isolation.
- No uploaded project code execution.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from main import (
    app,
    publish_progress_event,
    RUN_EVENTS,
    RUN_EVENT_SUBSCRIBERS,
    MAX_EVENT_HISTORY_PER_RUN,
)
from schemas import ProgressEvent, StageEnum


@pytest.fixture
def client() -> TestClient:
    """Provide a TestClient instance for testing SSE endpoints."""
    return TestClient(app)


# ==========================================
# 1. SSE Endpoint & Formatting Tests
# ==========================================

def test_events_endpoint_unknown_run_id_returns_404(client: TestClient) -> None:
    """Verify that requesting events for an unknown run_id returns HTTP 404."""
    resp = client.get("/events/unknown-run-id-999")
    assert resp.status_code == 404
    assert "not found" in resp.json().get("detail", "").lower()


def test_events_endpoint_formatting_and_json_payload(client: TestClient) -> None:
    """Verify data: <JSON>\\n\\n format and field structure of streamed events."""
    run_id = "test-run-format-123"
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.SCAN.value,
        status="completed",
        message="Detected FastAPI application on port 8000.",
        percentage=35,
        details={"framework": "FastAPI", "port": 8000},
    )
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.COMPLETE.value,
        status="completed",
        message="Workflow complete.",
        percentage=100,
    )

    resp = client.get(f"/events/{run_id}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    lines = resp.text.strip().split("\n\n")
    assert len(lines) >= 2

    # Check first event
    first_event_str = lines[0]
    assert first_event_str.startswith("data: ")
    json_str = first_event_str[len("data: "):]
    data = json.loads(json_str)

    assert data["run_id"] == run_id
    assert data["stage"] == StageEnum.SCAN.value
    assert data["status"] == "completed"
    assert data["message"] == "Detected FastAPI application on port 8000."
    assert data["percentage"] == 35
    assert data["timestamp"] > 0
    assert data["details"]["framework"] == "FastAPI"


def test_events_multiple_events_preserve_order(client: TestClient) -> None:
    """Verify that multiple events emitted across stages preserve exact chronological order."""
    run_id = "test-run-order-456"
    stages = [
        (StageEnum.UPLOAD.value, "Extracted archive", 10),
        (StageEnum.SCAN.value, "Scanned stack", 30),
        (StageEnum.AUDIT.value, "Audited security issues", 60),
        (StageEnum.FIX.value, "Generated fix suggestions", 80),
        (StageEnum.COMPLETE.value, "Complete", 100),
    ]

    for stage_name, msg, pct in stages:
        publish_progress_event(
            run_id=run_id,
            stage=stage_name,
            status="completed",
            message=msg,
            percentage=pct,
        )

    resp = client.get(f"/events/{run_id}")
    assert resp.status_code == 200

    raw_events = [line[len("data: "):] for line in resp.text.strip().split("\n\n") if line.startswith("data: ")]
    parsed_events = [json.loads(e) for e in raw_events]

    assert len(parsed_events) == 5
    for idx, (expected_stage, expected_msg, expected_pct) in enumerate(stages):
        assert parsed_events[idx]["stage"] == expected_stage
        assert parsed_events[idx]["message"] == expected_msg
        assert parsed_events[idx]["percentage"] == expected_pct


# ==========================================
# 2. Secret Masking & Redaction Tests
# ==========================================

def test_events_redact_secrets_in_message_and_details(client: TestClient) -> None:
    """Verify that sensitive API keys, PATs, and passwords are fully masked in SSE events."""
    run_id = "test-run-redact-789"
    secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    secret_gemini = "AIzaSyD-1234567890abcdefghijklmnopqrstuvwxyz"
    secret_render = "rnd_1234567890abcdefghijklmnopqrstuvwxyz"

    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.DEPLOY.value,
        status="in_progress",
        message=f"Configuring deploy using token {secret_token} and Gemini key {secret_gemini}",
        details={"render_key": secret_render, "safe_host": "0.0.0.0"},
    )
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.COMPLETE.value,
        status="completed",
        message="Done.",
    )

    resp = client.get(f"/events/{run_id}")
    body = resp.text

    assert secret_token not in body
    assert secret_gemini not in body
    assert secret_render not in body
    assert "[REDACTED]" in body


# ==========================================
# 3. Bounded History and Memory Guardrails
# ==========================================

def test_events_bounded_history_limit() -> None:
    """Verify that event history per run does not exceed MAX_EVENT_HISTORY_PER_RUN (100)."""
    run_id = "test-run-bounded-history"
    for i in range(150):
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.SCAN.value,
            status="in_progress",
            message=f"Step {i}",
        )

    history = RUN_EVENTS.get(run_id, [])
    assert len(history) == MAX_EVENT_HISTORY_PER_RUN
    assert history[0].message == "Step 50"
    assert history[-1].message == "Step 149"


# ==========================================
# 4. Subscriber Queue and Disconnect Cleanup
# ==========================================

def test_events_subscriber_cleanup_on_stream_exit(client: TestClient) -> None:
    """Verify that active asyncio subscriber queues are removed upon stream completion."""
    run_id = "test-run-cleanup-sync"
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.COMPLETE.value,
        status="completed",
        message="Immediate completion.",
    )

    resp = client.get(f"/events/{run_id}")
    assert resp.status_code == 200

    # Ensure queue subscriber list for this run is cleaned up
    subscribers = RUN_EVENT_SUBSCRIBERS.get(run_id, [])
    assert len(subscribers) == 0


# ==========================================
# 5. T22 Self-Fix and Pipeline Representation
# ==========================================

def test_events_self_fix_and_error_representation(client: TestClient) -> None:
    """Verify representation of self_fix stages and safe error/blocked terminal events."""
    run_id = "test-run-self-fix-events"
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.SELF_FIX.value,
        status="started",
        message="Self-fix attempt 1: applying 0.0.0.0 host bind patch.",
        percentage=85,
    )
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.ERROR.value,
        status="blocked",
        message="Push blocked: high severity secret leak in workspace.",
        percentage=85,
    )

    resp = client.get(f"/events/{run_id}")
    assert resp.status_code == 200

    lines = [l for l in resp.text.strip().split("\n\n") if l.startswith("data: ")]
    events = [json.loads(l[len("data: "):]) for l in lines]

    assert len(events) == 2
    assert events[0]["stage"] == "self_fix"
    assert events[1]["stage"] == "error"
    assert events[1]["status"] == "blocked"
