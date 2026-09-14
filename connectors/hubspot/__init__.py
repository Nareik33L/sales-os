"""HubSpot connector package. Importing registers the factory for the orchestrator."""

from __future__ import annotations

from connectors.base import ConnectorSpec, register_connector
from connectors.hubspot.connector import HubSpotConnector

__all__ = ["HubSpotConnector", "create_hubspot_connector"]


def create_hubspot_connector(spec: ConnectorSpec) -> HubSpotConnector:
    return HubSpotConnector(spec)


register_connector("hubspot", create_hubspot_connector)
