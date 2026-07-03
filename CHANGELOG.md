# Changelog

All notable changes to `lifecycle-graph` are listed here, most recent first.

---

## [Unreleased] — 2026-07-03

### Added
- **Dark / light mode toggle** — button in header (☀/🌙); defaults to OS `prefers-color-scheme`; manual choice persisted in `localStorage`; no flash of wrong theme (blocking `<head>` script applies theme before paint)
- **Versions sorted descending** — newest version shown at top in all charts
- **Daily CI pipeline** — GitHub Actions now runs every day at 06:00 UTC (was weekly)

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

## 2026-07-02 — Initial release (`608f687`)

### Added
- Standalone Python script — no pip dependencies (stdlib only: `urllib`, `json`, `argparse`)
- OCP Gantt chart generated from Red Hat Product Life Cycles API with static fallback
- HTML output with interactive phase segment bars
- SVG + PNG export via `rsvg-convert`
- Phase legend (Full Support, Maintenance, EUS-1, EUS-2, Extended Life)
- `--from` / `--to` version range filter
- `--open` flag to open browser after generation
- GitHub Actions workflow for automated chart updates
