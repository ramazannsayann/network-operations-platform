"""M4/M5 - Configuration management and central configuration.

M4 (this package today): ``show running-config`` backups, normalized (``normalize``),
versioned in a local Git repository (``store``), compared (``diff``) and redacted before
anything leaves the backend (``parser`` + ``redact``); external changes are detected from
syslog and from scheduled backups (``changes``). Decisions: docs/adr/0007-config-management.md.

M5 will render templated changes and push them with dry-run, approval and rollback.
"""
