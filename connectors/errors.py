"""Typed connector errors.

`BaseConnector.run()` maps these to `sync_runs.status` and never re-raises them
to the refresh orchestrator or the UI.
"""

from __future__ import annotations


class ConnectorError(Exception):
    """Base class for connector failures."""


class ConnectorNotConfigured(ConnectorError):
    """Required credentials, files, or config are missing.

    Mapped to `sync_runs.status = NOT_CONFIGURED`. `env_vars` are *names* only —
    never values — so the UI can say "Not connected — set HUBSPOT_ACCESS_TOKEN".
    """

    def __init__(self, message: str = "", *, env_vars: list[str] | None = None) -> None:
        self.env_vars = list(env_vars or [])
        if not message and self.env_vars:
            message = not_configured_message(self.env_vars)
        super().__init__(message)


class ConnectorAuthError(ConnectorError):
    """Credentials were present but rejected (expired token, 401/403)."""


class ConnectorTransientError(ConnectorError):
    """Retryable failure (timeout, 429, 5xx). Caller still records FAILED/PARTIAL."""


def not_configured_message(env_vars: list[str]) -> str:
    """Human status line for a missing-env NOT_CONFIGURED run."""
    if not env_vars:
        return "Not connected — missing configuration"
    return f"Not connected — set {', '.join(env_vars)}"
