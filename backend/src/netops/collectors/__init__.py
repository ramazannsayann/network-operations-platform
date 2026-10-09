"""M3 - Monitoring collectors.

Will poll devices on a schedule (SNMP counters, SSH "show" commands, and later syslog
and streaming telemetry), normalise the results into time-series metrics stored in
TimescaleDB hypertables, and feed threshold and state-change evaluation for alarms.
"""
