# Lifecycle Methodology

This document explains how each product's lifecycle is modelled in `lifecycle-graph.py` and how to extend or correct the data. It is aimed at contributors.

---

## How it works — the basics

Every product goes through the same pipeline:

```
fetch_lifecycle(cfg)      →  raw dict  {version: {ga, fs_end, mnt_end, ...}}
       ↓
build_versions(raw, cfg)  →  version list  [{version, ga, last_end, segments, is_eol, ...}]
       ↓
_render_card(versions)    →  HTML Gantt chart
```

**`PHASES`** maps phase keys (e.g. `"fs"`, `"eus1"`) to display label and colours.  
**`PHASE_KEYS`** defines the order phases are checked when building segments.  
**`PRODUCT_CONFIGS` / `OPERATOR_CONFIGS` / `MIDDLEWARE_CONFIGS`** are populated at startup from `lifecycle-config.yaml`.

---

## Configuration (`lifecycle-config.yaml`)

All product, operator, and middleware data lives in `lifecycle-config.yaml`, alongside `lifecycle-graph.py`. The Python script starts with empty dicts and loads everything from this file at startup. **To change lifecycle data or add new entries, edit only the YAML — no Python changes are needed.**

### Requirements

PyYAML must be installed:

```bash
pip install pyyaml
```

If the file is missing or PyYAML is not installed, the script prints a warning and generates empty charts.

### Field reference

#### `products`

```yaml
products:
  <key>:
    api_name: "Exact Red Hat API product name"   # required
    title: "Display title in the chart"          # required
    page_url: "https://..."                      # optional — linked from chart header
    info_html: "<b>HTML</b> snippet..."          # optional — tooltip / legend footnote
    version_strategy: ocp-minor                  # required — see table below
    min_version: "4.12"                          # required — versions below this are skipped
    phase_map:                                   # required
      "API phase string": phase_key
    fallback:                                    # recommended — used when API is unreachable
      "4.16": { ga: "2024-10-28", fs_end: "2025-05-19", mnt_end: "2026-05-19" }
```

#### `rhel_minors`

```yaml
rhel_minors:
  "9":
    "9.4": { ga: "2024-04-30", std_end: "2024-11-12", eus_end: "2026-05-31", elc_end: "2030-04-30" }
    "9.6": { ga: "2025-05-13", std_end: "2025-11-12", eus_end: "2027-05-31", elc_end: "2031-05-13" }
  "8":
    "8.10": { ga: "2024-05-22", std_end: "2029-05-31", eus_end: "2026-05-31", elc_end: "2030-05-22", elcp_end: "2032-06-30" }
```

Fields per entry:

| Field | Required | Meaning |
|-------|----------|---------|
| `ga` | yes | GA date |
| `std_end` | yes | End of Standard subscription window |
| `eus_end` | no | End of Premium/EUS (even minors) |
| `elc_end` | no | End of ELC, Premium (even minors ≥ 9.2, and 8.10) |
| `elcp_end` | no | End of Long Life (last minor of each major: 8.10, 9.10, 10.10) |

> **Date format**: always quote dates as strings — `"2024-05-18"` not `2024-05-18`. Bare dates are auto-converted to Python `datetime.date` objects by PyYAML, which breaks string comparisons.

#### `operators`

```yaml
operators:
  <key>:
    api_name: "Red Hat OpenShift Pipelines"   # required
    title: "OpenShift Pipelines"              # optional — defaults to api_name
    version_strategy: xy                      # required — see table below
    min_version: "1.14"                       # required
    phase_map_preset: op-standard             # use preset OR inline phase_map
    phase_map:                                # inline overrides preset
      "General availability": ga
      "End of Life": fs_end
    fallback:                                 # recommended
      "1.16": { ga: "2024-10-09", fs_end: "2025-01-12", mnt_end: "2025-03-17" }
```

#### `middleware`

Same structure as `operators`, using `phase_map_preset: els2` for JBoss products.

### `version_strategy` values

| Value | Parser | EUS check | Use for |
|-------|--------|-----------|---------|
| `ocp-minor` | `X.Y` OCP format | even Y | OCP |
| `xy` | `X.Y` | none | most operators, AAP, Quarkus |
| `xy-exact` | `X.Y` exact (no `X.x`) | none | Keycloak |
| `xy-eus-even` | `X.Y` | even Y | ODF |
| `x-dotx` | `X.x` dotx format | none | JBoss EAP, JWS |
| `rhel-major` | integer major | none | RHEL |
| `aap` | AAP `X.Y` | none | AAP |
| `rhoai` | RHOAI `X.Y` | none | RHOAI |
| `ceph` | integer | none | Ceph |
| `rolling-eol` | `X.Y` | none | VolSync, Dev Spaces |

### `phase_map_preset` values

| Preset | Phases |
|--------|--------|
| `op-standard` | Full Support / Maintenance / EUS-1 / EUS-2 |
| `op-odf` | Full Support / Maintenance / EUS-1 / EUS-2 / EUS-3 |
| `els2` | Full Support / Maintenance / ELS-1 / ELS-2 |
| `keycloak` | General availability / Full support / Maintenance support |
| `rolling-ga-eol` | General availability / End of Life |

### Add a new operator in 3 lines of YAML

```yaml
operators:
  my-op:
    api_name: "Red Hat My Operator"   # exact string from the lifecycle API
    version_strategy: xy
    min_version: "1.0"
    phase_map_preset: op-standard
```

To find the exact API name:

```bash
curl "https://access.redhat.com/product-life-cycles/api/v1/products?name=My+Operator"
```

Add a `fallback:` block with known dates to protect against API downtime (see other operators in the YAML for examples).

---

## OpenShift Container Platform (OCP)

**Policy**: https://access.redhat.com/support/policy/updates/openshift

| Phase | Key | Who gets it |
|-------|-----|-------------|
| Full Support | `fs` | all versions |
| Maintenance | `mnt` | all versions |
| EUS-1 | `eus1` | **even** minor only (4.14, 4.16 …) |
| EUS-2 | `eus2` | even minor, requires EUS add-on |
| Extended Life | `elp` | all versions |

`eus_check` returns `True` for even minors → `build_versions` adds `eus1_end`/`eus2_end` segments only for those. `min_filter` skips versions below 4.12 and any non-`4.X` strings from the API.

**To add a future minor**: nothing to do — the API returns it automatically once Red Hat publishes dates.

---

## RHEL (major versions)

**Policy**: https://access.redhat.com/support/policy/updates/errata

| Phase | Key | Notes |
|-------|-----|-------|
| Full Support | `fs` | 5 years from GA |
| Maintenance | `mnt` | up to year 10 |
| ELS add-on | `els` | optional paid add-on |
| Extended Life | `elp` | |

RHEL major versions (7, 8, 9, 10) are fetched from the API. The `min_filter` accepts only integer version strings ≥ 7.

> **ELS vs ELC — terminology note**
>
> These are two different programs that share similar names. This chart uses both:
>
> | Abbreviation | Full name | Applies to | Source |
> |---|---|---|---|
> | **ELS** | Extended Life Cycle Support add-on | RHEL **major** versions (7, 8, 9, 10) | Red Hat lifecycle API returns `"Extended life cycle support (ELS) add-on"` as the exact phase name |
> | **ELC** | Extended Life Cycle | RHEL **minor** versions (even minors ≥ 9.2, 8.10) | Not in the API — dates sourced manually from the errata page; field key `elc_end` in `lifecycle-config.yaml` |
>
> The API does **not** expose ELC data for minor versions. Minor release dates (including ELC end dates) must be maintained manually in the `rhel_minors` block of `lifecycle-config.yaml`.

### RHEL minor versions (the "Show minor releases" toggle)

Minor release dates are **not** available from any Red Hat API — they are embedded as images on the errata page. They are stored in the `rhel_minors` block of `lifecycle-config.yaml`.

| Phase | Key | Who gets it |
|-------|-----|-------------|
| Standard | `rhel_std` | all minors |
| Premium (EUS) | `rhel_prem` | **even** minors |
| ELC, Premium | `rhel_elcp` | even minors from 9.2+ and 8.10 |
| Long Life | `rhel_ll` | last minor of a major (8.10, 9.10, 10.10) |

**ELC rule**: 6 years from minor GA, available for even minors ≥ 9.2 and for 8.10.  
**Long Life rule**: extends beyond major year-10, only for the last minor release.

`build_rhel_minor_versions(major_ver)` reads `_RHEL_MINOR_DATA[major_ver]` (populated from YAML at startup) and builds segments using the four `rhel_*` phase keys.

**To update minor version dates**: edit the `rhel_minors` block in `lifecycle-config.yaml`. See the [Field reference](#field-reference) above for key names.

---

## AAP — Ansible Automation Platform

**Policy**: https://access.redhat.com/support/policy/updates/ansible-automation-platform

| Phase | Key |
|-------|-----|
| Full Support | `fs` |
| Maintenance 1 | `mnt` |
| Maintenance 2 | `mnt2` |

AAP versions follow a `X.Y` scheme. No EUS. `min_filter` accepts versions ≥ 2.0.

---

## RHOAI — Red Hat OpenShift AI

**Policy**: https://access.redhat.com/support/policy/updates/rhoai

| Phase | Key |
|-------|-----|
| Full Support | `fs` |
| EUS-1 | `eus1` |
| EUS-2 | `eus2` |

`eus_check` is `None` (no EUS for RHOAI currently). `min_filter` accepts versions ≥ 2.19.

---

## Ceph Storage

**Policy**: https://access.redhat.com/support/policy/updates/ceph-storage

| Phase | Key |
|-------|-----|
| Support | `sup` (→ mapped to `fs_end` in API) |
| ELS | `els` |
| ELS Term 2 | `els2` |

Ceph uses integer version strings (4, 5, 6, 7). The API returns "End of Life" as the single support end; this is mapped to `fs_end` and displayed with the `sup` phase key. `min_filter` accepts ≥ 4.

---

## OpenShift Operators

**Policy**: https://access.redhat.com/support/policy/updates/openshift_operators

Three tiers with different lifecycle models:

### Platform-Aligned operators

Track OCP minor releases 1:1. Examples: Virtualization, Pipelines, GitOps, ODF, RHACS.

- Version strings are `4.X` (same as OCP).
- `eus_check` mirrors OCP even-minor rule where applicable.
- `min_filter` typically starts at 4.14.
- Use `phase_map_preset: op-standard` (or `op-odf` for ODF).

### Platform-Agnostic operators

Follow their own `X.Y` versioning. Examples: RHACM, cert-manager, OADP, MTC, RHDH, Keycloak.

- `version_strategy: xy` → `(X, Y)` tuple for version ordering.
- No `eus_check`.
- `min_filter` sets a floor version to avoid historical noise.

### Rolling-Stream operators

Rapid release cadence; lifecycle tied to next release, not absolute dates. Examples: VolSync, Dev Spaces, Serverless Logic.

- API often returns relative dates ("Release of X+1 + 3 months") which cannot be resolved → those versions render with GA only.
- `fallback:` blocks in `lifecycle-config.yaml` provide static GA dates for recent versions.
- Use `version_strategy: rolling-eol` and `phase_map_preset: rolling-ga-eol`.

**To add a new operator**: see [Add a new operator in 3 lines of YAML](#add-a-new-operator-in-3-lines-of-yaml) above.

**ODF** uses `phase_map_preset: op-odf` which adds a third EUS tier (`eus3`).

---

## Middleware & Application Services

**Policy**: https://access.redhat.com/support/policy/updates/jboss_notes

| Phase | Key |
|-------|-----|
| Full Support | `fs` |
| Maintenance | `mnt` |
| ELS-1 | `els` |
| ELS-2 | `els2` |

Versions are `X.x` strings (e.g. `8.x`, `7.x`). `version_strategy: x-dotx` extracts the major number for sorting. Use `phase_map_preset: els2`.

**To add a new middleware product**: add an entry under `middleware:` in `lifecycle-config.yaml` with the same structure as existing entries (see `eap`, `jws`, `quarkus`).

---

## Phase palette

All phases are defined in the `PHASES` dict in `lifecycle-graph.py`. Each entry:

```python
"key": {"label": "Display Name", "bg": "#hex", "border": "#hex", "text": "#hex"}
```

The `PHASE_KEYS` list defines the chronological order phases are checked when building version segments. New phase keys must be added there too. This is the one part that still requires a Python edit when introducing a completely new phase type.

---

## Data sources and fallbacks

| Priority | Source | When used |
|----------|--------|-----------|
| 1st | Red Hat Product Life Cycles API | Always attempted first |
| 2nd | `fallback:` blocks in `lifecycle-config.yaml` | API unreachable or returns 0 results |

The API is queried with `Accept-Language: en-US` to prevent localised responses.

`_parse_api_date` handles ISO datetimes, ISO dates with trailing text, and `"Month D, YYYY"` format. Returns `None` for relative strings like `"Release of X+1"` or `"N/A"`.

---

## Adding a new product category

1. Add phase keys to `PHASES` and `PHASE_KEYS` in `lifecycle-graph.py` if needed.
2. Add a `*_CONFIGS` dict and populate it from YAML via a new `_apply_*_overrides()` function called from `_load_external_config()`.
3. Add a `_fetch_*` block in `_fetch_all()`.
4. Add a `_render_*_section()` renderer or reuse `_render_operator_section()`.
5. Wire into `render_combined_html()`: add nav button and include section in `body`.
6. Write a per-product HTML file in `main()` under `--product all`.
7. Add the new top-level key to `lifecycle-config.yaml`.
