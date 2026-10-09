"""M1 - Discovery and topology.

Will find devices from seed addresses and subnets, identify them (SNMP sysObjectID,
SSH "show version"), walk CDP/LLDP neighbours, and build the L2/L3 topology graph
that the UI renders and the diagnosis module reasons over.
"""
