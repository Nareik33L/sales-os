"""Injectable writer callback used by ``execute_approved``.

Real connector ``write()`` implementations (HubSpot ``complete_task``, Sheets
``mark_done``) are owned by ``salesos-connector-engineer`` and must be registered
or passed in. This package never imports ``connectors/``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ExternalWriter(Protocol):
    """Stand-in for ``connector.write(capability, payload)``.

    ``audit_id`` is required so a later real ``write()`` can assert it was
    reached only through ``execute_approved``.
    """

    def __call__(
        self,
        capability: str,
        payload: dict[str, Any],
        *,
        audit_id: str,
    ) -> Mapping[str, Any] | None: ...


_default_writer: ExternalWriter | None = None


def set_writer(writer: ExternalWriter | None) -> None:
    """Install or clear the process-wide default writer (tests pass ``writer=``)."""
    global _default_writer
    _default_writer = writer


def get_writer() -> ExternalWriter | None:
    return _default_writer
