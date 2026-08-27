# CLAUDE.md — lifecycle-graph

Instructions for Claude Code when working in this repository.

## What this project is

Standalone Python 3.12 script (`lifecycle-graph.py`) that generates HTML/SVG/PNG Gantt charts for Red Hat product lifecycles. No pip dependencies by default (stdlib only). PyYAML is the only optional dependency, required for config loading.

## Single source of truth

**All product/operator/middleware data lives in `lifecycle-config.yaml`.** The Python script starts with empty dicts and loads everything from YAML at startup. Never add hardcoded dates, fallback dicts, or product configs to the Python file — edit YAML only.

The one exception: `PHASES` dict and `PHASE_KEYS` list in `lifecycle-graph.py` define visual styling for phase types. New phase *types* (not new products) require Python edits there.

## Running the script

```bash
# Generate all charts
python3 lifecycle-graph.py --product all --output-dir docs

# Generate one product (faster for testing)
python3 lifecycle-graph.py --product ocp --output-dir /tmp/test

# Validate API phase_map coverage (RHEL skipped)
python3 lifecycle-graph.py --validate-phases

# Containerized local preview
docker build -t lifecycle-graph:local -f Containerfile .
docker run --rm -p 8080:8080 lifecycle-graph:local

# Install PyYAML first if needed
pip install pyyaml
```

No virtual environment needed. Python 3.12+ required.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Offline (fetchers monkeypatched). Run after any change to parsers, details data, or rendering; CI runs it before generation. When changing a parser for a new document layout, add a fixture to `tests/test_lifecycle_graph.py` first. Human-oriented contributor guide: `DEVELOPMENT.md`.

## Architecture

```
lifecycle-config.yaml  ──load──▶  PRODUCT_CONFIGS / OPERATOR_CONFIGS / MIDDLEWARE_CONFIGS / _RHEL_MINOR_DATA / _RHEL_MAJOR_DATA
                                         │
                           fetch_lifecycle(cfg)  [Red Hat API, then fallback:]  — skipped for RHEL (use_major_phases)
                                         │
                           build_versions(raw, cfg)  /  build_rhel_major_versions()
                                         │
                           _render_card(versions)  →  HTML Gantt
```

Key functions:
- `_load_external_config()` — loads YAML into runtime dicts at module level
- `_apply_product_overrides()` / `_apply_operator_overrides()` / `_apply_middleware_overrides()` — populate runtime dicts from YAML
- `fetch_lifecycle(cfg)` — calls Red Hat lifecycle API, falls back to `cfg["fallback"]` dict
- `build_versions(raw, cfg)` — filters by min_version, detects EUS, builds phase segments
- `render_combined_html()` — assembles all charts + nav into `lifecycle.html`
- `_generate_lifecycle_about(path)` — renders LIFECYCLE.md → `lifecycle-about.html` (stdlib Markdown converter)
- `_generate_details_page(out_dir, key, cfg, versions)` — z-stream/errata Details page (see below)

## Details pages (z-stream errata)

Products with a `details:` block in YAML (all main products, RHEL included) get two static pages built from one errata fetch: `lifecycle-{key}-details.html` (z-stream releases per minor with errata badges, highlight cards, a From→To version delta filter, release-notes links) and `lifecycle-{key}-timeline.html` (month-grouped vertical timeline of z-stream releases with minor/kind filters). The card gains a `↗ details` link automatically; the two pages cross-link via their topbar.

```yaml
products:
  ocp:
    details:
      errata_query: "OpenShift Container Platform {minor}"   # Hydra search query, {minor} substituted
      release_notes_url: "https://docs.redhat.com/.../{minor}/html/release_notes/"
```

If `errata_query` contains no `{minor}` (e.g. RHOAI, whose synopses read "RHOAI 3.3.5 - …"), a single product-wide query is run and docs are attributed to minors by version parsing; unmatched docs are dropped. Per-minor queries keep unmatched docs as a per-minor "unversioned" list.

Each z-stream body shows **highlight cards** (🔒 Security Fixes / 🔧 Bug Fixes / ✨ Enhancements) built from `* ` bullet lists in `portal_description` — deduplicated across the z-stream's errata. Cards appear only when bullets exist (some products, e.g. RHOAI, have empty descriptions in the search index). Note: docs.redhat.com cannot be scraped at build time (Akamai blocks non-browser clients) — release-notes URLs are link-outs only.

**Feature cards** ("What's new in X.Y", per minor) have two sources, chosen per product in YAML:

- `features_url` (best; OCP): the release-notes *source* asciidoc fetched from the product's public docs repo (openshift/openshift-docs, `enterprise-{minor}` branch — `{minor_dash}` = dots→dashes, `{major}` = major part). The "New features and enhancements" section is parsed into area-grouped title+description entries. The parser (`_parse_adoc_features`) is level-aware (book files and standalone modules), follows one `include::…new-features…` indirection (4.21+ modular books), and handles both `==== Title` headings and `Title::` definition lists. Asciidoc attributes come from `details.attributes_url` plus explicit `details.attributes:` overrides in YAML (e.g. `product-title`).
- `features_search` (all other products): the portal search index (`documentKind:Documentation`, `language:en`, `view_uri:` wildcard from the template) — the only reachable form of docs.redhat.com content. English docs are indexed at *chapter* granularity, so entries are release-notes chapters (Overview / New features / Technology previews, keyword-filtered) with title, abstract snippet, and link.

Either way failures are non-fatal — the minor just has no features card.

Card look & feel is standardized in `RELEASE_NOTE_TEMPLATE.md` — any new feature source must map into that schema/rendering (never add a new rendering path).

**RHEL special case**: `details` with no `errata_query` (RHEL erratas aren't x.y.z-versioned and volume is huge) makes a feature-only details page — no z-streams, no delta filter. `minors_from: rhel_minors` sources the minor list from the `rhel_minors:` YAML block (majors ≥ 8) instead of chart versions.

Data comes from the unauthenticated Hydra errata search (`access.redhat.com/hydra/rest/search/kcs`) at build time — no runtime fetches; the page works over `file://`. A sidecar `lifecycle-{key}-details.json` is written next to the HTML and serves as the fallback cache: if the live fetch fails, the page is rebuilt from the last committed JSON with a stale-data notice, and chart generation is never blocked. `--skip-details` skips these pages (and the card links) for faster test runs.

## Version strategies (`version_strategy` in YAML)

| Strategy | Parser | When to use |
|----------|--------|-------------|
| `xy` | `X.Y` integers | Operators and products with distinct minor releases (e.g. `"1.16"`) |
| `x-dotx` | Major integer only | JBoss products — API returns literal `"8.x"`, `"7.x"` strings |
| `xy-exact` | Strict 2-part numeric | Keycloak — rejects `"26.x"` aliases and 3-part versions |
| `xy-eus-even` | `X.Y`, EUS on even Y | ODF |
| `ocp-minor` | OCP `4.X`, EUS on even X | OCP |
| `rhel-major` | Integer | RHEL major (7, 8, 9, 10) |
| `aap` | `X.Y` | AAP |
| `rhoai` | `X.Y` (strips trailing `*`) | RHOAI |
| `ceph` | Integer | Ceph |
| `rolling-eol` | `X.Y` | Rolling-stream operators (VolSync, Dev Spaces) |

## Adding a new operator (YAML only)

```yaml
operators:
  my-op:
    api_name: "Red Hat My Operator"   # exact string from lifecycle API
    title: "My Operator"              # optional display name
    version_strategy: xy
    min_version: "1.0"
    phase_map_preset: op-standard
    fallback:
      "1.2": { ga: "2024-06-01", fs_end: "2024-12-01", mnt_end: "2025-06-01" }
```

Find the exact `api_name`:
```bash
curl "https://access.redhat.com/product-life-cycles/api/v1/products?name=My+Operator"
```

## RHEL date updates

RHEL bypasses the lifecycle API for minors (`use_major_phases: true`). All dates live in two YAML blocks:

**Major versions** — `rhel_majors:` (`std_end`, `els_end` for RHEL 7, `elc_end` for 8/9/10). No `ll_end` field: the lifecycle API's `phases[]` array gives Long Life ("Extended life phase") no `end_date` — it's Ongoing — so `build_rhel_major_versions()` always draws it as a projected bar once `elc_end` is set (capped at a fixed 3-year width for plotting, tooltip shows "Ongoing"); once `today` reaches `elc_end` the badge shows `Ongoing` instead of a countdown. Source for `elc_end`: the API's own major-level phase dates (`https://access.redhat.com/product-life-cycles/api/v1/products?name=Red+Hat+Enterprise+Linux`), which — unlike its minor-level data — are accurate for ELS/ELC and Long Life.

**Minor versions** — `rhel_minors:` per the field reference below.

Source: [RHEL errata policy page](https://access.redhat.com/support/policy/updates/errata). Phase names follow the subscription model (Standard / Premium / ELC Premium / Long Life), not API phase names.

Field meanings for `rhel_minors`:
- `std_end` — end of Standard subscription window (= next minor GA)
- `eus_end` — end of Premium subscription additional maintenance (even minors, RHEL 8+)
- `elc_end` — end of Extended Life Cycle, Premium subscription additional maintenance (GA + 6 years; even minors ≥ 9.2, 8.10, 10.2+)
- `elcp_end` — end of Long Life add-on terms (last minor of each major: 8.10, 9.10, 10.10)

All dates **must** be quoted strings: `"2024-05-18"` not `2024-05-18`. Bare dates become `datetime.date` objects in Python and break string comparisons.

## CI / GitHub Actions

`.github/workflows/update-lifecycle.yml` runs daily at 06:00 UTC and on push to `main` when `lifecycle-graph.py`, `lifecycle-config.yaml`, or `LIFECYCLE.md` change. It installs `pyyaml` and regenerates `docs/` output.

## Security / correctness notes

- Never embed date logic in Python — all dates go in YAML `fallback:` blocks
- `_coerce_date_str(v)` converts PyYAML `datetime.date` → ISO string (handles unquoted dates defensively)
- `_make_min_filter()` uses default-argument capture (`_mt=min_t`) to avoid late-binding closure bugs

## What NOT to change in Python

These things are stable; editing them risks breaking all charts:
- `PHASES` dict — colour palette for phase types
- `PHASE_KEYS` list — chronological order for segment building
- `_parse_*` functions — version parsers (one per strategy)
- `fetch_lifecycle()` — API call + fallback merge logic
- `build_versions()` — segment assembly

For any data-only change (new product, new version dates, corrected dates), the answer is always: **edit `lifecycle-config.yaml`**.
