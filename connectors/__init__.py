"""Connectors turn external sources into the internal model and report health.

The rest of the application should call `core.ingestion.refresh`, not import a
concrete connector directly.
"""

from connectors.base import (
    BaseConnector,
    Connector,
    ConnectorSpec,
    FetchResult,
    NormalisedBatch,
    SaveStats,
    SyncRunResult,
    WriteResult,
    register_connector,
    registered_connectors,
)
from connectors.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorTransientError,
)


def load_builtin_connectors() -> None:
    """Import concrete connectors so their factories register with BaseConnector.

    Safe to call more than once. New sources add an import here (Excel, Calendly, …).
    """
    from connectors import hubspot as _hubspot  # noqa: F401


__all__ = [
    "BaseConnector",
    "Connector",
    "ConnectorAuthError",
    "ConnectorError",
    "ConnectorNotConfigured",
    "ConnectorSpec",
    "ConnectorTransientError",
    "FetchResult",
    "NormalisedBatch",
    "SaveStats",
    "SyncRunResult",
    "WriteResult",
    "load_builtin_connectors",
    "register_connector",
    "registered_connectors",
]
