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
    "9.6": { ga: "2025-04-29", std_end: "2025-11-04", eus_end: "2027-05-31", elc_end: "2031-04-29" }
  "8":
    "8.10": { ga: "2024-05-22", std_end: "2029-05-31", eus_end: "2026-05-31", elc_end: "2030-05-22", elcp_end: "2033-05-31" }
```

Fields per entry:

| Field | Required | Meaning |
|-------|----------|---------|
| `ga` | yes | GA date |
| `std_end` | yes | End of Standard subscription window |
| `eus_end` | no | End of Premium/EUS (even minors) |
| `elc_end` | no | End of **Extended Life Cycle, Premium subscription additional maintenance** (even minors ≥ 9.2, 8.10, 10.2+) |
| `elcp_end` | no | End of **Long Life add-on terms** (last minor of each major: 8.10, 9.10, 10.10) |

#### `rhel_majors`

Major-version bars (RHEL 7, 8, 9, 10). Used when `use_major_phases: true` — the lifecycle API is **not** queried for RHEL.

```yaml
rhel_majors:
  "8": { ga: "2019-05-07", std_end: "2029-05-31", elc_end: "2030-05-22", ll_end: "2033-05-31" }
  "7": { ga: "2014-06-10", std_end: "2024-06-30", els_end: "2029-05-31" }
```

| Field | Required | Meaning |
|-------|----------|---------|
| `ga` | yes | Major release GA |
| `std_end` | yes | End of Standard subscription (= year 10 / Maintenance support end) |
| `els_end` | no | End of Extended life cycle support (ELS) add-on — **RHEL 7 only** |
| `elc_end` | no | End of Extended Life Cycle, Premium subscription additional maintenance |
| `ll_end` | no | End of Long Life add-on terms (majors with a `.10` minor) |

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
| `osp-els3` | Full Support / 3rd-party Cert / Maintenance / ELS-1 / ELS-2 / ELS-3 |
| `els2` | Full Support / Maintenance / ELS-1 / ELS-2 |
| `keycloak` | General availability / Full support / Maintenance support |
| `rolling-ga-eol` | General availability / End of Life |

Products and operators both support `phase_map_preset`. Inline `phase_map` keys are merged on top of the preset.

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

## RHEL

**Policy**: https://access.redhat.com/support/policy/updates/errata

RHEL is **not** driven by the [Product Life Cycles API](https://access.redhat.com/product-life-cycles/api/v1/products?name=Red+Hat+Enterprise+Linux). That API returns legacy phase names (Full support, Maintenance support, ELS add-on) that do not match the current **subscription model**. Instead, RHEL uses `use_major_phases: true` and reads dates from `rhel_majors` and `rhel_minors` in YAML.

Reference: [RHEL in a nutshell — Extended Life Cycle](https://docs.google.com/presentation/d/1GEVy4z9j2eUOFTuLODywBc9p1cDIp0oUTyZkiczknBs/edit?slide=id.g3d84542a08c_0_266).

### Subscription phases (official names)

These four phases apply at **minor** release level.

| Subscription phase | Chart key | Who gets it |
|--------------------|-----------|-------------|
| Standard subscription | `rhel_std` | all minors (~6 months per minor) |
| Premium subscription additional maintenance | `rhel_prem` | **even** minors (EUS, 2 years) |
| Extended Life Cycle, Premium subscription additional maintenance | `rhel_elcp` | even minors from RHEL 9.2+, 8.10, 10.2+ (6 years from GA) |
| Long Life add-on terms | `rhel_ll` | last minor of a major (8.10, 9.10, 10.10) |

**ELC eligibility**: 6 years from minor GA on even minors ≥ 9.2, on 8.10, and on 10.2+ (not 10.0/10.1).  
**Long Life**: extends beyond major year 10 on the final minor; yearly renewal per Long Life add-on terms.

### Major versions (default chart view)

| Subscription phase | Chart key | Notes |
|--------------------|-----------|-------|
| Standard subscription | `rhel_std` | years 1–10 (Full + Maintenance support combined) |
| Extended life cycle support (ELS) add-on | `rhel_els` | **RHEL 7 only** |
| Extended Life Cycle, Premium subscription additional maintenance | `rhel_elcp` | RHEL 8/9/10 — extended maintenance after year 10 |
| Long Life add-on terms | `rhel_ll` | RHEL 8+ when `.10` minor dates are known |

`build_rhel_major_versions()` reads `_RHEL_MAJOR_DATA` (from `rhel_majors`).  
`build_rhel_minor_versions(major)` reads `_RHEL_MINOR_DATA` (from `rhel_minors`).

### ELS vs ELC

| Abbreviation | Full name | Applies to | YAML field |
|---|---|---|---|
| **ELS** | Extended life cycle support (ELS) add-on | RHEL **7** major only | `els_end` in `rhel_majors` |
| **ELC** | Extended Life Cycle, Premium subscription additional maintenance | RHEL **8/9/10** minors and majors | `elc_end` in `rhel_minors` / `rhel_majors` |

The lifecycle API conflates these programs and returns inaccurate major-level dates. Maintain RHEL dates manually from the [errata policy page](https://access.redhat.com/support/policy/updates/errata).

### RHEL minor versions (the "Show minor releases" toggle)

Minor release dates are embedded as images on the errata page — not available from any API. Stored in `rhel_minors`.

**To update dates**: edit `rhel_minors` and/or `rhel_majors` in `lifecycle-config.yaml`. See the [field reference](#field-reference) above.

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

- API often returns relative dates (`Release of X.Y`, `Release of X.Y + N months`) instead of ISO dates.
- When the referenced version is **not yet published** in the API, the chart treats that phase as **ongoing** (badge shows **active**) rather than EOL.
- Once Red Hat publishes the referenced version with a GA date, the phase end resolves automatically.
- Use `version_strategy: rolling-eol` and `phase_map_preset: rolling-ga-eol` for operators with only GA + EOL phases.

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
| 2nd | `fallback:` blocks in `lifecycle-config.yaml` | API unreachable or returns 0 versions |

**API-first rule:** when the API returns a version, only phases present in the API response are used. The `fallback:` dict is **not** merged field-by-field to fill missing phases. If the API omits a phase date (N/A or unparseable), that segment is simply omitted from the chart.

The API is queried with `Accept-Language: en-US` to prevent localised responses.

`_parse_api_date` handles ISO datetimes, ISO dates with trailing text, `"Month D, YYYY"`, and `"Estimated Month, YYYY"` (last day of month). Returns `None` for `"N/A"` and other unparseable strings.

**Relative release dates:** some products and operators return phase ends as relative strings instead of calendar dates, for example:

| Pattern | Example |
|---------|---------|
| `Release of X.Y` (+ optional `+ N months`) | Pipelines, VolSync |
| `X.YGA + N Months` | ODF |
| `X.Y GA + N months` | Windows Containers, LSO |
| `GA of X.Y + N Months` | Quay, NUMA Resources, PTP |
| `with the release of X.Y` | Gatekeeper |
| `ReleaseX.Y+N month` | cert-manager |

The generator builds a GA-date index from all versions in the API response and resolves these references. If the referenced version is not published yet (or uses a wildcard like `4.N`), the phase is marked **open-ended** (still supported, shown as **active** on the chart). This applies to all API-backed entries.

### Validating phase_map coverage

Before adding or changing a product, run:

```bash
python3 lifecycle-graph.py --validate-phases
```

This fetches each API-backed entry and reports `UNMAPPED_PHASE` errors when `product.all_phases` contains a name not in `phase_map`. Exit code 0 means all entries are covered. RHEL (`use_major_phases`) is skipped.

Use `phase_map_preset` for standard phase shapes; add inline `phase_map` entries to **extend** a preset (they are merged on top, not replaced).

---

## Adding a new product category

1. Add phase keys to `PHASES` and `PHASE_KEYS` in `lifecycle-graph.py` if needed.
2. Add a `*_CONFIGS` dict and populate it from YAML via a new `_apply_*_overrides()` function called from `_load_external_config()`.
3. Add a `_fetch_*` block in `_fetch_all()`.
4. Add a `_render_*_section()` renderer or reuse `_render_operator_section()`.
5. Wire into `render_combined_html()`: add nav button and include section in `body`.
6. Write a per-product HTML file in `main()` under `--product all`.
7. Add the new top-level key to `lifecycle-config.yaml`.
