# ruff: noqa: E501 - configuration lines in the case tables are kept whole for readability
"""Config normalization, the IOS config parser, the redactor and redacted diffs.

Every secret below is made up; most say FAKE so a leak would be obvious.
"""

import pytest

from netops.configmgmt.diff import redacted_diff
from netops.configmgmt.normalize import content_hash, normalize
from netops.configmgmt.parser import parse
from netops.configmgmt.redact import (
    CERTIFICATE_MARKER,
    MARKER,
    redact,
    redact_commands,
    redact_lines,
)

RAW = """\r
Building configuration...\r
\r
Current configuration : 4211 bytes\r
!\r
! Last configuration change at 10:41:12 UTC Sat Oct 10 2026 by jdoe\r
! NVRAM config last updated at 09:00:01 UTC Sat Oct 10 2026 by netops\r
!\r
version 17.9   \r
hostname dist1\r
ntp clock-period 36028797\r
!\r
end\r
"""


# --- normalization ------------------------------------------------------------------------


def test_normalize_drops_volatile_lines_and_fixes_line_ends() -> None:
    assert normalize(RAW) == "!\n!\nversion 17.9\nhostname dist1\n!\nend\n"


def test_volatile_lines_do_not_change_the_hash() -> None:
    later = RAW.replace("10:41:12", "23:59:59").replace("4211", "4299")
    later = later.replace("36028797", "36028801")
    assert content_hash(normalize(RAW)) == content_hash(normalize(later))
    assert content_hash(normalize(RAW)) != content_hash(normalize(RAW + "ip domain lookup\n"))
    assert len(content_hash("")) == 64


def test_normalize_of_empty_output() -> None:
    assert normalize("\r\n\r\n") == ""


# --- parser -------------------------------------------------------------------------------

CONFIG = """\
hostname core1
!
interface GigabitEthernet1/0/3
 description to access3
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 !
interface Vlan10
 ip address 10.10.10.2 255.255.255.0
 standby 10 ip 10.10.10.1
!
router ospf 1
 network 10.255.0.0 0.0.0.255 area 0
!
banner motd ^C
Authorised access only!
 interface text inside a banner is not a command
^C
line vty 0 4
 password 7 FAKE0822455D0A16
 transport input ssh
!
end
"""


def test_parser_builds_the_indentation_hierarchy() -> None:
    tree = parse(CONFIG)
    (trunk,) = tree.section(r"interface GigabitEthernet1/0/3")
    assert [child.command for child in trunk.children] == [
        "description to access3",
        "switchport mode trunk",
        "switchport trunk allowed vlan 10,20,30",
        "!",
    ]
    (allowed,) = tree.find(r"switchport trunk allowed vlan")
    assert allowed.parent is trunk
    (password,) = tree.find(r"password ")
    assert password.parent is not None
    assert password.parent.command == "line vty 0 4"
    assert [line.command for line in tree.roots][:2] == ["hostname core1", "!"]


def test_banners_are_opaque() -> None:
    tree = parse(CONFIG)
    (banner,) = tree.section(r"banner motd")
    assert [line.opaque for line in banner.children] == [True, True, True]
    assert not tree.find(r"interface text")  # no command line, only banner text
    (line_vty,) = tree.section(r"line vty")
    assert line_vty.parent is None


def test_every_line_is_kept_in_order() -> None:
    tree = parse(CONFIG)
    assert "\n".join(line.text for line in tree.lines) + "\n" == CONFIG


def test_walk_and_ancestors() -> None:
    tree = parse("router bgp 65000\n address-family ipv4\n  neighbor 192.0.2.1 activate\n")
    leaf = tree.lines[2]
    assert [a.command for a in leaf.ancestors()] == ["address-family ipv4", "router bgp 65000"]
    assert [line.command for line in tree.roots[0].walk()] == [
        "router bgp 65000",
        "address-family ipv4",
        "neighbor 192.0.2.1 activate",
    ]


# --- redaction ----------------------------------------------------------------------------

# (configuration line(s), expected redacted line(s)); secrets contain FAKE or "s3cr3t".
CASES = [
    # enable
    ("enable secret 9 $9$FAKEhash$FAKEFAKE", f"enable secret 9 {MARKER}"),
    ("enable secret 5 $1$FAKE$abcdefghij", f"enable secret 5 {MARKER}"),
    ("enable secret FAKEs3cr3t", f"enable secret {MARKER}"),
    ("enable password 7 FAKE0822455D0A16", f"enable password 7 {MARKER}"),
    ("enable password level 15 FAKEclear", f"enable password level 15 {MARKER}"),
    (
        "enable algorithm-type scrypt secret FAKEs3cr3t",
        f"enable algorithm-type scrypt secret {MARKER}",
    ),
    # usernames, every type
    ("username admin secret 0 FAKEclear", f"username admin secret 0 {MARKER}"),
    ("username admin secret 5 $1$FAKE$hash", f"username admin secret 5 {MARKER}"),
    ("username admin password 7 FAKE0822455D0A16", f"username admin password 7 {MARKER}"),
    (
        "username admin privilege 15 secret 8 $8$FAKE$hash",
        f"username admin privilege 15 secret 8 {MARKER}",
    ),
    (
        "username admin privilege 15 secret 9 $9$FAKE$hash",
        f"username admin privilege 15 secret 9 {MARKER}",
    ),
    (
        "username ops privilege 15 algorithm-type sha256 secret FAKEs3cr3t",
        f"username ops privilege 15 algorithm-type sha256 secret {MARKER}",
    ),
    ("username ops password FAKEclear", f"username ops password {MARKER}"),
    # line passwords
    ("line vty 0 4\n password 7 FAKE0822455D0A16", f"line vty 0 4\n password 7 {MARKER}"),
    ("line con 0\n password FAKEclear", f"line con 0\n password {MARKER}"),
    # SNMP
    ("snmp-server community FAKE-community RO 10", f"snmp-server community {MARKER} RO 10"),
    ("snmp-server community FAKErw RW", f"snmp-server community {MARKER} RW"),
    (
        "snmp-server host 192.0.2.50 version 2c FAKE-community",
        f"snmp-server host 192.0.2.50 version 2c {MARKER}",
    ),
    ("snmp-server host 192.0.2.50 FAKE-community", f"snmp-server host 192.0.2.50 {MARKER}"),
    (
        "snmp-server host 192.0.2.50 informs version 3 priv netops-user",
        f"snmp-server host 192.0.2.50 informs version 3 priv {MARKER}",
    ),
    (
        "snmp-server user netops NMS v3 auth sha FAKEauthkey priv aes 128 FAKEprivkey",
        f"snmp-server user netops NMS v3 auth sha {MARKER} priv aes 128 {MARKER}",
    ),
    (
        "snmp-server user netops NMS v3 encrypted auth sha256 FAKEauth priv des FAKEpriv",
        f"snmp-server user netops NMS v3 encrypted auth sha256 {MARKER} priv des {MARKER}",
    ),
    # TACACS+ / RADIUS, old and new syntax
    (
        "tacacs-server host 192.0.2.10 key 7 FAKE0822455D",
        f"tacacs-server host 192.0.2.10 key 7 {MARKER}",
    ),
    ("tacacs-server key FAKEclear", f"tacacs-server key {MARKER}"),
    (
        "radius-server host 192.0.2.11 auth-port 1812 acct-port 1813 key FAKEclear",
        f"radius-server host 192.0.2.11 auth-port 1812 acct-port 1813 key {MARKER}",
    ),
    ("radius-server key 7 FAKE0822455D", f"radius-server key 7 {MARKER}"),
    (
        "tacacs server ISE1\n address ipv4 192.0.2.10\n key 7 FAKE0822455D",
        f"tacacs server ISE1\n address ipv4 192.0.2.10\n key 7 {MARKER}",
    ),
    (
        "radius server NPS\n address ipv4 192.0.2.11 auth-port 1812 acct-port 1813\n key 6 FAKEaes",
        f"radius server NPS\n address ipv4 192.0.2.11 auth-port 1812 acct-port 1813\n key 6 {MARKER}",
    ),
    (
        "aaa group server tacacs+ GRP\n server-private 192.0.2.12 key 7 FAKE0822",
        f"aaa group server tacacs+ GRP\n server-private 192.0.2.12 key 7 {MARKER}",
    ),
    # IKE pre-shared keys
    (
        "crypto isakmp key FAKEpsk address 198.51.100.1",
        f"crypto isakmp key {MARKER} address 198.51.100.1",
    ),
    (
        "crypto isakmp key 6 FAKEaes address 0.0.0.0",
        f"crypto isakmp key 6 {MARKER} address 0.0.0.0",
    ),
    (
        "crypto keyring KR\n pre-shared-key address 198.51.100.1 key FAKEpsk",
        f"crypto keyring KR\n pre-shared-key address 198.51.100.1 key {MARKER}",
    ),
    (
        "crypto ikev2 keyring KR2\n peer HUB\n  pre-shared-key local FAKElocal\n  pre-shared-key remote 6 FAKEremote",
        f"crypto ikev2 keyring KR2\n peer HUB\n  pre-shared-key local {MARKER}\n  pre-shared-key remote 6 {MARKER}",
    ),
    # NTP
    ("ntp authentication-key 1 md5 FAKEntpkey 7", f"ntp authentication-key 1 md5 {MARKER} 7"),
    ("ntp authentication-key 2 sha1 FAKEntp", f"ntp authentication-key 2 sha1 {MARKER}"),
    # key chains: the key number stays, the key string goes
    (
        "key chain EIGRP\n key 1\n  key-string 7 FAKE0822455D\n  accept-lifetime infinite",
        f"key chain EIGRP\n key 1\n  key-string 7 {MARKER}\n  accept-lifetime infinite",
    ),
    # routing protocol and FHRP keys
    (
        "interface Gi1/0/1\n ip ospf message-digest-key 1 md5 7 FAKE0822",
        f"interface Gi1/0/1\n ip ospf message-digest-key 1 md5 7 {MARKER}",
    ),
    (
        "interface Gi1/0/1\n ip ospf authentication-key FAKEospf",
        f"interface Gi1/0/1\n ip ospf authentication-key {MARKER}",
    ),
    (
        "interface Vlan10\n standby 10 authentication md5 key-string FAKEhsrp",
        f"interface Vlan10\n standby 10 authentication md5 key-string {MARKER}",
    ),
    (
        "interface Vlan10\n standby 10 authentication FAKEplain",
        f"interface Vlan10\n standby 10 authentication {MARKER}",
    ),
    (
        "interface Vlan10\n vrrp 5 authentication text FAKEvrrp",
        f"interface Vlan10\n vrrp 5 authentication text {MARKER}",
    ),
    (
        "router bgp 65000\n neighbor 192.0.2.1 password 7 FAKE0822",
        f"router bgp 65000\n neighbor 192.0.2.1 password 7 {MARKER}",
    ),
    # wireless
    (
        "dot11 ssid STAFF\n authentication key-management wpa version 2\n wpa-psk ascii 7 FAKE0822455D",
        f"dot11 ssid STAFF\n authentication key-management wpa version 2\n wpa-psk ascii 7 {MARKER}",
    ),
    (
        "wlan STAFF 1 STAFF\n security wpa psk set-key ascii 0 FAKEpsk",
        f"wlan STAFF 1 STAFF\n security wpa psk set-key ascii 0 {MARKER}",
    ),
    # other passwords, caught by the generic rule
    (
        "interface Serial0/0\n ppp chap password 0 FAKEchap",
        f"interface Serial0/0\n ppp chap password 0 {MARKER}",
    ),
    ("ip ftp password 7 FAKE0822455D", f"ip ftp password 7 {MARKER}"),
    (
        "crypto pki trustpoint TP\n enrollment url http://192.0.2.9\n password FAKEenroll",
        f"crypto pki trustpoint TP\n enrollment url http://192.0.2.9\n password {MARKER}",
    ),
]

NOT_SECRETS = [
    "service password-encryption",
    "security passwords min-length 8",
    "password encryption aes",
    "username guest privilege 1 nopassword",
    "key chain EIGRP",
    " key 1",
    "crypto key generate rsa modulus 2048",
    "authentication key-management wpa version 2",
    "snmp-server enable traps config",
    "snmp-server contact noc@example.net",
    "aaa authentication login default group tacacs+ local",
    "ip ssh version 2",
    "description link to core1 Te1/1/1",
    "switchport trunk allowed vlan 10,20,30,98,99",
    "standby 10 ip 10.10.10.1",
    "logging host 192.0.2.20",
]


@pytest.mark.parametrize(("config", "expected"), CASES)
def test_secrets_are_redacted(config: str, expected: str) -> None:
    redacted = redact(config + "\n")
    assert redacted == expected + "\n"
    for secret in ("FAKE", "s3cr3t"):
        assert secret not in redacted


@pytest.mark.parametrize("line", NOT_SECRETS)
def test_non_secrets_are_left_alone(line: str) -> None:
    assert redact(line + "\n") == line + "\n"


def test_certificates_collapse_to_one_marker() -> None:
    config = (
        "crypto pki certificate chain TP-self-signed-1\n"
        " certificate self-signed 01\n"
        "  3082022B 30820194 A0030201 02020101 300D0609 2A864886 F70D0101\n"
        "  05050030 31312F30 2D060355 04031326 494F532D 53656C66 2D536967\n"
        "  \tquit\n"
        "!\n"
        "hostname core1\n"
    )
    assert redact(config) == (
        "crypto pki certificate chain TP-self-signed-1\n"
        " certificate self-signed 01\n"
        f"  {CERTIFICATE_MARKER}\n"
        "  \tquit\n"
        "!\n"
        "hostname core1\n"
    )
    assert "3082022B" not in redact(config)
    assert redact_lines(config)[3] is None  # collapsed, not just blanked


def test_banner_text_is_not_mistaken_for_commands() -> None:
    config = "banner motd ^C\nThe password is on the wiki\n^C\nhostname x\n"
    # Banner text is shown as it is: it is a message to users, not a credential.
    assert redact(config) == config


def test_commands_from_syslog_are_redacted_without_their_block() -> None:
    assert redact_commands(
        [
            "interface GigabitEthernet1/0/2",
            "switchport trunk allowed vlan remove 20",
            "username backup secret 0 FAKEtyped",
            "key 7 FAKE0822455D",  # typed inside "tacacs server X"
        ]
    ) == [
        "interface GigabitEthernet1/0/2",
        "switchport trunk allowed vlan remove 20",
        f"username backup secret 0 {MARKER}",
        f"key 7 {MARKER}",
    ]


def test_redaction_keeps_every_line_and_is_idempotent() -> None:
    config = "\n".join(case[0] for case in CASES) + "\n"
    once = redact(config)
    assert len(once.splitlines()) == len(config.splitlines())
    assert redact(once) == once


# --- redacted diffs -----------------------------------------------------------------------

BEFORE = """\
hostname dist1
enable secret 9 $9$FAKEold$hash
!
interface GigabitEthernet1/0/2
 description to access2 Gi1/1/1
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30,98,99
!
end
"""


def test_diff_shows_the_changed_line() -> None:
    after = BEFORE.replace("10,20,30,98,99", "10,30,98,99")
    diff = redacted_diff(BEFORE, after, from_label="dist1 @ v1", to_label="dist1 @ v2")
    assert diff.added == diff.removed == 1
    lines = diff.text.splitlines()
    assert lines[:2] == ["--- dist1 @ v1", "+++ dist1 @ v2"]
    assert "- switchport trunk allowed vlan 10,20,30,98,99" in lines
    assert "+ switchport trunk allowed vlan 10,30,98,99" in lines
    assert lines[2] == "@@ -4,6 +4,6 @@"


def test_a_changed_secret_shows_as_a_changed_line_without_its_values() -> None:
    after = BEFORE.replace("$9$FAKEold$hash", "$9$FAKEnew$hash")
    diff = redacted_diff(BEFORE, after, from_label="a", to_label="b")
    assert f"-enable secret 9 {MARKER}" in diff.text.splitlines()
    assert f"+enable secret 9 {MARKER}" in diff.text.splitlines()
    assert (diff.added, diff.removed) == (1, 1)
    assert "FAKE" not in diff.text


def test_identical_configs_have_an_empty_diff() -> None:
    assert redacted_diff(BEFORE, BEFORE, from_label="a", to_label="b").text == ""


def test_context_lines_are_redacted_too() -> None:
    config = "line vty 0 4\n password 7 FAKE0822\n transport input ssh\n"
    diff = redacted_diff(config, config.replace("ssh", "ssh telnet"), from_label="a", to_label="b")
    assert f"  password 7 {MARKER}" in diff.text.splitlines()
    assert "FAKE" not in diff.text
