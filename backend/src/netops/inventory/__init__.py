"""M2 - Inventory.

Will collect and periodically refresh per-device state (facts, interfaces, VLANs, ARP and
MAC tables, routes, HSRP, spanning tree, EtherChannel) over SSH with NAPALM and TextFSM,
write it to the shared data model, and serve the device detail page with an on-demand
"refresh now" and a whitelisted show-command runner.
"""
