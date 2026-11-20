"""Projection contracts from the installed native chat source, without model calls."""

import json

import pytest

from claw_orchestrator.chat_activity import STARTUP, activity_view, history_activities
from claw_orchestrator.frontend_api import event_view, in_flight_view, message_view

SESSION = "agent:main:activity-check"
FOREIGN = "agent:main:other-conversation"


def envelope(stream="tool", *, event="agent", session=SESSION, **data):
    return {
        "type": "event",
        "event": event,
        "payload": {
            "sessionKey": session,
            "runId": "run-123",
            "seq": 7,
            "ts": 123456,
            "stream": stream,
            "data": data,
        },
    }


@pytest.mark.parametrize("phase,label", STARTUP.items())
def test_native_startup_catalogue_projects_both_status_envelopes(phase, label):
    frame = envelope("run_status", phase=phase)
    view = event_view(frame, SESSION)
    assert view["type"] == "activity"
    assert view["data"]["label"] == label
    assert view["data"]["phase"] == phase
    frame["event"] = "chat"
    frame["payload"].update(state="status", phase=phase)
    view = event_view(frame, SESSION)
    assert view["type"] == "chat"
    assert view["data"]["activity"]["label"] == label


@pytest.mark.parametrize("event", ["agent", "session.tool"])
@pytest.mark.parametrize("phase", ["start", "update", "input_delta", "result", "review"])
def test_native_tool_phases_keep_identity_sequence_and_safe_results(event, phase):
    frame = envelope(
        event=event,
        phase=phase,
        name="read",
        toolCallId="call-1",
        args={"path": "/private/config", "api_key": "secret-arguments"},
        partialResult={"content": [{"type": "text", "text": "Reading selected file"}]},
        result={"content": [{"type": "text", "text": "File inspected"}]},
        diff={"added": 3, "removed": 1, "unknown": "hidden"},
        review={"id": "review-1", "command": "secret command", "credential": "secret-review"},
        provider="hidden-provider",
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "tool" and view["label"] == "Read file"
    assert view["item_id"] == "call-1" and view["run_id"] == "run-123"
    assert view["sequence"] == 7 and view["timestamp"] == 123456
    assert view["phase"] == phase
    assert view["terminal"] is (phase == "result")
    assert view["changes"] == {"added": 3, "removed": 1}
    if phase == "update":
        assert view["detail"] == "Reading selected file"
    elif phase == "result":
        assert view["detail"] == "File inspected" and view["outcome"] == "completed"
    elif phase == "review":
        assert view["detail"] == "Checking this action before it continues."
    serialized = json.dumps(view)
    for private in ["secret-arguments", "secret-review", "secret command", "hidden-provider"]:
        assert private not in serialized
    assert "args" not in view and "review" not in view


def test_failed_tool_does_not_forward_raw_provider_failure():
    view = activity_view(
        {
            "runId": "r",
            "stream": "tool",
            "data": {
                "phase": "result",
                "name": "exec",
                "toolCallId": "t",
                "isError": True,
                "result": "provider secret and stack trace",
                "toolErrorSummary": "private",
            },
        }
    )
    assert view["outcome"] == "failed" and view["terminal"] is True
    assert view["detail"] == "This action failed."
    assert "provider secret" not in json.dumps(view)


def test_nonzero_command_exit_is_failed_even_when_native_is_error_is_false():
    message = {
        "role": "toolResult",
        "toolCallId": "failed-command",
        "toolName": "exec",
        "isError": False,
        "content": [{"type": "text", "text": "private diagnostic stack"}],
        "details": {"status": "completed", "exitCode": 1, "cwd": "/private/runtime"},
    }
    view = history_activities(message)[0]
    assert view["outcome"] == "failed"
    assert view["detail"] == "Command exited with code 1."
    assert "private" not in json.dumps(view)
    live = activity_view(
        {
            "stream": "tool",
            "data": {
                "phase": "result",
                "toolCallId": "failed-command",
                "name": "exec",
                "isError": False,
                "result": {"details": {"exitCode": 1}},
            },
        }
    )
    assert live["outcome"] == "failed" and live["detail"] == view["detail"]


def test_warning_text_does_not_fail_a_successful_command():
    view = history_activities(
        {
            "role": "toolResult",
            "toolCallId": "successful-command",
            "toolName": "exec",
            "isError": False,
            "content": [{"type": "text", "text": "oom_score_adj: Permission denied\nDone"}],
            "details": {"exitCode": 0},
        }
    )[0]
    assert view["outcome"] == "completed" and "Done" in view["detail"]


def test_exit_metadata_is_not_interpreted_for_unrelated_tools():
    view = history_activities(
        {
            "role": "toolResult",
            "toolCallId": "read-command",
            "toolName": "read",
            "isError": False,
            "content": [{"type": "text", "text": "Read complete"}],
            "details": {"exitCode": 1},
        }
    )[0]
    assert view["outcome"] == "completed"


@pytest.mark.parametrize(
    "event",
    ["agent", "session.tool", "session.observer", "session.operation", "sessions.changed", "chat"],
)
@pytest.mark.parametrize("selection", [FOREIGN, None])
def test_live_events_require_exact_session_not_parent_hint(event, selection):
    frame = envelope("lifecycle", event=event, session=selection, phase="start")
    frame["payload"]["spawnedBy"] = SESSION
    assert event_view(frame, SESSION) is None
    frame["payload"].pop("sessionKey")
    assert event_view(frame, SESSION) is None


def test_nested_task_scope_is_required_and_not_outer_or_child_scope():
    frame = envelope(event="task")
    frame["payload"]["task"] = {
        "id": "task-1",
        "sessionKey": SESSION,
        "childSessionKey": FOREIGN,
        "status": "running",
        "title": "Inspect selected file",
        "config": "hidden-config",
    }
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "task" and view["item_id"] == "task-1"
    assert view["detail"] == "Inspect selected file" and not view["terminal"]
    assert "hidden-config" not in json.dumps(view)
    assert event_view(frame, FOREIGN) is None
    frame["payload"]["task"]["sessionKey"] = FOREIGN
    assert event_view(frame, SESSION) is None
    frame["payload"]["task"].pop("sessionKey")
    assert event_view(frame, SESSION) is None
    frame["payload"].pop("task")
    frame["payload"].update(action="deleted", taskId="task-1")
    assert event_view(frame, SESSION) is None


@pytest.mark.parametrize("stream", ["configuration", "credentials", "unknown-plugin", ""])
def test_unknown_agent_streams_are_not_public(stream):
    assert event_view(envelope(stream, secret="hidden"), SESSION) is None


def test_thinking_reports_only_status_without_reasoning_or_signatures():
    frame = envelope(
        "thinking",
        text="private reasoning",
        delta="private delta",
        progressTokens=17,
        thinkingSignature="signature",
        provider="private-model",
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "thinking" and view["label"] == "Thinking"
    assert "detail" not in view
    for hidden in ["private reasoning", "private delta", "signature", "private-model"]:
        assert hidden not in json.dumps(view)


def test_public_narrative_neutralizes_brand_credentials_and_private_runtime_paths():
    frame = envelope(
        "item",
        kind="preamble",
        phase="update",
        itemId="commentary-1",
        progressText=(
            "OpenClaw checked /sandbox/.openclaw/openclaw.json. "
            "api_key=secret-value Bearer ABCDEFGHIJKLMN sk-test-12345678901234567890"
        ),
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "progress" and view["item_id"] == "commentary-1"
    assert "Morrow" in view["detail"]
    for private in ["openclaw", "secret-value", "ABCDEFGHIJKLMN", "12345678901234567890"]:
        assert private.lower() not in json.dumps(view).lower()
    assert "[private credential]" in view["detail"]
    assert "[private workspace configuration]" in view["detail"]


@pytest.mark.parametrize(
    "health,terminal",
    [
        ("on-track", False),
        ("grinding", False),
        ("stuck", False),
        ("waiting-on-user", False),
        ("wrapping-up", False),
        ("done", True),
        ("failed", True),
    ],
)
def test_observer_health_is_optional_summary_not_chat_message(health, terminal):
    frame = envelope(event="session.observer")
    frame["payload"].update(health=health, headline="Checking selected results", revision=3)
    view = event_view(frame, SESSION)
    assert view["type"] == "activity" and view["data"]["kind"] == "observer"
    assert view["data"]["phase"] == health
    assert view["data"]["terminal"] is terminal
    assert view["data"]["detail"] == "Checking selected results"


def test_plan_is_bounded_and_keeps_typed_steps():
    frame = envelope(
        "plan",
        phase="update",
        explanation="OpenClaw is checking the result",
        steps=[
            {"step": "Inspect", "status": "completed", "private": "hidden"},
            {"step": "Verify", "status": "in_progress"},
            {"step": "Finish", "status": "unexpected"},
        ]
        + [{"step": "Extra", "status": "pending"}] * 40,
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "plan" and len(view["steps"]) == 30
    assert view["steps"][:3] == [
        {"text": "Inspect", "status": "completed"},
        {"text": "Verify", "status": "in_progress"},
        {"text": "Finish", "status": "pending"},
    ]
    assert view["detail"] == "Morrow is checking the result"
    assert "hidden" not in json.dumps(view)


def test_compaction_retry_is_not_terminal_and_manual_compaction_is_supported():
    frame = envelope(
        "compaction", phase="end", completed=True, willRetry=True, reason="private reason"
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "compaction" and not view["terminal"]
    assert "retrying" in view["label"] and "private reason" not in json.dumps(view)
    frame["payload"]["data"]["willRetry"] = False
    assert event_view(frame, SESSION)["data"]["terminal"] is True
    frame = envelope(event="session.operation")
    frame["payload"].update(
        operation="compact", operationId="compact-1", phase="end", completed=True
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "compaction" and view["item_id"] == "compact-1"
    assert view["terminal"] is True
    frame["payload"]["operation"] = "config.change"
    assert event_view(frame, SESSION) is None


@pytest.mark.parametrize("phase", ["fallback", "fallback_cleared"])
def test_model_route_notice_does_not_expose_provider_diagnostics(phase):
    frame = envelope(
        "lifecycle",
        phase=phase,
        reason="provider secret",
        provider="hidden-provider",
        attempts=["secret attempt"],
    )
    view = event_view(frame, SESSION)["data"]
    assert view["kind"] == "fallback"
    assert view["terminal"] is (phase == "fallback_cleared")
    for private in ["provider secret", "hidden-provider", "secret attempt"]:
        assert private not in json.dumps(view)


def test_yield_and_waiting_lifecycle_do_not_claim_response_completion():
    frame = envelope(
        "lifecycle", phase="end", yielded=True, livenessState="paused", stopReason="end_turn"
    )
    view = event_view(frame, SESSION)["data"]
    assert view["terminal"] is False and "Waiting" in view["label"]
    frame = envelope("lifecycle", phase="waiting-question")
    assert event_view(frame, SESSION)["data"]["label"] == "Waiting for your answer"
    frame = envelope("lifecycle", phase="end", aborted=True)
    view = event_view(frame, SESSION)["data"]
    assert view["terminal"] is True and view["label"] == "Response stopped"


def test_terminal_history_tools_restore_without_arguments_or_reasoning():
    call = {
        "role": "assistant",
        "runId": "r",
        "content": [
            {"type": "thinking", "thinking": "hidden reasoning", "thinkingSignature": "hidden"},
            {"type": "text", "text": "OpenClaw inspected it"},
            {
                "type": "toolCall",
                "id": "t",
                "name": "read",
                "arguments": {"path": "/private/runtime", "password": "hidden argument"},
            },
        ],
        "provider": "hidden provider",
    }
    view = message_view(call)
    assert view["role"] == "assistant" and view["text"] == "Morrow inspected it"
    assert view["activities"][0]["phase"] == "recorded"
    assert view["activities"][0]["terminal"] is True
    result = message_view(
        {
            "role": "toolResult",
            "toolCallId": "t",
            "toolName": "read",
            "isError": False,
            "content": [{"type": "text", "text": "Selected file inspected"}],
            "details": {"api_key": "hidden result metadata"},
        }
    )
    assert result["role"] == "activity" and result["text"] == ""
    assert result["activities"][0]["outcome"] == "completed"
    assert result["activities"][0]["detail"] == "Selected file inspected"
    for private in [
        "hidden reasoning",
        "hidden argument",
        "hidden provider",
        "hidden result metadata",
    ]:
        assert private not in json.dumps([view, result])
    assert history_activities({"role": "user", "content": call["content"]}) == []


def test_in_flight_projection_keeps_own_activity_and_rejects_foreign_events():
    own = envelope(phase="update", name="read", toolCallId="own", partialResult="Reading own file")[
        "payload"
    ]
    foreign = envelope(
        session=FOREIGN,
        phase="result",
        name="read",
        toolCallId="foreign",
        result="foreign private result",
    )["payload"]
    snapshot = in_flight_view(
        {
            "runId": "run-123",
            "text": "OpenClaw is working",
            "events": [own, foreign],
            "config": {"api_key": "hidden snapshot"},
        },
        SESSION,
    )
    assert snapshot["run_id"] == "run-123" and snapshot["text"] == "Morrow is working"
    assert len(snapshot["activities"]) == 1
    assert snapshot["activities"][0]["item_id"] == "own"
    assert "foreign private result" not in json.dumps(snapshot)
    assert "hidden snapshot" not in json.dumps(snapshot)
    assert in_flight_view(None, SESSION) is None
    assert in_flight_view({"events": [own]}, SESSION) is None


def test_normalizer_preserves_native_sequence_for_consumer_deduplication():
    first = envelope("item", phase="update", kind="preamble", itemId="p", progressText="First")
    second = envelope("item", phase="update", kind="preamble", itemId="p", progressText="Second")
    second["payload"]["seq"] = 8
    one, two = event_view(first, SESSION)["data"], event_view(second, SESSION)["data"]
    assert one["id"] == two["id"] and (one["sequence"], two["sequence"]) == (7, 8)


def question_frame(event="question.requested", *, session=SESSION, status="pending"):
    return {
        "type": "event",
        "event": event,
        "payload": {
            "id": "question-1",
            "runId": "run-123",
            "sessionKey": session,
            "status": status,
            "questions": [
                {
                    "questionId": "q1",
                    "question": "secret prompt text",
                    "isSecret": True,
                    "secretStore": {"binding": "private binding"},
                }
            ],
            "drafts": {"q1": "private draft"},
            "answers": {"q1": ["private answer"]},
            "binding": "private outer binding",
        },
    }


def test_question_request_is_generic_waiting_status_without_secret_question_material():
    view = event_view(question_frame(), SESSION)
    assert view["type"] == "activity"
    result = view["data"]
    assert result["kind"] == "question" and result["phase"] == "requested"
    assert result["label"] == "Waiting for your input" and result["terminal"] is False
    assert result["item_id"] == "question-1" and result["run_id"] == "run-123"
    assert "not available in this prototype" in result["detail"]
    for private in [
        "secret prompt text",
        "private binding",
        "private draft",
        "private answer",
        "private outer binding",
        "secretStore",
        "questions",
        "drafts",
        "answers",
    ]:
        assert private not in json.dumps(result)


@pytest.mark.parametrize(
    "status,label",
    [
        ("answered", "Input received"),
        ("cancelled", "Input request cancelled"),
        ("expired", "Input request expired"),
    ],
)
def test_question_resolution_updates_same_card_and_keeps_answers_private(status, label):
    requested = event_view(question_frame(), SESSION)["data"]
    resolved = event_view(question_frame("question.resolved", status=status), SESSION)["data"]
    assert resolved["id"] == requested["id"]
    assert resolved["kind"] == "question" and resolved["phase"] == status
    assert resolved["label"] == label and resolved["terminal"] is True
    assert "detail" not in resolved
    assert "private answer" not in json.dumps(resolved)


@pytest.mark.parametrize("event", ["question.requested", "question.resolved"])
@pytest.mark.parametrize("selection", [FOREIGN, None])
def test_question_events_cannot_adopt_ids_or_spawned_by_as_session_authority(event, selection):
    # A pure projector must not remember a prior question ID and bypass ownership.
    assert event_view(question_frame(), SESSION) is not None
    frame = question_frame(event, session=selection, status="answered")
    frame["payload"]["spawnedBy"] = SESSION
    assert event_view(frame, SESSION) is None
    frame["payload"].pop("sessionKey")
    assert event_view(frame, SESSION) is None


@pytest.mark.parametrize("status", ["pending", "unknown", "secret answer", None])
def test_unknown_question_resolution_states_are_not_public(status):
    assert event_view(question_frame("question.resolved", status=status), SESSION) is None


@pytest.mark.parametrize(
    "metadata,label",
    [
        ({"__openclaw": {"kind": "compaction"}}, "Conversation context updated"),
        ({"__openclaw": {"kind": "reset"}}, "Conversation context reset"),
        ({"customType": "openclaw.context-compaction"}, "Conversation context updated"),
    ],
)
def test_known_context_history_dividers_use_generic_labels_and_no_raw_metadata(metadata, label):
    message = {
        "id": "context-1",
        "role": "custom",
        "content": "private compaction summary",
        "provider": "private provider",
        **metadata,
    }
    if "__openclaw" in message:
        message["__openclaw"]["secret"] = "private metadata"
    view = message_view(message)
    assert view["role"] == "activity" and view["text"] == ""
    assert len(view["activities"]) == 1
    activity = view["activities"][0]
    assert activity["id"] == "context:context-1"
    assert activity["label"] == label and activity["kind"] == "context"
    assert activity["phase"] == "recorded" and activity["terminal"] is True
    for private in [
        "private compaction summary",
        "private provider",
        "private metadata",
        "openclaw",
    ]:
        assert private not in json.dumps(view).lower()


def test_unknown_custom_history_does_not_become_context_activity():
    assert (
        message_view(
            {
                "role": "custom",
                "id": "custom-1",
                "content": "private custom data",
                "customType": "unknown.plugin",
                "__openclaw": {"kind": "configuration"},
            }
        )
        is None
    )


def test_in_flight_started_at_is_preserved_and_foreign_run_events_are_rejected():
    own = envelope(
        "item", phase="update", kind="preamble", itemId="own", progressText="Current run progress"
    )["payload"]
    stale_run = envelope(
        "item",
        phase="update",
        kind="preamble",
        itemId="stale",
        progressText="Private previous run progress",
    )["payload"]
    stale_run["runId"] = "old-run"
    snapshot = in_flight_view(
        {
            "runId": "run-123",
            "startedAt": 1234567890,
            "events": [own, stale_run],
        },
        SESSION,
    )
    assert snapshot["started_at"] == 1234567890
    assert len(snapshot["activities"]) == 1
    assert snapshot["activities"][0]["item_id"] == "own"
    assert "Private previous run progress" not in json.dumps(snapshot)


def test_native_policy_block_is_not_presented_as_completed_or_reviewable():
    message = {
        "role": "toolResult",
        "toolCallId": "blocked-browser",
        "toolName": "browser",
        "isError": False,
        "content": [{"type": "text", "text": "private policy detail"}],
        "details": {
            "status": "blocked",
            "deniedReason": "plugin-before-tool-call",
            "reason": "private policy detail",
            "approvalId": "not-a-review",
        },
    }
    history = history_activities(message)[0]
    live = activity_view(
        {
            "stream": "tool",
            "data": {
                "phase": "result",
                "toolCallId": "blocked-browser",
                "name": "browser",
                "isError": False,
                "result": {"content": message["content"], "details": message["details"]},
            },
        }
    )
    for view in (history, live):
        assert view["outcome"] == "blocked" and view["terminal"] is True
        assert view["detail"] == "This action was blocked before it ran."
        assert "private" not in json.dumps(view)
        assert "approval" not in json.dumps(view)
