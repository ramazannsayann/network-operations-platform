"""TimescaleDB settings for the shared data model: chunk size and data retention.

This module is the single place where retention periods are defined (ADR-0002). The
migration that creates the hypertables reads them from here. Changing a value later
requires a new migration that replaces the policy, e.g.::

    SELECT remove_retention_policy('mac_entries');
    SELECT add_retention_policy('mac_entries', drop_after => INTERVAL '14 days');
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Table

# Observation rows (one collection run each) feed "state at time T" and before/after
# comparisons for fault diagnosis; a month covers incident follow-up and reporting.
OBSERVATION_RETENTION = timedelta(days=30)
# Metrics and raw syslog/trap events are kept longer for trend graphs and capacity reports.
METRICS_RETENTION = timedelta(days=90)
EVENTS_RETENTION = timedelta(days=90)

# Size of one hypertable chunk. Retention drops whole chunks, so data is deleted with
# up to one chunk interval of delay. One day keeps a 200-device network's busiest chunk
# (metrics) small enough for its indexes to stay in memory.
CHUNK_INTERVAL = timedelta(days=1)

# Key in ``Table.info`` that marks a table as a hypertable.
HYPERTABLE_INFO_KEY = "hypertable"


@dataclass(frozen=True)
class Hypertable:
    """How a table is partitioned and how long its rows are kept."""

    time_column: str
    retention: timedelta
    chunk_interval: timedelta = CHUNK_INTERVAL


def hypertable_info(time_column: str, retention: timedelta) -> dict[str, Hypertable]:
    """Value for ``__table_args__``'s ``info`` that marks a model's table as a hypertable."""
    return {HYPERTABLE_INFO_KEY: Hypertable(time_column, retention)}


def hypertable_of(table: Table) -> Hypertable | None:
    """The hypertable settings of a table, or None for a regular table."""
    spec = table.info.get(HYPERTABLE_INFO_KEY)
    return spec if isinstance(spec, Hypertable) else None
