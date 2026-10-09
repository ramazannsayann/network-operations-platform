## What and why

<!-- One logical change. Which module (M1–M7) and which requirement (FR-xx) does it serve? -->

## How it was tested

<!-- Commands you ran, fixtures used, what you checked by hand. -->

## Checklist

- [ ] Tests added or updated (integration tests too if the schema or a query changed)
- [ ] `make lint` and `make test` pass locally
- [ ] No secrets: no credentials, keys, tokens or `.env` files
- [ ] No real network data: no real device configs, no institution's IP plan, no pilot data (fixtures use made-up documentation/private addresses)
- [ ] Docs updated where needed (README, CLAUDE.md, `docs/data-model.md`), and a new ADR for significant decisions
- [ ] If models changed: Alembic migration included and its downgrade works
