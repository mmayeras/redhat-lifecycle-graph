# Changelog

All notable changes to `lifecycle-graph` are listed here, most recent first.

---

## [Unreleased]

---

## [0.2.6] — 2026-07-07

### Fixed
- **Today marker in light mode** — stronger red line and label (no faded opacity) for readable contrast on bright backgrounds

---

## [0.2.5] — 2026-07-07

### Fixed
- **Mobile product filter** — filter bar no longer stays sticky on small screens; collapsed behind a “Filter products” toggle and auto-closes after a selection
- **Product display names** — drop “Lifecycle” suffix from filter pills and chart headers; rename RHOAI to Red Hat OpenShift AI

---

## [0.2.4] — 2026-07-07

### Fixed
- **Disclaimer panel** — collapsible on all screen sizes; collapsed by default with a left-edge tab on desktop and a toggle bar on mobile; open/closed state remembered in `localStorage`

---

## [0.2.3] — 2026-07-07

### Fixed
- **Disclaimer sidebar layout** — keep floating left panel on tablet/desktop (removed overly broad 1024px static fallback); collapsible panel on phones; fixed flex `min-width` bug that inflated SVG icons and crushed labels; wider sidebar for long product names; cache-bust `chart.css` after static updates

---

## [0.2.2] — 2026-07-07

### Added
- **Unofficial-tool disclaimer sidebar** — fixed left panel (vertically centered while scrolling) on the main charts page with official Red Hat technology icons, per-product lifecycle policy links, and **Contribute** moved from the masthead into the sidebar
- **Product icons** — Red Hat technology SVGs in `static/icons/products/` used consistently in the sidebar, product nav pills, chart card headers, and Operators/Middleware section headings

### Changed
- **Product display names** — OCP → OpenShift Container Platform, RHEL → Red Hat Enterprise Linux, AAP → Ansible Automation Platform, Operators → OpenShift Operators (nav, cards, and sidebar)
- **OpenStack chart titles** — drop `(OSP)` / `(RHOSO)` parenthetical abbreviations; OpenStack products omitted from the official-sources sidebar (charts remain on the page)
- **RHOAI policy link** — updated to `rhoai-sm/lifecycle` URL

### Fixed
- **Relative API phase dates** — resolves `Release of X.Y`, `X.YGA + N months`, `GA of X.Y`, `with the release of X.Y`, and related patterns against other versions' GA dates; when the referenced release is not published yet, the version is shown as still supported (not EOL)

---

## [0.2.1] — 2026-07-06

### Added
- **Additive product nav filter** — default shows all charts; first click isolates one product, further clicks add more; **Reset filter** button restores show-all
- **RHEL short bar labels** — `short_label` on in-bar text (e.g. "ELC, Premium"); full subscription names remain in tooltips and legend

### Changed
- **Product nav** — replaced per-section show/hide toggles with isolate-then-add filter model; nav pills wrap on two rows
- **RHEL phase colours** — distinct palette per subscription phase (Standard, Premium, ELC, Long Life, ELS add-on)
- **Sticky scroll offset** — `--sticky-offset` computed from masthead + subnav height (accounts for two-row nav)

### Fixed
- **Zebra row striping** — alternates on visible rows only; hidden EOL rows no longer break the pattern
- **Card title hidden under sticky nav** — scroll offset recalculated after filter/layout changes

---

## [0.2.0] — 2026-07-06

### Added
- **RHEL subscription model** — major and minor charts use official phase names (Standard subscription, Premium subscription additional maintenance, Extended Life Cycle Premium, Long Life add-on terms) from Red Hat lifecycle materials; bypasses inaccurate lifecycle API via `use_major_phases: true`
- **`rhel_majors` YAML block** — major-version dates (`std_end`, `els_end`, `elc_end`, `ll_end`) as single source of truth for RHEL 7–10
- **`rhel_els` phase key** — RHEL 7 major Extended life cycle support (ELS) add-on segment
- **`--validate-phases` CLI** — audits `phase_map` coverage against the Red Hat API for all non-RHEL entries
- **API-first lifecycle fetch** — no per-field YAML backfill when API returns a version; `fallback:` used only when API is unreachable
- **`phase_map_preset` for products** — presets merge with inline `phase_map` overrides
- **`osp-els3` preset** and `tpc` phase for OpenStack Platform third-party certification
- **PatternFly v6 UI** — external CSS (`static/css/chart.css`), Flask dev server (`server.py`), `Containerfile` for containerized local preview
- **Nav improvements** — wrapped product pills, sticky scroll offset for card titles (superseded by additive filter in 0.2.1)

### Changed
- **RHEL phase display labels** — match subscription terminology (not API Full support / Maintenance names)
- **RHEL 8 major chart** — split Extended Life Cycle, Premium (to 2030-05-22) and Long Life add-on (to 2033-05-31) segments
- **Removed RHEL API fallback** — `phase_map` and `fallback:` removed from RHEL product entry (YAML blocks only)
- **LIFECYCLE.md** — rewritten RHEL section with ELC/ELS terminology, `rhel_majors` field reference, API bypass documented
- **README** — Containerfile local development instructions, RHEL phase legend, `--validate-phases`

### Fixed
- Satellite, OCP, AAP, OSP, Global Hub, Quay family, and 12 operators — phase_map gaps causing missing EUS/ELS segments
- Containerfile — copies config/docs inputs, installs PyYAML, generates `docs/` at build time
- Missing `static/` directory — graceful warning instead of crash when assets absent

---

## [0.1.1] — 2026-07-03

### Added
- **OpenStack Platform (OSP)** — `lifecycle-osp.html`; versions 16.1–17.1; Full Support / Maintenance / ELS / ELS-2 / ELS-3 phases; dates from API
- **OpenStack on OpenShift (RHOSO)** — `lifecycle-rhoso.html`; version 18.0; separate product from classic OSP
- **Red Hat Satellite** — `lifecycle-satellite.html`; versions 6.13–6.19; Full Support / Maintenance phases; dates from API
- **Compliance Operator** — added to operators section; `op-standard` phase map
- **`els3` phase** — new ELS Term 3 phase key and colour (`#c94040`) for OSP; added to `PHASES`, `PHASE_KEYS`, and fallback merge list
- **`has_minors` YAML flag** — replaces hardcoded `cfg_key == "rhel"` check; enables minor-version toggle for any product that sets `has_minors: true` in YAML
- **Products fully driven from YAML** — `_fetch_all()` and `main()` now iterate `PRODUCT_CONFIGS.keys()` instead of a hardcoded list; `--product` choices also dynamic; adding a product to YAML automatically creates its HTML page and nav button

### Fixed
- RHEL ELS fallback dates corrected from API: RHEL 7 (`2028-06-30` → `2029-05-31`), RHEL 8/9/10 `els_end` previously missing
- RHEL 10 GA date corrected (`2025-05-01` → `2025-05-20`)
- RHEL 10.1 removed — not published by Red Hat; RHEL 10 EUS minors are 10.2/10.4/10.6/10.8 (even only)
- `build_rhel_minor_versions` no longer crashes on entries missing `std_end` (skips gracefully)
- Windows Containers 10.19–10.21 `fs_end` was missing (API returns relative string `"4.N GA + 3 months"`); resolved from OCP schedule and added to fallback
- OSP integer-only versions (13, 16) excluded by `xy` strategy dot-check; fixed by raising `min_version` to `16.1`
- `blockquote` rendering in `lifecycle-about.html` — tables inside blockquotes now render correctly (recursive Markdown conversion)
- `_parse_api_date` now handles `"Estimated Month, YYYY"` strings — parses to last day of that month; abbreviated month names (`Nov`, `Dec`, …) also supported; future products with estimated dates render correctly without fallback overrides

### Known limitations
- **VolSync 0.12–0.16**: `End of Life` is relative in API (`"Release of 0.N"`) — renders GA-only bar; resolves automatically once Red Hat publishes absolute dates

---

## [0.1.0] — 2026-07-03

### Added
- **Dark / light mode toggle** — button in header (☀/🌙); defaults to OS `prefers-color-scheme`; manual choice persisted in `localStorage`; no flash of wrong theme (blocking `<head>` script applies theme before paint)
- **Versions sorted descending** — newest version shown at top in all charts
- **Daily CI pipeline** — GitHub Actions now runs every day at 06:00 UTC (was weekly)
- **`lifecycle-config.yaml` — YAML as sole source of truth** — all product/operator/middleware data (dates, fallbacks, phase maps, version strategies) moved out of Python into a declarative YAML config file; Python script starts with empty dicts and loads everything at startup; no hardcoded data remains in the script
- **`lifecycle-about.html`** — LIFECYCLE.md rendered as an HTML page within the generated site; linked from the nav bar and footer
- **`LIFECYCLE.md` contributor guide** — documents YAML schema, `version_strategy` and `phase_map_preset` reference tables, field definitions, and "Add a new operator in 3 lines of YAML" example
- **`CLAUDE.md` instructions file** — guidance for AI-assisted edits; explains architecture, what lives in YAML vs Python, and what must not change in the script
- **`xy-exact` version strategy** — strict 2-part numeric filter for Keycloak; rejects API aliases like `"26.x"` and 3-part version strings
- **`name_transform` on Ceph strategy** — strips "Red Hat Ceph Storage " prefix from API version names before display
- **43 operator fallback blocks in YAML** — all operator version date data migrated from Python dicts to YAML; `fallback:` blocks used when the API is unreachable
- **`lifecycle-about.html` redesign** — clean static page with hero, visual pipeline strip, and TOC sidebar; no external JS dependencies; replaces earlier diagram-based approach
- **ELS vs ELC terminology note in LIFECYCLE.md** — clarifies that ELS (major versions, from API) and ELC (minor versions, manually maintained) are distinct programs; explains why ELC data is not in the API
- **PyYAML missing → clear error + exit** — script now prints actionable message and exits instead of silently producing empty charts

### Fixed
- RHEL 8.10 missing `eus_end` date (2026-05-31) — even minor was incorrectly omitting the EUS add-on end date
- RHEL 9.8 `std_end` incorrect — was set to RHEL 9 major EOM date (2032-05-31) instead of projected next minor GA (~Nov 2026)
- Added `elc_end` for RHEL 8.10 (2030-05-22 = GA + 6 years per ELC policy)
- `lifecycle-about.html` stale in repo — script now outputs to `docs/` via CI; local runs require explicit `--output-dir .`

---

## 2026-07-02

### Added
- **Phase hover tooltips** — global fixed `position:fixed` tooltip shows phase name + exact start → end dates on mouse hover (escapes `overflow:hidden` chart bars)
- **EOL warning badge** — versions within 30 days of end-of-life show ⚠️ badge with day count; hover or click for pinnable tooltip with upgrade guidance
- **GitHub Contribute button** — green pill in page header; opens prefilled GitHub issue template
- **Operator search / filter** — live text filter above the operators section collapses non-matching operators
- **Version range filter** — per-card From/To selectors and "Show EOL" checkbox in card controls
- **29 OpenShift operator lifecycle charts** — collapsible `<details>` per operator, sourced from Red Hat Product Life Cycles API, aligned with the [OpenShift Operator Life Cycles policy](https://access.redhat.com/support/policy/updates/openshift_operators); operators sorted alphabetically
- **RHOAI product** (`Red Hat OpenShift AI`) chart
- **Ceph Storage** chart with ELS / ELS Term 2 phases
- **AAP** (Ansible Automation Platform) chart with Maintenance 1 / Maintenance 2 phases
- **RHEL** chart with ELS add-on phase
- **`--product all`** flag — generates all product charts in one run
- **`--output-dir`** flag — CI passes `docs/`, local default is `./` (gitignored)
- **Responsive mobile layout** — compact header grid, scrollable nav pills, dynamic chart `min-width`, smaller font/row sizes on narrow screens
- **Year label density control** — auto-adjusts label step (1 / 2 / 5 years) based on chart span to avoid overlap
- **Exact UTC timestamp** in card footer (`Generated YYYY-MM-DD HH:MM UTC`)
- **`docs/` output directory** for GitHub Pages compatibility

### Fixed
- Missing operator versions (MTV 2.11/2.12, Builds 1.4–1.8, Pipelines 1.22, GitOps 1.20/1.21, ODF 4.21, Logging 6.5) — generalised fallback merge fills all date keys when API returns unparseable values
- Ceph graph bar overlap
- RHOAI EOL versions now hidden by default (consistent with other products)
- Duplicate footer links removed

---

## [0.0.1] — 2026-07-02 — Initial release (`608f687`)

### Added
- Standalone Python script — no pip dependencies (stdlib only: `urllib`, `json`, `argparse`)
- OCP Gantt chart generated from Red Hat Product Life Cycles API with static fallback
- HTML output with interactive phase segment bars
- SVG + PNG export via `rsvg-convert`
- Phase legend (Full Support, Maintenance, EUS-1, EUS-2, Extended Life)
- `--from` / `--to` version range filter
- `--open` flag to open browser after generation
- GitHub Actions workflow for automated chart updates
