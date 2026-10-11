# Device prerequisites (Cisco IOS / IOS-XE)

What a device needs before the platform can discover it, collect from it, back up its
configuration and notice changes made on it. The addresses below are documentation
examples (`192.0.2.10` is the platform server, `Vlan99` the management interface): put in
your own, and never commit an institution's addressing plan (see CONTRIBUTING.md).

## 1. SSH and the read account (M1, M2, M4)

- SSH version 2 on the vty lines: `ip ssh version 2`, `transport input ssh`.
- One account for the platform's credential profile. The platform only ever sends `show`
  commands and `terminal length 0` / `terminal width N` (the read-only guard, ADR-0004).
- **`show running-config` needs privilege level 15.** Below it IOS shows only the commands
  the user could configure, and the platform rejects such partial output instead of
  storing it as a version. Give the account privilege 15 and, where TACACS+ is used, limit
  it with command authorization to `show` commands.
- With local accounts only: `username netops-ro privilege 15 secret <password>`; the
  password goes into the platform as a credential profile (`netops credentials add`), never
  into a file in the repository.

## 2. Syslog to the platform (M3 events, M4 change detection)

The events service listens on UDP 514. It accepts messages only from addresses it knows as
a device's management address or interface address, so the messages must leave from such
an address (`logging source-interface`). Severity 5 (notifications) includes the two
messages change detection uses: `%SYS-5-CONFIG_I` and `%PARSER-5-CFGLOG_LOGGEDCMD`.

```
service timestamps log datetime msec localtime show-timezone
logging source-interface Vlan99
logging trap notifications
logging host 192.0.2.10
```

`service sequence-numbers` and `logging origin-id hostname` are optional; the receiver
parses messages with and without them. If the receiver is published on another port:
`logging host 192.0.2.10 transport udp port 5514`.

## 3. Configuration change logging (archive)

With archive logging the device logs every configuration command with the user who typed
it; the platform shows them in the change list. `hidekeys` keeps passwords and keys out of
those messages (the platform redacts them anyway).

```
archive
 log config
  logging enable
  logging size 200
  notify syslog contenttype plaintext
  hidekeys
```

## 4. SCP server (for M5)

Central configuration (M5) will copy configurations to the device for `configure replace`:

```
ip scp server enable
```

## Ready to paste

```
! NetOps platform prerequisites. Example values: replace 192.0.2.10 (platform server)
! and Vlan99 (the interface with the management address).
ip ssh version 2
line vty 0 15
 transport input ssh
!
service timestamps log datetime msec localtime show-timezone
logging source-interface Vlan99
logging trap notifications
logging host 192.0.2.10
!
archive
 log config
  logging enable
  logging size 200
  notify syslog contenttype plaintext
  hidekeys
!
ip scp server enable
end
```

Check: `show logging | include 192.0.2.10` (the host is logging), `show archive log config
all` (commands are being recorded). After a change, the platform shows it in "Config
değişiklikleri" about `CONFIG_CHANGE_DEBOUNCE_SECONDS` (30 s) after the last message.

## Network and host

- From the platform server to the devices: TCP 22. From the devices to the platform: UDP
  514 (or the port set in `SYSLOG_HOST_PORT`).
- The receiver must see the devices' real source addresses: on a Linux host run the events
  service with host networking (ADR-0007). Docker Desktop rewrites the source of UDP coming
  from outside, so there the receiver only serves the fake lab.
- NTP on the devices keeps syslog and configuration timestamps comparable.
