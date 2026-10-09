"""M3 - Monitoring collectors.

Will poll devices on a schedule (SNMPv3 counters and SSH "show" commands) and receive
syslog messages and SNMP traps, normalise the results into time-series metrics stored in
TimescaleDB hypertables, and feed threshold and state-change evaluation for alarms.
"""
