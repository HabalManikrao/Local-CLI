"""Evidence source classification (master prompt §10).

Every piece of information CLE surfaces is tagged with where it came from:

- ``LOCAL``  — read directly from the local project/index (files, symbols).
- ``CACHED`` — previously fetched and stored locally (e.g. cached research).
- ``LIVE``   — fetched from a live external source this moment.

The classification must be preserved end-to-end and must never be *upgraded*:
LOCAL or CACHED information can never be relabelled LIVE. :func:`assert_no_upgrade`
enforces that invariant wherever sources are combined or relabelled.
"""

from __future__ import annotations

from enum import Enum


class EvidenceSource(str, Enum):
    LOCAL = "LOCAL"
    CACHED = "CACHED"
    LIVE = "LIVE"


# Illegal upgrades: a value on the left must never become LIVE.
_NON_LIVE = {EvidenceSource.LOCAL, EvidenceSource.CACHED}


def assert_no_upgrade(original: EvidenceSource, new: EvidenceSource) -> None:
    """Raise if *new* illegally upgrades *original* to LIVE."""
    if original in _NON_LIVE and new is EvidenceSource.LIVE:
        raise ValueError(
            f"Illegal evidence upgrade: {original.value} -> {new.value}. "
            "LOCAL/CACHED sources must never be relabelled LIVE."
        )
