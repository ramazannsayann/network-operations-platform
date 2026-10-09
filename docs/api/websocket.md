# WebSocket channel (contract, not implemented yet)

Live updates for the UI: alarms, incidents, discovery progress and job status. REST
(`docs/api/openapi.json`) stays the source of truth; the WebSocket only tells clients that
something changed, so they never have to poll. Conventions are those of
[ADR-0003](../adr/0003-api-conventions.md).

## Connection

- URL: `wss://<host>/ws/v1` (`ws://localhost:8080/ws/v1` in development). nginx proxies
  everything under `/ws/` to the API.
- One connection per browser tab. Messages are JSON text frames.
- Authentication: the first client message must be `auth` with the bearer token from
  `POST /api/v1/auth/login` (browsers cannot set an `Authorization` header on WebSockets,
  and tokens in URLs end up in logs). Until M7 the token is not checked.
- Keep-alive: the server sends a WebSocket ping frame every 30 s; clients that miss two
  are disconnected. Clients reconnect with exponential backoff (1 s, 2 s, 4 s ... max 30 s).

## Message envelope

Every message, in both directions:

```json
{
  "type": "alarm.opened",
  "id": "8a4c1f3e-2b7d-4e1a-9c5b-0d6e7f8a9b10",
  "sent_at": "2026-10-08T22:43:05Z",
  "seq": 42,
  "data": {}
}
```

| Field | Meaning |
| --- | --- |
| `type` | Message type, see below. |
| `id` | UUID of this message. |
| `sent_at` | When it was sent (UTC). |
| `seq` | Server messages only: 1, 2, 3 ... per connection. A gap means messages were lost; refetch over REST. |
| `data` | Payload. For server events it is the same schema the REST API returns for that resource. |

Delivery is at most once and there is no replay. After connecting (or reconnecting) and
subscribing, a client loads current state over REST and then applies the events it
receives.

## Client messages

| `type` | `data` | Effect |
| --- | --- | --- |
| `auth` | `{"token": "<JWT>"}` | Must be first. Answered by `auth.ok`, or the connection is closed with 4401. |
| `subscribe` | `{"topics": ["alarms", "jobs:<job id>"]}` | Start receiving events for the topics. Answered by `subscribed`. |
| `unsubscribe` | `{"topics": ["alarms"]}` | Stop receiving them. |

Topics:

| Topic | Events |
| --- | --- |
| `alarms` | `alarm.opened`, `alarm.updated`, `alarm.cleared` |
| `incidents` | `incident.updated` |
| `discovery` or `discovery:<run id>` | `discovery.progress` (all runs, or one) |
| `jobs:<job id>` | `job.status` for one job |

## Server messages

| `type` | `data` schema (OpenAPI component) | Sent when |
| --- | --- | --- |
| `auth.ok` | `CurrentUser` | The token was accepted. |
| `subscribed` | `{"topics": [...]}` | Subscription confirmed. |
| `alarm.opened` | `Alarm` | A new alarm was raised. |
| `alarm.updated` | `Alarm` | Occurrence count, state (acknowledged) or incident changed. |
| `alarm.cleared` | `Alarm` | The alarm cleared. |
| `incident.updated` | `IncidentSummary` | An incident was opened, gained alarms, or was resolved. |
| `discovery.progress` | `DiscoveryRunSummary` | Discovery progress changed (at most once per second per run). |
| `job.status` | `Job` | A job changed status or progress. |
| `error` | `Problem` | A client message was invalid; the connection stays open. |

Example:

```json
{
  "type": "alarm.opened",
  "id": "8a4c1f3e-2b7d-4e1a-9c5b-0d6e7f8a9b10",
  "sent_at": "2026-10-08T22:43:05Z",
  "seq": 42,
  "data": {
    "id": "5e0c7a1d-0000-4000-8000-000000005001",
    "device": {"id": "5e0c7a1d-0000-4000-8000-000000002004", "hostname": "sw-b2-03", "mgmt_ip": "10.0.0.23"},
    "interface": {"id": "5e0c7a1d-0000-4000-8000-000000003002", "device_id": "5e0c7a1d-0000-4000-8000-000000002004", "name": "Gi1/0/49"},
    "rule_key": "link.allowed_vlans_mismatch",
    "severity": "major",
    "state": "open",
    "dedup_key": "link.allowed_vlans_mismatch:5e0c7a1d-0000-4000-8000-000000003501",
    "occurrence_count": 1,
    "opened_at": "2026-10-08T22:43:05Z",
    "last_occurrence_at": "2026-10-08T22:43:05Z",
    "acknowledged_at": null,
    "acknowledged_by": null,
    "cleared_at": null,
    "incident_id": "5e0c7a1d-0000-4000-8000-000000005101",
    "summary": "Allowed VLANs differ on sw-b2-03 Gi1/0/49 <-> dist-sw-b Gi1/0/3 (VLAN 20)",
    "details": {"missing_on_peer": [20]}
  }
}
```

## Close codes

| Code | Meaning |
| --- | --- |
| 1000 | Normal closure. |
| 1011 | Server error; reconnect with backoff. |
| 4400 | The first message was not `auth`, or a message was not valid JSON. |
| 4401 | Missing or invalid token; log in again before reconnecting. |
| 4403 | The user may not subscribe to a requested topic (M7 roles). |

## Timing

Alarm events must reach the UI within 60 s of the syslog message or trap that caused
them (NFR-03); the channel itself should add well under a second.
