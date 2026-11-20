import pytest

from claw_orchestrator.automations import safe_error


@pytest.mark.parametrize(
    "reason,fragment",
    [
        ("⚠️ API rate limit reached. Please try again later.", "provider's request limit"),
        (
            "429 Rate limit exceeded: free-models-per-day /private/path sk-secret",
            "daily free quota",
        ),
        ("heartbeat skipped: no-route", "No delivery destination"),
        ("request timed out at /private/path", "timed out"),
        ("unknown diagnostic secret /private/path", "cause could not be confirmed"),
    ],
)
def test_automation_failures_have_safe_actionable_messages(reason, fragment):
    result = safe_error(reason)
    assert fragment in result
    assert "/private" not in result and "sk-secret" not in result
    assert "configuration" not in result


def test_no_failure_does_not_create_an_error():
    assert safe_error(None) is None
