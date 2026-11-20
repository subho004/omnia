"""Public chat activity projected from the pinned native protocol, never raw RPC data."""

import re

from .presentation import public_text

STARTUP = {
    "preparing_workspace": "Preparing workspace",
    "naming_worktree": "Naming workspace",
    "creating_worktree": "Creating workspace",
    "running_setup": "Running setup",
    "provisioning_environment": "Preparing environment",
    "preparing_context": "Preparing context",
    "starting_model": "Starting assistant",
}
EVENTS = frozenset(
    {
        "chat",
        "agent",
        "session.tool",
        "session.message",
        "session.approval",
        "session.operation",
        "session.observer",
        "sessions.changed",
        "task",
        "question.requested",
        "question.resolved",
    }
)
TOOL_LABELS = {
    "exec": "Run command",
    "process": "Manage process",
    "read": "Read file",
    "write": "Write file",
    "edit": "Edit file",
    "apply_patch": "Apply changes",
    "web_search": "Search the web",
    "web_fetch": "Read webpage",
    "browser": "Use browser",
    "sessions_spawn": "Delegate to assistant",
    "sessions_send": "Contact assistant",
    "sessions_list": "Find conversations",
    "sessions_history": "Read conversation",
    "session_status": "Check session",
    "subagents": "Manage assistants",
    "memory_search": "Search memory",
    "memory_get": "Read memory",
    "cron": "Manage automation",
    "message": "Prepare message",
    "image": "Inspect image",
}


def identifier(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value) else None
    )


def text_content(value, limit=12000):
    if isinstance(value, str):
        return public_text(value, limit=limit)
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("text"), str):
        return public_text(value["text"], limit=limit)
    content = value.get("content")
    if not isinstance(content, list):
        return ""
    return public_text(
        "\n".join(
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ),
        limit=limit,
    )


def tool_label(name):
    # Unknown plugin names may contain internal identifiers; keep them generic.
    return TOOL_LABELS.get(name, "Use workspace action")


def command_exit_code(data):
    if data.get("name") != "exec" or not isinstance(data.get("result"), dict):
        return None
    details = data["result"].get("details")
    code = details.get("exitCode") if isinstance(details, dict) else None
    return code if type(code) is int and -65535 <= code <= 65535 else None


def activity_view(payload, *, event="agent"):
    """Return one bounded, allowlisted status. Caller must first check session ownership."""
    if not isinstance(payload, dict):
        return None
    run = identifier(payload.get("runId") or payload.get("clientRunId"))
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    kind = payload.get("stream")
    phase = data.get("phase")
    result = {"kind": "status", "phase": "running", "label": "Working", "terminal": False}
    if run:
        result["run_id"] = run
    for source, target in (("seq", "sequence"), ("ts", "timestamp")):
        if type(payload.get(source)) in (int, float) and payload[source] >= 0:
            result[target] = payload[source]
    item = identifier(data.get("toolCallId") or data.get("itemId") or data.get("id"))
    if item:
        result["item_id"] = item
    detail = ""
    if event in {"question.requested", "question.resolved"}:
        item = identifier(payload.get("id"))
        if not item:
            return None
        phase = "requested" if event == "question.requested" else payload.get("status")
        if phase not in {"requested", "answered", "cancelled", "expired"}:
            return None
        result.update(
            kind="question",
            label={
                "requested": "Waiting for your input",
                "answered": "Input received",
                "cancelled": "Input request cancelled",
                "expired": "Input request expired",
            }[phase],
            terminal=phase != "requested",
        )
        if phase == "requested":
            detail = (
                "Your assistant requested input. Interactive question forms "
                "are not available in this prototype."
            )
        # Never return question text, secret-store bindings, drafts or answers.
    elif event == "chat" and payload.get("state") == "status":
        phase = payload.get("phase")
        result.update(kind="startup", label=STARTUP.get(phase, "Preparing assistant"))
    elif event == "session.operation":
        if payload.get("operation") != "compact":
            return None
        phase = payload.get("phase")
        result.update(kind="compaction", label="Updating conversation context")
        if phase == "end":
            result.update(
                label="Context updated" if payload.get("completed") else "Context update stopped",
                terminal=True,
            )
        item = identifier(payload.get("operationId"))
    elif event == "session.observer":
        # Observer digests are optional summaries, not assistant messages or completion proof.
        result.update(kind="observer", label="Progress update")
        phase = payload.get("health")
        result.update(
            label={
                "on-track": "Making progress",
                "grinding": "Working through the task",
                "stuck": "Task needs attention",
                "waiting-on-user": "Waiting for your input",
                "wrapping-up": "Wrapping up",
                "done": "Task completed",
                "failed": "Task failed",
            }.get(phase, "Progress update"),
            terminal=phase in {"done", "failed"},
        )
        detail = public_text(payload.get("headline") or payload.get("assessment") or "", limit=2000)
        if type(payload.get("revision")) is int:
            result["sequence"] = payload["revision"]
    elif event == "sessions.changed":
        # Session changes are also emitted for title/metadata updates. Only lifecycle is activity.
        phase = payload.get("phase")
        if phase not in {"start", "end", "error"}:
            return None
        kind = "lifecycle"
    elif event == "task":
        task = payload.get("task")
        task = task if isinstance(task, dict) else payload
        phase = task.get("status")
        if phase not in {"queued", "running", "completed", "failed", "cancelled", "timed_out"}:
            return None
        result.update(
            kind="task",
            label={
                "queued": "Delegated task queued",
                "running": "Delegated task running",
                "completed": "Delegated task completed",
                "failed": "Delegated task failed",
                "cancelled": "Delegated task cancelled",
                "timed_out": "Delegated task timed out",
            }[phase],
            terminal=phase not in {"queued", "running"},
        )
        item = identifier(task.get("id") or task.get("taskId"))
        detail = public_text(task.get("progressSummary") or task.get("title") or "", limit=2000)
    elif kind == "tool":
        if not item or phase not in {"start", "update", "input_delta", "result", "review"}:
            return None
        result.update(kind="tool", label=tool_label(data.get("name")))
        if phase == "result":
            exit_code = command_exit_code(data)
            failed = data.get("isError") is True or exit_code not in (None, 0)
            tool_result = data.get("result")
            metadata = tool_result.get("details") if isinstance(tool_result, dict) else None
            blocked = isinstance(metadata, dict) and metadata.get("status") == "blocked"
            result.update(
                terminal=True, outcome="blocked" if blocked else "failed" if failed else "completed"
            )
            detail = (
                "This action was blocked before it ran."
                if blocked
                else f"Command exited with code {exit_code}."
                if exit_code not in (None, 0)
                else "This action failed."
                if failed
                else text_content(data.get("result"))
            )
        elif phase == "update":
            detail = text_content(data.get("partialResult"))
        elif phase == "review":
            # Review payloads and exact commands belong to the one-use review adapter.
            detail = "Checking this action before it continues."
        diff = data.get("diff")
        if isinstance(diff, dict):
            counts = {
                k: diff[k]
                for k in ("added", "removed")
                if type(diff.get(k)) is int and 0 <= diff[k] <= 10000000
            }
            if counts:
                result["changes"] = counts
    elif kind == "thinking":
        # A status is sufficient: do not expose reasoning text, signatures or model internals.
        result.update(kind="thinking", label="Thinking")
    elif kind == "approval":
        result.update(
            kind="approval",
            label="Waiting for your review" if phase == "requested" else "Review decision received",
            terminal=phase == "resolved",
        )
        if approval := identifier(data.get("approvalId")):
            result["approval_id"] = approval
            item = approval
    elif kind == "run_status":
        result.update(kind="startup", label=STARTUP.get(phase, "Preparing assistant"))
    elif kind == "compaction":
        result.update(kind="compaction", label="Updating conversation context")
        if phase == "end":
            retry = data.get("willRetry") is True and data.get("completed") is True
            result.update(
                label="Context updated · retrying"
                if retry
                else "Context updated"
                if data.get("completed")
                else "Context update stopped",
                terminal=not retry,
            )
    elif kind == "fallback" or kind == "lifecycle" and phase in {"fallback", "fallback_cleared"}:
        result.update(
            kind="fallback",
            label="Primary model restored"
            if phase == "fallback_cleared"
            else "Trying another available model",
            terminal=phase == "fallback_cleared",
        )
        # Reasons/attempts can include raw provider diagnostics; never forward them.
    elif kind in {"notice", "codex_app_server.guardian"}:
        result.update(
            kind="notice",
            label={
                "strict_review_required": "Action needs review",
                "warning": "Action warning",
                "started": "Reviewing action",
                "completed": "Action review finished",
            }.get(phase, "Action notice"),
            terminal=phase == "completed",
        )
        status = data.get("status")
        if status in {"approved", "denied", "timedOut", "aborted", "inProgress"}:
            result["outcome"] = {"timedOut": "timed out", "inProgress": "reviewing"}.get(
                status, status
            )
        detail = public_text(data.get("message") or data.get("rationale") or "", limit=2000)
    elif kind == "item":
        item_kind = data.get("kind")
        if item_kind not in {"preamble", "status", "tool", "command", "patch", "answer_candidate"}:
            return None
        result.update(
            kind="progress",
            label={
                "preamble": "Assistant update",
                "status": "Working",
                "tool": "Using workspace action",
                "command": "Running command",
                "patch": "Preparing changes",
                "answer_candidate": "Preparing response",
            }[item_kind],
            terminal=phase == "end",
        )
        detail = public_text(data.get("progressText") or "", limit=4000)
    elif kind == "plan":
        result.update(kind="plan", label="Plan updated")
        steps = data.get("steps")
        if isinstance(steps, list):
            result["steps"] = [
                {
                    "text": public_text(step.get("step", ""), limit=500),
                    "status": step.get("status")
                    if step.get("status") in {"pending", "in_progress", "completed"}
                    else "pending",
                }
                for step in steps[:30]
                if isinstance(step, dict)
            ]
        detail = public_text(data.get("explanation") or "", limit=2000)
    elif kind == "command_output":
        result.update(kind="output", label="Command output", terminal=phase == "end")
        detail = public_text(data.get("delta") or "", limit=12000)
    elif kind == "patch":
        result.update(kind="patch", label="Changes applied", terminal=phase == "end")
        detail = public_text(data.get("summary") or "", limit=2000)
    elif kind == "usage":
        count = data.get("outputTokens")
        if type(count) is not int or not 0 <= count <= 100000000:
            return None
        result.update(kind="usage", label="Generating response", output_tokens=count)
    elif kind == "error":
        result.update(
            kind="recovery",
            label="Live activity interrupted",
            detail="Reconnecting and checking saved conversation history.",
        )
    elif kind not in {"lifecycle"} and event not in {
        "chat",
        "session.operation",
        "session.observer",
        "task",
    }:
        return None
    if kind == "lifecycle":
        labels = {
            "start": "Assistant started",
            "finishing": "Finishing response",
            "end": "Response completed",
            "error": "Response interrupted",
            "waiting-approval": "Waiting for your review",
            "approval-resolved": "Review decision received",
            "waiting-question": "Waiting for your answer",
        }
        if phase not in labels and phase not in {"fallback", "fallback_cleared"}:
            return None
        if phase in labels:
            result.update(
                kind="lifecycle",
                label=labels[phase],
                terminal=phase in {"end", "error", "approval-resolved"},
            )
            if data.get("yielded") is True and data.get("aborted") is not True and phase == "end":
                result.update(label="Waiting for delegated work", terminal=False)
            elif data.get("aborted") is True:
                result.update(label="Response stopped", terminal=True)
        approval = identifier(data.get("approvalId"))
        if approval:
            result["approval_id"] = approval
            item = approval
    result["phase"] = (
        phase if isinstance(phase, str) and re.fullmatch(r"[a-zA-Z_-]{1,64}", phase) else "running"
    )
    if detail:
        result["detail"] = detail
    result["id"] = ":".join(filter(None, [run, result["kind"], item]))[:600]
    if item:
        result["item_id"] = item
    return result


def history_activities(message):
    """Restore transcript tool cards without admitting arbitrary metadata/config objects."""
    if not isinstance(message, dict):
        return []
    metadata = message.get("__openclaw")
    metadata = metadata if isinstance(metadata, dict) else {}
    divider = metadata.get("kind")
    if (
        divider in {"compaction", "reset"}
        or message.get("customType") == "openclaw.context-compaction"
    ):
        return [
            {
                "id": "context:" + str(identifier(message.get("id")) or "recorded"),
                "kind": "context",
                "phase": "recorded",
                "terminal": True,
                "label": "Conversation context reset"
                if divider == "reset"
                else "Conversation context updated",
            }
        ]
    role, content = message.get("role"), message.get("content")
    run = identifier(message.get("runId"))
    output = []
    if role == "assistant" and isinstance(content, list):
        for block in content[:100]:
            if not isinstance(block, dict) or str(block.get("type", "")).lower() not in {
                "toolcall",
                "tool_use",
            }:
                continue
            payload = {
                "runId": run,
                "stream": "tool",
                "data": {
                    "phase": "start",
                    "toolCallId": block.get("id") or block.get("toolCallId"),
                    "name": block.get("name"),
                },
            }
            if view := activity_view(payload):
                view["phase"] = "recorded"
                view["terminal"] = True
                output.append(view)
    if role in {"toolResult", "tool", "toolresult"}:
        payload = {
            "runId": run,
            "stream": "tool",
            "data": {
                "phase": "result",
                "toolCallId": message.get("toolCallId") or message.get("toolUseId"),
                "name": message.get("toolName") or message.get("name"),
                "isError": message.get("isError"),
                "result": {
                    "content": content,
                    "details": {
                        "exitCode": message.get("details", {}).get("exitCode")
                        if isinstance(message.get("details"), dict)
                        else None,
                        "status": "blocked"
                        if isinstance(message.get("details"), dict)
                        and message["details"].get("status") == "blocked"
                        else None,
                    },
                }
                if isinstance(content, list)
                else content,
            },
        }
        if view := activity_view(payload):
            output.append(view)
    return output
