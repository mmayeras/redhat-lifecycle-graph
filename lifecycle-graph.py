#!/usr/bin/env python3
"""Red Hat product lifecycle Gantt chart generator.

Standalone by default (stdlib only). Install pyyaml to enable lifecycle-config.yaml
for declarative configuration of products, operators, middleware, and RHEL minor dates.
"""

import argparse
import calendar
import html as _html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# ── Runtime data (populated from lifecycle-config.yaml) ──────────────────────
_RHEL_MINOR_DATA: dict[str, dict[str, dict]] = {}
_RHEL_MAJOR_DATA: dict[str, dict] = {}

# ── Date parsing ─────────────────────────────────────────────────────────────

_MONTHS: dict[str, str] = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _parse_api_date(s: str) -> str | None:
    """Parse date strings from the Red Hat Product Life Cycles API.

    Handles ISO datetimes, ISO dates with trailing text, and "Month D, YYYY" format.
    Returns YYYY-MM-DD string or None for unparseable/N/A values.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if s in ("N/A", "Available on request"):
        return None
    # ISO datetime "2026-01-29T00:00:00.000Z" or ISO date "2026-01-29"
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        try:
            date.fromisoformat(s[:10])
            return s[:10]
        except ValueError:
            pass
    # "YYYY-MM-DD (extended from ...)"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    # "Month Day, Year" or "Month Day, Year (extra text)"
    m = re.match(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", s)
    if m:
        month = _MONTHS.get(m.group(1))
        if month:
            return f"{m.group(3)}-{month}-{int(m.group(2)):02d}"
    # "Estimated Month, YYYY" — use last day of month as conservative estimate
    s2 = re.sub(r"^Estimated\s+", "", s)
    m = re.match(r"(\w+),?\s+(\d{4})$", s2)
    if m:
        month = _MONTHS.get(m.group(1))
        if month:
            import calendar
            yr, mo = int(m.group(2)), int(month)
            last = calendar.monthrange(yr, mo)[1]
            return f"{yr}-{month}-{last:02d}"
    return None


# Phase end tied to a future release not yet in the API — support is still ongoing.
OPEN_END = "__open__"

# Relative phase-end strings from the Red Hat API (not ISO dates).  Tried in order.
_RELATIVE_REF_PATTERNS: list[re.Pattern] = [
    re.compile(r"^Release of (.+?)(?:\s*\+\s*(\d+)\s+months?)?$", re.IGNORECASE),
    re.compile(r"^with the release of (.+?)(?:\s*\+\s*(\d+)\s+months?)?$", re.IGNORECASE),
    re.compile(r"^GA of (.+?)(?:\s*\+\s*(\d+)\s+months?)?$", re.IGNORECASE),
    re.compile(r"^(\d+(?:\.\d+)+)\s*GA(?:\s*\+\s*(\d+)\s+months?)?$", re.IGNORECASE),
    re.compile(r"^Release(\d+(?:\.\d+)+)(?:\+(\d+)\s*months?)?$", re.IGNORECASE),
    re.compile(r"^(\d+\.N)\s*GA(?:\s*\+\s*(\d+)\s+months?)?$", re.IGNORECASE),
]


def _add_months(d: date, months: int) -> date:
    """Return *d* plus *months* calendar months (day clamped to month end)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def _parse_relative_ref(s: str) -> tuple[str, int] | None:
    """Parse relative API phase-end strings into (version_ref, month_offset).

    Handles patterns such as ``Release of 1.23 + 1 month``, ``4.22GA + 3 Months``,
    ``GA of 3.18 + 3 Months``, ``with the release of 3.20``, and ``Release1.20+1 month``.
    """
    text = s.strip()
    for pat in _RELATIVE_REF_PATTERNS:
        m = pat.match(text)
        if m:
            months = int(m.group(2)) if m.group(2) else 0
            return m.group(1).strip(), months
    return None


def _lookup_ga(ref_ver: str, ga_index: dict[str, str]) -> str | None:
    """Resolve a referenced version name against the GA-date index."""
    ref = ref_ver.strip()
    if ref in ga_index:
        return ga_index[ref]
    # Product-prefixed refs: "Logging 6.6" → "6.6", "Serverless 1.38" → "1.38"
    if " " in ref:
        suffix = ref.rsplit(" ", 1)[-1]
        if suffix in ga_index:
            return ga_index[suffix]
    return None


def _resolve_api_phase_end(raw: str, ga_index: dict[str, str]) -> str | None:
    """Resolve a phase ``end_date`` to YYYY-MM-DD, OPEN_END, or None.

    Absolute ISO / prose dates are parsed normally.  Relative strings reference
    another version's GA (optionally ``+ N months``).  When that version is not
    published yet — or uses a wildcard (``4.N``) — returns OPEN_END so the phase
    is treated as ongoing support rather than EOL.
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if raw in ("N/A", "Available on request"):
        return None
    absolute = _parse_api_date(raw)
    if absolute:
        return absolute
    release = _parse_relative_ref(raw)
    if release is None:
        return None
    ref_ver, months = release
    ga = _lookup_ga(ref_ver, ga_index)
    if ga:
        d = date.fromisoformat(ga)
        if months:
            d = _add_months(d, months)
        return d.isoformat()
    return OPEN_END


def _build_ga_index(
    product_versions: list,
    name_transform,
    min_filter,
) -> dict[str, str]:
    """Map version name → GA date (YYYY-MM-DD) from API version entries."""
    index: dict[str, str] = {}
    for ver_data in product_versions:
        raw = ver_data["name"]
        name = name_transform(raw) if name_transform else raw
        if not name_transform and " " in raw:
            continue
        if not min_filter(name):
            continue
        for phase in ver_data.get("phases", []):
            if phase.get("name") == "General availability":
                ga = _parse_api_date(phase.get("end_date", ""))
                if ga:
                    index[name] = ga
                break
    return index


def _parse_ocp(v: str) -> tuple:
    return (4, int(v.split(".")[1]))


def _parse_rhel(v: str) -> tuple:
    return (int(v),)


def _parse_aap(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _parse_rhoai(v: str) -> tuple:
    """Parse RHOAI version like '2.25', '3.4', '2.21*' → (major, minor)."""
    parts = v.rstrip("*").strip().split(".")
    try:
        return tuple(int(x) for x in parts[:2])
    except ValueError:
        return (0, 0)


def _parse_xy(v: str) -> tuple:
    """Parse X.Y version string → (X, Y) int tuple."""
    parts = v.split(".")
    try:
        return tuple(int(x) for x in parts[:2])
    except ValueError:
        return (0, 0)


PRODUCT_CONFIGS: dict[str, dict] = {}

_OP_PHASE_MAP: dict[str, str] = {
    "General availability":           "ga",
    "Full support":                   "fs_end",
    "Maintenance support":            "mnt_end",
    "Extended update support":        "eus1_end",
    "Extended update support Term 2": "eus2_end",
}

# ODF has a 3rd EUS tier and slightly different GA dates from OCP.
_ODF_PHASE_MAP: dict[str, str] = {
    "General availability":           "ga",
    "Full support":                   "fs_end",
    "Maintenance support":            "mnt_end",
    "Extended update support":        "eus1_end",
    "Extended update support Term 2": "eus2_end",
    "Extended update support Term 3": "eus3_end",
}

_KEYCLOAK_PHASE_MAP: dict[str, str] = {
    "General availability": "ga",
    "Full support":         "fs_end",
    "Maintenance support":  "mnt_end",
}

_ROLLING_GA_EOL_PHASE_MAP: dict[str, str] = {
    "General availability": "ga",
    "End of Life":          "fs_end",
}

OPERATOR_CONFIGS: dict[str, dict] = {}

_MW_ELS_PHASE_MAP: dict[str, str] = {
    "General availability":                        "ga",
    "Full support":                                "fs_end",
    "Maintenance support":                         "mnt_end",
    "Extended life cycle support (ELS) 1":         "els_end",
    "Extended life cycle support (ELS) 2":         "els2_end",
}

_OSP_PHASE_MAP: dict[str, str] = {
    "General availability":                              "ga",
    "Full support":                                      "fs_end",
    "Third-party certification period":                  "tpc_end",
    "Maintenance support":                               "mnt_end",
    "Extended life cycle support (ELS) add-on":          "els_end",
    "Extended life cycle support (ELS) Term 2 add-on":   "els2_end",
    "Extended life cycle support (ELS) Term 3 add-on":   "els3_end",
}

def _parse_xdotx(v: str) -> tuple:
    """Parse 'X.x' or 'X.Y.x' middleware version like '8.x' → (8,), '7.x' → (7,)."""
    base = v.split(".")[0]
    try:
        return (int(base),)
    except ValueError:
        return (0,)

MIDDLEWARE_CONFIGS: dict[str, dict] = {}

# ── Declarative YAML config support ──────────────────────────────────────────
# Maps strategy name → {parse_ver, eus_check}. min_filter is built by _make_min_filter().
# Populated here so all parse functions are already defined above.
_VERSION_STRATEGIES: dict[str, dict] = {
    "ocp-minor":   {"parse_ver": _parse_ocp,    "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0},
    "xy":          {"parse_ver": _parse_xy,     "eus_check": None},
    "xy-exact":    {"parse_ver": _parse_xy,     "eus_check": None},
    "xy-eus-even": {"parse_ver": _parse_xy,     "eus_check": lambda v: _parse_xy(v)[1] % 2 == 0},
    "x-dotx":      {"parse_ver": _parse_xdotx,  "eus_check": None},
    "rhel-major":  {"parse_ver": _parse_rhel,   "eus_check": None},
    "aap":         {"parse_ver": _parse_aap,    "eus_check": None},
    "rhoai":       {"parse_ver": _parse_rhoai,  "eus_check": None},
    "ceph":        {
        "parse_ver": lambda v: (int(v),) if v.isdigit() else (0,),
        "eus_check": None,
        "name_transform": lambda n: n.replace("Red Hat Ceph Storage ", "").replace("Inktank Ceph Enterprise ", "").strip(),
    },
    "rolling-eol": {"parse_ver": _parse_xy,     "eus_check": None},
}

# Maps preset name → phase_map dict for use in lifecycle-config.yaml.
_PHASE_MAP_PRESETS: dict[str, dict] = {
    "op-standard":    _OP_PHASE_MAP,
    "op-odf":         _ODF_PHASE_MAP,
    "els2":           _MW_ELS_PHASE_MAP,
    "osp-els3":       _OSP_PHASE_MAP,
    "keycloak":       _KEYCLOAK_PHASE_MAP,
    "rolling-ga-eol": _ROLLING_GA_EOL_PHASE_MAP,
}


def _coerce_date_str(v: object) -> str:
    """PyYAML auto-converts bare ISO dates to datetime.date — turn them back to strings."""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)


def _make_min_filter(strategy: str, min_version: str):
    """Build a min_filter callable from a strategy name and minimum version string."""
    if strategy == "ocp-minor":
        min_t = _parse_ocp(min_version)
        return lambda v, _mt=min_t: (
            "." in v and v.startswith("4.") and len(v.split(".")) == 2
            and v.split(".")[1].isdigit() and _parse_ocp(v) >= _mt
        )
    if strategy in ("rhel-major", "ceph"):
        min_i = int(min_version)
        return lambda v, _mi=min_i: v.isdigit() and int(v) >= _mi
    if strategy == "aap":
        min_t = _parse_aap(min_version)
        return lambda v, _mt=min_t: (
            "." in v and len(v.split(".")) == 2
            and all(x.isdigit() for x in v.split("."))
            and _parse_aap(v) >= _mt
        )
    if strategy == "rhoai":
        min_t = _parse_rhoai(min_version)
        return lambda v, _mt=min_t: _parse_rhoai(v) >= _mt and "." in v.rstrip("*")
    if strategy == "xy-exact":
        min_t = _parse_xy(min_version)
        return lambda v, _mt=min_t: (
            "." in v and not v.endswith(".x")
            and len(v.split(".")) == 2
            and all(p.isdigit() for p in v.split("."))
            and _parse_xy(v) >= _mt
        )
    if strategy == "x-dotx":
        min_i = int(min_version)
        return lambda v, _mi=min_i: v.endswith(".x") and v[:-2].isdigit() and int(v[:-2]) >= _mi
    # xy, xy-eus-even, rolling-eol, unknown
    parse = _VERSION_STRATEGIES.get(strategy, {}).get("parse_ver", _parse_xy)
    min_t = parse(min_version)
    return lambda v, _p=parse, _mt=min_t: _p(v) >= _mt and "." in v


def _apply_product_overrides(products: dict) -> None:
    for key, raw in products.items():
        cfg = PRODUCT_CONFIGS.setdefault(key, {})
        for field in ("api_name", "title", "page_url", "info_html", "has_minors", "use_major_phases"):
            if field in raw:
                cfg[field] = raw[field]
        if "details" in raw:
            cfg["details"] = dict(raw["details"])
            cfg["details_url"] = f"lifecycle-{key}-details.html"
        preset = raw.get("phase_map_preset")
        if preset and preset in _PHASE_MAP_PRESETS:
            cfg["phase_map"] = dict(_PHASE_MAP_PRESETS[preset])
        if "phase_map" in raw:
            cfg["phase_map"] = {**cfg.get("phase_map", {}), **dict(raw["phase_map"])}
        if "fallback" in raw:
            cfg["fallback"] = {
                str(k): {str(fk): _coerce_date_str(fv) for fk, fv in v.items()}
                for k, v in raw["fallback"].items()
            }
        strat = raw.get("version_strategy")
        if strat and strat in _VERSION_STRATEGIES:
            vs = _VERSION_STRATEGIES[strat]
            cfg["parse_ver"] = vs["parse_ver"]
            cfg["eus_check"] = vs["eus_check"]
            if "name_transform" in vs:
                cfg["name_transform"] = vs["name_transform"]
            if "min_version" in raw:
                cfg["min_filter"] = _make_min_filter(strat, str(raw["min_version"]))


def _apply_operator_overrides(operators: dict) -> None:
    for key, raw in operators.items():
        cfg = OPERATOR_CONFIGS.setdefault(key, {})
        for field in ("api_name", "title", "page_url"):
            if field in raw:
                cfg[field] = raw[field]
        preset = raw.get("phase_map_preset")
        if preset and preset in _PHASE_MAP_PRESETS:
            cfg["phase_map"] = dict(_PHASE_MAP_PRESETS[preset])
        if "phase_map" in raw:
            cfg["phase_map"] = {**cfg.get("phase_map", {}), **dict(raw["phase_map"])}
        if "fallback" in raw:
            cfg["fallback"] = {
                str(k): {str(fk): _coerce_date_str(fv) for fk, fv in v.items()}
                for k, v in raw["fallback"].items()
            }
        else:
            cfg.setdefault("fallback", {})
        strat = raw.get("version_strategy")
        cfg["version_strategy"] = strat
        if strat and strat in _VERSION_STRATEGIES:
            vs = _VERSION_STRATEGIES[strat]
            cfg["parse_ver"] = vs["parse_ver"]
            cfg["eus_check"] = vs["eus_check"]
            cfg["min_filter"] = _make_min_filter(strat, str(raw.get("min_version", "0.0")))
        cfg.setdefault("eus_check", None)


def _apply_middleware_overrides(middleware: dict) -> None:
    for key, raw in middleware.items():
        cfg = MIDDLEWARE_CONFIGS.setdefault(key, {})
        for field in ("api_name", "title", "page_url"):
            if field in raw:
                cfg[field] = raw[field]
        preset = raw.get("phase_map_preset")
        if preset and preset in _PHASE_MAP_PRESETS:
            cfg["phase_map"] = dict(_PHASE_MAP_PRESETS[preset])
        if "phase_map" in raw:
            cfg["phase_map"] = {**cfg.get("phase_map", {}), **dict(raw["phase_map"])}
        if "fallback" in raw:
            cfg["fallback"] = {
                str(k): {str(fk): _coerce_date_str(fv) for fk, fv in v.items()}
                for k, v in raw["fallback"].items()
            }
        else:
            cfg.setdefault("fallback", {})
        strat = raw.get("version_strategy")
        if strat and strat in _VERSION_STRATEGIES:
            vs = _VERSION_STRATEGIES[strat]
            cfg["parse_ver"] = vs["parse_ver"]
            cfg["eus_check"] = vs["eus_check"]
            cfg["min_filter"] = _make_min_filter(strat, str(raw.get("min_version", "0")))
        cfg.setdefault("eus_check", None)


def _load_external_config() -> None:
    """Merge lifecycle-config.yaml into the runtime dicts (requires pyyaml)."""
    if not _HAS_YAML:
        print(
            "Error: PyYAML is required but not installed.\n"
            "  Run: pip install pyyaml\n"
            "  lifecycle-config.yaml is the sole source of product data — without it no charts can be generated.",
            file=sys.stderr,
        )
        sys.exit(1)
    cfg_path = Path(__file__).parent / "lifecycle-config.yaml"
    if not cfg_path.exists():
        print("Warning: lifecycle-config.yaml not found — no chart data will be generated.", file=sys.stderr)
        return
    with open(cfg_path, encoding="utf-8") as f:
        raw = _yaml.safe_load(f)
    if not isinstance(raw, dict):
        return
    if raw.get("products"):
        _apply_product_overrides(raw["products"])
    if raw.get("operators"):
        _apply_operator_overrides(raw["operators"])
    if raw.get("middleware"):
        _apply_middleware_overrides(raw["middleware"])
    if raw.get("rhel_minors"):
        for major, minors in raw["rhel_minors"].items():
            major_str = str(major)
            _RHEL_MINOR_DATA.setdefault(major_str, {})
            for ver, fields in minors.items():
                _RHEL_MINOR_DATA[major_str][str(ver)] = {
                    str(fk): _coerce_date_str(fv) for fk, fv in fields.items()
                }
    if raw.get("rhel_majors"):
        for major, fields in raw["rhel_majors"].items():
            _RHEL_MAJOR_DATA[str(major)] = {
                str(fk): _coerce_date_str(fv) for fk, fv in fields.items()
            }


_load_external_config()

# ── Phase palette (PatternFly-aligned) ───────────────────────────────────────
PHASES: dict[str, dict] = {
    "sup":  {"label": "Support",       "bg": "#bde5b8", "border": "#1e4f18", "text": "#1e4f18"},
    "fs":   {"label": "Full Support",  "bg": "#bde5b8", "border": "#1e4f18", "text": "#1e4f18"},
    "mnt":  {"label": "Maintenance",   "bg": "#f9e0a2", "border": "#795600", "text": "#795600"},
    "tpc":  {"label": "3rd-party Cert","bg": "#d4e7f7", "border": "#336699", "text": "#336699"},
    "mnt2": {"label": "Maintenance 2", "bg": "#f4b678", "border": "#8f4700", "text": "#8f4700"},
    "eus1": {"label": "EUS-1",         "bg": "#bee1f4", "border": "#004080", "text": "#004080"},
    "eus2": {"label": "EUS-2",         "bg": "#e7d4ff", "border": "#40199a", "text": "#40199a"},
    "eus3": {"label": "EUS-3",         "bg": "#f2c4ff", "border": "#6a0080", "text": "#6a0080"},
    "elc":  {"label": "ELC",           "bg": "#9ec8ff", "border": "#004499", "text": "#004499"},
    "elcp": {"label": "ELC Premium",   "bg": "#b8e6b8", "border": "#1e6b1e", "text": "#1e5c1e"},
    # RHEL subscription phases — names from Red Hat RHEL lifecycle materials
    # (see LIFECYCLE.md; API Full support/Maintenance/ELS names are not used)
    "rhel_std":  {"label": "Standard subscription", "short_label": "Standard",
                  "bg": "#fae0dc", "border": "#ee0000", "text": "#7d1007"},
    "rhel_prem": {"label": "Premium subscription additional maintenance", "short_label": "Premium",
                  "bg": "#fdf2cf", "border": "#f0ab00", "text": "#6e4800"},
    "rhel_elcp": {"label": "Extended Life Cycle, Premium subscription additional maintenance", "short_label": "ELC, Premium",
                  "bg": "#d4e7f7", "border": "#336699", "text": "#004080"},
    "rhel_ll":   {"label": "Long Life add-on terms", "short_label": "Long Life",
                  "bg": "#c7ebee", "border": "#006970", "text": "#003f4f"},
    "rhel_els":  {"label": "Extended life cycle support (ELS) add-on", "short_label": "ELS add-on",
                  "bg": "#e7d4ff", "border": "#6a1b9a", "text": "#40199a"},
    "els":  {"label": "ELS",           "bg": "#f5b8b4", "border": "#c9190b", "text": "#a30000"},
    "els2": {"label": "ELS-2",         "bg": "#e88080", "border": "#8b0000", "text": "#fff"},
    "els3": {"label": "ELS-3",         "bg": "#c94040", "border": "#6b0000", "text": "#fff"},
    "elp":  {"label": "Ext. Life",     "bg": "#e4e4e4", "border": "#6a6e73", "text": "#3c3f42"},
}

# Chronological order — segments built and phase status detected in this order.
# sup/els/els2 are Ceph-specific; eus3 is ODF-specific. Other products skip these keys.
PHASE_KEYS = [
    ("sup",  "sup_end"),   # Ceph: single-tier support (no fs/mnt split)
    ("fs",   "fs_end"),
    ("tpc",  "tpc_end"),   # OSP: third-party certification period
    ("mnt",  "mnt_end"),
    ("mnt2", "mnt2_end"),
    ("eus1", "eus1_end"),
    ("eus2", "eus2_end"),
    ("eus3", "eus3_end"),  # ODF: Extended Update Support Term 3
    ("elc",  "elc_end"),   # RHEL ELC (minor only, built in build_rhel_minor_versions)
    ("elcp", "elcp_end"),  # RHEL ELC Premium (minor only)
    ("els",  "els_end"),
    ("els2", "els2_end"),  # Ceph / OSP: ELS Term 2 add-on
    ("els3", "els3_end"),  # OSP: ELS Term 3 add-on
    ("elp",  "elp_end"),
]


def _phase_bar_text(ph: dict, width_pct: float) -> str:
    """Return in-bar label text; empty when the segment is too narrow."""
    if width_pct < 3:
        return ""
    return ph.get("short_label", ph["label"])


def _phase_legend_text(ph: dict) -> str:
    return ph.get("short_label", ph["label"])


def _d(s: str) -> date:
    return date.fromisoformat(s)


_SUPPORT_END_KEYS = ("fs_end", "mnt_end", "mnt2_end", "sup_end", "tpc_end")


def _api_phases_to_dates(
    ver_data: dict,
    phase_map: dict[str, str],
    ga_index: dict[str, str],
) -> dict[str, str]:
    """Map API phase end_dates to internal field names via phase_map."""
    dates: dict[str, str] = {}
    for phase in ver_data.get("phases", []):
        field = phase_map.get(phase["name"])
        if not field:
            continue
        resolved = _resolve_api_phase_end(phase.get("end_date", ""), ga_index)
        if resolved:
            dates[field] = resolved
    return dates


def _fetch_api_product(cfg: dict) -> dict | None:
    """Return the raw API product dict, or None if the request fails."""
    name_param = cfg["api_name"].replace(" ", "+")
    url = f"https://access.redhat.com/product-life-cycles/api/v1/products?name={name_param}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "lifecycle-graph/1.0", "Accept-Language": "en-US,en;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data["data"][0]
    except Exception:
        return None


def validate_phases() -> int:
    """Audit phase_map coverage against the Red Hat API. Returns error count."""
    errors = 0
    entries: list[tuple[str, dict]] = []
    for key, cfg in PRODUCT_CONFIGS.items():
        if cfg.get("use_major_phases"):
            continue
        entries.append((f"product:{key}", cfg))
    for key, cfg in OPERATOR_CONFIGS.items():
        entries.append((f"operator:{key}", cfg))
    for key, cfg in MIDDLEWARE_CONFIGS.items():
        entries.append((f"middleware:{key}", cfg))

    for label, cfg in entries:
        product = _fetch_api_product(cfg)
        if product is None:
            print(f"SKIP {label}: API unavailable", file=sys.stderr)
            continue
        phase_map = cfg.get("phase_map", {})
        api_phases = {p["name"] for p in product.get("all_phases", [])}
        for phase_name in sorted(api_phases):
            if phase_name not in phase_map:
                print(f"ERROR {label}: UNMAPPED_PHASE {phase_name!r}", file=sys.stderr)
                errors += 1
    if errors:
        print(f"\n{errors} unmapped phase(s) — fix phase_map or phase_map_preset in lifecycle-config.yaml.",
              file=sys.stderr)
    else:
        print("All API-backed entries have complete phase_map coverage.", file=sys.stderr)
    return errors


def fetch_lifecycle(cfg: dict) -> dict[str, dict]:
    """Fetch lifecycle for a product from the Red Hat API; fall back to static data.

    phase_map translates API phase names to internal date fields (ga, fs_end, …).
    When the API returns a version, only API-provided phases are used — fallback
    is not merged field-by-field. fallback: is used only when the API is unreachable.
    """
    phase_map = cfg["phase_map"]
    min_filter = cfg["min_filter"]
    fallback = cfg.get("fallback", {})
    name_transform = cfg.get("name_transform")
    product = _fetch_api_product(cfg)
    if product is None:
        print(f"API fetch failed for {cfg['title']}, using fallback.", file=sys.stderr)
        return dict(fallback)
    # Capture the operator lifecycle tier (versions are newest-first, so the first
    # meaningful value reflects the current alignment). "Aligned" = tied to the OCP
    # release it ships with; "Agnostic" = independent lifecycle.
    cfg["_api_tier"] = next(
        (v["tier"] for v in product["versions"] if v.get("tier") and v["tier"] != "N/A"),
        None,
    )
    ga_index = _build_ga_index(product["versions"], name_transform, min_filter)
    result: dict[str, dict] = {}
    for ver_data in product["versions"]:
        raw = ver_data["name"]
        name = name_transform(raw) if name_transform else raw
        if not name_transform and " " in raw:
            continue
        if not min_filter(name):
            continue
        dates = _api_phases_to_dates(ver_data, phase_map, ga_index)
        if "ga" in dates and any(dates.get(k) for k in _SUPPORT_END_KEYS):
            result[name] = dates
    if result:
        print(f"Fetched {len(result)} {cfg['title']} versions from Red Hat API.", file=sys.stderr)
        return result
    print(f"API returned 0 versions for {cfg['title']}, using fallback.", file=sys.stderr)
    return dict(fallback)


# ── Details pages: z-stream errata (Hydra search, no auth) ───────────────────

_ERRATA_SEARCH_URL = "https://access.redhat.com/hydra/rest/search/kcs"
_ERRATA_FIELDS = "id,portal_synopsis,portal_publication_date,portal_advisory_type,portal_severity,view_uri,portal_description"
_ERRATA_KINDS = {
    "Security Advisory": "security",
    "Bug Fix Advisory": "bugfix",
    "Product Enhancement Advisory": "enhancement",
}
_ERRATA_KIND_LABELS = {
    "security": "Security",
    "bugfix": "Bug Fix",
    "enhancement": "Enhancement",
    "other": "Advisory",
}


def _fetch_errata_page(query: str, start: int, rows: int = 100) -> dict:
    """One page of Hydra errata search results (raises on failure)."""
    params = urllib.parse.urlencode({
        "q": f'"{query}"',
        "fq": 'documentKind:("Errata")',
        "rows": rows,
        "start": start,
        "sort": "portal_publication_date desc",
        "fl": _ERRATA_FIELDS,
    })
    req = urllib.request.Request(
        f"{_ERRATA_SEARCH_URL}?{params}",
        headers={"User-Agent": "lifecycle-graph/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_errata_for_minor(query: str) -> list[dict] | None:
    """All errata docs matching query, paginated. None on any failure."""
    docs: list[dict] = []
    start, rows, cap = 0, 100, 1000
    try:
        while start < cap:
            payload = _fetch_errata_page(query, start, rows)
            resp = payload["response"]
            docs.extend(resp.get("docs", []))
            start += rows
            if start >= resp.get("numFound", 0):
                break
            time.sleep(0.2)
    except Exception as exc:
        print(f"Errata fetch failed for {query!r}: {exc}", file=sys.stderr)
        return None
    return docs


def _parse_zstream(synopsis: str, minor: str) -> str | None:
    """Extract 'X.Y.Z' from an errata synopsis, anchored to a known minor."""
    m = re.search(rf"\b{re.escape(minor)}\.(\d+)\b", synopsis)
    return f"{minor}.{m.group(1)}" if m else None


def _advisory_kind(advisory_type: str) -> str:
    return _ERRATA_KINDS.get(advisory_type, "other")


def _extract_bullets(text: str, max_items: int = 20, max_len: int = 250) -> list[dict]:
    """Pull '* item' bullet lines (with continuations) out of an erratum description."""
    items: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("* "):
            if current:
                items.append(" ".join(current))
            current = [stripped[2:].strip()]
        elif current and stripped:
            current.append(stripped)
        elif current:
            items.append(" ".join(current))
            current = []
    if current:
        items.append(" ".join(current))
    return [_trunc(i, max_len) for i in items[:max_items]]


def _doc_to_erratum(doc: dict) -> dict:
    erratum = {
        "id": doc.get("id", ""),
        "synopsis": doc.get("portal_synopsis", ""),
        "kind": _advisory_kind(doc.get("portal_advisory_type", "")),
        "severity": doc.get("portal_severity", "") or "",
        "date": (doc.get("portal_publication_date", "") or "")[:10],
        "url": doc.get("view_uri", ""),
    }
    items = _extract_bullets(doc.get("portal_description", "") or "")
    if items:
        erratum["items"] = items
    return erratum


def _trunc(s: str, limit: int) -> str:
    """Truncate at a word boundary with an ellipsis (no mid-word cuts)."""
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if s[limit] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:. ") + "…"


def _fmt_minor(tpl: str, minor: str) -> str:
    """Substitute {minor}, {minor_dash} (4-19), {minor_nodot} (26) and {major} (9 for 9.6)."""
    return tpl.format(minor=minor, minor_dash=minor.replace(".", "-"),
                      minor_nodot=minor.replace(".", ""),
                      major=minor.split(".")[0])


_DOCS_FEATURE_KEYWORDS = ("new feature", "enhancement", "what", "major change",
                          "overview", "technology preview")


def fetch_features_docs_search(details: dict, minor: str) -> list[dict] | None:
    """Feature entries from the portal search index of docs.redhat.com chapters.

    Fallback source for products whose release-notes asciidoc is not in a public
    repo (docs.redhat.com itself blocks non-browser clients). Chapter-level
    granularity: title + abstract snippet + link.
    """
    pattern = _fmt_minor(details["features_search"], minor)
    params = urllib.parse.urlencode([
        ("q", minor),
        ("fq", 'documentKind:("Documentation")'),
        ("fq", 'language:("en")'),
        ("fq", f"view_uri:{pattern}"),
        ("rows", 100),
        ("fl", "view_uri,allTitle,abstract"),
    ])
    try:
        req = urllib.request.Request(
            f"{_ERRATA_SEARCH_URL}?{params}",
            headers={"User-Agent": "lifecycle-graph/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            docs = json.loads(resp.read())["response"].get("docs", [])
    except Exception as exc:
        print(f"Docs-search features fetch failed for {minor}: {exc}", file=sys.stderr)
        return None
    groups = []
    seen: set[str] = set()
    for doc in docs:
        uri = doc.get("view_uri", "")
        title = doc.get("allTitle", "") or ""
        if "/en/" not in uri or uri in seen:
            continue
        seen.add(uri)
        lt, lu = title.lower(), uri.lower()
        if not (any(k in lt for k in _DOCS_FEATURE_KEYWORDS)
                or "new-feature" in lu or "enhancement" in lu):
            continue
        short = title.split(" - ")[0].strip()
        short = re.sub(r"^(Chapter\s+)?[\d.]+\s*", "", short) or short
        desc = " ".join((doc.get("abstract") or "").split())
        groups.append({"area": short, "items": _split_chapter_abstract(short, desc),
                       "_sort": title})
    groups.sort(key=lambda g: g.pop("_sort"))
    groups = [g for g in groups if g["items"]]
    return groups or None


_ABSTRACT_BOILERPLATE = re.compile(
    r"^(Important\s+)?(This (part|section|document|chapter)|These release notes)\b.*?\.(?=\s|$)\s*"
)
_ITEM_NOISE_PREFIXES = ("For information", "Additional resources", "See ", "For more information")


def _split_chapter_abstract(chapter_title: str, abstract: str) -> list[dict]:
    """Break a docs-index chapter abstract into per-subsection feature lines.

    Chapter abstracts flatten numbered subsections ("6.1. Installer and image
    creation Review new features … <feature text>"); split on the numbering
    markers so each subsection renders as one plain line, OCP-card style.
    Per RELEASE_NOTE_TEMPLATE.md items carry no links — the minor header's
    "release notes" link is the single way out.
    """
    abstract = _ABSTRACT_BOILERPLATE.sub("", abstract)
    segs = re.split(r"\s(?=\d+(?:\.\d+)+\.\s)", " " + abstract)
    items = []
    for seg in segs:
        m = re.match(r"\s*\d+(?:\.\d+)+\.\s+(.*)", seg)
        if not m:
            continue
        body = m.group(1)
        cut = len(body)
        for marker in (": ", " Review ", " Key highlights", ". "):
            i = body.find(marker)
            if 0 < i < cut:
                cut = i
        title = body[:cut].strip().rstrip(".")
        desc = body[cut:].lstrip()
        desc = re.sub(r"^(Review|Key highlights)\b(.*?\.(?=\s)|.*$)\s*", "", desc)
        desc = desc.lstrip(".: ")
        if title and not any(title.startswith(p) for p in _ITEM_NOISE_PREFIXES):
            items.append({"t": _trunc(title, 90), "d": _trunc(desc, 350)})
    if not items and abstract.strip():
        items = [{"t": chapter_title, "d": _trunc(abstract, 350)}]
    return items


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lifecycle-graph/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_adoc_attributes(text: str) -> dict[str, str]:
    """Parse ':name: value' asciidoc attribute definitions, resolving nested refs."""
    attrs: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^:([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            attrs[m.group(1)] = m.group(2).strip()
    for _ in range(3):
        changed = False
        for k, v in attrs.items():
            nv = re.sub(r"\{([A-Za-z0-9_-]+)\}", lambda m: attrs.get(m.group(1), m.group(0)), v)
            if nv != v:
                attrs[k] = nv
                changed = True
        if not changed:
            break
    return attrs


def _clean_adoc_inline(s: str, attrs: dict[str, str]) -> str:
    for _ in range(2):  # attr values may themselves contain {refs}
        s = re.sub(r"\{([A-Za-z0-9_-]+)\}", lambda m: attrs.get(m.group(1), m.group(0)), s)
    s = re.sub(r"(?:link|xref):[^\[\]]+\[([^\]]*)\]", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = s.replace("`", "")
    s = re.sub(r"\{([A-Za-z0-9_-]+)\}", r"\1", s)  # unresolved attrs: keep name, drop braces
    return " ".join(s.split())


_ADOC_SKIP_PREFIXES = ("[", "//", "ifdef", "ifndef", "endif", "include::", "image::", "|", "'''", "+")
# Sections that live inside "New features" docs but are not features
_FEATURE_TITLE_SKIP = ("Upgrade", "Upgrading", "Migration")


def _parse_adoc_features(text: str, attrs: dict[str, str],
                         section: str = "new features and enhancements",
                         flat: bool = False) -> list[dict]:
    """Extract feature entries (area → title + first paragraph) from a release-notes adoc.

    Level-aware: works both on book files (section at `==`) and standalone
    modules (section at `=`); areas/features sit one/two levels below it.
    flat=True treats section+1 headings as feature titles directly (no area
    level) — the AAP release-notes module layout.
    """
    lines = text.splitlines()
    heading_re = re.compile(r"^(=+)\s+(\S.*)$")
    sec_level = None
    start = 0
    for i, line in enumerate(lines):
        m = heading_re.match(line.rstrip())
        if m and section in _clean_adoc_inline(m.group(2), attrs).lower():
            sec_level, start = len(m.group(1)), i + 1
            break
    if sec_level is None:
        return []

    groups: list[dict] = []
    bullets: list[dict] = []
    in_code = False
    in_comment = False
    saw_title = False
    title: str | None = None
    desc: list[str] = []

    def flush() -> None:
        nonlocal title, desc, saw_title
        if title:
            saw_title = True
            t = _trunc(_clean_adoc_inline(title, attrs), 200)
            d = _trunc(_clean_adoc_inline(" ".join(desc), attrs), 400)
            # In flat mode a heading without body text is an area, not a feature;
            # upgrade/migration sections inside "New features" docs are not features.
            if not (flat and not d) and not t.startswith(_FEATURE_TITLE_SKIP):
                if not groups:
                    groups.append({"area": "General", "items": []})
                groups[-1]["items"].append({"t": t, "d": d})
        title, desc = None, []

    for line in lines[start:]:
        stripped = line.rstrip()
        if stripped == "////":  # block comment fence
            in_comment = not in_comment
            continue
        if in_comment:
            continue
        if stripped in ("----", "...."):  # code fences
            in_code = not in_code
            continue
        if in_code:
            continue
        m = heading_re.match(stripped)
        if m:
            level = len(m.group(1))
            if level <= sec_level:
                break
            flush()
            if level == sec_level + 1:
                if flat:
                    title = m.group(2)
                else:
                    groups.append({"area": _clean_adoc_inline(m.group(2), attrs), "items": []})
            elif level == sec_level + 2 and not flat:
                title = m.group(2)
            continue
        if stripped in ("====", "--"):  # admonition / open-block fences
            continue
        if any(stripped.startswith(p) for p in _ADOC_SKIP_PREFIXES):
            continue
        m_def = re.match(r"^(\S.*?)::\s*$", stripped)
        if m_def:  # definition-list entry: "Feature title::" (OCP 4.21+ modules)
            flush()
            title = m_def.group(1)
            continue
        if title is not None:
            if not stripped:
                if desc:
                    flush()  # first paragraph only
                continue
            if stripped.startswith(("* ", ". ")):
                desc.append(stripped[2:].strip())
            else:
                desc.append(stripped.strip())
        elif stripped.startswith("* ") and not saw_title:
            # buffered: only used when the section turns out to be bullet-only
            bullet = _clean_adoc_inline(stripped[2:], attrs)
            if bullet:
                bullets.append({"t": _trunc(bullet, 200), "d": ""})
    flush()
    groups = [g for g in groups if g["items"]]
    if bullets and not saw_title and not groups:
        # bullet-only sections (e.g. AAP 2.4): each bullet is a feature line
        groups = [{"area": "General", "items": bullets}]
    return groups


def fetch_release_features(details: dict, minor: str) -> list[dict] | None:
    """Feature entries for one minor from its docs source repo. None on any failure."""
    url = _fmt_minor(details["features_url"], minor)
    try:
        attrs: dict[str, str] = {}
        attrs_url = details.get("attributes_url")
        if attrs_url:
            attrs = _parse_adoc_attributes(_fetch_text(_fmt_minor(attrs_url, minor)))
        attrs.update(details.get("attributes") or {})  # YAML overrides win
        attrs.setdefault("product-version", minor)
        attrs.setdefault("nbsp", " ")
        for k in list(attrs):  # docs sometimes use {Capitalized-attr} refs
            if k and k[0].islower():
                attrs.setdefault(k[0].upper() + k[1:], attrs[k])
        def best_parse(t: str) -> list[dict]:
            # Nested (areas + feature headings) is the canonical layout; use the
            # flat reading only when nested finds nothing or clearly misreads the
            # document (e.g. AAP, where features sit at the area level and nested
            # only picks up a few stray sub-headings).
            nested = _parse_adoc_features(t, attrs)
            flat = _parse_adoc_features(t, attrs, flat=True)
            n_count = sum(len(g["items"]) for g in nested)
            f_count = sum(len(g["items"]) for g in flat)
            return flat if (n_count == 0 or f_count > 2 * n_count) else nested

        text = _fetch_text(url)
        groups = best_parse(text)
        if not groups:
            # Modularized books (OCP 4.21+): content lives in an included module.
            m = re.search(r"^include::(\S*new-features\S*?)\[", text, re.M)
            if m:
                repo_root = url.rsplit("/", 2)[0]
                groups = best_parse(_fetch_text(f"{repo_root}/{m.group(1)}"))
        return groups or None
    except Exception as exc:
        print(f"Release-notes features fetch failed for {minor}: {exc}", file=sys.stderr)
        return None


def build_details_data(key: str, cfg: dict, versions: list[dict]) -> dict | None:
    """Fetch + group errata per minor/z-stream. None if any fetch fails.

    errata_query containing "{minor}" → one Hydra query per minor (unmatched
    synopses kept as per-minor "unversioned"). Without "{minor}" → a single
    product-wide query; docs are attributed to minors by version parsing and
    unmatched docs are dropped (they can't be tied to a minor).
    """
    details = cfg["details"]
    q_template = details.get("errata_query")
    shared_query = bool(q_template) and "{minor}" not in q_template
    if details.get("minors_from") == "rhel_minors":
        minors = sorted(
            {m for data in _RHEL_MINOR_DATA.values() for m in data},
            key=lambda v: tuple(int(p) for p in v.split(".")), reverse=True,
        )
    else:
        minors = [v["version"] for v in versions]
    # Older EOL minors beyond the chart's min_version — full history coverage.
    for extra in details.get("extra_minors", []):
        if str(extra) not in minors:
            minors.append(str(extra))
    shared_docs: list[dict] | None = None
    if shared_query:
        shared_docs = fetch_errata_for_minor(q_template)
        if shared_docs is None:
            return None
    minors_out = []
    for minor in minors:
        if q_template is None:
            docs = []
        elif shared_docs is not None:
            docs = shared_docs
        else:
            docs = fetch_errata_for_minor(_fmt_minor(q_template, minor))
            if docs is None:
                return None
        zstreams: dict[str, list[dict]] = {}
        unversioned: list[dict] = []
        for doc in docs:
            synopsis = doc.get("portal_synopsis", "")
            zver = _parse_zstream(synopsis, minor)
            if zver:
                zstreams.setdefault(zver, []).append(_doc_to_erratum(doc))
            elif not shared_query:
                unversioned.append(_doc_to_erratum(doc))
        zstream_list = [
            {
                "version": zver,
                "date": min((e["date"] for e in errata if e["date"]), default=""),
                "errata": sorted(errata, key=lambda e: e["date"], reverse=True),
            }
            for zver, errata in zstreams.items()
        ]
        zstream_list.sort(key=lambda z: int(z["version"].rsplit(".", 1)[1]), reverse=True)
        rn_tpl = details.get("release_notes_url", "")
        minor_entry = {
            "minor": minor,
            "release_notes_url": _fmt_minor(rn_tpl, minor) if rn_tpl else "",
            "zstreams": zstream_list,
            "unversioned": unversioned,
        }
        features = None
        if details.get("features_url"):
            features = fetch_release_features(details, minor)
        if features is None and details.get("features_search"):
            features = fetch_features_docs_search(details, minor)
            time.sleep(0.2)
        if features:
            minor_entry["features"] = features
        if not (zstream_list or unversioned or features):
            continue  # nothing known about this minor — no empty section
        minors_out.append(minor_entry)
        attributed = sum(len(z["errata"]) for z in zstream_list) + len(unversioned)
        print(f"Errata: {minor} → {len(zstream_list)} z-streams, {attributed} advisories.", file=sys.stderr)
    try:
        minors_out.sort(key=lambda m: tuple(int(p) for p in m["minor"].split(".")), reverse=True)
    except ValueError:
        pass  # non-numeric versions keep chart order
    return {
        "product": key,
        "title": cfg.get("title", key),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minors": minors_out,
    }


def _load_cached_details(out_dir: Path, key: str) -> dict | None:
    """Previously committed sidecar JSON — fallback when the live fetch fails."""
    cache = out_dir / f"lifecycle-{key}-details.json"
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return None


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

    keys = sorted(lifecycle.keys(), key=parse_ver, reverse=True)
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
        phase_open = False
        for key, field in PHASE_KEYS:
            val = lc.get(field)
            if not val:
                continue
            if val == OPEN_END:
                if prev <= today:
                    segments.append({"key": key, "start": prev, "end": today})
                    prev = today
                phase_open = True
                break
            end = _d(val)
            if end > prev:
                segments.append({"key": key, "start": prev, "end": end})
                prev = end
        last_end = prev
        is_eus = bool(eus_check(ver)) if eus_check else bool(lc.get("eus1_end"))
        phase_key = "eol"
        days_left = 0
        for key, field in PHASE_KEYS:
            val = lc.get(field)
            if val == OPEN_END:
                phase_key = key
                phase_open = True
                break
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
            "phase_open": phase_open,
        })
    return result


def build_rhel_minor_versions(major_ver: str) -> list[dict]:
    """Build per-minor-release version dicts for the RHEL minor details toggle."""
    minors = _RHEL_MINOR_DATA.get(major_ver, {})
    today = date.today()
    result = []
    for ver in sorted(minors.keys(), key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True):
        m = minors[ver]
        ga = _d(m["ga"])
        if "std_end" not in m:
            continue  # next minor GA not yet published — skip
        std_end = _d(m["std_end"])
        eus_end = _d(m["eus_end"]) if "eus_end" in m else None
        elc_end = _d(m["elc_end"]) if "elc_end" in m else None
        elcp_end = _d(m["elcp_end"]) if "elcp_end" in m else None
        last_end = std_end
        for cand in (eus_end, elc_end, elcp_end):
            if cand and cand > last_end:
                last_end = cand
        segments = [{"key": "rhel_std", "start": ga, "end": std_end}]
        if eus_end and eus_end > std_end:
            segments.append({"key": "rhel_prem", "start": std_end, "end": eus_end})
        # ELC, Premium starts where Premium/EUS ends (or std_end if no EUS)
        elc_start = eus_end if (eus_end and eus_end > std_end) else std_end
        if elc_end and elc_end > elc_start:
            segments.append({"key": "rhel_elcp", "start": elc_start, "end": elc_end})
        if elcp_end and elcp_end > (elc_end or elc_start):
            segments.append({"key": "rhel_ll", "start": elc_end or elc_start, "end": elcp_end})
        phase_key = "eol"
        days_left = 0
        for seg in segments:
            if today <= seg["end"]:
                phase_key = seg["key"]
                days_left = (seg["end"] - today).days
                break
        is_eol = phase_key == "eol"
        result.append({
            "version": ver, "ga": ga, "last_end": last_end,
            "segments": segments, "is_eus": bool(eus_end),
            "is_eol": is_eol, "phase_key": phase_key, "days_left": days_left,
        })
    return result


def build_rhel_major_versions() -> list[dict]:
    """Build major-version dicts for RHEL using subscription phase keys from rhel_majors."""
    today = date.today()
    result = []
    for ver in sorted(_RHEL_MAJOR_DATA.keys(), key=lambda v: int(v), reverse=True):
        m = _RHEL_MAJOR_DATA[ver]
        ga = _d(m["ga"])
        std_end = _d(m["std_end"])
        els_end = _d(m["els_end"]) if "els_end" in m else None
        elc_end = _d(m["elc_end"]) if "elc_end" in m else None
        ll_end = _d(m["ll_end"]) if "ll_end" in m else None
        segments = [{"key": "rhel_std", "start": ga, "end": std_end}]
        ext_start = std_end
        if els_end and els_end > ext_start:
            segments.append({"key": "rhel_els", "start": ext_start, "end": els_end})
            ext_start = els_end
        if elc_end and elc_end > ext_start:
            segments.append({"key": "rhel_elcp", "start": ext_start, "end": elc_end})
            ext_start = elc_end
        if ll_end and ll_end > ext_start:
            segments.append({"key": "rhel_ll", "start": ext_start, "end": ll_end})
        last_end = segments[-1]["end"]
        phase_key = "eol"
        days_left = 0
        for seg in segments:
            if today <= seg["end"]:
                phase_key = seg["key"]
                days_left = (seg["end"] - today).days
                break
        is_eol = phase_key == "eol"
        result.append({
            "version": ver, "ga": ga, "last_end": last_end,
            "segments": segments, "is_eus": False,
            "is_eol": is_eol, "phase_key": phase_key, "days_left": days_left,
        })
    return result


_PAGE_CSS = ""  # CSS served externally via PatternFly v6 CDN + chart.css

_STATIC_PREFIX = "static"
_ASSET_VERSION = "0.2.16"  # bump when static/css or icons change (cache bust)

# Inline SVG icon bodies (16x16 viewBox, stroke-based) for card-header chip links.
_CHIP_ICONS = {
    "document": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h8"/><path d="M8 9h2"/>'
    ),
    "external": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
    ),
}


def _chip_link(href: str, label: str, icon: str, *, external: bool = False,
               extra_cls: str = "", title: str = "", onclick: str = "") -> str:
    """Render a pill-style card-header link (Policy / Details / Release notes)."""
    if not href:
        return ""
    cls = "card-chip" + (f" {extra_cls}" if extra_cls else "")
    tgt = ' target="_blank" rel="noopener"' if external else ""
    ttl = f' title="{_html.escape(title)}"' if title else ""
    oc = f' onclick="{onclick}"' if onclick else ""
    svg = (
        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f'{_CHIP_ICONS[icon]}</svg>'
    )
    return f'<a href="{_html.escape(href)}" class="{cls}"{tgt}{ttl}{oc}>{svg}{label}</a>'


def _render_card(versions: list[dict], chart_label: str, anchor: str = "",
                 show_footer: bool = True, show_controls: bool = False,
                 minor_data: dict[str, list[dict]] | None = None,
                 page_url: str = "", info_html: str = "", details_url: str = "",
                 static_prefix: str = _STATIC_PREFIX) -> str:
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
    year_span = chart_end.year - chart_start.year + 1
    year_step = 1 if year_span <= 10 else (2 if year_span <= 18 else 5)
    year_markers = []
    for y in range(chart_start.year, chart_end.year + 2):
        d = date(y, 1, 1)
        if chart_start <= d <= chart_end:
            year_markers.append({"year": y, "pct": pct(d), "label": y % year_step == 0})

    year_lines_html = "".join(
        f'<div style="position:absolute;left:{m["pct"]:.3f}%;top:0;bottom:0;'
        f'border-left:1px dashed var(--grid-line);z-index:0"></div>'
        + (
            f'<div style="position:absolute;left:{m["pct"]:.3f}%;top:-20px;'
            f'font-size:11px;color:var(--text-secondary);transform:translateX(-50%);font-weight:600;white-space:nowrap">'
            f'{m["year"]}</div>'
            if m["label"] else ""
        )
        for m in year_markers
    )

    today_html = (
        f'<div class="chart-today-line" style="left:{today_pct:.3f}%"></div>'
        f'<div class="chart-today-label" style="left:{today_pct:.3f}%">Today</div>'
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
            show_label = w > 3
            bar_text = _phase_bar_text(ph, w)
            fs = "10px" if w < 12 else "11px"
            inner = (
                f'<span class="phase-bar-label" style="font-size:{fs};color:{ph["text"]};font-weight:600">'
                f'{bar_text}</span>'
            ) if show_label and bar_text else ""
            _tip_text = f'{ph["label"]} | {seg["start"].isoformat()} → {seg["end"].isoformat()}'
            segs_html += (
                f'<div data-phase="{_tip_text}" '
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
            days_badge = '<span style="color:var(--red);font-weight:700;font-size:13px">EOL</span>'
        elif v.get("phase_open"):
            ph = PHASES[v["phase_key"]]
            days_badge = (
                f'<span style="color:{ph["text"]};font-weight:600;font-size:13px" '
                f'title="{ph["label"]} — ongoing until the referenced release is published">active</span>'
            )
        elif v["days_left"] <= 30:
            _eol_date = v["last_end"].isoformat()
            _eol_days = v["days_left"]
            _msg = f"EOL on {_eol_date} ({_eol_days} days) — Please plan an upgrade and/or contact your support representative for assistance about this version before due date."
            days_badge = (
                f'<span class="eol-warn">'
                f'<span style="color:var(--red);font-weight:700;font-size:13px">⚠️ {_eol_days}d</span>'
                f'<span class="eol-tip">{_msg}</span>'
                f'</span>'
            )
        else:
            ph = PHASES[v["phase_key"]]
            days_badge = f'<span style="color:{ph["text"]};font-weight:600;font-size:13px" title="{ph["label"]} — {v["days_left"]} days remaining">{v["days_left"]}d</span>'

        eus_badge = '<span style="font-size:9px;color:#40199a;font-weight:700;margin-left:4px;vertical-align:middle">EUS</span>' if v["is_eus"] else ""

        rows_html += (
            f'<div class="chart-row" data-ver="{v["version"]}" data-eol="{str(v["is_eol"]).lower()}">'
            f'  <div class="chart-row-label">'
            f'    <code class="ver-code">{v["version"]}</code>{eus_badge}'
            f'  </div>'
            f'  <div class="chart-row-bar">'
            f'    <div style="position:absolute;left:{bar_left:.3f}%;width:{bar_width:.3f}%;height:100%;'
            f'border-radius:4px;overflow:hidden;display:flex">{segs_html}{eol_overlay}</div>'
            f'  </div>'
            f'  <div class="chart-row-days">{days_badge}</div>'
            f'</div>'
        )

        # ── Minor release sub-rows ───────────────────────────────────────────
        if minor_data and v["version"] in minor_data:
            minor_rows_html = ""
            for mv in minor_data[v["version"]]:
                mv_bar_left = pct(mv["ga"])
                mv_bar_right = pct(mv["last_end"])
                mv_bar_width = mv_bar_right - mv_bar_left
                mv_total_days = max((mv["last_end"] - mv["ga"]).days, 1)
                mv_segs_html = ""
                for i, seg in enumerate(mv["segments"]):
                    ph = PHASES[seg["key"]]
                    w = (seg["end"] - seg["start"]).days / mv_total_days * 100
                    is_first, is_last = i == 0, i == len(mv["segments"]) - 1
                    r = f"{'3px' if is_first else '0'} {'3px' if is_last else '0'} {'3px' if is_last else '0'} {'3px' if is_first else '0'}"
                    bl = f"1px solid {ph['border']}" if is_first else "none"
                    br = f"1px solid {ph['border']}" if is_last else "none"
                    _tip = f'{ph["label"]} | {seg["start"].isoformat()} → {seg["end"].isoformat()}'
                    mv_segs_html += (
                        f'<div data-phase="{_tip}" '
                        f'style="width:{w:.3f}%;height:100%;background:{ph["bg"]};'
                        f'border-top:1px solid {ph["border"]};border-bottom:1px solid {ph["border"]};'
                        f'border-left:{bl};border-right:{br};border-radius:{r}"></div>'
                    )
                mv_eus_badge = '<span style="font-size:8px;color:#40199a;font-weight:700;margin-left:3px">EUS</span>' if mv["is_eus"] else ""
                if mv["is_eol"]:
                    mv_days_badge = '<span style="color:var(--red);font-weight:700;font-size:11px">EOL</span>'
                else:
                    _ph = PHASES[mv["phase_key"]]
                    mv_days_badge = f'<span style="color:{_ph["text"]};font-weight:600;font-size:11px">{mv["days_left"]}d</span>'
                minor_rows_html += (
                    f'<div class="minor-row" data-eol="{str(mv["is_eol"]).lower()}">'
                    f'  <div class="chart-row-label">'
                    f'    <code class="ver-code">{mv["version"]}</code>{mv_eus_badge}'
                    f'  </div>'
                    f'  <div class="chart-row-bar">'
                    f'    <div style="position:absolute;left:{mv_bar_left:.3f}%;width:{mv_bar_width:.3f}%;height:100%;'
                    f'border-radius:3px;overflow:hidden;display:flex">{mv_segs_html}</div>'
                    f'  </div>'
                    f'  <div class="chart-row-days">{mv_days_badge}</div>'
                    f'</div>'
                )
            rows_html += f'<div class="minor-group" data-major="{v["version"]}">{minor_rows_html}</div>'

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_html = " ".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--text-primary)"'
        f' title="{PHASES[k]["label"]}">'
        f'<span style="display:inline-block;width:14px;height:12px;border-radius:2px;'
        f'background:{PHASES[k]["bg"]};border:1.5px solid {PHASES[k]["border"]}"></span>'
        f'{_phase_legend_text(PHASES[k])}</span>'
        for k, _ in PHASE_KEYS
        if k in used_phases
    )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    anchor_attr = f' id="{anchor}"' if anchor else ""

    footer_html = (
        f'<div class="footer">'
        f'Source: <a href="https://access.redhat.com/product-life-cycles/" target="_blank">'
        f'Red Hat Product Life Cycles</a>'
        f' &nbsp;·&nbsp; Generated {now_str}'
        f'</div>'
    ) if show_footer else ""

    if show_controls:
        ver_names = [v["version"] for v in versions]
        from_opts = "".join(f'<option value="{v}">{v}</option>' for v in ver_names)
        to_opts   = "".join(f'<option value="{v}">{v}</option>' for v in ver_names)
        minor_toggle_html = (
            f'<label><input type="checkbox" class="ctrl-minor" onchange="toggleMinorRows(this.closest(\'.card\'))"> '
            f'Show minor releases</label>'
        ) if minor_data else ""
        controls_html = (
            f'<div class="card-controls">'
            f'<span class="ctrl-label">Range:</span>'
            f'<select class="ctrl-from" onchange="filterCard(this.closest(\'.card\'))">'
            f'<option value="">All from</option>{from_opts}</select>'
            f'<span class="ctrl-label">→</span>'
            f'<select class="ctrl-to" onchange="filterCard(this.closest(\'.card\'))">'
            f'<option value="">All to</option>{to_opts}</select>'
            f'<label><input type="checkbox" class="ctrl-eol" onchange="filterCard(this.closest(\'.card\'))"> '
            f'Include EOL</label>'
            f'{minor_toggle_html}'
            f'</div>'
        )
    else:
        controls_html = ""

    page_link_html = (" " + _chip_link(
        page_url, "Policy", "external", external=True,
        extra_cls="card-chip--policy", title="Official Lifecycle Policy",
    )) if page_url else ""

    details_link_html = (" " + _chip_link(
        details_url, "Details", "document",
        extra_cls="card-chip--details", title="Z-stream releases & errata",
    )) if details_url else ""

    anchor_link_html = (
        f' <a href="#{anchor}" '
        f'onclick="var u=location.href.split(\'#\')[0]+\'#{anchor}\';navigator.clipboard.writeText(u);event.preventDefault()" '
        f'style="font-size:10px;color:var(--muted);font-weight:400;'
        f'text-decoration:none;white-space:nowrap;margin-left:4px;vertical-align:middle;opacity:0.5" '
        f'title="Copy link to this chart">'
        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle">'
        f'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        f'<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
        f'</svg></a>'
    ) if anchor else ""

    info_block_html = (
        f'<details class="card-info-block">'
        f'<summary>ℹ More info</summary>'
        f'<div class="card-info-body">{info_html}</div>'
        f'</details>'
    ) if info_html else ""

    heading_label = _chart_display_heading(chart_label)
    title_icon = _product_icon_img(
        _chart_icon_key(chart_label), static_prefix, 20, 20, "card-title__icon",
    )

    return f"""<div class="card"{anchor_attr}>
  <div class="card-header">
    <span class="card-title">
      {title_icon}
      {heading_label}{page_link_html}{details_link_html}{anchor_link_html}
    </span>
    <div class="legend">
      {legend_html}
      <span class="legend-today">┆ Today ({today.isoformat()})</span>
    </div>
  </div>
  {controls_html}
  {info_block_html}
  <div class="chart-area">
    <div class="chart-inner" style="--mobile-min-width:{max(520, year_span * (24 if year_span > 18 else 40))}px">
      <div class="chart-grid">
        {year_lines_html}
        {today_html}
      </div>
      <div class="chart-rows">
        {rows_html}
      </div>
    </div>
  </div>
  {footer_html}
</div>"""


_TIER_BADGES = {
    "aligned": (
        "op-tier--aligned", "OCP-aligned",
        "Lifecycle aligned to the OpenShift Container Platform release it ships with "
        "(same Full Support / Maintenance / EUS windows as the underlying OCP minor).",
    ),
    "agnostic": (
        "op-tier--agnostic", "Version-agnostic",
        "Independent lifecycle, not tied to a specific OpenShift Container Platform version.",
    ),
    "rolling": (
        "op-tier--rolling", "Rolling-Stream",
        "Rolling release cadence — each version is supported until the next one ships, "
        "rather than on fixed calendar dates.",
    ),
}


def _operator_tier_key(cfg: dict) -> str | None:
    """Resolve an operator's badge category. Rolling-stream (a config-level release
    model) takes precedence over the API's Aligned/Agnostic tier."""
    if cfg.get("version_strategy") == "rolling-eol":
        return "rolling"
    return {"Aligned": "aligned", "Agnostic": "agnostic"}.get(cfg.get("_api_tier") or "")


def _tier_badge_html(tier_key: str | None) -> str:
    entry = _TIER_BADGES.get(tier_key or "")
    if not entry:
        return ""
    cls, label, tip = entry
    return f'<span class="op-tier {cls}" title="{_html.escape(tip)}">{label}</span>'


def _render_operator_section(operators_data: list[tuple[str, list[dict], str | None]]) -> str:
    if not operators_data:
        return ""
    _anchor_icon = (
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle">'
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
        '</svg>'
    )
    items = []
    for label, versions, tier in operators_data:
        if not versions:
            continue
        slug = "op-" + label.lower().replace(" ", "-")
        n_active = sum(1 for v in versions if not v["is_eol"])
        meta = f"{len(versions)} version{'s' if len(versions) != 1 else ''}"
        if n_active:
            meta += f" · {n_active} active"
        tier_badge = _tier_badge_html(tier)
        anchor_link = (
            f' <a href="#{slug}" '
            f'onclick="var u=location.href.split(\'#\')[0]+\'#{slug}\';navigator.clipboard.writeText(u);event.preventDefault()" '
            f'style="font-size:10px;color:var(--muted);font-weight:400;text-decoration:none;'
            f'white-space:nowrap;margin-left:4px;vertical-align:middle;opacity:0.5" '
            f'title="Copy link to this chart">{_anchor_icon}</a>'
        )
        card = _render_card(versions, label, show_footer=False, show_controls=True)
        items.append(
            f'<details id="{slug}" class="op-details">'
            f'<summary class="op-summary">'
            f'<span class="op-name">{label}{anchor_link}</span>'
            f'<span class="op-summary__right">{tier_badge}<span class="op-meta">{meta}</span></span>'
            f'</summary>'
            f'{card}'
            f'</details>'
        )
    search = (
        '<div style="margin:12px 0 8px">'
        '<input type="search" id="op-search" placeholder="Filter operators…" autocomplete="off" '
        'style="width:100%;max-width:340px;padding:6px 10px;border:1px solid var(--border-base);'
        'border-radius:4px;font-size:13px;font-family:inherit;outline:none;'
        'background:var(--input-bg);color:var(--text-primary)" '
        'oninput="(function(q){var all=document.querySelectorAll(\'#operators .op-details\');'
        'q=q.toLowerCase();all.forEach(function(el){'
        'var n=el.querySelector(\'.op-name\').textContent.toLowerCase();'
        'el.style.display=n.includes(q)?\'\':\''
        'none\'});})(this.value)">'
        '</div>'
    )
    return (
        f'<div id="operators">'
        f'<div class="section-heading">'
        f'{_product_icon_img("operators", _STATIC_PREFIX, 22, 22, "section-heading__icon")}'
        f'<span>OpenShift Operators</span>'
        f'</div>'
        f'{search}'
        f'<div class="op-section">'
        + "\n".join(items)
        + "</div></div>"
    )


def _render_middleware_section(middleware_data: list[tuple[str, list[dict], dict]]) -> str:
    if not middleware_data:
        return ""
    _anchor_icon = (
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle">'
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
        '</svg>'
    )
    items = []
    for label, versions, cfg in middleware_data:
        if not versions:
            continue
        slug = "mw-" + label.lower().replace(" ", "-")
        n_active = sum(1 for v in versions if not v["is_eol"])
        meta = f"{len(versions)} version{'s' if len(versions) != 1 else ''}"
        if n_active:
            meta += f" · {n_active} active"
        page_url = cfg.get("page_url", "")
        page_link = (" " + _chip_link(
            page_url, "Policy", "external", external=True,
            extra_cls="card-chip--policy", title="Lifecycle policy",
        )) if page_url else ""
        anchor_link = (
            f' <a href="#{slug}" '
            f'onclick="var u=location.href.split(\'#\')[0]+\'#{slug}\';navigator.clipboard.writeText(u);event.preventDefault()" '
            f'style="font-size:10px;color:var(--muted);font-weight:400;text-decoration:none;'
            f'white-space:nowrap;margin-left:4px;vertical-align:middle;opacity:0.5" '
            f'title="Copy link to this chart">{_anchor_icon}</a>'
        )
        card = _render_card(versions, label, show_footer=False, show_controls=True)
        items.append(
            f'<details id="{slug}" class="op-details">'
            f'<summary class="op-summary">'
            f'<span class="op-name">{label}{page_link}{anchor_link}</span>'
            f'<span class="op-meta">{meta}</span>'
            f'</summary>'
            f'{card}'
            f'</details>'
        )
    return (
        f'<div id="middleware">'
        f'<div class="section-heading">'
        f'{_product_icon_img("middleware", _STATIC_PREFIX, 22, 22, "section-heading__icon")}'
        f'<span>Middleware &amp; Application Services '
        f'<a href="https://access.redhat.com/support/policy/updates/jboss_notes" '
        f'target="_blank" rel="noopener" style="font-size:11px;color:var(--link-color);font-weight:400">↗ policy</a>'
        f'</span></div>'
        f'<div class="op-section">'
        + "\n".join(items)
        + "</div></div>"
    )


_OPERATOR_POLICY_URL = "https://access.redhat.com/support/policy/updates/openshift_operators"
_MIDDLEWARE_POLICY_URL = "https://access.redhat.com/support/policy/updates/jboss_notes"

_POLICY_LINK_LABELS: dict[str, str] = {
    "OCP Lifecycle": "OpenShift Container Platform",
    "RHEL Lifecycle": "Red Hat Enterprise Linux",
    "AAP Lifecycle": "Ansible Automation Platform",
    "RHOAI Lifecycle": "Red Hat OpenShift AI",
    "Ceph Lifecycle": "Ceph",
    "Red Hat Satellite": "Satellite",
}

# Chart titles excluded from the official-sources sidebar (charts remain on the page).
_DISCLAIMER_SKIP_TITLES: frozenset[str] = frozenset({
    "OpenStack Platform",
    "OpenStack on OpenShift",
    "OpenStack Platform (OSP)",
    "OpenStack on OpenShift (RHOSO)",
})

# Red Hat technology icons in static/icons/products/ (from Red Hat open asset repos).
_DISCLAIMER_ICONS: dict[str, str] = {
    "Product Life Cycles": "product-life-cycles",
    "API": "api",
    "OpenShift Container Platform": "ocp",
    "Red Hat Enterprise Linux": "rhel",
    "Ansible Automation Platform": "aap",
    "Red Hat OpenShift AI": "rhoai",
    "Ceph": "ceph",
    "Satellite": "satellite",
    "OpenShift Operators": "operators",
    "Middleware": "middleware",
}

_CHART_ICON_KEYS: dict[str, str] = {
    "OCP Lifecycle": "ocp",
    "RHEL Lifecycle": "rhel",
    "AAP Lifecycle": "aap",
    "RHOAI Lifecycle": "rhoai",
    "Ceph Lifecycle": "ceph",
    "OpenStack Platform": "osp",
    "OpenStack on OpenShift": "osp",
    "OpenStack Platform (OSP)": "osp",
    "OpenStack on OpenShift (RHOSO)": "osp",
    "Red Hat Satellite": "satellite",
}


def _chart_icon_key(chart_title: str) -> str:
    return _CHART_ICON_KEYS.get(chart_title, "product-life-cycles")


def _chart_display_heading(chart_title: str) -> str:
    short = _POLICY_LINK_LABELS.get(chart_title)
    if short:
        return short
    return chart_title.removesuffix(" Lifecycle")


def _product_icon_img(
    icon_key: str,
    static_prefix: str = _STATIC_PREFIX,
    width: int = 20,
    height: int = 20,
    css_class: str = "product-icon",
) -> str:
    return (
        f'<img class="{css_class}" src="{static_prefix}/icons/products/{icon_key}.svg" '
        f'alt="" width="{width}" height="{height}" loading="lazy">'
    )


def _policy_link_label(chart_title: str) -> str:
    return _POLICY_LINK_LABELS.get(chart_title, chart_title.removesuffix(" Lifecycle"))


def _disclaimer_nav_item(text: str, url: str, static_prefix: str) -> str:
    icon_key = _DISCLAIMER_ICONS.get(text, "product-life-cycles")
    icon = _product_icon_img(icon_key, static_prefix, 18, 18, "disclaimer-sidebar__icon")
    return (
        f'<li class="disclaimer-sidebar__item">'
        f'<a class="disclaimer-sidebar__link" href="{url}" target="_blank" rel="noopener">'
        f'<span class="disclaimer-sidebar__icon-wrap" aria-hidden="true">{icon}</span>'
        f'<span class="disclaimer-sidebar__label">{_html.escape(text)}</span>'
        f'</a></li>'
    )


def _build_disclaimer_html(
    product_list: list[tuple[str, list[dict], dict]],
    operators_data: list | None,
    middleware_data: list | None,
    contribute_html: str = "",
    static_prefix: str = _STATIC_PREFIX,
) -> str:
    """Left sidebar: disclaimer, official source links with product icons, Contribute."""
    links: list[tuple[str, str]] = [
        ("Product Life Cycles", "https://access.redhat.com/product-life-cycles/"),
        ("API", "https://access.redhat.com/product-life-cycles/api/v1/products"),
    ]
    seen_urls: set[str] = {url for _, url in links}
    for chart_title, _, cfg in product_list:
        if chart_title in _DISCLAIMER_SKIP_TITLES:
            continue
        url = cfg.get("page_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            links.append((_policy_link_label(chart_title), url))
    if operators_data and _OPERATOR_POLICY_URL not in seen_urls:
        links.append(("OpenShift Operators", _OPERATOR_POLICY_URL))
    if middleware_data and _MIDDLEWARE_POLICY_URL not in seen_urls:
        links.append(("Middleware", _MIDDLEWARE_POLICY_URL))
    items = "".join(
        _disclaimer_nav_item(text, url, static_prefix) for text, url in links
    )
    contrib = (
        f'<div class="disclaimer-sidebar__contrib">{contribute_html}</div>'
        if contribute_html else ""
    )
    return (
        '<details class="disclaimer-sidebar-shell" id="disclaimer-sidebar-shell">'
        '<summary class="disclaimer-sidebar__toggle">Official sources &amp; Disclaimer</summary>'
        '<aside class="disclaimer-sidebar" aria-label="Disclaimer and official sources">'
        '<p class="disclaimer-sidebar__note">'
        '<strong>Unofficial community tool</strong> - not a Red Hat product or publication. '
        'Dates are compiled from public Red Hat sources.'
        '</p>'
        '<p class="disclaimer-sidebar__heading">Official sources</p>'
        f'<ul class="disclaimer-sidebar__list">{items}</ul>'
        f'{contrib}'
        '</aside>'
        '</details>'
    )


def _page_wrap(title: str, body: str, nav_links: str = "", contribute_html: str = "",
               static_prefix: str = _STATIC_PREFIX, disclaimer_html: str = "",
               sidebar_layout: bool = False) -> str:
    subnav_html = ""
    if nav_links:
        subnav_html = (
            '<section class="pf-v6-c-page__main-subnav pf-m-limit-width pf-m-align-center pf-m-sticky-top">'
            '<div class="pf-v6-c-page__main-body">'
            '<details class="product-nav-shell" id="product-nav-shell">'
            '<summary class="product-nav__toggle">Filter products'
            '<span class="product-nav__badge" id="nav-filter-badge" hidden></span>'
            '</summary>'
            f'<div class="product-nav" role="navigation" aria-label="Product navigation">'
            f'<div class="product-nav__list">{nav_links}</div>'
            '</div>'
            '</details>'
            '</div>'
            '</section>'
        )
    masthead_contrib = "" if sidebar_layout else contribute_html
    masthead_right = (
        '<div class="pf-v6-c-masthead__content">'
        '<div class="pf-v6-l-flex pf-m-align-items-center pf-m-justify-content-flex-end pf-m-flex-1 pf-m-gap-sm">'
        '<button class="pf-v6-c-button pf-m-plain" type="button" id="theme-toggle" aria-label="Toggle theme">'
        '<svg id="theme-icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42'
        'M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
        '<svg id="theme-icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:none">'
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
        '</button>'
        f'{masthead_contrib}'
        '</div></div>'
    )
    if sidebar_layout and disclaimer_html:
        main_content = (
            f'<div class="page-content-offset"><div class="pf-v6-l-stack pf-m-gutter">\n{body}\n</div></div>'
        )
    else:
        main_content = f'<div class="pf-v6-l-stack pf-m-gutter">\n{disclaimer_html}{body}\n</div>'
    page_class = "pf-v6-c-page pf-v6-c-page--with-sidebar" if sidebar_layout and disclaimer_html else "pf-v6-c-page"
    sidebar_html = disclaimer_html if sidebar_layout else ""
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark" class="pf-v6-theme-dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" type="image/svg+xml" href="{static_prefix}/icons/redhat-hat-red.svg">
<script>(function(){{function apply(d){{if(d){{document.documentElement.classList.add('pf-v6-theme-dark');document.documentElement.setAttribute('data-theme','dark');}}else{{document.documentElement.classList.remove('pf-v6-theme-dark');document.documentElement.setAttribute('data-theme','light');}}}}var q=new URLSearchParams(location.search).get('theme');var t=localStorage.getItem('lifecycle-theme'),d;if(q==='dark'||q==='light')d=q==='dark';else if(t==='light')d=false;else if(t==='dark')d=true;else d=window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches;apply(d);window.addEventListener('message',function(e){{var m=e.data;if(m&&m.type==='casedoctor-theme'&&(m.theme==='dark'||m.theme==='light'))apply(m.theme==='dark');}});}})();</script>
<link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@6/patternfly.min.css">
<link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@6/patternfly-addons.css">
<link rel="stylesheet" href="{static_prefix}/css/chart.css?v={_ASSET_VERSION}">
</head>
<body>
<div class="{page_class}">
  <header class="pf-v6-c-masthead">
    <div class="pf-v6-c-masthead__main">
      <a class="pf-v6-c-masthead__brand pf-v6-l-flex pf-m-align-items-center pf-m-gap-sm pf-v6-u-text-color-regular" href="#">
        <img src="{static_prefix}/icons/redhat-hat-red.svg" alt="Red Hat" width="28" height="28">
        <span class="pf-v6-c-title pf-m-md">{title}</span>
      </a>
    </div>
    {masthead_right}
  </header>
  <div class="pf-v6-c-page__main-container">
    <main class="pf-v6-c-page__main" id="main-content">
      {sidebar_html}
      {subnav_html}
      <section class="pf-v6-c-page__main-section pf-m-limit-width pf-m-align-center">
        <div class="pf-v6-c-page__main-body">
          {main_content}
        </div>
      </section>
    </main>
  </div>
</div>
<script>
function getStickyOffset() {{
  var offset = 16;
  var masthead = document.querySelector('.pf-v6-c-masthead');
  var subnav = document.querySelector('.pf-v6-c-page__main-subnav');
  if (masthead) offset += masthead.getBoundingClientRect().height;
  if (subnav) offset += subnav.getBoundingClientRect().height;
  return offset;
}}
function getScrollParent(el) {{
  var node = el.parentElement;
  while (node) {{
    var style = window.getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) {{
      return node;
    }}
    node = node.parentElement;
  }}
  return null;
}}
function updateStickyOffset() {{
  document.documentElement.style.setProperty('--sticky-offset', getStickyOffset() + 'px');
}}
function scrollToElement(el) {{
  if (!el) return;
  updateStickyOffset();
  requestAnimationFrame(function() {{
    updateStickyOffset();
    var offset = getStickyOffset();
    var parent = getScrollParent(el);
    if (parent) {{
      var top = el.getBoundingClientRect().top - parent.getBoundingClientRect().top + parent.scrollTop - offset;
      parent.scrollTo({{ top: Math.max(0, top), behavior: 'smooth' }});
    }} else {{
      var top = el.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({{ top: Math.max(0, top), behavior: 'smooth' }});
    }}
  }});
}}
function findProductSection(target) {{
  return document.getElementById(target) || document.querySelector('[data-anchor="' + target + '"]');
}}
function getNavButtons() {{
  return Array.from(document.querySelectorAll('.nav-toggle[data-target]'));
}}
function isFilterActive() {{
  var nav = document.querySelector('.product-nav');
  return nav && nav.classList.contains('is-filtered');
}}
function getSelectedTargets() {{
  var selected = new Set();
  getNavButtons().forEach(function(btn) {{
    if (btn.getAttribute('aria-pressed') === 'true') selected.add(btn.getAttribute('data-target'));
  }});
  return selected;
}}
function applyProductFilter(selected, scrollTarget) {{
  var nav = document.querySelector('.product-nav');
  var resetBtn = document.getElementById('nav-reset');
  var buttons = getNavButtons();
  var allTargets = buttons.map(function(b) {{ return b.getAttribute('data-target'); }});
  if (!selected || selected.size === 0) {{
    allTargets.forEach(function(t) {{
      var sec = findProductSection(t);
      if (sec) sec.style.display = '';
    }});
    buttons.forEach(function(b) {{ b.setAttribute('aria-pressed', 'true'); }});
    if (nav) nav.classList.remove('is-filtered');
    if (resetBtn) resetBtn.hidden = true;
    updateNavFilterBadge(null);
    return;
  }}
  allTargets.forEach(function(t) {{
    var sec = findProductSection(t);
    if (sec) sec.style.display = selected.has(t) ? '' : 'none';
  }});
  buttons.forEach(function(b) {{
    b.setAttribute('aria-pressed', selected.has(b.getAttribute('data-target')) ? 'true' : 'false');
  }});
  if (nav) nav.classList.add('is-filtered');
  if (resetBtn) resetBtn.hidden = false;
  updateNavFilterBadge(selected);
  if (scrollTarget) {{
    var el = findProductSection(scrollTarget);
    if (el) scrollToElement(el);
  }}
}}
function updateNavFilterBadge(selected) {{
  var badge = document.getElementById('nav-filter-badge');
  if (!badge) return;
  if (!selected || selected.size === 0 || selected.size === getNavButtons().length) {{
    badge.hidden = true;
    badge.textContent = '';
    return;
  }}
  badge.hidden = false;
  badge.textContent = selected.size + ' selected';
}}
function collapseMobileProductNav() {{
  var shell = document.getElementById('product-nav-shell');
  if (!shell || !window.matchMedia('(max-width: 768px)').matches) return;
  shell.removeAttribute('open');
  localStorage.setItem('lifecycle-product-nav-open', 'false');
  updateStickyOffset();
}}
function onProductNavClick(btn) {{
  var target = btn.getAttribute('data-target');
  if (!isFilterActive()) {{
    applyProductFilter(new Set([target]), target);
    collapseMobileProductNav();
    return;
  }}
  var selected = getSelectedTargets();
  if (selected.has(target)) {{
    selected.delete(target);
    applyProductFilter(selected.size ? selected : null);
  }} else {{
    selected.add(target);
    applyProductFilter(selected, target);
    collapseMobileProductNav();
  }}
}}
function resetProductFilter() {{
  applyProductFilter(null);
}}
function initProductNav() {{
  var list = document.querySelector('.product-nav__list');
  if (!list) return;
  list.addEventListener('click', function(e) {{
    if (e.target.closest('#nav-reset')) {{
      resetProductFilter();
      collapseMobileProductNav();
      return;
    }}
    var btn = e.target.closest('.nav-toggle[data-target]');
    if (btn) onProductNavClick(btn);
  }});
}}
function applyRowStripes(card) {{
  var rows = Array.from(card.querySelectorAll('.chart-row[data-ver]'));
  var visible = rows.filter(function(r) {{ return r.style.display !== 'none'; }});
  rows.forEach(function(r) {{ r.classList.remove('row-alt'); }});
  visible.forEach(function(row, i) {{
    if (i % 2 === 1) row.classList.add('row-alt');
  }});
}}
function filterCard(card) {{
  var rows = Array.from(card.querySelectorAll('.chart-row[data-ver]'));
  if (!rows.length) return;
  var fromSel = card.querySelector('.ctrl-from');
  var toSel   = card.querySelector('.ctrl-to');
  var eolCk   = card.querySelector('.ctrl-eol');
  var showEol = eolCk ? eolCk.checked : false;
  var fromIdx = 0, toIdx = rows.length - 1;
  if (fromSel && fromSel.value) {{
    var fi = rows.findIndex(function(r) {{ return r.dataset.ver === fromSel.value; }});
    if (fi >= 0) fromIdx = fi;
  }}
  if (toSel && toSel.value) {{
    var ti = rows.findIndex(function(r) {{ return r.dataset.ver === toSel.value; }});
    if (ti >= 0) toIdx = ti;
  }}
  rows.forEach(function(row, i) {{
    var eol = row.dataset.eol === 'true';
    var visible = i >= fromIdx && i <= toIdx && (showEol || !eol);
    row.style.display = visible ? '' : 'none';
    var group = row.nextElementSibling;
    if (group && group.classList.contains('minor-group')) {{
      if (!visible) {{
        group.style.display = 'none';
      }} else {{
        group.style.display = group.classList.contains('visible') ? 'flex' : 'none';
        group.querySelectorAll('.minor-row').forEach(function(mr) {{
          mr.style.display = (showEol || mr.dataset.eol !== 'true') ? '' : 'none';
        }});
      }}
    }}
  }});
  applyRowStripes(card);
}}
function toggleMinorRows(card) {{
  var show = card.querySelector('.ctrl-minor') && card.querySelector('.ctrl-minor').checked;
  card.querySelectorAll('.minor-group').forEach(function(g) {{
    g.classList.toggle('visible', show);
  }});
  filterCard(card);
}}
function navigateToHash(hash) {{
  if (!hash) return;
  var id = hash.replace(/^#/, '');
  var el = document.getElementById(id);
  if (!el) return;
  var node = el;
  while (node) {{
    if (node.tagName === 'DETAILS') node.open = true;
    node = node.parentElement;
  }}
  applyProductFilter(new Set([id]), id);
  setTimeout(function() {{ scrollToElement(el); }}, 50);
}}
document.addEventListener('DOMContentLoaded', function() {{
  updateStickyOffset();
  initProductNav();
  document.querySelectorAll('.card').forEach(function(card) {{ filterCard(card); }});
  navigateToHash(window.location.hash);
}});
window.addEventListener('resize', updateStickyOffset);
window.addEventListener('hashchange', function() {{ navigateToHash(window.location.hash); }});
(function() {{
  var tip = document.createElement('div');
  tip.id = 'phase-tooltip';
  document.body.appendChild(tip);
  document.addEventListener('mouseover', function(e) {{
    var el = e.target.closest('[data-phase]');
    if (el) {{ tip.textContent = el.dataset.phase; tip.style.display = 'block'; }}
    else {{ tip.style.display = 'none'; }}
  }});
  document.addEventListener('mousemove', function(e) {{
    if (tip.style.display === 'block') {{
      var x = e.clientX + 14, y = e.clientY + 14;
      if (x + 220 > window.innerWidth) x = e.clientX - tip.offsetWidth - 8;
      if (y + 60 > window.innerHeight) y = e.clientY - tip.offsetHeight - 8;
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    }}
  }});
  document.addEventListener('mouseout', function(e) {{
    if (!e.relatedTarget || !e.relatedTarget.closest('[data-phase]')) tip.style.display = 'none';
  }});
}})();
document.addEventListener('click', function(e) {{
  var warn = e.target.closest('.eol-warn');
  if (warn) {{ warn.classList.toggle('pinned'); e.stopPropagation(); }}
  else {{ document.querySelectorAll('.eol-warn.pinned').forEach(function(w) {{ w.classList.remove('pinned'); }}); }}
}});
(function(){{
  var shell = document.getElementById('disclaimer-sidebar-shell');
  if (!shell) return;
  var KEY = 'lifecycle-disclaimer-open';
  var saved = localStorage.getItem(KEY);
  if (saved === 'true') shell.setAttribute('open', '');
  else if (saved === 'false') shell.removeAttribute('open');
  shell.addEventListener('toggle', function() {{
    localStorage.setItem(KEY, shell.open ? 'true' : 'false');
    updateStickyOffset();
  }});
  updateStickyOffset();
}})();
(function(){{
  var shell = document.getElementById('product-nav-shell');
  if (!shell) return;
  var mq = window.matchMedia('(min-width: 769px)');
  var KEY = 'lifecycle-product-nav-open';
  function syncProductNavShell() {{
    if (mq.matches) shell.setAttribute('open', '');
    else {{
      var saved = localStorage.getItem(KEY);
      if (saved === 'true') shell.setAttribute('open', '');
      else shell.removeAttribute('open');
    }}
    updateStickyOffset();
  }}
  if (typeof mq.addEventListener === 'function') mq.addEventListener('change', syncProductNavShell);
  else if (typeof mq.addListener === 'function') mq.addListener(syncProductNavShell);
  shell.addEventListener('toggle', function() {{
    if (!mq.matches) localStorage.setItem(KEY, shell.open ? 'true' : 'false');
    updateStickyOffset();
  }});
  syncProductNavShell();
}})();
(function(){{
  var btn = document.getElementById('theme-toggle');
  var sunIcon = document.getElementById('theme-icon-sun');
  var moonIcon = document.getElementById('theme-icon-moon');
  function applyTheme(dark){{
    if(dark){{
      document.documentElement.classList.add('pf-v6-theme-dark');
      document.documentElement.setAttribute('data-theme','dark');
      sunIcon.style.display='inline';moonIcon.style.display='none';
    }}else{{
      document.documentElement.classList.remove('pf-v6-theme-dark');
      document.documentElement.setAttribute('data-theme','light');
      sunIcon.style.display='none';moonIcon.style.display='inline';
    }}
  }}
  var cur = document.documentElement.getAttribute('data-theme')==='dark';
  if (btn && sunIcon && moonIcon) {{
    applyTheme(cur);
    btn.addEventListener('click',function(){{
      var isDark = document.documentElement.getAttribute('data-theme')==='dark';
      var next = !isDark;
      localStorage.setItem('lifecycle-theme', next?'dark':'light');
      applyTheme(next);
    }});
  }}
}})();
</script>
</body>
</html>"""


def _rhel_minor_data(versions: list[dict]) -> dict[str, list[dict]]:
    """Build minor version data for RHEL cards. Only includes majors present in versions."""
    return {
        v["version"]: build_rhel_minor_versions(v["version"])
        for v in versions
        if v["version"] in _RHEL_MINOR_DATA
    }


def render_html(versions: list[dict], chart_label: str, show_footer: bool = True,
                minor_data: dict[str, list[dict]] | None = None,
                page_url: str = "", info_html: str = "", details_url: str = "") -> str:
    card = _render_card(versions, chart_label, show_footer=show_footer, show_controls=True,
                        minor_data=minor_data, page_url=page_url, info_html=info_html,
                        details_url=details_url)
    heading = _chart_display_heading(chart_label)
    crumb = _breadcrumb([
        (f"{_BC_HOME_ICON}All products", "index.html"),
        (f"{_html.escape(heading)} lifecycle", ""),
    ])
    toggle = ""
    if details_url:
        key = details_url.removeprefix("lifecycle-").removesuffix("-details.html")
        toggle = f'<div class="details-topbar__right">{_view_toggle("chart", key)}</div>'
    topbar = f'<div class="details-topbar">{crumb}{toggle}</div>'
    return _page_wrap(chart_label, f"{topbar}\n{card}")


def render_combined_html(
    product_list: list[tuple[str, list[dict], dict]],
    title: str = "Red Hat Product Lifecycle",
    operators_data: list[tuple[str, list[dict], str | None]] | None = None,
    middleware_data: list[tuple[str, list[dict], dict]] | None = None,
) -> str:
    _btn_cls = "pf-v6-c-button pf-m-secondary nav-toggle"
    nav_links = (
        '<button type="button" class="pf-v6-c-button pf-m-primary nav-reset" id="nav-reset" hidden>'
        'Reset filter</button>'
        + "".join(
            f'<button type="button" class="{_btn_cls}" aria-pressed="true"'
            f' data-target="{label.lower().replace(" ", "-")}"'
            f' aria-label="Filter to {_chart_display_heading(label)}">'
            f'{_product_icon_img(_chart_icon_key(label), css_class="nav-toggle__icon", width=16, height=16)}'
            f'{_chart_display_heading(label)}</button>'
            for label, _, _ in product_list
        )
    )
    if middleware_data:
        nav_links += (
            f'<button type="button" class="{_btn_cls}" aria-pressed="true" data-target="middleware"'
            f' aria-label="Filter to Middleware">'
            f'{_product_icon_img("middleware", css_class="nav-toggle__icon", width=16, height=16)}'
            f'Middleware</button>'
        )
    if operators_data:
        nav_links += (
            f'<button type="button" class="{_btn_cls}" aria-pressed="true" data-target="operators"'
            f' aria-label="Filter to OpenShift Operators">'
            f'{_product_icon_img("operators", css_class="nav-toggle__icon", width=16, height=16)}'
            f'OpenShift Operators</button>'
        )
    # Guide link lives in the footer, not the nav
    _gh_svg = (
        '<svg height="11" width="11" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:middle;margin-right:4px">'
        '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38'
        ' 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13'
        '-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66'
        '.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15'
        '-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09'
        ' 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15'
        ' 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2'
        ' 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>'
        '</svg>'
    )
    _issue_body = (
        "%23%23%23%20%F0%9F%9A%80%20Contribution%20Proposal%0A%0A"
        "%2A%2AWhat%20kind%20of%20contribution%20is%20this%3F%2A%2A%0A"
        "-%20%5B%20%5D%20Bug%20Fix%0A"
        "-%20%5B%20%5D%20Feature%20%2F%20Enhancement%0A"
        "-%20%5B%20%5D%20Life-cycle%20Data%20Update%20%28e.g.%2C%20adding%20missing%20product%20timelines%29%0A"
        "-%20%5B%20%5D%20Documentation%20Improvement%0A%0A"
        "---%0A%0A"
        "%23%23%23%20%F0%9F%93%9D%20Description%0A%0A"
        "%23%23%23%20%F0%9F%9B%A0%EF%B8%8F%20Proposed%20Implementation%20%2F%20Changes%0A%0A"
        "%23%23%23%20%F0%9F%8E%A8%20Visuals%20%28if%20applicable%29%0A%0A"
        "%23%23%23%20%F0%9F%99%8B%E2%80%8D%E2%99%82%EF%B8%8F%20Assignee%0A"
        "-%20%5B%20%5D%20I%20would%20like%20to%20work%20on%20this%20myself%21"
    )
    contribute_html = (
        f'<a href="https://github.com/mmayeras/redhat-lifecycle-graph/issues/new?body={_issue_body}" '
        f'class="gh-contribute" target="_blank">{_gh_svg}Contribute</a>'
    )
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "\n".join(
        _render_card(versions, label, anchor=label.lower().replace(" ", "-"),
                     show_footer=False, show_controls=True,
                     minor_data=_rhel_minor_data(versions) if label == "RHEL Lifecycle" else None,
                     page_url=cfg.get("page_url", ""),
                     info_html=cfg.get("info_html", ""),
                     details_url=cfg.get("details_url", ""))
        for label, versions, cfg in product_list
    )
    operators_section = _render_operator_section(operators_data or [])
    middleware_section = _render_middleware_section(middleware_data or [])
    footer = (
        f'<p style="text-align:center;font-size:11px;color:#6a6e73;margin-top:4px">'
        f'Source: <a href="https://access.redhat.com/product-life-cycles/" '
        f'style="color:#0066cc" target="_blank">Red Hat Product Life Cycles</a>'
        f' &nbsp;·&nbsp; Generated {now_str}'
        f' &nbsp;·&nbsp; '
        f'<a href="lifecycle-about.html" style="color:#0066cc">How it works</a>'
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
        f' &nbsp;·&nbsp; '
        f'<a href="https://www.linkedin.com/in/mickaelmayeras/" style="color:#0066cc;display:inline-flex;align-items:center;gap:4px;vertical-align:middle" target="_blank">'
        f'<svg height="13" width="13" viewBox="0 0 24 24" fill="#0066cc" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>'
        f'</svg>Mickael Mayeras</a></p>'
        f'<p style="text-align:center;font-size:11px;color:#6a6e73;margin-top:6px">'
        f'📣 If you find this useful and want to contribute: '
        f'<a href="https://github.com/mmayeras/redhat-lifecycle-graph/issues/new?body={_issue_body}" style="color:#0066cc" target="_blank">Open an Issue</a>'
        f'&nbsp;·&nbsp;'
        f'<a href="https://github.com/mmayeras/redhat-lifecycle-graph/compare" style="color:#0066cc" target="_blank">Open a Pull Request</a>'
        f'</p>'
    )
    body = (cards
            + ("\n" + middleware_section if middleware_section else "")
            + ("\n" + operators_section if operators_section else "")
            + "\n" + footer)
    return _page_wrap(
        title, body, nav_links, contribute_html,
        disclaimer_html=_build_disclaimer_html(
            product_list, operators_data, middleware_data, contribute_html,
        ),
        sidebar_layout=True,
    )


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
            if sw > 40:
                lbl_x = sx + sw / 2
                bar_lbl = _phase_bar_text(ph, sw / bar_w * 100 if bar_w else 0)
                if bar_lbl:
                    els.append(f'<text x="{lbl_x:.1f}" y="{bar_y + BAR_H/2 + 4:.1f}" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="600" fill="{ph["text"]}">{bar_lbl}</text>')
        if v["is_eol"]:
            els.append(f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{BAR_H}" fill="url(#eol)"/>')
        els.append('</g>')

        els.append(f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{BAR_H}" rx="3" fill="none" stroke="{C_BORDER}" stroke-width="1"/>')

        for seg in v["segments"][:-1]:
            dx = px(seg["end"])
            els.append(f'<line x1="{dx:.1f}" y1="{bar_y:.1f}" x2="{dx:.1f}" y2="{bar_y + BAR_H:.1f}" stroke="{C_DIVIDER}" stroke-width="1"/>')

        if v["is_eol"]:
            els.append(f'<text x="{chart_right + 8}" y="{cy + 5:.1f}" font-family="{FONT}" font-size="12" font-weight="700" fill="{C_EOL}">EOL</text>')
        elif v.get("phase_open"):
            ph = PHASES[v["phase_key"]]
            els.append(f'<text x="{chart_right + 8}" y="{cy + 5:.1f}" font-family="{FONT}" font-size="12" font-weight="600" fill="{ph["text"]}">active</text>')
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


def _fetch_all(
    args: argparse.Namespace,
) -> tuple[list[tuple[str, list[dict], dict]], list[tuple[str, list[dict]]], list[tuple[str, list[dict], dict]]]:
    """Return (product_list, operators_data, middleware_data) with ALL versions (incl. EOL).

    product_list/middleware_data entries are (label, versions, cfg).
    Callers must filter by is_eol themselves when generating SVG/PNG.
    """
    product_list: list[tuple[str, list[dict], dict]] = []
    for product, cfg in PRODUCT_CONFIGS.items():
        if cfg.get("use_major_phases"):
            versions = build_rhel_major_versions()
        else:
            lifecycle = fetch_lifecycle(cfg)
            versions = build_versions(
                lifecycle, cfg,
                versions_filter=args.versions,
                from_version=args.from_version,
                to_version=args.to_version,
                include_eol=True,  # always; HTML controls filter via JS
            )
        if versions:
            product_list.append((cfg["title"], versions, cfg))
        else:
            print(f"No versions matched for {product}.", file=sys.stderr)

    operators_data: list[tuple[str, list[dict], str | None]] = []
    for op_cfg in OPERATOR_CONFIGS.values():
        lifecycle = fetch_lifecycle(op_cfg)
        versions = build_versions(lifecycle, op_cfg, include_eol=True)
        if versions:
            operators_data.append((op_cfg["title"], versions, _operator_tier_key(op_cfg)))
    operators_data.sort(key=lambda t: t[0].lower())

    middleware_data: list[tuple[str, list[dict], dict]] = []
    for mw_cfg in MIDDLEWARE_CONFIGS.values():
        lifecycle = fetch_lifecycle(mw_cfg)
        versions = build_versions(lifecycle, mw_cfg, include_eol=True)
        if versions:
            middleware_data.append((mw_cfg["title"], versions, mw_cfg))
    middleware_data.sort(key=lambda t: t[0].lower())

    return product_list, operators_data, middleware_data


def _svg_versions(versions: list[dict], include_eol: bool) -> list[dict]:
    """Filter version list for SVG/PNG output (EOL hidden unless explicitly requested)."""
    return versions if include_eol else [v for v in versions if not v["is_eol"]]


def _generate_product(
    product: str,
    out_html: Path,
    args: argparse.Namespace,
) -> None:
    cfg = PRODUCT_CONFIGS[product]
    chart_label = args.title if args.title else cfg["title"]

    if cfg.get("use_major_phases"):
        versions_html = build_rhel_major_versions()
    else:
        lifecycle = fetch_lifecycle(cfg)
        versions_html = build_versions(
            lifecycle, cfg,
            versions_filter=args.versions,
            from_version=args.from_version,
            to_version=args.to_version,
            include_eol=True,  # always; JS controls visibility
        )
    if not versions_html:
        print(f"No versions matched for {product}.", file=sys.stderr)
        return

    minor_data = _rhel_minor_data(versions_html) if cfg.get("has_minors") else None
    html = render_html(versions_html, chart_label, minor_data=minor_data,
                       page_url=cfg.get("page_url", ""), info_html=cfg.get("info_html", ""),
                       details_url=cfg.get("details_url", ""))
    out_html.write_text(html, encoding="utf-8")
    print(f"HTML: {out_html}  ({len(versions_html)} versions)")

    if cfg.get("details") and not getattr(args, "skip_details", False):
        _generate_details_page(out_html.parent, product, cfg, versions_html)

    if args.png:
        versions_svg = _svg_versions(versions_html, args.include_eol)
        svg_out = out_html.with_suffix(".svg")
        png_out = out_html.with_suffix(".png")
        svg_out.write_text(render_svg(versions_svg, chart_label, args.width), encoding="utf-8")
        print(f"SVG:  {svg_out}")
        ok = export_png(svg_out, png_out)
        if ok:
            print(f"PNG:  {png_out}")

    if args.open:
        subprocess.run(["open", str(out_html)], check=False)


def _markdown_to_html(text: str) -> str:
    """Convert a Markdown document to HTML (stdlib only, covers LIFECYCLE.md structure)."""
    # Phase 1: extract fenced code blocks to protect them from inline transforms
    placeholders: dict[str, str] = {}
    counter = [0]

    def _extract_fence(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = _html.escape(m.group(2))
        ph = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        cls = f' class="language-{lang}"' if lang else ""
        placeholders[ph] = f'<pre><code{cls}>{code}</code></pre>'
        return "\n" + ph + "\n"

    text = re.sub(r"```(\w+)?\n(.*?)```", _extract_fence, text, flags=re.DOTALL)

    def _inline(s: str) -> str:
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'`([^`]+)`', lambda m: f'<code>{_html.escape(m.group(1))}</code>', s)

        def _link(m: re.Match) -> str:
            label, href = m.group(1), m.group(2)
            target = '' if href.startswith('#') else ' target="_blank"'
            return f'<a href="{href}"{target}>{label}</a>'

        s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _link, s)
        return s

    lines = text.splitlines()
    out: list[str] = []
    in_list: str | None = None
    i = 0

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Code block placeholder
        if stripped in placeholders:
            flush_list()
            out.append(placeholders[stripped])
            i += 1
            continue

        # Blockquote: collect consecutive > lines, recursively convert
        if stripped.startswith('>'):
            flush_list()
            bq_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                bq_lines.append(re.sub(r'^>\s?', '', lines[i]))
                i += 1
            inner = _markdown_to_html('\n'.join(bq_lines))
            out.append(f'<blockquote>{inner}</blockquote>')
            continue

        # ATX headings
        hm = re.match(r'^(#{1,4})\s+(.+)', line)
        if hm:
            flush_list()
            lvl = len(hm.group(1))
            heading = hm.group(2)
            slug = re.sub(r'[^a-z0-9 -]', '', re.sub(r'`([^`]*)`', r'\1', heading).lower())
            slug = re.sub(r'\s+', '-', slug.strip())
            id_attr = f' id="{slug}"' if slug else ''
            out.append(f'<h{lvl}{id_attr}>{_inline(heading)}</h{lvl}>')
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^---+\s*$', stripped):
            flush_list()
            out.append('<hr>')
            i += 1
            continue

        # Table: header row followed by separator
        if '|' in line and i + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', lines[i + 1]):
            flush_list()
            headers = [c.strip() for c in line.strip('|').split('|')]
            i += 2  # skip separator row
            rows: list[list[str]] = []
            while i < len(lines) and '|' in lines[i]:
                rows.append([c.strip() for c in lines[i].strip('|').split('|')])
                i += 1
            ths = ''.join(f'<th>{_inline(c)}</th>' for c in headers)
            trs = ''.join(
                '<tr>' + ''.join(f'<td>{_inline(c)}</td>' for c in row) + '</tr>'
                for row in rows
            )
            out.append(f'<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>')
            continue

        # Unordered list item
        ulm = re.match(r'^- (.+)', line)
        if ulm:
            if in_list != 'ul':
                flush_list()
                in_list = 'ul'
                out.append('<ul>')
            out.append(f'<li>{_inline(ulm.group(1))}</li>')
            i += 1
            continue

        # Ordered list item
        olm = re.match(r'^\d+\.\s+(.+)', line)
        if olm:
            if in_list != 'ol':
                flush_list()
                in_list = 'ol'
                out.append('<ol>')
            out.append(f'<li>{_inline(olm.group(1))}</li>')
            i += 1
            continue

        # Blank line
        if not stripped:
            flush_list()
            i += 1
            continue

        # Paragraph: accumulate consecutive non-special lines
        flush_list()
        para: list[str] = [_inline(line)]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            ns = nxt.strip()
            if (not ns or ns in placeholders
                    or re.match(r'^[#\-\d]|^---', nxt) or '|' in nxt):
                break
            para.append(_inline(nxt))
            i += 1
        out.append(f'<p>{" ".join(para)}</p>')

    flush_list()

    result = '\n'.join(out)
    for ph, block in placeholders.items():
        result = result.replace(ph, block)
    return result


def _generate_lifecycle_about(path: Path) -> None:
    """Render a clean About page explaining how the project works."""
    md_path = Path(__file__).parent / "LIFECYCLE.md"
    if not md_path.exists():
        return
    md_text = md_path.read_text(encoding="utf-8")
    content = _markdown_to_html(md_text)

    # Build TOC from headings in markdown
    toc_items = []
    for m in re.finditer(r'^(#{2,3})\s+(.+)', md_text, re.MULTILINE):
        lvl = len(m.group(1))
        title = re.sub(r'[`*]', '', m.group(2)).strip()
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        toc_cls = "" if lvl == 2 else " toc-h3"
        toc_items.append(f'<li class="{toc_cls}"><a href="#{slug}">{_html.escape(title)}</a></li>')

    def _add_id(m: re.Match) -> str:
        lvl, inner = m.group(1), m.group(2)
        text = re.sub(r'<[^>]+>', '', inner)
        slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
        return f'<h{lvl} id="{slug}">{inner}</h{lvl}>'

    content = re.sub(r'<h([23])>(.*?)</h\1>', _add_id, content)
    toc_html = '<ul class="toc-list">' + ''.join(toc_items) + '</ul>'

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>How it works — lifecycle-graph</title>
<style>
:root {
  --bg:#0d1117; --bg2:#161b22; --bg3:#1c2128; --border:#30363d;
  --text:#c9d1d9; --dim:#8b949e; --accent:#58a6ff; --green:#3fb950;
  --orange:#f0883e; --purple:#d2a8ff; --link:#58a6ff;
  --code-bg:#161b22; --th:#1c2128;
}
[data-theme="light"] {
  --bg:#f6f8fa; --bg2:#ffffff; --bg3:#f0f3f6; --border:#d0d7de;
  --text:#1f2328; --dim:#57606a; --accent:#0969da; --green:#1a7f37;
  --orange:#bc4c00; --purple:#6639ba; --link:#0969da;
  --code-bg:#f6f8fa; --th:#f0f3f6;
}
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px;line-height:1.65}

/* nav */
.nav{position:sticky;top:0;z-index:99;height:52px;
  display:flex;align-items:center;gap:12px;padding:0 28px;
  background:var(--bg2);border-bottom:1px solid var(--border)}
.nav-back{display:inline-flex;align-items:center;gap:5px;
  color:var(--accent);text-decoration:none;font-size:13px;
  padding:5px 12px;border:1px solid var(--border);border-radius:6px;
  transition:.15s}
.nav-back:hover{border-color:var(--accent)}
.nav-title{font-size:14px;font-weight:600}
.nav-spacer{flex:1}
.theme-btn{background:none;border:1px solid var(--border);border-radius:6px;
  color:var(--dim);cursor:pointer;padding:4px 10px;font-size:14px;line-height:1}

/* hero */
.hero{padding:56px 28px 44px;text-align:center;
  background:linear-gradient(175deg,var(--bg2) 0%,var(--bg) 100%);
  border-bottom:1px solid var(--border)}
.hero h1{margin:0 0 10px;font-size:2.1rem;font-weight:700;letter-spacing:-.5px}
.hero p{margin:0 auto;max-width:520px;color:var(--dim);font-size:1rem}
.badges{display:flex;gap:8px;justify-content:center;margin-top:18px;flex-wrap:wrap}
.badge{display:inline-flex;align-items:center;padding:3px 12px;
  border-radius:20px;font-size:12px;font-weight:500;border:1px solid;cursor:default}
.b-blue  {color:var(--accent);border-color:#58a6ff44;background:#58a6ff0d}
.b-green {color:var(--green);border-color:#3fb95044;background:#3fb9500d}
.b-orange{color:var(--orange);border-color:#f0883e44;background:#f0883e0d}
.b-purple{color:var(--purple);border-color:#d2a8ff44;background:#d2a8ff0d}

/* pipeline strip */
.pipeline{display:flex;align-items:center;justify-content:center;
  gap:0;padding:32px 28px;flex-wrap:wrap;
  border-bottom:1px solid var(--border);background:var(--bg2)}
.pipe-step{display:flex;flex-direction:column;align-items:center;
  padding:14px 18px;background:var(--bg3);border:1px solid var(--border);
  border-radius:10px;min-width:130px;text-align:center;gap:4px}
.pipe-step .ps-icon{font-size:22px}
.pipe-step .ps-label{font-size:12px;font-weight:600;color:var(--text)}
.pipe-step .ps-sub{font-size:11px;color:var(--dim)}
.pipe-arrow{font-size:20px;color:var(--border);padding:0 6px;flex-shrink:0}
.pipe-step.c-orange{border-color:#f0883e66}
.pipe-step.c-blue  {border-color:#58a6ff66}
.pipe-step.c-green {border-color:#3fb95066}
.pipe-step.c-purple{border-color:#d2a8ff66}
.pipe-step.c-gray  {border-color:#8b949e66}

/* layout */
.layout{display:grid;grid-template-columns:210px 1fr;
  max-width:1160px;margin:0 auto;padding:0 28px 80px}

/* toc */
.toc{position:sticky;top:52px;align-self:start;
  height:calc(100vh - 52px);overflow-y:auto;
  padding:28px 18px 28px 0;border-right:1px solid var(--border)}
.toc-hd{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:var(--dim);margin:0 0 10px}
.toc ul{list-style:none;margin:0;padding:0}
.toc li{margin:1px 0}
.toc a{display:block;padding:4px 8px;font-size:13px;color:var(--dim);
  text-decoration:none;border-radius:5px;border-left:2px solid transparent;
  transition:.12s}
.toc a:hover{color:var(--text);background:var(--bg2)}
.toc a.on{color:var(--accent);border-left-color:var(--accent);background:var(--bg2)}
.toc .h3 a{padding-left:18px;font-size:12px}

/* article */
.art{padding:32px 0 0 32px;min-width:0}
.art h1{font-size:1.8rem;margin:0 0 6px}
.art h2{font-size:1.15rem;font-weight:600;margin:38px 0 10px;
  padding-bottom:6px;border-bottom:1px solid var(--border);scroll-margin-top:68px}
.art h3{font-size:.98rem;font-weight:600;margin:22px 0 6px;scroll-margin-top:68px}
.art h4{font-size:.88rem;font-weight:600;margin:14px 0 4px;color:var(--dim)}
.art p{margin:8px 0}
.art ul,.art ol{margin:6px 0 6px 22px}
.art li{margin:3px 0}
.art hr{border:none;border-top:1px solid var(--border);margin:28px 0}
.art a{color:var(--link)}
.art code{background:var(--code-bg);border:1px solid var(--border);
  border-radius:4px;padding:1px 6px;font-size:.83em;
  font-family:"SF Mono",Menlo,Consolas,monospace}
.art pre{background:var(--code-bg);border:1px solid var(--border);
  border-radius:8px;padding:14px 18px;overflow-x:auto;margin:12px 0}
.art pre code{background:none;border:none;padding:0;font-size:.84em}
.art table{border-collapse:collapse;margin:12px 0;font-size:.87em;
  display:block;overflow-x:auto;width:100%}
.art th,.art td{border:1px solid var(--border);padding:6px 14px;
  text-align:left;white-space:nowrap}
.art th{background:var(--th);font-weight:600}
.art tr:nth-child(even) td{background:var(--bg2)}
.art blockquote{margin:16px 0;padding:12px 16px 12px 20px;
  border-left:3px solid var(--accent);border-radius:0 6px 6px 0;
  background:var(--bg2)}
.art blockquote p{margin:4px 0;font-size:.9em}
.art blockquote table{font-size:.84em}

/* footer */
.foot{text-align:center;padding:24px;font-size:12px;color:var(--dim);
  border-top:1px solid var(--border)}
.foot a{color:var(--link);text-decoration:none}
.foot a:hover{text-decoration:underline}

@media(max-width:720px){
  .layout{grid-template-columns:1fr}
  .toc{display:none}
  .art{padding:24px 0 0}
  .pipeline{gap:4px}
  .pipe-arrow{display:none}
}
</style>
<script>(function(){
  function apply(d){document.documentElement.setAttribute('data-theme',d?'dark':'light');}
  var q=new URLSearchParams(location.search).get('theme');
  var s=localStorage.getItem('lifecycle-theme');
  var d;
  if(q==='dark'||q==='light')d=q==='dark';
  else d=s?s==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;
  apply(d);
  window.addEventListener('message',function(e){
    var m=e.data;
    if(m&&m.type==='casedoctor-theme'&&(m.theme==='dark'||m.theme==='light'))apply(m.theme==='dark');
  });
})();</script>
</head>
<body>

<nav class="nav">
  <a class="nav-back" href="lifecycle.html">← Charts</a>
  <span class="nav-title">How it works</span>
  <span class="nav-spacer"></span>
  <button class="theme-btn" id="tbtn">☀</button>
</nav>

<div class="hero">
  <h1>How it works</h1>
  <p>lifecycle-graph fetches Red Hat product support data, models it as phase timelines, and renders interactive Gantt charts — updated daily.</p>
  <div class="badges">
    <span class="badge b-orange">lifecycle-config.yaml</span>
    <span class="badge b-blue">Red Hat Lifecycle API</span>
    <span class="badge b-green">GitHub Pages</span>
    <span class="badge b-blue">5 products</span>
    <span class="badge b-purple">43 operators</span>
  </div>
</div>

<div class="pipeline">
  <div class="pipe-step c-orange">
    <span class="ps-icon">📄</span>
    <span class="ps-label">lifecycle-config.yaml</span>
    <span class="ps-sub">sole source of truth</span>
  </div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-step c-blue">
    <span class="ps-icon">🔗</span>
    <span class="ps-label">Red Hat API</span>
    <span class="ps-sub">live lifecycle dates</span>
  </div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-step c-blue">
    <span class="ps-icon">⚙</span>
    <span class="ps-label">build_versions()</span>
    <span class="ps-sub">filter · EUS · segments</span>
  </div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-step c-purple">
    <span class="ps-icon">📊</span>
    <span class="ps-label">render_card()</span>
    <span class="ps-sub">Gantt HTML per version</span>
  </div>
  <span class="pipe-arrow">→</span>
  <div class="pipe-step c-green">
    <span class="ps-icon">🌐</span>
    <span class="ps-label">GitHub Pages</span>
    <span class="ps-sub">published daily</span>
  </div>
</div>

<div class="layout">
  <aside class="toc">
    <p class="toc-hd">Contents</p>
    """ + toc_html + """
  </aside>
  <article class="art">
    """ + content + """
  </article>
</div>

<div class="foot">
  <a href="lifecycle.html">← Back to charts</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/mmayeras/redhat-lifecycle-graph" target="_blank">GitHub</a>
  &nbsp;·&nbsp;
  Data from <a href="https://access.redhat.com/product-life-cycles/" target="_blank">Red Hat Product Life Cycles</a>
</div>

<script>
document.getElementById('tbtn').addEventListener('click',function(){
  var t=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',t);
  localStorage.setItem('lifecycle-theme',t);
});
var hs=Array.from(document.querySelectorAll('.art h2,.art h3'));
var ls=Array.from(document.querySelectorAll('.toc a'));
window.addEventListener('scroll',function(){
  var pos=window.scrollY+80;
  var cur=hs.filter(function(h){return h.offsetTop<=pos;}).pop();
  ls.forEach(function(l){l.classList.remove('on');});
  if(cur){var l=document.querySelector('.toc a[href="#'+cur.id+'"]');if(l)l.classList.add('on');}
},{passive:true});
</script>
</body>
</html>"""

    path.write_text(html, encoding="utf-8")


# ── Details page rendering ───────────────────────────────────────────────────

_DETAILS_JS = """
(function () {
  var idxEl = document.getElementById('details-index');
  if (!idxEl) return;
  var IDX = JSON.parse(idxEl.textContent);
  var selFrom = document.getElementById('delta-from');
  var selTo = document.getElementById('delta-to');
  var reset = document.getElementById('delta-reset');
  var summary = document.getElementById('delta-summary');

  function fill(sel, placeholder) {
    var opt = document.createElement('option');
    opt.value = '';
    opt.textContent = placeholder;
    sel.appendChild(opt);
    IDX.forEach(function (z) {
      var o = document.createElement('option');
      o.value = z.v;
      o.textContent = z.v;
      sel.appendChild(o);
    });
  }
  fill(selFrom, 'version…');
  fill(selTo, 'version…');

  function cmpVer(a, b) {
    var pa = a.split('.').map(Number), pb = b.split('.').map(Number);
    for (var i = 0; i < 3; i++) {
      if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
    }
    return 0;
  }

  function applyDelta(push) {
    var from = selFrom.value, to = selTo.value;
    var active = from && to;
    var lo = from, hi = to;
    if (active && cmpVer(from, to) > 0) { lo = to; hi = from; }
    var counts = { n: 0, security: 0, bugfix: 0, enhancement: 0, other: 0 };
    var inRange = {};
    IDX.forEach(function (z) {
      var keep = !active || (cmpVer(z.v, lo) > 0 && cmpVer(z.v, hi) <= 0);
      inRange[z.v] = keep;
      if (active && keep) {
        counts.n += 1;
        counts.security += z.sec; counts.bugfix += z.bug;
        counts.enhancement += z.enh; counts.other += z.oth;
      }
    });
    document.querySelectorAll('.zstream-block').forEach(function (el) {
      el.hidden = !inRange[el.dataset.zver];
    });
    document.querySelectorAll('.unversioned-block').forEach(function (el) {
      el.hidden = !!active;
    });
    document.querySelectorAll('.minor-block').forEach(function (el) {
      var visible = el.querySelectorAll('.zstream-block:not([hidden])').length;
      el.hidden = active && visible === 0;
      if (active && visible > 0) el.open = true;
    });
    if (active) {
      summary.hidden = false;
      summary.textContent = counts.n + ' z-stream release' + (counts.n === 1 ? '' : 's') + ' \\u00b7 '
        + counts.security + ' Security \\u00b7 ' + counts.bugfix + ' Bug Fix \\u00b7 '
        + counts.enhancement + ' Enhancement'
        + (counts.other ? ' \\u00b7 ' + counts.other + ' other' : '')
        + ' between ' + lo + ' and ' + hi;
      reset.hidden = false;
    } else {
      summary.hidden = true;
      reset.hidden = true;
    }
    if (push) {
      var url = location.pathname + (active ? '?from=' + from + '&to=' + to : '') + location.hash;
      history.replaceState(null, '', url);
    }
  }

  selFrom.addEventListener('change', function () { applyDelta(true); });
  selTo.addEventListener('change', function () { applyDelta(true); });
  reset.addEventListener('click', function () {
    selFrom.value = ''; selTo.value = '';
    applyDelta(true);
  });

  var q = new URLSearchParams(location.search);
  var qf = q.get('from'), qt = q.get('to');
  if (qf) selFrom.value = qf;
  if (qt) selTo.value = qt;
  if (selFrom.value && selTo.value) applyDelta(false);
})();
"""


def _errata_badge(kind: str, label: str) -> str:
    return f'<span class="errata-badge errata-badge--{kind}">{_html.escape(label)}</span>'


def _render_errata_rows(errata: list[dict]) -> str:
    rows = []
    for e in errata:
        label = _ERRATA_KIND_LABELS.get(e["kind"], "Advisory")
        if e["kind"] == "security" and e["severity"] and e["severity"] != "None":
            label += f' · {e["severity"]}'
        rows.append(
            f'<div class="errata-row" data-kind="{e["kind"]}">'
            f'{_errata_badge(e["kind"], label)}'
            f'<a class="errata-row__id" href="{_html.escape(e["url"])}" target="_blank" rel="noopener">'
            f'{_html.escape(e["id"])}</a>'
            f'<span class="errata-row__synopsis">{_html.escape(e["synopsis"])}</span>'
            f'<span class="errata-row__date">{_html.escape(e["date"])}</span>'
            f'</div>'
        )
    return "".join(rows)


def _zstream_count_badges(errata: list[dict]) -> str:
    counts: dict[str, int] = {}
    for e in errata:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return "".join(
        _errata_badge(kind, f"{counts[kind]} {_ERRATA_KIND_LABELS[kind]}")
        for kind in ("security", "bugfix", "enhancement", "other")
        if counts.get(kind)
    )


_NOTE_CARD_META = {
    "enhancement": ("✨", "New Features & Enhancements"),
    "security": ("🔒", "Security Fixes"),
    "bugfix": ("🔧", "Bug Fixes"),
    "other": ("ℹ️", "Notes"),
}


def _render_highlight_cards(errata: list[dict]) -> str:
    """whatsnew-style colored cards built from erratum description bullets."""
    cards = []
    for kind, (emoji, label) in _NOTE_CARD_META.items():
        seen: set[str] = set()
        items: list[str] = []
        for e in errata:
            if e["kind"] != kind:
                continue
            for item in e.get("items", []):
                if item not in seen:
                    seen.add(item)
                    items.append(item)
        if not items:
            continue
        lis = "".join(f"<li>{_html.escape(i)}</li>" for i in items)
        cards.append(
            f'<details class="note-card note-card--{kind}" open>'
            f'<summary><span class="note-card__emoji">{emoji}</span>'
            f'<span class="note-card__title">{label}</span>'
            f'{_errata_badge(kind, str(len(items)))}'
            f'</summary>'
            f'<ul class="note-card__items">{lis}</ul>'
            f'</details>'
        )
    return "".join(cards)


def _render_zstream_body(errata: list[dict]) -> str:
    return _render_highlight_cards(errata) + _render_errata_rows(errata)


def _render_features_card(features: list[dict] | None, minor: str) -> str:
    """Minor-level '✨ New Features & Enhancements' card from the release-notes source."""
    if not features:
        return ""
    total = sum(len(g["items"]) for g in features)
    sections = []
    for group in features:
        # Plain titles only — per RELEASE_NOTE_TEMPLATE.md the sole link is
        # the minor header's "release notes".
        lis = "".join(
            f'<li><b>{_html.escape(item["t"])}</b>'
            + (f' — {_html.escape(item["d"])}' if item["d"] else "")
            + '</li>'
            for item in group["items"]
        )
        area_heading = (
            f'<h4 class="features-card__area">{_html.escape(group["area"])}</h4>'
            if group["area"] != "General" else ""
        )
        sections.append(f'{area_heading}<ul class="note-card__items">{lis}</ul>')
    return (
        f'<details class="note-card note-card--enhancement features-card">'
        f'<summary><span class="note-card__emoji">✨</span>'
        f'<span class="note-card__title">What\'s new in {_html.escape(minor)}</span>'
        f'{_errata_badge("enhancement", f"{total} features")}'
        f'<span class="features-card__src">from release notes</span>'
        f'</summary>'
        f'<div class="features-card__body">{"".join(sections)}</div>'
        f'</details>'
    )


_BC_HOME_ICON = (
    '<svg class="bc-home-icon" width="12" height="12" viewBox="0 0 576 512" '
    'fill="currentColor" aria-hidden="true">'
    '<path d="M280.37 148.26L96 300.11V464a16 16 0 0 0 16 16l112.06-.29a16 16 0 0 0 '
    '15.92-16V368a16 16 0 0 1 16-16h64a16 16 0 0 1 16 16v95.64a16 16 0 0 0 16 '
    '16.05L464 480a16 16 0 0 0 16-16V300L295.67 148.26a12.19 12.19 0 0 0-15.3 0zM571.6 '
    '251.47L488 182.56V44.05a12 12 0 0 0-12-12h-56a12 12 0 0 0-12 12v72.61L318.47 '
    '43a48 48 0 0 0-61 0L4.34 251.47a12 12 0 0 0-1.6 16.9l25.5 31A12 12 0 0 0 45.15 '
    '301l235.22-193.74a12.19 12.19 0 0 1 15.3 0L530.9 301a12 12 0 0 0 16.9-1.6l25.5-31a12 '
    '12 0 0 0-1.7-16.93z"/></svg>'
)

_BC_DIVIDER = (
    '<span class="pf-v6-c-breadcrumb__item-divider">'
    '<svg width="7" height="10" viewBox="0 0 256 512" fill="currentColor" aria-hidden="true">'
    '<path d="M224.3 273l-136 136c-9.4 9.4-24.6 9.4-33.9 0l-22.6-22.6c-9.4-9.4-9.4-24.6 '
    '0-33.9l96.4-96.4-96.4-96.4c-9.4-9.4-9.4-24.6 0-33.9L54.3 103c9.4-9.4 24.6-9.4 33.9 '
    '0l136 136c9.5 9.4 9.5 24.6.1 34z"/></svg></span>'
)


def _breadcrumb(items: list[tuple[str, str]]) -> str:
    """PatternFly v6 breadcrumb. items = (label_html, href); last item is current page."""
    lis = []
    for i, (label, href) in enumerate(items):
        divider = _BC_DIVIDER if i else ""
        if i == len(items) - 1:
            lis.append(
                f'<li class="pf-v6-c-breadcrumb__item">{divider}'
                f'<span class="pf-v6-c-breadcrumb__link pf-m-current" aria-current="page">{label}</span></li>'
            )
        else:
            lis.append(
                f'<li class="pf-v6-c-breadcrumb__item">{divider}'
                f'<a class="pf-v6-c-breadcrumb__link" href="{href}">{label}</a></li>'
            )
    return (
        '<nav class="pf-v6-c-breadcrumb" aria-label="Breadcrumb">'
        f'<ol class="pf-v6-c-breadcrumb__list" role="list">{"".join(lis)}</ol></nav>'
    )


def _view_toggle(current: str, key: str) -> str:
    """PatternFly v6 toggle group switching between Chart / Details / Timeline."""
    views = (
        ("chart", "Chart", f"lifecycle-{key}.html"),
        ("details", "Details", f"lifecycle-{key}-details.html"),
        ("timeline", "Timeline", f"lifecycle-{key}-timeline.html"),
    )
    items = []
    for view, label, href in views:
        selected = " pf-m-selected" if view == current else ""
        aria = ' aria-current="page"' if view == current else ""
        items.append(
            f'<div class="pf-v6-c-toggle-group__item">'
            f'<a class="pf-v6-c-toggle-group__button{selected}" href="{href}"{aria}>'
            f'<span class="pf-v6-c-toggle-group__text">{label}</span></a></div>'
        )
    return (
        f'<div class="pf-v6-c-toggle-group" role="group" aria-label="View switcher">'
        f'{"".join(items)}</div>'
    )


def _details_topbar(key: str, cfg: dict, data: dict | None, current: str) -> str:
    """Shared header bar (breadcrumb + view switcher) for the details/timeline pages."""
    heading = _chart_display_heading(cfg.get("title", key))
    page_label = "Release details" if current == "details" else "Release timeline"
    crumb = _breadcrumb([
        (f"{_BC_HOME_ICON}All products", "index.html"),
        (f"{_html.escape(heading)} lifecycle", f"lifecycle-{key}.html"),
        (page_label, ""),
    ])
    generated = (
        f'<span class="details-topbar__generated">Data generated {_html.escape(data["generated"])}</span>'
        if data and data.get("generated") else ""
    )
    return (
        f'<div class="details-topbar">{crumb}'
        f'<div class="details-topbar__right">{_view_toggle(current, key)}{generated}</div>'
        f'</div>'
    )


_TIMELINE_JS = """
(function () {
  var sel = document.getElementById('tl-minor');
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.tl-kind'));
  var countEl = document.getElementById('tl-count');
  if (!sel) return;

  function applyFilters(push) {
    var minor = sel.value;
    var kinds = {};
    boxes.forEach(function (b) { kinds[b.value] = b.checked; });
    var shown = 0, total = 0;
    document.querySelectorAll('.timeline-entry').forEach(function (el) {
      total += 1;
      var okMinor = !minor || el.dataset.minor === minor;
      var okKind = el.dataset.kinds.split(' ').some(function (k) { return kinds[k]; });
      var visible = okMinor && okKind;
      el.hidden = !visible;
      if (visible) shown += 1;
      el.querySelectorAll('.errata-row').forEach(function (row) {
        row.hidden = !kinds[row.dataset.kind];
      });
    });
    document.querySelectorAll('.timeline-month').forEach(function (m) {
      m.hidden = m.querySelectorAll('.timeline-entry:not([hidden])').length === 0;
    });
    countEl.textContent = shown === total
      ? total + ' entries'
      : shown + ' of ' + total + ' entries';
    if (push) {
      var off = boxes.filter(function (b) { return !b.checked; })
                     .map(function (b) { return b.value; });
      var p = new URLSearchParams();
      if (minor) p.set('minor', minor);
      if (off.length) p.set('hide', off.join(','));
      var qs = p.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
    }
  }

  sel.addEventListener('change', function () { applyFilters(true); });
  boxes.forEach(function (b) { b.addEventListener('change', function () { applyFilters(true); }); });

  var q = new URLSearchParams(location.search);
  var qm = q.get('minor');
  if (qm) sel.value = qm;
  var hide = (q.get('hide') || '').split(',');
  boxes.forEach(function (b) { if (hide.indexOf(b.value) >= 0) b.checked = false; });
  applyFilters(false);
})();
"""

_TIMELINE_DOT_ORDER = ("security", "bugfix", "enhancement", "other")


def render_timeline_html(data: dict | None, key: str, cfg: dict, notice_html: str = "") -> str:
    heading = _chart_display_heading(cfg.get("title", key))
    page_title = f"{heading} Release Timeline"
    topbar = _details_topbar(key, cfg, data, current="timeline")

    if not data or not data.get("minors"):
        return _page_wrap(page_title, f"{topbar}\n{notice_html}")

    entries = []  # (minor, sort_date, sort_ver, z_or_none, erratum_or_none)
    minors_seen = []
    for minor in data["minors"]:
        minors_seen.append(minor["minor"])
        for z in minor["zstreams"]:
            entries.append((minor["minor"], z["date"], z["version"], z, None))
        for e in minor["unversioned"]:
            # products without x.y.z-versioned erratas (AAP, OSP…) still get a
            # timeline: each advisory is its own dated entry
            entries.append((minor["minor"], e["date"], "", None, e))
    entries.sort(key=lambda t: (t[1], t[2]), reverse=True)

    months: list[tuple[str, list[str]]] = []  # (label, entry_html list) newest first
    current_month = None
    for minor_ver, date_str, _ver, z, erratum in entries:
        if z is not None:
            kinds_present = []
            for e in z["errata"]:
                if e["kind"] not in kinds_present:
                    kinds_present.append(e["kind"])
            label_html = f'<code class="timeline-entry__ver">{_html.escape(z["version"])}</code>'
            badges = _zstream_count_badges(z["errata"])
            body = _render_zstream_body(z["errata"])
        else:
            kinds_present = [erratum["kind"]]
            label_html = (
                f'<code class="timeline-entry__ver">{_html.escape(minor_ver)}</code>'
                f'<span class="timeline-entry__syn">{_html.escape(_trunc(erratum["synopsis"], 110))}</span>'
            )
            badges = _zstream_count_badges([erratum])
            body = _render_zstream_body([erratum])
        dot_kind = next((k for k in _TIMELINE_DOT_ORDER if k in kinds_present), "other")
        month_key = date_str[:7] if date_str else "unknown"
        if month_key != current_month:
            if month_key == "unknown":
                label = "Undated"
            else:
                y, m = month_key.split("-")
                label = f"{calendar.month_name[int(m)]} {y}"
            months.append((label, []))
            current_month = month_key
        entry_html = (
            f'<details class="timeline-entry" data-minor="{_html.escape(minor_ver)}" '
            f'data-kinds="{" ".join(kinds_present)}">'
            f'<summary>'
            f'<span class="timeline-dot timeline-dot--{dot_kind}"></span>'
            f'{label_html}'
            f'<span class="timeline-entry__date">{_html.escape(date_str)}</span>'
            f'<span class="zstream-block__badges">{badges}</span>'
            f'</summary>'
            f'<div class="timeline-entry__body">{body}</div>'
            f'</details>'
        )
        months[-1][1].append(entry_html)

    month_sections = "".join(
        f'<section class="timeline-month">'
        f'<h3 class="timeline-month__label">{_html.escape(label)}</h3>'
        f'{"".join(items)}'
        f'</section>'
        for label, items in months
    )

    kind_boxes = "".join(
        f'<label class="tl-filter__kind"><input type="checkbox" class="tl-kind" value="{kind}" checked>'
        f'{_errata_badge(kind, _ERRATA_KIND_LABELS[kind])}</label>'
        for kind in _TIMELINE_DOT_ORDER
    )
    minor_options = "".join(
        f'<option value="{_html.escape(m)}">{_html.escape(m)}</option>' for m in minors_seen
    )
    filter_bar = (
        '<div class="delta-bar">'
        '<span class="delta-bar__label">Filter:</span>'
        f'<label>Minor <select id="tl-minor" class="delta-select">'
        f'<option value="">all</option>{minor_options}</select></label>'
        f'{kind_boxes}'
        '<span class="delta-summary" id="tl-count"></span>'
        '<p class="delta-bar__hint">Z-stream releases and advisories newest first, grouped by month.</p>'
        '</div>'
    )

    today_html = (
        f'<div class="timeline-today">┆ Today ({date.today().isoformat()})</div>'
    )
    body = (
        f'{topbar}\n{notice_html}\n{filter_bar}\n'
        f'<div class="timeline">{today_html}{month_sections}</div>\n'
        f'<script>{_TIMELINE_JS}</script>'
    )
    return _page_wrap(page_title, body)


def _minor_meta(minor: dict, adv_total: int) -> str:
    parts = []
    if minor["zstreams"] or minor["unversioned"]:
        parts.append(f'{len(minor["zstreams"])} z-streams')
        parts.append(f"{adv_total} advisories")
    if minor.get("features"):
        parts.append(f'{sum(len(g["items"]) for g in minor["features"])} features')
    return " · ".join(parts)


def render_details_html(data: dict | None, key: str, cfg: dict, notice_html: str = "") -> str:
    heading = _chart_display_heading(cfg.get("title", key))
    page_title = f"{heading} Release Details"

    topbar = _details_topbar(key, cfg, data, current="details")

    if not data or not data.get("minors"):
        body = f"{topbar}\n{notice_html}"
        return _page_wrap(page_title, body)

    index_entries = []
    minor_sections = []
    for i, minor in enumerate(data["minors"]):
        zblocks = []
        adv_total = 0
        for z in minor["zstreams"]:
            counts = {"security": 0, "bugfix": 0, "enhancement": 0, "other": 0}
            for e in z["errata"]:
                counts[e["kind"]] = counts.get(e["kind"], 0) + 1
            adv_total += len(z["errata"])
            index_entries.append({
                "v": z["version"], "m": minor["minor"], "d": z["date"],
                "sec": counts["security"], "bug": counts["bugfix"],
                "enh": counts["enhancement"], "oth": counts["other"],
            })
            zblocks.append(
                f'<details class="zstream-block" data-zver="{_html.escape(z["version"])}">'
                f'<summary>'
                f'<code class="zstream-block__ver">{_html.escape(z["version"])}</code>'
                f'<span class="zstream-block__date">{_html.escape(z["date"])}</span>'
                f'<span class="zstream-block__badges">{_zstream_count_badges(z["errata"])}</span>'
                f'</summary>'
                f'<div class="zstream-block__errata">{_render_zstream_body(z["errata"])}</div>'
                f'</details>'
            )
        unversioned_html = ""
        if minor.get("unversioned"):
            adv_total += len(minor["unversioned"])
            unversioned_html = (
                f'<details class="zstream-block unversioned-block">'
                f'<summary>'
                f'<span class="zstream-block__ver zstream-block__ver--other">Other {_html.escape(minor["minor"])} advisories</span>'
                f'<span class="zstream-block__badges">{_zstream_count_badges(minor["unversioned"])}</span>'
                f'</summary>'
                f'<div class="zstream-block__errata">{_render_zstream_body(minor["unversioned"])}</div>'
                f'</details>'
            )
        rn_url = minor.get("release_notes_url", "")
        rn_link = _chip_link(
            rn_url, "Release notes", "external", external=True,
            extra_cls="card-chip--rn minor-block__rn", title="Release notes on docs.redhat.com",
            onclick="event.stopPropagation()",
        )
        minor_sections.append(
            f'<details class="minor-block" data-minor="{_html.escape(minor["minor"])}"{" open" if i == 0 else ""}>'
            f'<summary>'
            f'<span class="minor-block__title">{_html.escape(minor["minor"])}</span>'
            f'<span class="minor-block__meta">{_minor_meta(minor, adv_total)}</span>'
            f'{rn_link}'
            f'</summary>'
            f'<div class="minor-block__body">'
            f'{_render_features_card(minor.get("features"), minor["minor"])}'
            f'{"".join(zblocks)}{unversioned_html}</div>'
            f'</details>'
        )

    delta_bar = (
        '<div class="delta-bar">'
        '<span class="delta-bar__label">Delta between versions:</span>'
        '<label>From <select id="delta-from" class="delta-select"></select></label>'
        '<span class="delta-bar__arrow">→</span>'
        '<label>To <select id="delta-to" class="delta-select"></select></label>'
        '<button type="button" class="pf-v6-c-button pf-m-secondary pf-m-small" id="delta-reset" hidden>Reset</button>'
        '<span class="delta-summary" id="delta-summary" hidden></span>'
        '<p class="delta-bar__hint">Shows every z-stream release and advisory after From up to and including To.</p>'
        '</div>'
    )

    if index_entries:
        index_json = json.dumps(index_entries, separators=(",", ":"))
        script_html = (
            f'\n<script type="application/json" id="details-index">{index_json}</script>\n'
            f'<script>{_DETAILS_JS}</script>'
        )
    else:
        delta_bar = ""  # feature-only product (no versioned errata): no delta filter
        script_html = ""
    body = (
        f'{topbar}\n{notice_html}\n{delta_bar}\n'
        f'<div class="details-minors">{"".join(minor_sections)}</div>'
        f'{script_html}'
    )
    return _page_wrap(page_title, body)


def _generate_details_page(out_dir: Path, key: str, cfg: dict, versions: list[dict]) -> None:
    out_html = (out_dir / f"lifecycle-{key}-details.html").resolve()
    out_json = (out_dir / f"lifecycle-{key}-details.json").resolve()
    data = build_details_data(key, cfg, versions)
    notice = ""
    if data is not None:
        out_json.write_text(json.dumps(data, indent=1), encoding="utf-8")
    else:
        data = _load_cached_details(out_dir, key)
        if data is not None:
            notice = (
                '<div class="details-notice">⚠ Live errata refresh failed at build time — showing '
                f'cached data from {_html.escape(str(data.get("generated", "an earlier run")))}.</div>'
            )
        else:
            notice = (
                '<div class="details-notice">⚠ Errata data could not be fetched and no cached data '
                'is available yet. Lifecycle charts are unaffected — this page will fill in on the '
                'next successful build.</div>'
            )
    out_html.write_text(render_details_html(data, key, cfg, notice_html=notice), encoding="utf-8")
    print(f"HTML: {out_html}  (details)")
    out_timeline = (out_dir / f"lifecycle-{key}-timeline.html").resolve()
    out_timeline.write_text(render_timeline_html(data, key, cfg, notice_html=notice), encoding="utf-8")
    print(f"HTML: {out_timeline}  (timeline)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Red Hat product lifecycle Gantt charts as HTML + PNG")
    ap.add_argument("-o", "--output", default=None,
                    help="Output HTML file (default: lifecycle-{product}.html; all: lifecycle.html + index.html)")
    ap.add_argument("--product", default="ocp", choices=[*PRODUCT_CONFIGS.keys(), "all"],
                    help="Product to chart: ocp, rhel, aap, rhoai, ceph, or all (default: ocp)")
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
    ap.add_argument("--output-dir", dest="output_dir", default=".",
                    help="Output directory (default: current dir; CI uses docs/)")
    ap.add_argument("--validate-phases", action="store_true",
                    help="Audit phase_map coverage against the Red Hat API and exit")
    ap.add_argument("--skip-details", dest="skip_details", action="store_true",
                    help="Skip errata Details pages (faster test runs, no details links)")
    args = ap.parse_args()

    if args.skip_details:
        for _cfg in PRODUCT_CONFIGS.values():
            _cfg.pop("details_url", None)

    if args.validate_phases:
        sys.exit(1 if validate_phases() else 0)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)

    static_src = Path(__file__).parent / "static"
    if static_src.is_dir():
        static_dst = out_dir / "static"
        if static_dst.exists():
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)
    else:
        print(f"Warning: {static_src} not found — skipping static asset copy.", file=sys.stderr)

    if args.product == "all":
        product_list, operators_data, middleware_data = _fetch_all(args)
        page_title = args.title or "Red Hat Product Lifecycle"
        combined = render_combined_html(product_list, title=page_title,
                                        operators_data=operators_data,
                                        middleware_data=middleware_data)
        lifecycle_out = (out_dir / "lifecycle.html").resolve()
        index_out = (out_dir / "index.html").resolve()
        lifecycle_out.write_text(combined, encoding="utf-8")
        index_out.write_text(combined, encoding="utf-8")
        print(f"HTML: {lifecycle_out}  (all products)")
        print(f"HTML: {index_out}  (GitHub Pages index)")
        if args.png:
            svg_combined = (out_dir / "lifecycle.svg").resolve()
            png_combined = (out_dir / "lifecycle.png").resolve()
            svg_list = [(lbl, _svg_versions(vers, args.include_eol)) for lbl, vers, _ in product_list]
            svg_combined.write_text(render_combined_svg(svg_list, args.width), encoding="utf-8")
            print(f"SVG:  {svg_combined}  (combined)")
            ok = export_png(svg_combined, png_combined)
            if ok:
                print(f"PNG:  {png_combined}  (combined)")
        for cfg_key, (label, versions, pcfg) in zip(PRODUCT_CONFIGS.keys(), product_list):
            out = (out_dir / f"lifecycle-{cfg_key}.html").resolve()
            minor_data = _rhel_minor_data(versions) if pcfg.get("has_minors") else None
            html = render_html(versions, label, minor_data=minor_data,
                               page_url=pcfg.get("page_url", ""), info_html=pcfg.get("info_html", ""),
                               details_url=pcfg.get("details_url", ""))
            out.write_text(html, encoding="utf-8")
            print(f"HTML: {out}  ({len(versions)} versions)")
            if pcfg.get("details") and not args.skip_details:
                _generate_details_page(out_dir, cfg_key, pcfg, versions)
        if middleware_data:
            mw_out = (out_dir / "lifecycle-middleware.html").resolve()
            mw_combined = render_combined_html([], title="Red Hat Middleware Lifecycle",
                                               middleware_data=middleware_data)
            mw_out.write_text(mw_combined, encoding="utf-8")
            print(f"HTML: {mw_out}  (middleware)")
            if args.png:
                svg_out = out.with_suffix(".svg")
                png_out = out.with_suffix(".png")
                svg_out.write_text(render_svg(_svg_versions(versions, args.include_eol), label, args.width), encoding="utf-8")
                print(f"SVG:  {svg_out}")
                ok = export_png(svg_out, png_out)
                if ok:
                    print(f"PNG:  {png_out}")
        about_out = (out_dir / "lifecycle-about.html").resolve()
        _generate_lifecycle_about(about_out)
        print(f"HTML: {about_out}  (lifecycle guide)")
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
