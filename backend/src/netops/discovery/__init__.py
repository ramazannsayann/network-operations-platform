"""M1 - Discovery and topology.

Breadth-first CDP/LLDP discovery from seed addresses within allowed subnets (``engine``),
links derived from neighbour observations (``links``), device type and role heuristics
(``classify``, ``roles``), run requests (``service``) and the ``netops.discover`` Celery
task (``tasks``). Decisions are recorded in docs/adr/0005-discovery.md.
"""
