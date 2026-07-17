# Development guide

How to work on lifecycle-graph from the code base: where things live, how to
change behavior safely, and how to verify your change. Companion files:
[README.md](README.md) (usage), [LIFECYCLE.md](LIFECYCLE.md) (YAML schema
reference), [RELEASE_NOTE_TEMPLATE.md](RELEASE_NOTE_TEMPLATE.md) (feature-card
look & feel), [CLAUDE.md](CLAUDE.md) (condensed rules; same constraints apply
to humans).

## Setup

```bash
pip install pyyaml                 # only dependency (rsvg-convert for --png)
python3 lifecycle-graph.py --product ocp --output-dir /tmp/test   # fast smoke
python3 -m unittest discover -s tests -v                          # offline tests
```

Local preview of the full site:

```bash
python3 lifecycle-graph.py --product all --output-dir docs   # ~3-5 min (network)
python3 -m http.server 8080 --directory docs                 # or: python3 server.py
```

`--skip-details` skips the errata/feature fetches (and the details/timeline
pages) — use it when you only work on charts.

## Big picture

One script, `lifecycle-graph.py` (~3000 lines), stdlib-only, generates a fully
static site into `docs/`. No template engine — HTML is built with f-strings.
No runtime backend: every page works over `file://`; the only JS is inline
vanilla (filters, delta compare, theme toggle).

```
lifecycle-config.yaml ──▶ PRODUCT_CONFIGS / OPERATOR_CONFIGS / MIDDLEWARE_CONFIGS / _RHEL_*_DATA
        │                                (loaded at import by _load_external_config)
        ├─ charts:   fetch_lifecycle ─▶ build_versions ─▶ _render_card ─▶ _page_wrap
        └─ details:  build_details_data ─▶ render_details_html / render_timeline_html
                     │        ▲ sidecar lifecycle-{key}-details.json = offline cache
                     ├─ errata:   Hydra search (access.redhat.com/hydra/rest/search/kcs)
                     └─ features: docs repo asciidoc (OCP/AAP) or portal docs index
```

Data sources (all unauthenticated):

| Source | Used for | Notes |
|---|---|---|
| `access.redhat.com/product-life-cycles/api/v1/products` | chart phases | fallback: YAML `fallback:` blocks |
| `access.redhat.com/hydra/rest/search/kcs` | errata (z-streams) + docs index (feature cards) | `documentKind:Errata` / `Documentation` |
| `raw.githubusercontent.com` (openshift-docs, aap-docs) | feature cards, best fidelity | branch per minor |
| docs.redhat.com | **link-outs only** | Akamai blocks all non-browser clients — do not try to scrape it |

## Function index (what to touch for what)

| Change | Where |
|---|---|
| Product/operator/version data, dates | `lifecycle-config.yaml` **only** — never Python |
| YAML → runtime config | `_apply_product_overrides` / `_apply_operator_overrides` / `_apply_middleware_overrides` |
| Chart phase colors / new phase *type* | `PHASES` dict + `PHASE_KEYS` list (order matters — chronological) |
| Version parsing strategy | `_VERSION_STRATEGIES` + `_parse_*` functions; wire via `version_strategy` in YAML |
| Card layout (Gantt) | `_render_card` |
| Page shell, masthead, theme bootstrap | `_page_wrap` |
| Breadcrumb / Chart-Details-Timeline switcher | `_breadcrumb`, `_view_toggle`, `_details_topbar` |
| Errata fetch/grouping | `_fetch_errata_page`, `fetch_errata_for_minor`, `build_details_data` |
| Erratum highlight cards (🔒/🔧/✨ per z-stream) | `_extract_bullets`, `_render_highlight_cards` |
| Feature cards from asciidoc repos | `fetch_release_features`, `_parse_adoc_features`, `_parse_adoc_attributes`, `_clean_adoc_inline` |
| Feature cards from the docs index | `fetch_features_docs_search`, `_split_chapter_abstract` |
| Details page assembly | `render_details_html`, `_render_features_card`, `_minor_meta` |
| Timeline page | `render_timeline_html`, `_TIMELINE_JS` |
| Delta (From→To) filter JS | `_DETAILS_JS` |
| CSS | `static/css/chart.css` — bump `_ASSET_VERSION` after every change (cache bust) |
| SVG/PNG export | `render_svg`, `export_png` |

## Recipes

### Add a product / operator (data only)

Edit `lifecycle-config.yaml` — see LIFECYCLE.md for the schema and CLAUDE.md
for the api_name lookup curl. No Python changes.

### Give a product a Details/Timeline page

Add a `details:` block (see CLAUDE.md "Details pages"). Minimum: an
`errata_query`. Options: `features_url`/`attributes_url`/`attributes`
(asciidoc repo), `features_search` (docs-index fallback), `minors_from:
rhel_minors`, omit `errata_query` for feature-only pages (RHEL). The card
link, both pages, and the JSON sidecar appear automatically.

### Tune the feature cards

- Rendering/format rules live in RELEASE_NOTE_TEMPLATE.md — keep both sources
  mapping to the same `{area, items:[{t,d,u}]}` schema.
- Asciidoc parsing quirks (new doc layout): `_parse_adoc_features` supports
  heading levels (book vs module), definition lists (`Title::`), bullet-only
  sections, and one `include::…new-features…` hop. `fetch_release_features`
  picks nested vs flat parse by item count (flat wins only when nested finds
  nothing or <½ of flat's entries).
- Docs-index quirks: `_split_chapter_abstract` splits chapter abstracts on
  `N.N.` numbering; boilerplate/noise filters are `_ABSTRACT_BOILERPLATE` and
  `_ITEM_NOISE_PREFIXES`.

### Change look & feel

- Theme variables: `html[data-theme="light"]` / `html[data-theme="dark"]`
  blocks in `chart.css`. Details/errata colors: `--errata-security/-bugfix/-enhancement`.
- PatternFly v6 comes from the CDN; components used as plain markup
  (`pf-v6-c-breadcrumb`, `pf-v6-c-toggle-group`, masthead). Dark mode = both
  `data-theme="dark"` and `pf-v6-theme-dark` class on `<html>` (set by the
  inline bootstrap script in `_page_wrap`).
- Always bump `_ASSET_VERSION`.

### RHEL dates

`rhel_majors` / `rhel_minors` YAML blocks; field meanings in CLAUDE.md. Dates
must be quoted strings.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_lifecycle_graph.py` is offline — all fetchers are monkeypatched;
fixtures cover every asciidoc layout the parser supports, abstract splitting,
details-data grouping (per-minor, shared query, feature-only, RHEL minors) and
rendering invariants (delta bar only with z-streams, no "General" heading,
linked feature titles). CI runs the suite before generating.

When you change a parser, add a fixture reproducing the new layout first.

Manual verification of a generated page:

```bash
python3 lifecycle-graph.py --product ocp --output-dir /tmp/t
open /tmp/t/lifecycle-ocp-details.html      # works over file://
```

Failure paths worth re-checking after touching `_generate_details_page`: run
offline → charts must still generate, details page rebuilds from the committed
sidecar JSON with a stale notice, sidecar not overwritten.

## CI

`.github/workflows/update-lifecycle.yml`: daily 06:00 UTC + push to `main`
(paths: script, YAML, LIFECYCLE.md, tests/, static/) + manual dispatch.
Steps: tests → generate `--product all --png` → commit `docs/` if changed.
The committed `docs/lifecycle-*-details.json` files double as the offline
cache for the graceful-failure path — don't gitignore them.

## Ground rules

- Data lives in YAML, never in Python (`fallback` dicts, dates, product names).
- Static only: no runtime fetches from pages, no auth, nothing that breaks `file://`.
- Network failures must never break chart generation.
- New feature sources map into the existing card schema — no new rendering paths.
- Comment density: sparse; explain constraints, not mechanics.
