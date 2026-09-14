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
    "register_connector",
    "registered_connectors",
]
