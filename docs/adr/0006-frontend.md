# ADR-0006: Frontend stack and conventions

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** project team (4 members)

## Context

Step 7 adds the first real screens: the app shell, the device inventory, discovery and the
topology map (proposal 7.1 and 7.2). ADR-0001 fixed React, TypeScript (strict) and Vite;
ADR-0003 fixed the API contract and its generated types. What was still open: routing,
server state, the component library, the graph library, translations, and how the UI is
tested.

## Decision

### Libraries

| Concern | Choice | Why |
| --- | --- | --- |
| Routing | React Router | The standard for React SPAs; URL search params hold list filters, so filtered views can be shared and reloaded. Large pages (the map) load lazily per route. |
| Server state | TanStack Query | Caching, deduplication, retries and **polling** (`refetchInterval`) for jobs and discovery runs without hand-written effects. Every call goes through hooks in `src/api/queries.ts`, which use the typed openapi-fetch client (`src/api/client.ts`). |
| Components | **Mantine** (core + hooks) | See below. |
| Graph | **Cytoscape.js** | Built for network graphs: thousands of nodes on canvas, per-element classes and a CSS-like stylesheet (shape by device type, border by status), preset positions for our own role layout and saved layouts, headless mode for tests. Alternatives: vis-network (less control over styling, unmaintained periods), React Flow (DOM nodes; heavy beyond a few hundred nodes, built for node editors), D3 (everything by hand). |
| Translations | i18next + react-i18next | ICU-style interpolation and Turkish/English plural rules; resources are plain JSON a teammate can edit. |
| Icons | Tabler icons | Mantine's companion icon set; tree-shaken per icon. |

**Why Mantine.** We need dense, accessible building blocks (tables, multi-selects, tags
inputs, drawers, an app shell) with a dark theme, and we are four students with one
frontend-heavy semester, so a complete library beats assembling one.

- *Complete and accessible:* AppShell, Table, Select/MultiSelect/TagsInput (combobox
  semantics, keyboard support), Drawer, Accordion, Badge; labels, descriptions and errors
  are wired to inputs (`aria-describedby`, `aria-invalid`).
- *Light and dark built in:* `defaultColorScheme="auto"` follows the system, with a manual
  switch; components use CSS variables, so the theme needs no runtime CSS-in-JS.
- *TypeScript first, small API:* props are typed; no styling system to learn.
- *Alternatives:* MUI (Material look, Emotion runtime styling, heavier); Ant Design (strong
  tables, but a large bundle, its own design language and less flexible theming); Chakra UI
  (fewer data-heavy components); shadcn/ui + Tailwind (copy-in components we would then
  maintain ourselves, plus a second styling system).

One deliberate global rule: badges never upper-case their text, because CSS upper-casing
follows the page language and Turkish turns "switch" into "SWİTCH".

### Language

- The UI is **Turkish by default**, English selectable in the header (remembered in local
  storage). Every user-facing string comes from `src/i18n/locales/tr.json` / `en.json`;
  a unit test keeps their keys identical. Code, identifiers and comments stay English.
- Network terms engineers use in English stay English in both languages: VLAN, trunk,
  EtherChannel, HSRP, port names, device types (switch, router, AP) and roles (core,
  distribution, access, edge).
- Times are shown relative ("3 dk. önce") with the exact time on hover, through
  `Intl.RelativeTimeFormat` / `Intl.DateTimeFormat` in the UI language.
- Messages the API writes (problem details, collection errors) are shown as they are;
  where the UI knows the meaning (discovery outcomes), it says it in the UI language and
  keeps the API text in a tooltip.

### Data flow

- **Polling, not WebSocket**, for now: jobs and discovery runs are polled every 2 s while
  queued or running, API health every 15 s. The WebSocket arrives with alarms (M3).
- Errors are `ApiError` objects carrying the RFC 9457 problem; `ProblemAlert` shows its
  title, detail and status everywhere a request can fail. Empty states explain what to do
  next (no devices → start a discovery).
- Mock mode (`npm run dev:mock`) sends a placeholder bearer token because the Prism mock
  enforces the contract's security; the real API checks no tokens until M7.

### The map

- Node positions come from our own layout (`layoutByRole`): rows by role (out of scope,
  edge, core, distribution, access, endpoints/APs), each row ordered by the average position
  of its neighbours above; on L3 the subnets sit between or below their members.
  Positions an operator saved (`PUT /topology/layout`) override it per node.
- Status is never colour alone: border style (solid, dashed, double, dotted) and a second
  caption line carry it, shapes carry the device type, and a legend explains both.
- The canvas is not keyboard accessible by nature; the search box (a combobox of all nodes)
  and the side panel give keyboard users the same information.

### Accessibility basics

Every control is a native or ARIA-correct element reachable by keyboard; every input has
a label; status badges have an icon and text; live regions announce progress (job state,
counts, map summary).

### Tests

- **Vitest + Testing Library** (jsdom) for logic and components: topology → Cytoscape
  element mapping and layout, form validation, badges, translations.
- **Playwright**: a smoke test against the Prism mock runs in CI (shell, devices list, map
  nodes, language switch). A local test against the real stack with the fake lab drives a
  discovery from the UI and checks the map (`npm run e2e:fakelab`); the same setup produces
  the documentation screenshots (`npm run screenshots`).

## Consequences

- The main bundle is ~0.8 MB before gzip (React, Mantine, router, query, i18n), split into
  cached vendor chunks; Cytoscape (~0.4 MB) loads only with the map.
- Adding a screen means: a route, hooks in `src/api/queries.ts`, strings in both resource
  files, and a component test for its logic.
- Mantine's major versions have renamed props before (e.g. `Collapse` `in` → `expanded`);
  upgrades need a pass over the components.
