"""The Coding Plan reader: three reads, one advisory answer.

The model plane knows nothing about the plan.  The allowance lives on the
control plane, which accepts only the control key the device sign-in stores,
so this probe declares ``credential_role = "control"`` and drives its own
multi-step read.  What it returns is shown on the panel and never demotes a
model credential.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from llm_rosetta_shim_opendesign.providers.opendesign.quota import (
    CONTROL_PLANE,
    PROBES,
    OpenDesignQuota,
    _plan_name,
    _share,
)
from llm_rosetta.shims.quota_probe import (
    QuotaProbeError,
)

# The contract these tests exercise is newer than some cores the package can
# still import on; without it the probe reports "no keyed endpoint" and the
# module below is inert, so the module is skipped rather than failing.
try:
    from llm_rosetta.shims.quota_probe import (  # noqa: F401
        PROBE_ROLE_API_KEY,
        ProbeRefused,
        probe_credential_role,
        probe_fetch,
    )

    HAVE_CONTRACT = True
except ImportError:  # pragma: no cover - a core older than the contract
    HAVE_CONTRACT = False

pytestmark = pytest.mark.skipif(
    not HAVE_CONTRACT, reason="this core predates the second-credential contract"
)

_CONTROL = "vela_ctrl_" + "0" * 32


class _Reads:
    """A stand-in for the gateway's ``read`` callable."""

    def __init__(self, answers: dict[str, tuple[int, Any]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, Any]] = []

    async def __call__(self, url: str, extra: Any = None) -> tuple[int, Any]:
        self.calls.append((url, extra))
        for suffix, answer in self.answers.items():
            if url.endswith(suffix):
                return answer
        return 404, {"error": {"message": "no such route"}}


def _iso(hours: int) -> str:
    """A reset *hours* from now: a fixed date turns stale the day it passes."""
    moment = datetime.now(timezone.utc) + timedelta(hours=hours)
    return moment.isoformat().replace("+00:00", "Z")


def _preflight(**overrides: Any) -> dict[str, Any]:
    body = {
        "codingPlan": {
            "windows": [
                {
                    "durationSeconds": 18000,
                    "usedCredits": 25,
                    "limitCredits": 100,
                    "resetsAt": _iso(2),
                    "eligible": True,
                },
                {
                    "durationSeconds": 604800,
                    "usedCredits": 90,
                    "limitCredits": 100,
                    "resetsAt": _iso(96),
                    "eligible": True,
                },
            ]
        }
    }
    body.update(overrides)
    return body


def _answers(preflight: dict[str, Any] | None = None) -> dict[str, tuple[int, Any]]:
    return {
        "/api/v1/workspaces/current": (200, {"activeWorkspaceId": "ws-1"}),
        "/api/v1/workspaces/ws-1/billing/preflight": (200, preflight or _preflight()),
        "/api/v1/billing/summary": (200, {"tier": "pro"}),
    }


def _recorded_preflight() -> dict[str, Any]:
    """The preflight body production answered on 2026-11-19, same shapes.

    Credit quantities are decimal strings, not JSON numbers.  The reset times
    move with the clock so the fixture cannot turn stale.
    """
    return {
        "balanceUsd": "-0.0808",
        "codingPlan": {
            "eligible": True,
            "tier": "go",
            "windows": [
                {
                    "durationSeconds": 18000,
                    "resetMode": "anchored_recurring",
                    "usedCredits": "0",
                    "limitCredits": "50000",
                    "remainingCredits": "50000",
                    "resetsAt": _iso(2),
                },
                {
                    "durationSeconds": 604800,
                    "resetMode": "anchored_recurring",
                    "usedCredits": "150021",
                    "limitCredits": "150000",
                    "remainingCredits": "0",
                    "resetsAt": _iso(96),
                },
            ],
        },
    }


def _recorded_answers() -> dict[str, tuple[int, Any]]:
    """The answers around the recorded preflight, summary included."""
    answers = _answers(_recorded_preflight())
    answers["/api/v1/billing/summary"] = (
        200,
        {"membershipTier": "go", "balanceUsd": "0.0000"},
    )
    return answers


def _fetch(answers: dict[str, tuple[int, Any]]) -> tuple[str | None, list[Any]]:
    probe = OpenDesignQuota()
    reads = _Reads(answers)
    return asyncio.run(probe.fetch(reads, _CONTROL, CONTROL_PLANE))


class TestTheDeclaration:
    def test_the_probe_is_exported_and_names_its_role(self):
        probe = PROBES[0]

        assert probe.id == "opendesign"
        assert probe_credential_role(probe) == "control"
        assert probe_credential_role(probe) != PROBE_ROLE_API_KEY
        assert probe_fetch(probe) is not None

    def test_the_vendor_match_answers_the_control_plane(self):
        probe = OpenDesignQuota()

        assert probe.match("https://amr-link.open-design.ai/v1") == CONTROL_PLANE
        assert probe.match("https://api.example.test/v1") is None

    def test_the_read_is_signed_with_the_control_key(self):
        headers = OpenDesignQuota().headers(_CONTROL)

        assert headers["Authorization"] == f"Bearer {_CONTROL}"
        # The control plane refuses urllib's default agent (Cloudflare 1010).
        assert headers["User-Agent"].startswith("open-design-cli/")


class TestTheRead:
    def test_both_windows_come_back_with_their_reset_and_span(self):
        plan, windows = _fetch(_answers())

        assert plan == "pro"
        assert [window.name for window in windows] == ["5 hours", "7 days"]
        assert windows[0].used_percent == pytest.approx(25.0)
        assert windows[1].used_percent == pytest.approx(90.0)
        assert windows[0].span_seconds == 18000
        assert windows[1].resets_at is not None

    def test_the_workspace_is_read_first_and_names_the_preflight(self):
        reads = _Reads(_answers())
        asyncio.run(OpenDesignQuota().fetch(reads, _CONTROL, CONTROL_PLANE))

        assert [url for url, _ in reads.calls] == [
            f"{CONTROL_PLANE}/api/v1/workspaces/current",
            f"{CONTROL_PLANE}/api/v1/workspaces/ws-1/billing/preflight",
            f"{CONTROL_PLANE}/api/v1/billing/summary",
        ]

    def test_a_refused_step_carries_the_status_for_the_gateway_to_describe(self):
        answers = _answers()
        answers["/api/v1/workspaces/ws-1/billing/preflight"] = (
            403,
            {"error": "forbidden"},
        )

        with pytest.raises(ProbeRefused) as caught:
            _fetch(answers)

        assert caught.value.status_code == 403

    def test_a_summary_that_fails_costs_only_the_tier(self):
        answers = _answers()
        answers["/api/v1/billing/summary"] = (500, {"error": "boom"})

        plan, windows = _fetch(answers)

        assert plan is None
        assert len(windows) == 2

    def test_no_workspace_is_an_error_the_operator_can_act_on(self):
        answers = _answers()
        answers["/api/v1/workspaces/current"] = (200, {})

        with pytest.raises(QuotaProbeError, match="workspace"):
            _fetch(answers)

    def test_no_window_is_an_error_rather_than_an_empty_reading(self):
        answers = _answers()
        answers["/api/v1/workspaces/ws-1/billing/preflight"] = (200, {"codingPlan": {}})

        with pytest.raises(QuotaProbeError, match="no Coding Plan window"):
            _fetch(answers)

    def test_an_ineligible_window_reads_exhausted(self):
        body = _preflight()
        body["codingPlan"]["windows"][0]["eligible"] = False

        _plan, windows = _fetch(_answers(body))

        assert windows[0].exhausted is True
        assert windows[1].exhausted is False


class TestTheRecordedPayload:
    """The shapes production answered, not a tidied version of them.

    The vendor writes credit quantities as decimal strings.  A decoder that
    accepts only JSON numbers reads a spent plan as "no data" and leaves the
    panel green while the model plane answers 402.
    """

    def test_the_decimal_string_quantities_decode(self):
        plan, windows = _fetch(_recorded_answers())

        assert plan == "go"
        assert [window.name for window in windows] == ["5 hours", "7 days"]
        assert windows[0].used_percent == pytest.approx(0.0)
        assert windows[1].used_percent == pytest.approx(100.0)

    def test_the_over_limit_window_is_exhausted(self):
        """150021/150000 is 100.014%: remaining 0, and the dot must be red."""
        _plan, windows = _fetch(_recorded_answers())

        assert windows[0].exhausted is False
        assert windows[1].exhausted is True

    def test_a_string_quantity_is_a_number(self):
        """Red if ``_share`` goes back to accepting only int/float."""
        assert _share("0", "50000") == pytest.approx(0.0)
        assert _share("150021", "150000") == pytest.approx(100.0)

    def test_what_is_not_a_number_stays_unmeasured(self):
        assert _share("many", "50000") is None
        assert _share("0", "0") is None
        assert _share("0", "-1") is None
        assert _share(True, 100) is None
        assert _share(None, 100) is None

    def test_the_plan_name_is_the_membership_tier(self):
        assert _plan_name({"membershipTier": "go"}) == "go"


class TestTheDirectParse:
    def test_a_preflight_answer_parses_on_its_own(self):
        plan, windows = OpenDesignQuota().parse(_preflight(balanceUsd=12.5))

        assert plan == "balance $12.50"
        assert len(windows) == 2

    def test_the_recorded_string_balance_parses_on_its_own(self):
        plan, windows = OpenDesignQuota().parse(_recorded_preflight())

        assert plan == "balance $-0.08"
        assert len(windows) == 2

    def test_an_answer_without_a_window_is_refused(self):
        with pytest.raises(QuotaProbeError):
            OpenDesignQuota().parse({"codingPlan": {}})


class TestWhatItWillNotDo:
    def test_no_in_band_signal_is_claimed(self):
        """The model plane's refusal shapes are unmeasured; a guess would demote."""
        assert OpenDesignQuota().inband(429, {"error": "rate limited"}) is None

    def test_a_refused_key_says_to_sign_in_again(self):
        described = OpenDesignQuota().describe_error(401, {"error": "invalid key"})

        assert "sign in again" in described


def test_a_core_without_the_contract_gets_no_endpoint(monkeypatch):
    """An older core would read this probe with the runtime key and get 401.

    Reporting "no keyed endpoint" keeps the lane usable and the panel honest
    on a core that cannot carry the second credential at all.
    """
    import llm_rosetta_shim_opendesign.providers.opendesign.quota as quota

    monkeypatch.setattr(quota, "CONTRACT_AVAILABLE", False)

    probe = quota.OpenDesignQuota()
    assert probe.match("https://amr-link.open-design.ai/v1") == ""
    assert probe.match("https://api.example.test/v1") is None
