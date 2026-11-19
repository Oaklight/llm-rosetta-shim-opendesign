"""Open Design Cloud — the Coding Plan allowance, read on the control plane.

The model plane knows nothing about the plan.  The allowance is reported by
the control plane (``https://amr-api.open-design.ai``), which refuses the
runtime key and accepts only the control key ``vela_ctrl_…`` that the device
sign-in in ``auth.py`` stores beside it.

So this probe declares ``credential_role = "control"``.  The gateway asks the
exchange for that role, and marks the reading **advisory**: it is shown on the
panel and may weight a lane's share, but it never demotes, excludes or dates a
model credential, because those decisions are about the key the requests send.

The read takes three requests, which is why it is a ``fetch`` rather than the
one GET the contract assumes by default:

1. ``GET /api/v1/workspaces/current`` → ``activeWorkspaceId``;
2. ``GET /api/v1/workspaces/{id}/billing/preflight`` → the Coding Plan windows
   (``usedCredits`` / ``limitCredits`` / ``durationSeconds`` / ``resetsAt``)
   and the credit balance;
3. ``GET /api/v1/billing/summary`` → membership tier (optional: a refusal
   there costs the plan name, not the reading).

The loader executes this file as a **flat module**: standard library only,
no relative or sibling imports.
"""

from __future__ import annotations

import math
from typing import Any

from llm_rosetta.shims.quota_probe import (
    QuotaProbeError,
    QuotaWindow,
    parse_iso,
    vendor_message,
)

#: Whether the core carries the second-credential contract (``credential_role``
#: and multi-step ``fetch``).  A core without it would read this probe with the
#: runtime key, which the control plane answers with 401, so the probe reports
#: the lane as having no endpoint instead: the panel then says the allowance is
#: unsupported, which is the truth on that core.  The dependency floor moves to
#: the dev that carries the contract; until then this file has to import.
try:
    from llm_rosetta.shims.quota_probe import ProbeRefused

    CONTRACT_AVAILABLE = True
except ImportError:  # pragma: no cover - taken only on a core older than the contract
    CONTRACT_AVAILABLE = False

    class ProbeRefused(Exception):  # type: ignore[no-redef]
        """Stand-in: nothing raises it when the contract is absent."""


CONTROL_PLANE = "https://amr-api.open-design.ai"

#: The control plane sits behind a CDN that refuses urllib's default agent
#: (Cloudflare 1010), so every request names a client.
USER_AGENT = "open-design-cli/0.1.4"

#: Window names for the spans the plan reports.  A vendor is free to add one;
#: anything unlisted is named by its length instead of guessed at.
_SPANS: dict[int, str] = {18000: "5 hours", 604800: "7 days"}


def _span_name(seconds: Any) -> str:
    """Return the human name of a window length."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "allowance"
    whole = int(seconds)
    return _SPANS.get(whole, f"{whole // 3600}h" if whole >= 3600 else f"{whole}s")


def _number(value: Any) -> float | None:
    """Return *value* as a finite number, or ``None`` when it is not one.

    The vendor encodes credit quantities as decimal strings (``"150021"``,
    ``"0"``), so a JSON number and its string spelling are both accepted.  A
    bool is not a quantity here, and neither is a string that does not spell
    a finite number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _share(used: Any, limit: Any) -> float | None:
    """Return the used share of one window as a percentage, or ``None``."""
    numerator = _number(used)
    denominator = _number(limit)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return max(0.0, min(100.0, numerator / denominator * 100.0))


def _status(window: dict[str, Any]) -> str:
    """Return the vendor's own word for a window, defaulting to ``ok``."""
    if window.get("eligible") is False:
        return "exhausted"
    status = window.get("status")
    return status if isinstance(status, str) and status else "ok"


def _windows(payload: dict[str, Any]) -> list[QuotaWindow]:
    """Decode the Coding Plan windows out of a preflight answer."""
    plan = payload.get("codingPlan")
    if not isinstance(plan, dict):
        return []
    rows = plan.get("windows")
    if not isinstance(rows, list):
        return []
    windows: list[QuotaWindow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        span = row.get("durationSeconds")
        windows.append(
            QuotaWindow(
                name=_span_name(span),
                used_percent=_share(row.get("usedCredits"), row.get("limitCredits")),
                span_seconds=(
                    int(span)
                    if isinstance(span, (int, float)) and not isinstance(span, bool)
                    else None
                ),
                resets_at=parse_iso(row.get("resetsAt")),
                status=_status(row),
            )
        )
    return windows


def _plan_name(summary: Any) -> str | None:
    """Return the membership tier a billing summary names, if it names one."""
    if not isinstance(summary, dict):
        return None
    for key in ("membershipTier", "tier", "plan", "membership", "subscription"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for inner in ("name", "tier", "id"):
                nested = value.get(inner)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return None


class OpenDesignQuota:
    """The Coding Plan allowance, read on the control plane."""

    id = "opendesign"
    #: The read needs the credential the model requests do not send; the
    #: gateway marks the reading advisory for that reason.
    credential_role = "control"
    default_url = CONTROL_PLANE

    def match(self, base_url: str) -> str | None:
        """Return the control plane for this vendor's model gateway.

        The control plane is not derivable from the model plane's host — it is
        a separate origin — so a recognised lane answers ``default_url``.

        A core without the second-credential contract answers ``""`` instead:
        it would read this probe with the runtime key, and the control plane
        refuses that with 401.  Reporting "no keyed endpoint" is the honest
        answer there, and it keeps the lane usable.
        """
        if "open-design" not in (base_url or ""):
            return None
        return CONTROL_PLANE if CONTRACT_AVAILABLE else ""

    def headers(self, key: str) -> dict[str, str]:
        """Authenticate the control-plane read.

        The runtime key is refused here; this is the second credential, sent
        as a Bearer token.  The API documents no other scheme for this plane.
        """
        return {
            "Authorization": f"Bearer {key}",
            "User-Agent": USER_AGENT,
        }

    def parse(self, body: Any) -> tuple[str | None, list[QuotaWindow]]:
        """Decode a preflight answer read directly.

        Used when someone points ``quota.url`` at the preflight endpoint; the
        shipped path is :meth:`fetch`, because the workspace id has to be
        looked up first.
        """
        if not isinstance(body, dict):
            raise QuotaProbeError("the control plane answered no object")
        windows = _windows(body)
        if not windows:
            raise QuotaProbeError("the control plane reported no Coding Plan window")
        balance = _number(body.get("balanceUsd"))
        plan = f"balance ${balance:.2f}" if balance is not None else None
        return plan, windows

    async def fetch(
        self,
        read: Any,
        credential: str,
        url: str,
    ) -> tuple[str | None, list[QuotaWindow]]:
        """Read the workspace, its billing preflight and the plan tier.

        Args:
            read: ``await read(url, headers) -> (status_code, body)``, supplied
                by the gateway.
            credential: The control key.  Only its presence matters here; the
                headers are built by :meth:`headers` on the gateway side.
            url: The control plane base URL.

        Raises:
            ProbeRefused: A required step was refused; carries the vendor's
                answer for :meth:`describe_error`.
            QuotaProbeError: The answers carried no Coding Plan window.
        """
        base = (url or CONTROL_PLANE).rstrip("/")
        status, body = await read(f"{base}/api/v1/workspaces/current", None)
        if status >= 400:
            raise ProbeRefused(status, body)
        workspace = body.get("activeWorkspaceId") if isinstance(body, dict) else None
        if not isinstance(workspace, str) or not workspace:
            raise QuotaProbeError(
                "the control plane named no active workspace for this account"
            )

        status, body = await read(
            f"{base}/api/v1/workspaces/{workspace}/billing/preflight", None
        )
        if status >= 400:
            raise ProbeRefused(status, body)
        windows = _windows(body if isinstance(body, dict) else {})
        if not windows:
            raise QuotaProbeError("the control plane reported no Coding Plan window")

        # The tier is decoration: a refusal there costs the plan name, not the
        # reading, so it never raises.
        plan: str | None = None
        try:
            status, summary = await read(f"{base}/api/v1/billing/summary", None)
            if status < 400:
                plan = _plan_name(summary)
        except Exception:  # noqa: BLE001 - decoration must not lose the reading
            plan = None
        return plan, windows

    def describe_error(self, status_code: int, body: Any) -> str:
        """Name a refused control-plane read for an operator."""
        detail = vendor_message(body)
        if status_code in (401, 403):
            return (
                f"the control plane refused the control key ({status_code}): "
                f"{detail}; sign in again to renew it"
            )
        return f"control-plane read failed ({status_code}): {detail}"

    def inband(self, status_code: int, body: Any) -> Any | None:
        """No in-band classifier: the model plane's refusal shapes are unmeasured.

        A 429 from the model plane is still counted by the gateway's own
        ladder; this vendor has published no error body that names the window
        it exhausted, and inventing one would demote on a guess.
        """
        return None


PROBES = (OpenDesignQuota(),)
