# Release-notes card template

Canonical look & feel for the "What's new" feature cards on `lifecycle-{key}-details.html`.
Every product's card must follow this template regardless of where its data comes from.
The renderer (`_render_features_card` in `lifecycle-graph.py`) enforces it; this file is
the reference when adding a product or a new feature source.

## Card anatomy

```
✨ What's new in {minor}   [N features]              from release notes        ▾
│
│  AREA NAME (uppercase, accent color)          ← omitted when source has no areas
│    **Feature title** — One-paragraph description trimmed to ~400 chars.
│    **Feature title** — Description…
│
│  NEXT AREA
│    …
```

Element rules:

| Element | Rule |
|---|---|
| Card container | `<details class="note-card note-card--enhancement features-card">`, collapsed by default |
| Header | `✨ What's new in {minor}` + count badge (`N features`) + right-aligned `from release notes` |
| Area heading | `<h4 class="features-card__area">` — uppercase via CSS, accent (enhancement blue). **Never render a literal "General" heading**; a `General` group means "no area structure" and its items render directly |
| Feature line | `<li><b>title</b> — description</li>` — **plain text, never a link**; the minor header's `↗ release notes` is the single way out to the source |
| Description | Single paragraph, plain text (no markup), ≤400 chars from adoc sources, ≤350 from the docs index; truncation is word-boundary with `…` (no mid-word cuts); may be empty (title-only line, e.g. bullet features) |
| Body | Scrollable (`max-height: 480px`) so huge cards don't dominate the page |
| Official link | The minor-section header (outside the card) always carries `↗ release notes` when `release_notes_url` is set — the card never duplicates it |

## Data schema (sidecar JSON, per minor)

```json
"features": [
  { "area": "Authentication and authorization",
    "items": [
      { "t": "Feature title", "d": "Short description…" }
    ] }
]
```

- `area` — grouping label. `"General"` = no grouping (renderer hides the heading).
- `t` — feature title, ≤200 chars (adoc) / ≤90 (docs index). `d` — description, may be `""`. No per-item URLs.
- Upgrade/migration/how-to sections that live inside "New features" docs are **not**
  features and must be filtered out (`_FEATURE_TITLE_SKIP`).

## Sources and how they map to the template

Configured per product in `lifecycle-config.yaml` under `details:` (see CLAUDE.md):

1. **`features_url`** (asciidoc from a public docs repo — best fidelity; OCP, AAP):
   areas = section headings, items = feature headings/definition-list entries/bullets
   with their first paragraph. Products whose adoc has no area level (AAP) produce a
   single `General` group → items render without a heading.
2. **`features_search`** (portal docs index — fallback for products without a public
   docs source; RHEL, RHOAI, Ceph, OSP, RHOSO, Satellite): areas = release-notes
   chapter titles (Overview / New features and enhancements / Technology Preview…),
   items = numbered subsections split out of the chapter abstract. Boilerplate
   sentences ("This part describes…", "Review new features…") are stripped; noise
   lines ("For information…", "Additional resources…") are dropped.

Both sources must emit the same schema above — any new source (new product repo,
new API) must map into it rather than introducing a new rendering path.

## Consistency checklist for a new product

- [ ] Card header reads `What's new in {minor}` with an accurate count badge
- [ ] No "General" heading visible; real areas render uppercase/accent
- [ ] Every feature is one `<b>title</b> — description` line, no text walls
- [ ] No links inside the card — titles and descriptions are plain text
- [ ] Truncation never cuts mid-word (ends with `…`); titles stay short (≤90/200)
- [ ] No upgrade/migration entries masquerading as features
- [ ] Descriptions carry no leftover asciidoc attributes (`{product-title}`) or
      boilerplate lead-ins
- [ ] Minor-section header has the `↗ release notes` link
- [ ] Failures are non-fatal: minors without data simply have no card
