"""The secrets in the fake lab's running-configs: made up, obviously fake and unique, so a
test can scan API responses and logs for every one of them (none may ever appear there).

They only look like what IOS shows (type 9 hashes, type 7 strings); nothing derives them from
a real password, and no fake device accepts them for a login.
"""

FAKE_SECRETS: dict[str, str] = {
    "enable": "$9$FAKElabENABLE$NotARealHash.FakeLabEnableSecret.000000000001",
    "user_admin": "$9$FAKElabADMIN0$NotARealHash.FakeLabAdminSecret.0000000000002",
    "user_readonly": "$9$FAKElabREADER$NotARealHash.FakeLabReaderSecret.000000000003",
    "line_vty": "FAKE7LINE0000004",
    "snmp_community": "FAKE-lab-snmp-community-5",
    "tacacs_key": "FAKE7TACACS00006",
    "ntp_key": "FAKE7NTP00000007",
    "hsrp_key": "FAKE7HSRP0000008",
    "ospf_key": "FAKE7OSPF0000009",
}
