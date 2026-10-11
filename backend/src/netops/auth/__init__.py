"""M7 - Authentication, authorization and audit (docs/adr/0008-authentication.md).

``passwords`` (argon2id, policy), ``tokens`` (JWT access and MFA challenge tokens, refresh
tokens), ``totp`` (TOTP, recovery codes), ``rbac`` (permissions per role), ``audit`` (the
append-only audit log), ``ratelimit`` (per-address limits), ``service`` (login, sessions,
MFA, password changes) and ``users`` (administration).
"""
