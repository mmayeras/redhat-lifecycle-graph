#!/usr/bin/env python3
"""Red Hat product lifecycle Gantt chart generator — standalone, no dependencies."""

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Fallback data (used when API is unreachable) ─────────────────────────────

_OCP_FALLBACK: dict[str, dict] = {
    "4.12": {"ga": "2023-01-17", "fs_end": "2023-08-17", "mnt_end": "2024-07-17",
             "eus1_end": "2025-01-17", "eus2_end": "2026-01-17"},
    "4.13": {"ga": "2023-05-17", "fs_end": "2024-01-31", "mnt_end": "2024-11-17"},
    "4.14": {"ga": "2023-10-31", "fs_end": "2024-05-27", "mnt_end": "2025-05-01",
             "eus1_end": "2025-10-31", "eus2_end": "2026-10-31"},
    "4.15": {"ga": "2024-02-27", "fs_end": "2024-09-27", "mnt_end": "2025-08-27"},
    "4.16": {"ga": "2024-06-27", "fs_end": "2025-01-01", "mnt_end": "2025-12-27",
             "eus1_end": "2026-06-27", "eus2_end": "2027-06-27"},
    "4.17": {"ga": "2024-10-01", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "4.18": {"ga": "2025-02-25", "fs_end": "2025-09-17", "mnt_end": "2026-08-25",
             "eus1_end": "2027-02-25", "eus2_end": "2028-02-25"},
    "4.19": {"ga": "2025-06-17", "fs_end": "2026-01-21", "mnt_end": "2026-12-17"},
    "4.20": {"ga": "2025-10-21", "fs_end": "2026-05-03", "mnt_end": "2027-04-21",
             "eus1_end": "2027-10-21", "eus2_end": "2028-10-21"},
    "4.21": {"ga": "2026-02-03", "fs_end": "2026-08-03", "mnt_end": "2027-08-03"},
}

_RHEL_FALLBACK: dict[str, dict] = {
    "7":  {"ga": "2014-06-10", "fs_end": "2019-08-06", "mnt_end": "2024-06-30",
           "els_end": "2028-06-30"},
    "8":  {"ga": "2019-05-07", "fs_end": "2024-05-31", "mnt_end": "2029-05-31"},
    "9":  {"ga": "2022-05-18", "fs_end": "2027-05-31", "mnt_end": "2032-05-31"},
    "10": {"ga": "2025-05-01", "fs_end": "2030-05-31", "mnt_end": "2035-05-31"},
}

_AAP_FALLBACK: dict[str, dict] = {
    "2.4": {"ga": "2023-09-27", "fs_end": "2024-09-27", "mnt_end": "2025-09-27",
            "mnt2_end": "2026-09-27"},
    "2.5": {"ga": "2024-10-01", "fs_end": "2025-10-01", "mnt_end": "2026-10-01",
            "mnt2_end": "2027-10-01"},
    "2.6": {"ga": "2025-10-01", "fs_end": "2026-10-01", "mnt_end": "2027-10-01",
            "mnt2_end": "2028-10-01"},
    "2.7": {"ga": "2026-10-01", "fs_end": "2027-10-01", "mnt_end": "2028-10-01",
            "mnt2_end": "2029-10-01"},
}


def _parse_ocp(v: str) -> tuple:
    return (4, int(v.split(".")[1]))


def _parse_rhel(v: str) -> tuple:
    return (int(v),)


def _parse_aap(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


PRODUCT_CONFIGS: dict[str, dict] = {
    "ocp": {
        "api_name": "OpenShift Container Platform 4",
        "title":    "OCP Lifecycle",
        "phase_map": {
            "General availability":           "ga",
            "Full support":                   "fs_end",
            "Maintenance support":            "mnt_end",
            "Extended update support":        "eus1_end",
            "Extended update support Term 2": "eus2_end",
            "Extended life phase":            "elp_end",
        },
        "fallback":   _OCP_FALLBACK,
        "parse_ver":  _parse_ocp,
        "min_filter": lambda v: (
            "." in v and v.startswith("4.") and len(v.split(".")) == 2
            and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 12
        ),
        "eus_check":  lambda v: int(v.split(".")[1]) % 2 == 0,
    },
    "rhel": {
        "api_name": "Red Hat Enterprise Linux",
        "title":    "RHEL Lifecycle",
        "phase_map": {
            "General availability":                      "ga",
            "Full support":                              "fs_end",
            "Maintenance support":                       "mnt_end",
            "Extended life cycle support (ELS) add-on": "els_end",
            "Extended life phase":                       "elp_end",
        },
        "fallback":   _RHEL_FALLBACK,
        "parse_ver":  _parse_rhel,
        "min_filter": lambda v: v.isdigit() and int(v) >= 7,
        "eus_check":  None,
    },
    "aap": {
        "api_name": "Red Hat Ansible Automation Platform",
        "title":    "AAP Lifecycle",
        "phase_map": {
            "General availability":           "ga",
            "Full support":                   "fs_end",
            "Maintenance Support 1":          "mnt_end",
            "Maintenance support 2":          "mnt2_end",
            "Extended update support":        "eus1_end",
            "Extended update support Term 2": "eus2_end",
        },
        "fallback":   _AAP_FALLBACK,
        "parse_ver":  _parse_aap,
        "min_filter": lambda v: (
            "." in v and len(v.split(".")) == 2
            and all(x.isdigit() for x in v.split("."))
            and int(v.split(".")[0]) >= 2
        ),
        "eus_check":  None,
    },
}

# ── Phase palette (PatternFly-aligned) ───────────────────────────────────────
PHASES: dict[str, dict] = {
    "fs":   {"label": "Full Support",  "bg": "#bde5b8", "border": "#1e4f18", "text": "#1e4f18"},
    "mnt":  {"label": "Maintenance",   "bg": "#f9e0a2", "border": "#795600", "text": "#795600"},
    "mnt2": {"label": "Maintenance 2", "bg": "#f4b678", "border": "#8f4700", "text": "#8f4700"},
    "eus1": {"label": "EUS-1",         "bg": "#bee1f4", "border": "#004080", "text": "#004080"},
    "eus2": {"label": "EUS-2",         "bg": "#e7d4ff", "border": "#40199a", "text": "#40199a"},
    "els":  {"label": "ELS",           "bg": "#faeae8", "border": "#c9190b", "text": "#a30000"},
    "elp":  {"label": "Ext. Life",     "bg": "#e4e4e4", "border": "#6a6e73", "text": "#3c3f42"},
}

# Chronological order — segments built and phase status detected in this order
PHASE_KEYS = [
    ("fs",   "fs_end"),
    ("mnt",  "mnt_end"),
    ("mnt2", "mnt2_end"),
    ("eus1", "eus1_end"),
    ("eus2", "eus2_end"),
    ("els",  "els_end"),
    ("elp",  "elp_end"),
]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def fetch_lifecycle(cfg: dict) -> dict[str, dict]:
    """Fetch lifecycle for a product from Red Hat API; fall back to static data."""
    name_param = cfg["api_name"].replace(" ", "+")
    url = f"https://access.redhat.com/product-life-cycles/api/v1/products?name={name_param}"
    phase_map = cfg["phase_map"]
    min_filter = cfg["min_filter"]
    fallback = cfg["fallback"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lifecycle-graph/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        product = data["data"][0]
        result: dict[str, dict] = {}
        for ver_data in product["versions"]:
            name = ver_data["name"]
            if " " in name or not min_filter(name):
                continue
            dates: dict[str, str] = {}
            for phase in ver_data["phases"]:
                key = phase_map.get(phase["name"])
                end = phase.get("end_date", "")
                if key and isinstance(end, str) and end.startswith("20"):
                    dates[key] = end[:10]
            if "fs_end" not in dates and name in fallback and "fs_end" in fallback[name]:
                dates["fs_end"] = fallback[name]["fs_end"]
            if "ga" in dates and "mnt_end" in dates:
                result[name] = dates
        if result:
            print(f"Fetched {len(result)} {cfg['title']} versions from Red Hat API.", file=sys.stderr)
            return result
    except Exception as exc:
        print(f"API fetch failed for {cfg['title']} ({exc}), using fallback.", file=sys.stderr)
    return dict(fallback)


def build_versions(
    lifecycle: dict[str, dict],
    cfg: dict,
    versions_filter: list[str] | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    include_eol: bool = False,
) -> list[dict]:
    parse_ver = cfg["parse_ver"]
    eus_check = cfg.get("eus_check")

    keys = sorted(lifecycle.keys(), key=parse_ver)
    if versions_filter:
        keys = [k for k in keys if k in versions_filter]
    if from_version:
        lo = parse_ver(from_version)
        keys = [k for k in keys if parse_ver(k) >= lo]
    if to_version:
        hi = parse_ver(to_version)
        keys = [k for k in keys if parse_ver(k) <= hi]

    today = date.today()
    result = []
    for ver in keys:
        lc = lifecycle[ver]
        ga = _d(lc["ga"])
        segments, prev = [], ga
        for key, field in PHASE_KEYS:
            val = lc.get(field)
            if not val:
                continue
            end = _d(val)
            if end > prev:
                segments.append({"key": key, "start": prev, "end": end})
                prev = end
        last_end = prev
        is_eus = bool(eus_check and eus_check(ver))
        phase_key = "eol"
        days_left = 0
        for key, field in PHASE_KEYS:
            val = lc.get(field)
            if val and today <= _d(val):
                phase_key = key
                days_left = (_d(val) - today).days
                break
        is_eol = phase_key == "eol"
        if is_eol and not include_eol:
            continue
        result.append({
            "version": ver, "ga": ga, "last_end": last_end,
            "segments": segments, "is_eus": is_eus,
            "is_eol": is_eol, "phase_key": phase_key, "days_left": days_left,
        })
    return result


_PAGE_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Red Hat Text","Red Hat Display","Open Sans",system-ui,sans-serif;
    background: #f5f5f5;
    color: #151515;
    padding: 0;
    margin: 0;
  }
  .page-header {
    background: #151515;
    color: #fff;
    padding: 18px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .page-header h1 { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }
  .page-nav { display: flex; gap: 8px; }
  .page-nav a {
    color: #e0e0e0;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 4px;
    border: 1px solid #444;
  }
  .page-nav a:hover { background: #333; color: #fff; }
  .page-content {
    max-width: 1148px;
    margin: 0 auto;
    padding: 28px 24px 48px;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .card {
    background: #fff;
    border: 1px solid #d2d2d2;
    border-radius: 8px;
    width: 100%;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    overflow: hidden;
  }
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 24px;
    background: #f0f0f0;
    border-bottom: 1px solid #d2d2d2;
    flex-wrap: wrap;
    gap: 10px;
  }
  .card-title {
    font-size: 15px;
    font-weight: 700;
    color: #151515;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
  .chart-area { padding: 64px 24px 20px; position: relative; background: #fff; }
  .chart-grid {
    position: absolute;
    top: 64px; bottom: 20px;
    left: calc(24px + 130px); right: calc(24px + 60px);
    pointer-events: none;
  }
  .chart-rows {
    position: relative; z-index: 1;
    display: flex; flex-direction: column; gap: 6px;
  }
  .chart-rows > div:nth-child(even) { background: #fafafa; }
  .footer {
    padding: 8px 24px 12px;
    font-size: 11px; color: #6a6e73;
    border-top: 1px solid #d2d2d2; background: #f0f0f0;
  }
  .footer a { color: #0066cc; text-decoration: none; }
  .footer a:hover { text-decoration: underline; }
  code { font-family: "Red Hat Mono","Courier New",monospace; }
"""


def _render_card(versions: list[dict], chart_label: str, anchor: str = "",
                 show_footer: bool = True) -> str:
    today = date.today()
    pad = timedelta(days=60)
    all_dates = [v["ga"] for v in versions] + [v["last_end"] for v in versions] + [today]
    chart_start = min(all_dates) - pad
    chart_end = max(all_dates) + pad
    total_days = (chart_end - chart_start).days

    def pct(d: date) -> float:
        return (d - chart_start).days / total_days * 100

    today_pct = pct(today)
    used_phases = {seg["key"] for v in versions for seg in v["segments"]}

    # ── Year markers ────────────────────────────────────────────────────────
    year_markers = []
    for y in range(chart_start.year, chart_end.year + 2):
        d = date(y, 1, 1)
        if chart_start <= d <= chart_end:
            year_markers.append({"year": y, "pct": pct(d)})

    year_lines_html = "".join(
        f'<div style="position:absolute;left:{m["pct"]:.3f}%;top:0;bottom:0;'
        f'border-left:1px dashed #d2d2d2;z-index:0"></div>'
        f'<div style="position:absolute;left:{m["pct"]:.3f}%;top:-20px;'
        f'font-size:11px;color:#6a6e73;transform:translateX(-50%);font-weight:600;white-space:nowrap">'
        f'{m["year"]}</div>'
        for m in year_markers
    )

    today_html = (
        f'<div style="position:absolute;left:{today_pct:.3f}%;top:0;bottom:0;'
        f'border-left:1.5px dashed #a30000;opacity:0.7;z-index:2"></div>'
        f'<div style="position:absolute;left:{today_pct:.3f}%;top:-52px;'
        f'font-size:11px;color:#a30000;transform:translateX(-50%);'
        f'font-weight:700;white-space:nowrap;background:rgba(255,255,255,0.9);'
        f'padding:1px 4px;border-radius:2px;border:1px solid rgba(163,0,0,0.25)">Today</div>'
    )

    # ── Rows ────────────────────────────────────────────────────────────────
    rows_html = ""
    for v in versions:
        bar_left = pct(v["ga"])
        bar_right = pct(v["last_end"])
        bar_width = bar_right - bar_left
        total_bar_days = (v["last_end"] - v["ga"]).days

        segs_html = ""
        for i, seg in enumerate(v["segments"]):
            ph = PHASES[seg["key"]]
            w = (seg["end"] - seg["start"]).days / total_bar_days * 100
            is_first, is_last = i == 0, i == len(v["segments"]) - 1
            r = f"{'4px' if is_first else '0'} {'4px' if is_last else '0'} {'4px' if is_last else '0'} {'4px' if is_first else '0'}"
            bl = f"1.5px solid {ph['border']}" if is_first else "none"
            br = f"1.5px solid {ph['border']}" if is_last else "none"
            show_label = w > 5
            inner = f'<span style="font-size:11px;color:{ph["text"]};font-weight:600;white-space:nowrap;padding:0 6px">{ph["label"]}</span>' if show_label else ""
            segs_html += (
                f'<div title="{ph["label"]} — ends {seg["end"].isoformat()}" '
                f'style="width:{w:.3f}%;height:100%;background:{ph["bg"]};'
                f'border-top:1.5px solid {ph["border"]};border-bottom:1.5px solid {ph["border"]};'
                f'border-left:{bl};border-right:{br};border-radius:{r};'
                f'display:flex;align-items:center;justify-content:center;overflow:hidden">'
                f'{inner}</div>'
            )

        eol_overlay = (
            '<div style="position:absolute;inset:0;background:repeating-linear-gradient('
            '135deg,transparent,transparent 3px,rgba(163,0,0,0.1) 3px,rgba(163,0,0,0.1) 6px);'
            'border-radius:3px;pointer-events:none"></div>'
        ) if v["is_eol"] else ""

        if v["is_eol"]:
            days_badge = '<span style="color:#a30000;font-weight:700;font-size:13px">EOL</span>'
        else:
            ph = PHASES[v["phase_key"]]
            days_badge = f'<span style="color:{ph["text"]};font-weight:600;font-size:13px" title="{ph["label"]} — {v["days_left"]} days remaining">{v["days_left"]}d</span>'

        eus_badge = '<span style="font-size:9px;color:#40199a;font-weight:700;margin-left:4px;vertical-align:middle">EUS</span>' if v["is_eus"] else ""

        rows_html += (
            f'<div style="display:flex;align-items:center;height:48px">'
            f'  <div style="width:130px;flex-shrink:0;padding-right:10px;overflow:hidden;display:flex;align-items:center">'
            f'    <code style="font-size:15px;color:#151515;font-weight:700">{v["version"]}</code>{eus_badge}'
            f'  </div>'
            f'  <div style="flex:1;position:relative;height:34px">'
            f'    <div style="position:absolute;left:{bar_left:.3f}%;width:{bar_width:.3f}%;height:100%;'
            f'border-radius:4px;overflow:hidden;display:flex">{segs_html}{eol_overlay}</div>'
            f'  </div>'
            f'  <div style="width:48px;flex-shrink:0;text-align:right;padding-left:8px">{days_badge}</div>'
            f'</div>'
        )

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_html = " ".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#151515">'
        f'<span style="display:inline-block;width:14px;height:12px;border-radius:2px;'
        f'background:{PHASES[k]["bg"]};border:1.5px solid {PHASES[k]["border"]}"></span>'
        f'{PHASES[k]["label"]}</span>'
        for k, _ in PHASE_KEYS
        if k in used_phases
    )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n = len(versions)
    rows_px = n * 48 + (n - 1) * 6
    chart_area_h = 64 + rows_px + 20
    anchor_attr = f' id="{anchor}"' if anchor else ""

    footer_html = (
        f'<div class="footer">'
        f'Source: <a href="https://access.redhat.com/product-life-cycles/" target="_blank">'
        f'Red Hat Product Life Cycles</a>'
        f' &nbsp;·&nbsp; Generated {now_str}'
        f'</div>'
    ) if show_footer else ""

    return f"""<div class="card"{anchor_attr}>
  <div class="card-header">
    <span class="card-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#151515" stroke-width="2">
        <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
      </svg>
      {chart_label}
    </span>
    <div class="legend">
      {legend_html}
      <span style="font-size:11px;color:#a30000;opacity:0.75">┆ Today ({today.isoformat()})</span>
    </div>
  </div>
  <div class="chart-area" style="height:{chart_area_h}px">
    <div class="chart-grid">
      {year_lines_html}
      {today_html}
    </div>
    <div class="chart-rows">
      {rows_html}
    </div>
  </div>
  {footer_html}
</div>"""


def _page_wrap(title: str, body: str, nav_links: str = "") -> str:
    nav_html = f'<nav class="page-nav">{nav_links}</nav>' if nav_links else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
{_PAGE_CSS}
</style>
</head>
<body>
<header class="page-header">
  <h1>{title}</h1>
  {nav_html}
</header>
<div class="page-content">
{body}
</div>
</body>
</html>"""


def render_html(versions: list[dict], chart_label: str, show_footer: bool = True) -> str:
    card = _render_card(versions, chart_label, show_footer=show_footer)
    return _page_wrap(chart_label, card)


def render_combined_html(
    product_list: list[tuple[str, list[dict]]],
    title: str = "Red Hat Product Lifecycle",
) -> str:
    nav_links = "".join(
        f'<a href="#{label.lower().replace(" ", "-")}">{label}</a>'
        for label, _ in product_list
    )
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "\n".join(
        _render_card(versions, label, anchor=label.lower().replace(" ", "-"), show_footer=False)
        for label, versions in product_list
    )
    footer = (
        f'<p style="text-align:center;font-size:11px;color:#6a6e73;margin-top:4px">'
        f'Source: <a href="https://access.redhat.com/product-life-cycles/" '
        f'style="color:#0066cc" target="_blank">Red Hat Product Life Cycles</a>'
        f' &nbsp;·&nbsp; Generated {now_str}'
        f' &nbsp;·&nbsp; '
        f'<a href="https://github.com/mmayeras/redhat-lifecycle-graph" style="color:#0066cc;display:inline-flex;align-items:center;gap:4px;vertical-align:middle" target="_blank">'
        f'<svg height="13" width="13" viewBox="0 0 16 16" fill="#0066cc" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38'
        f' 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13'
        f'-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66'
        f'.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15'
        f'-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09'
        f' 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15'
        f' 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2'
        f' 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>'
        f'</svg>View source on GitHub</a>'
        f' &nbsp;·&nbsp; Mickael Mayeras</p>'
    )
    return _page_wrap(title, cards + "\n" + footer, nav_links)


def render_svg(versions: list[dict], chart_label: str, width: int = 1400,
               _id_prefix: str = "c") -> str:
    LP, RP = 24, 24          # left/right padding
    LABEL_W = 130            # version label column
    DAYS_W = 60              # days badge column
    HEADER_H = 56            # card header
    CHART_TOP = 48           # space above rows for year labels
    ROW_H = 48               # row height
    ROW_GAP = 6              # gap between rows
    BOT_PAD = 24             # bottom padding
    BAR_H = 34               # bar height within row

    n = len(versions)
    rows_px = n * ROW_H + (n - 1) * ROW_GAP
    card_h = HEADER_H + CHART_TOP + rows_px + BOT_PAD

    chart_x = LP + LABEL_W
    chart_right = width - RP - DAYS_W
    chart_w = chart_right - chart_x

    today = date.today()
    pad = timedelta(days=60)
    all_dates = [v["ga"] for v in versions] + [v["last_end"] for v in versions] + [today]
    cs = min(all_dates) - pad   # chart start
    ce = max(all_dates) + pad   # chart end
    total = (ce - cs).days

    def px(d: date) -> float:
        return chart_x + (d - cs).days / total * chart_w

    C_BG        = "#ffffff"
    C_BG_ALT    = "#f0f0f0"
    C_BORDER    = "#d2d2d2"
    C_TEXT      = "#151515"
    C_MUTED     = "#6a6e73"
    C_TODAY     = "#a30000"
    C_EOL       = "#a30000"
    C_DIVIDER   = "rgba(0,0,0,0.18)"
    FONT        = "RedHatDisplay,RedHatText,'Red Hat Display','Red Hat Text','Open Sans',system-ui,sans-serif"
    MONO        = "RedHatMono,'Red Hat Mono','Courier New',monospace"

    els: list[str] = []

    els.append(
        '<defs>'
        '<pattern id="eol" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(135)">'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{C_EOL}" stroke-width="2" opacity="0.25"/>'
        '</pattern>'
        '</defs>'
    )

    els.append(f'<rect width="{width}" height="{card_h}" rx="8" fill="{C_BG}" stroke="{C_BORDER}" stroke-width="1"/>')
    els.append(f'<rect width="{width}" height="{HEADER_H}" rx="8" fill="{C_BG_ALT}"/>')
    els.append(f'<rect y="{HEADER_H - 8}" width="{width}" height="8" fill="{C_BG_ALT}"/>')
    els.append(f'<line x1="0" y1="{HEADER_H}" x2="{width}" y2="{HEADER_H}" stroke="{C_BORDER}" stroke-width="1"/>')

    els.append(f'<text x="{LP + 22}" y="35" font-family="{FONT}" font-size="14" font-weight="700" fill="{C_TEXT}">{chart_label}</text>')
    ix = LP
    els.append(f'<rect x="{ix}" y="19" width="15" height="15" rx="2" fill="none" stroke="{C_MUTED}" stroke-width="1.5"/>')
    els.append(f'<line x1="{ix+4}" y1="17" x2="{ix+4}" y2="22" stroke="{C_MUTED}" stroke-width="1.5"/>')
    els.append(f'<line x1="{ix+11}" y1="17" x2="{ix+11}" y2="22" stroke="{C_MUTED}" stroke-width="1.5"/>')
    els.append(f'<line x1="{ix}" y1="26" x2="{ix+15}" y2="26" stroke="{C_MUTED}" stroke-width="1"/>')

    used = {seg["key"] for v in versions for seg in v["segments"]}
    lx = LP + 185.0
    for k, _ in PHASE_KEYS:
        if k not in used:
            continue
        ph = PHASES[k]
        els.append(f'<rect x="{lx:.1f}" y="22" width="14" height="12" rx="2" fill="{ph["bg"]}" stroke="{ph["border"]}" stroke-width="1.5"/>')
        els.append(f'<text x="{lx + 19:.1f}" y="33" font-family="{FONT}" font-size="12" fill="{C_TEXT}">{ph["label"]}</text>')
        lx += 19 + len(ph["label"]) * 7.0 + 14
    els.append(f'<text x="{lx:.1f}" y="33" font-family="{FONT}" font-size="11" fill="{C_TODAY}" opacity="0.7">┆ Today ({today.isoformat()})</text>')

    grid_top = HEADER_H + CHART_TOP
    grid_bot = card_h - BOT_PAD
    for i in range(len(versions)):
        if i % 2 == 1:
            ry = HEADER_H + CHART_TOP + i * (ROW_H + ROW_GAP)
            els.append(f'<rect x="0" y="{ry}" width="{width}" height="{ROW_H}" fill="#fafafa"/>')

    tx = px(today)
    for y in range(cs.year, ce.year + 2):
        d = date(y, 1, 1)
        if not (cs <= d <= ce):
            continue
        x = px(d)
        els.append(f'<line x1="{x:.1f}" y1="{grid_top}" x2="{x:.1f}" y2="{grid_bot}" stroke="{C_BORDER}" stroke-width="1" stroke-dasharray="4 3"/>')
        els.append(f'<text x="{x:.1f}" y="{grid_top - 8}" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="600" fill="{C_MUTED}">{y}</text>')
    els.append(f'<line x1="{tx:.1f}" y1="{grid_top}" x2="{tx:.1f}" y2="{grid_bot}" stroke="{C_TODAY}" stroke-width="1.5" stroke-dasharray="5 3" opacity="0.7"/>')
    # Today label sits one row above year labels — white bg box ensures it's always readable
    els.append(f'<rect x="{tx - 22:.1f}" y="{grid_top - 40}" width="44" height="16" rx="3" fill="white" stroke="rgba(163,0,0,0.25)" stroke-width="1"/>')
    els.append(f'<text x="{tx:.1f}" y="{grid_top - 28}" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="700" fill="{C_TODAY}">Today</text>')

    for i, v in enumerate(versions):
        ry  = HEADER_H + CHART_TOP + i * (ROW_H + ROW_GAP)
        bar_y = ry + (ROW_H - BAR_H) / 2
        cy  = ry + ROW_H / 2

        bar_x = px(v["ga"])
        bar_w = px(v["last_end"]) - bar_x

        els.append(f'<text x="{chart_x - 10}" y="{cy + 5:.1f}" text-anchor="end" font-family="{MONO}" font-size="14" font-weight="700" fill="{C_TEXT}">{v["version"]}</text>')
        if v["is_eus"]:
            els.append(f'<text x="{chart_x - 8}" y="{cy - 7:.1f}" text-anchor="end" font-family="{FONT}" font-size="9" font-weight="700" fill="#40199a">EUS</text>')

        clip_id = f"{_id_prefix}{i}"
        els.append(f'<clipPath id="{clip_id}"><rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{BAR_H}" rx="3"/></clipPath>')

        els.append(f'<g clip-path="url(#{clip_id})">')
        for seg in v["segments"]:
            ph = PHASES[seg["key"]]
            sx = px(seg["start"])
            sw = px(seg["end"]) - sx
            els.append(f'<rect x="{sx:.1f}" y="{bar_y:.1f}" width="{sw:.1f}" height="{BAR_H}" fill="{ph["bg"]}"/>')
            if sw > 65:
                lbl_x = sx + sw / 2
                els.append(f'<text x="{lbl_x:.1f}" y="{bar_y + BAR_H/2 + 4:.1f}" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="600" fill="{ph["text"]}">{ph["label"]}</text>')
        if v["is_eol"]:
            els.append(f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{BAR_H}" fill="url(#eol)"/>')
        els.append('</g>')

        els.append(f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{BAR_H}" rx="3" fill="none" stroke="{C_BORDER}" stroke-width="1"/>')

        for seg in v["segments"][:-1]:
            dx = px(seg["end"])
            els.append(f'<line x1="{dx:.1f}" y1="{bar_y:.1f}" x2="{dx:.1f}" y2="{bar_y + BAR_H:.1f}" stroke="{C_DIVIDER}" stroke-width="1"/>')

        if v["is_eol"]:
            els.append(f'<text x="{chart_right + 8}" y="{cy + 5:.1f}" font-family="{FONT}" font-size="12" font-weight="700" fill="{C_EOL}">EOL</text>')
        else:
            ph = PHASES[v["phase_key"]]
            els.append(f'<text x="{chart_right + 8}" y="{cy + 5:.1f}" font-family="{FONT}" font-size="12" font-weight="600" fill="{ph["text"]}">{v["days_left"]}d</text>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{card_h}" '
        f'viewBox="0 0 {width} {card_h}">\n'
        + "\n".join(els)
        + "\n</svg>"
    )


def render_combined_svg(
    product_list: list[tuple[str, list[dict]]],
    width: int = 1400,
) -> str:
    """Stack per-product SVGs vertically into one combined SVG."""
    GAP = 24
    pieces: list[tuple[int, str]] = []  # (card_height, inner_svg_content)

    for i, (label, versions) in enumerate(product_list):
        svg_str = render_svg(versions, label, width, _id_prefix=f"p{i}r")
        # extract height="H" from opening <svg ...>
        import re
        m = re.search(r'height="(\d+)"', svg_str)
        h = int(m.group(1)) if m else 400
        # extract inner content (between first > and </svg>)
        inner_start = svg_str.index(">") + 1
        inner = svg_str[inner_start:svg_str.rindex("</svg>")]
        pieces.append((h, inner))

    total_h = sum(h for h, _ in pieces) + GAP * (len(pieces) - 1)
    parts = ['<defs></defs>']  # combined defs placeholder
    y = 0
    for h, inner in pieces:
        parts.append(f'<g transform="translate(0,{y})">{inner}</g>')
        y += h + GAP

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}" '
        f'viewBox="0 0 {width} {total_h}">\n'
        + "\n".join(parts)
        + "\n</svg>"
    )


def export_png(svg_path: Path, png_path: Path) -> bool:
    r = subprocess.run(["which", "rsvg-convert"], capture_output=True)
    if r.returncode != 0:
        print("PNG skipped: rsvg-convert not found. Install: apt install librsvg2-bin  |  brew install librsvg", file=sys.stderr)
        return False
    r = subprocess.run(["rsvg-convert", "-o", str(png_path), str(svg_path)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"PNG failed: {r.stderr[:200]}", file=sys.stderr)
        return False
    return True


def _fetch_all(args: argparse.Namespace) -> list[tuple[str, list[dict]]]:
    result = []
    for product in ["ocp", "rhel", "aap"]:
        cfg = PRODUCT_CONFIGS[product]
        lifecycle = fetch_lifecycle(cfg)
        label = cfg["title"]
        versions = build_versions(
            lifecycle, cfg,
            versions_filter=args.versions,
            from_version=args.from_version,
            to_version=args.to_version,
            include_eol=args.include_eol,
        )
        if versions:
            result.append((label, versions))
        else:
            print(f"No versions matched for {product}.", file=sys.stderr)
    return result


def _generate_product(
    product: str,
    out_html: Path,
    args: argparse.Namespace,
) -> None:
    cfg = PRODUCT_CONFIGS[product]
    lifecycle = fetch_lifecycle(cfg)
    chart_label = args.title if args.title else cfg["title"]

    versions = build_versions(
        lifecycle, cfg,
        versions_filter=args.versions,
        from_version=args.from_version,
        to_version=args.to_version,
        include_eol=args.include_eol,
    )
    if not versions:
        print(f"No versions matched for {product}.", file=sys.stderr)
        return

    html = render_html(versions, chart_label)
    out_html.write_text(html, encoding="utf-8")
    print(f"HTML: {out_html}  ({len(versions)} versions)")

    if args.png:
        svg_out = out_html.with_suffix(".svg")
        png_out = out_html.with_suffix(".png")
        svg_out.write_text(render_svg(versions, chart_label, args.width), encoding="utf-8")
        print(f"SVG:  {svg_out}")
        ok = export_png(svg_out, png_out)
        if ok:
            print(f"PNG:  {png_out}")

    if args.open:
        subprocess.run(["open", str(out_html)], check=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Red Hat product lifecycle Gantt charts as HTML + PNG")
    ap.add_argument("-o", "--output", default=None,
                    help="Output HTML file (default: lifecycle-{product}.html; all: lifecycle.html + index.html)")
    ap.add_argument("--product", default="ocp", choices=["ocp", "rhel", "aap", "all"],
                    help="Product to chart: ocp, rhel, aap, or all (default: ocp)")
    ap.add_argument("-v", "--versions", nargs="*", help="Explicit versions to include (e.g. 4.19 4.20)")
    ap.add_argument("--from", dest="from_version", metavar="VER", help="Start of version range, inclusive (e.g. 4.18)")
    ap.add_argument("--to", dest="to_version", metavar="VER", help="End of version range, inclusive (e.g. 4.22)")
    ap.add_argument("--title", default=None, help="Override page/card title")
    ap.add_argument("--open", action="store_true", help="Open HTML in browser after generating")
    ap.add_argument("--include-eol", dest="include_eol", action="store_true",
                    help="Include EOL versions (hidden by default)")
    ap.add_argument("--png", action="store_true",
                    help="Also export per-product SVG + PNG via rsvg-convert")
    ap.add_argument("--width", type=int, default=1400, help="SVG/PNG width in pixels (default: 1400)")
    args = ap.parse_args()

    out_dir = Path("docs")
    out_dir.mkdir(exist_ok=True)

    if args.product == "all":
        product_list = _fetch_all(args)
        page_title = args.title or "Red Hat Product Lifecycle"
        combined = render_combined_html(product_list, title=page_title)
        lifecycle_out = (out_dir / "lifecycle.html").resolve()
        index_out = (out_dir / "index.html").resolve()
        lifecycle_out.write_text(combined, encoding="utf-8")
        index_out.write_text(combined, encoding="utf-8")
        print(f"HTML: {lifecycle_out}  (all products)")
        print(f"HTML: {index_out}  (GitHub Pages index)")
        if args.png:
            svg_combined = (out_dir / "lifecycle.svg").resolve()
            png_combined = (out_dir / "lifecycle.png").resolve()
            svg_combined.write_text(render_combined_svg(product_list, args.width), encoding="utf-8")
            print(f"SVG:  {svg_combined}  (combined)")
            ok = export_png(svg_combined, png_combined)
            if ok:
                print(f"PNG:  {png_combined}  (combined)")
        for cfg_key, (label, versions) in zip(["ocp", "rhel", "aap"], product_list):
            out = (out_dir / f"lifecycle-{cfg_key}.html").resolve()
            html = render_html(versions, label)
            out.write_text(html, encoding="utf-8")
            print(f"HTML: {out}  ({len(versions)} versions)")
            if args.png:
                svg_out = out.with_suffix(".svg")
                png_out = out.with_suffix(".png")
                svg_out.write_text(render_svg(versions, label, args.width), encoding="utf-8")
                print(f"SVG:  {svg_out}")
                ok = export_png(svg_out, png_out)
                if ok:
                    print(f"PNG:  {png_out}")
        if args.open:
            subprocess.run(["open", str(lifecycle_out)], check=False)
    else:
        if args.output:
            out = Path(args.output).resolve()
        else:
            out = (out_dir / f"lifecycle-{args.product}.html").resolve()
        _generate_product(args.product, out, args)


if __name__ == "__main__":
    main()
