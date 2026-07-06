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

RHEL bypasses the lifecycle API (`use_major_phases: true`). All dates live in two YAML blocks:

**Major versions** — `rhel_majors:` (`std_end`, `els_end` for RHEL 7, `elc_end`, `ll_end` for 8+)

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
