"""Unit tests for the agent slice's pure logic. No I/O and no model call."""

import pytest

from api.features.agent.logic import PromptRejectedError, api_key_matches, normalize_prompt, to_response


def test_normalize_prompt_strips_whitespace() -> None:
    assert normalize_prompt("  audit checkout-api  ") == "audit checkout-api"


def test_normalize_prompt_rejects_blank() -> None:
    with pytest.raises(PromptRejectedError, match="blank"):
        normalize_prompt(" \n\t ")


@pytest.mark.parametrize(
    ("presented", "expected", "result"),
    [
        ("k" * 40, "k" * 40, True),
        ("k" * 40, "j" * 40, False),
        (None, "k" * 40, False),
        ("k" * 40, None, False),
        ("", "", False),
    ],
)
def test_api_key_matches_fails_closed(presented: str | None, expected: str | None, result: bool) -> None:
    assert api_key_matches(presented, expected) is result


def test_to_response_copies_tool_counts() -> None:
    calls = {"verify_service_slo_compliance": 2}
    response = to_response("ok", "STOP", calls)
    calls["verify_service_slo_compliance"] = 99
    assert response.text == "ok"
    assert response.finish_reason == "STOP"
    assert response.tool_calls == {"verify_service_slo_compliance": 2}
