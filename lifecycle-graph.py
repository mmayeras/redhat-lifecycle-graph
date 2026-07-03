#!/usr/bin/env python3
"""Red Hat product lifecycle Gantt chart generator — standalone, no dependencies."""

import argparse
import json
import re
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

_RHOAI_FALLBACK: dict[str, dict] = {
    "2.19": {"ga": "2025-04-16", "fs_end": "2025-11-17"},
    "2.20": {"ga": "2025-05-14", "fs_end": "2025-06-19"},
    "2.21": {"ga": "2025-06-17", "fs_end": "2025-12-17"},
    "2.22": {"ga": "2025-07-21", "fs_end": "2026-02-16"},
    "2.23": {"ga": "2025-08-14", "fs_end": "2025-09-18"},
    "2.24": {"ga": "2025-10-07", "fs_end": "2025-10-23"},
    "2.25": {"ga": "2025-10-23", "fs_end": "2026-05-25", "eus1_end": "2027-04-26"},
    "3.0":  {"ga": "2025-11-13", "fs_end": "2026-01-15"},
    "3.2":  {"ga": "2026-01-22", "fs_end": "2026-03-05"},
    "3.3":  {"ga": "2026-03-05", "fs_end": "2026-10-05"},
    "3.4":  {"ga": "2026-05-14", "fs_end": "2026-11-16"},
}

_PIPELINES_FALLBACK: dict[str, dict] = {
    "1.15": {"ga": "2024-06-21", "fs_end": "2024-11-09", "mnt_end": "2026-10-31"},
    "1.16": {"ga": "2024-10-09", "fs_end": "2025-01-12", "mnt_end": "2025-03-17"},
    "1.17": {"ga": "2024-12-12", "fs_end": "2025-04-17", "mnt_end": "2025-07-15"},
    "1.18": {"ga": "2025-03-17", "fs_end": "2025-08-15", "mnt_end": "2025-09-25"},
    "1.19": {"ga": "2025-07-15", "fs_end": "2025-10-25", "mnt_end": "2026-01-22"},
    "1.20": {"ga": "2025-09-25", "fs_end": "2026-02-22", "mnt_end": "2026-04-27"},
    "1.21": {"ga": "2026-01-22", "fs_end": "2026-05-27", "mnt_end": "2026-08-01"},
    "1.22": {"ga": "2026-04-27", "fs_end": "2026-08-27", "mnt_end": "2026-11-01"},
}

_GITOPS_FALLBACK: dict[str, dict] = {
    "1.14": {"ga": "2024-09-19", "fs_end": "2025-01-12", "mnt_end": "2025-08-07"},
    "1.15": {"ga": "2024-12-12", "fs_end": "2025-05-31", "mnt_end": "2025-09-25"},
    "1.16": {"ga": "2025-03-31", "fs_end": "2025-09-07", "mnt_end": "2025-12-18"},
    "1.17": {"ga": "2025-08-07", "fs_end": "2025-10-25", "mnt_end": "2026-03-25"},
    "1.18": {"ga": "2025-09-25", "fs_end": "2026-01-18", "mnt_end": "2026-06-24"},
    "1.19": {"ga": "2025-12-18", "fs_end": "2026-04-25"},
    "1.20": {"ga": "2026-03-25", "fs_end": "2026-07-24"},
    "1.21": {"ga": "2026-06-24", "fs_end": "2026-10-25"},
}

_SERVICE_MESH_FALLBACK: dict[str, dict] = {
    "3.0": {"ga": "2024-05-15", "fs_end": "2024-11-15", "mnt_end": "2026-05-15"},
    "3.1": {"ga": "2025-08-06", "fs_end": "2026-01-31", "mnt_end": "2027-07-27"},
    "3.2": {"ga": "2025-11-14", "fs_end": "2026-05-14", "mnt_end": "2027-08-25"},
    "3.3": {"ga": "2026-03-19", "fs_end": "2026-09-21", "mnt_end": "2028-02-25"},
}

_VIRT_FALLBACK: dict[str, dict] = {
    "4.15": {"ga": "2024-02-27", "fs_end": "2024-09-27", "mnt_end": "2025-08-27"},
    "4.16": {"ga": "2024-06-27", "fs_end": "2025-01-01", "mnt_end": "2025-12-27",
             "eus1_end": "2026-06-27", "eus2_end": "2027-06-27"},
    "4.17": {"ga": "2024-10-01", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "4.18": {"ga": "2025-02-25", "fs_end": "2025-09-17", "mnt_end": "2026-08-25",
             "eus1_end": "2027-02-25", "eus2_end": "2028-02-25"},
    "4.19": {"ga": "2025-06-17", "fs_end": "2026-01-21", "mnt_end": "2026-12-17"},
    "4.20": {"ga": "2025-10-21", "fs_end": "2026-05-03", "mnt_end": "2027-04-21",
             "eus1_end": "2027-10-21", "eus2_end": "2028-10-21"},
    "4.21": {"ga": "2026-02-12", "fs_end": "2026-09-09", "mnt_end": "2027-08-03"},
    "4.22": {"ga": "2026-06-16", "fs_end": "2026-12-31", "mnt_end": "2027-12-31",
             "eus1_end": "2028-06-30", "eus2_end": "2029-06-30"},
}

_ODF_FALLBACK: dict[str, dict] = {
    "4.16": {"ga": "2024-06-27", "fs_end": "2025-01-01", "mnt_end": "2025-12-27",
             "eus1_end": "2026-06-27", "eus2_end": "2027-06-27"},
    "4.17": {"ga": "2024-10-01", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "4.18": {"ga": "2025-02-25", "fs_end": "2025-09-17", "mnt_end": "2026-08-25",
             "eus1_end": "2027-02-25", "eus2_end": "2028-02-25"},
    "4.19": {"ga": "2025-07-28", "fs_end": "2026-02-18", "mnt_end": "2026-12-17"},
    "4.20": {"ga": "2025-11-18", "fs_end": "2026-06-09", "mnt_end": "2027-04-21",
             "eus1_end": "2027-10-21", "eus2_end": "2028-11-21"},
    "4.21": {"ga": "2026-03-09", "fs_end": "2027-01-09", "mnt_end": "2027-08-23"},
}

_LOGGING_FALLBACK: dict[str, dict] = {
    "6.1": {"ga": "2024-10-01", "fs_end": "2025-05-01", "mnt_end": "2025-11-13"},
    "6.2": {"ga": "2025-03-01", "fs_end": "2025-08-16", "mnt_end": "2026-01-30"},
    "6.3": {"ga": "2025-07-16", "fs_end": "2025-12-13", "mnt_end": "2026-04-01"},
    "6.4": {"ga": "2025-11-13", "fs_end": "2026-05-01"},
    "6.5": {"ga": "2026-04-01", "fs_end": "2026-10-01"},
}

_OADP_FALLBACK: dict[str, dict] = {
    "1.3": {"ga": "2024-03-01", "fs_end": "2024-10-21", "mnt_end": "2025-06-17",
            "eus1_end": "2025-12-27", "eus2_end": "2026-12-27"},
    "1.4": {"ga": "2024-07-10", "fs_end": "2025-06-17", "mnt_end": "2026-06-09",
            "eus1_end": "2027-02-25", "eus2_end": "2028-02-25"},
    "1.5": {"ga": "2025-06-17", "fs_end": "2026-05-03", "mnt_end": "2027-04-21",
            "eus1_end": "2027-10-21", "eus2_end": "2028-10-21"},
    "1.6": {"ga": "2026-06-09", "fs_end": "2026-12-31", "mnt_end": "2027-12-31",
            "eus1_end": "2028-06-30", "eus2_end": "2029-06-30"},
}

_BUILDS_FALLBACK: dict[str, dict] = {
    "1.4": {"ga": "2025-04-17", "fs_end": "2025-08-17", "mnt_end": "2025-10-10"},
    "1.5": {"ga": "2025-07-17", "fs_end": "2025-11-10", "mnt_end": "2026-02-10"},
    "1.6": {"ga": "2025-10-10", "fs_end": "2026-03-10", "mnt_end": "2026-05-18"},
    "1.7": {"ga": "2026-02-10", "fs_end": "2026-06-18", "mnt_end": "2026-09-01"},
    "1.8": {"ga": "2026-05-18", "fs_end": "2026-09-18", "mnt_end": "2026-12-18"},
}

_DR_HUB_FALLBACK: dict[str, dict] = {
    "4.16": {"ga": "2024-06-27", "fs_end": "2025-01-01", "mnt_end": "2025-12-27",
             "eus1_end": "2026-06-27", "eus2_end": "2027-06-27"},
    "4.17": {"ga": "2024-10-01", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "4.18": {"ga": "2025-03-11", "fs_end": "2025-10-28", "mnt_end": "2026-08-25",
             "eus1_end": "2027-02-25", "eus2_end": "2028-02-25"},
    "4.19": {"ga": "2025-07-28", "fs_end": "2026-02-18", "mnt_end": "2026-12-17"},
    "4.20": {"ga": "2025-11-18", "fs_end": "2026-06-09", "mnt_end": "2027-04-21",
             "eus1_end": "2027-10-21", "eus2_end": "2028-11-21"},
}

_CERTMGR_FALLBACK: dict[str, dict] = {
    "1.14": {"ga": "2024-06-01", "fs_end": "2024-09-30", "mnt_end": "2024-12-31"},
    "1.15": {"ga": "2024-09-01", "fs_end": "2024-12-31", "mnt_end": "2025-03-31"},
    "1.16": {"ga": "2024-12-01", "fs_end": "2025-03-31", "mnt_end": "2025-06-30"},
    "1.17": {"ga": "2025-03-01", "fs_end": "2025-06-30", "mnt_end": "2025-09-30"},
    "1.18": {"ga": "2025-06-01", "fs_end": "2025-09-30", "mnt_end": "2025-12-31"},
    "1.19": {"ga": "2026-04-20", "fs_end": "2026-11-20", "mnt_end": "2027-05-20", "eus1_end": "2028-02-25"},
}

# OCP-aligned operators share identical lifecycle dates with OCP itself.
_OCP_ALIGNED_OP_FALLBACK = _OCP_FALLBACK

_WINC_FALLBACK: dict[str, dict] = {
    "10.17": {"ga": "2024-10-30", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "10.18": {"ga": "2025-03-20", "fs_end": "2025-10-17", "mnt_end": "2026-08-25"},
    "10.19": {"ga": "2025-07-17", "mnt_end": "2026-12-17"},
    "10.20": {"ga": "2025-10-22", "mnt_end": "2027-04-21"},
    "10.21": {"ga": "2026-02-03", "mnt_end": "2027-08-03"},
}

_RHACM_FALLBACK: dict[str, dict] = {
    "2.12": {"ga": "2025-04-02", "fs_end": "2026-01-01", "mnt_end": "2026-10-02"},
    "2.13": {"ga": "2025-06-18", "fs_end": "2026-04-24", "mnt_end": "2026-12-24"},
    "2.14": {"ga": "2025-08-01", "fs_end": "2026-10-02", "mnt_end": "2027-02-24"},
    "2.15": {"ga": "2025-12-03", "fs_end": "2027-01-08", "mnt_end": "2027-06-01",
             "eus1_end": "2027-11-12", "eus2_end": "2028-11-13"},
    "2.16": {"ga": "2026-03-10", "fs_end": "2027-04-09", "mnt_end": "2027-09-10"},
    "2.17": {"ga": "2026-06-18", "fs_end": "2026-12-31", "mnt_end": "2027-12-31",
             "eus1_end": "2028-06-30", "eus2_end": "2029-06-30"},
}

_RHACS_FALLBACK: dict[str, dict] = {
    "4.7":  {"ga": "2025-01-29", "fs_end": "2025-07-29", "mnt_end": "2025-11-29"},
    "4.8":  {"ga": "2025-07-09", "fs_end": "2026-01-09", "mnt_end": "2026-05-09"},
    "4.9":  {"ga": "2025-10-30", "fs_end": "2026-04-30", "mnt_end": "2026-08-31"},
    "4.10": {"ga": "2026-03-03", "fs_end": "2026-09-03", "mnt_end": "2027-01-04"},
    "4.11": {"ga": "2026-06-15", "fs_end": "2026-12-15", "mnt_end": "2027-04-15"},
}

_SERVERLESS_FALLBACK: dict[str, dict] = {
    "1.34": {"ga": "2024-10-10", "fs_end": "2025-02-22", "mnt_end": "2025-05-22"},
    "1.35": {"ga": "2025-01-22", "fs_end": "2025-08-17", "mnt_end": "2025-11-17"},
    "1.36": {"ga": "2025-07-17", "fs_end": "2025-12-24", "mnt_end": "2026-03-24"},
    "1.37": {"ga": "2025-11-24", "fs_end": "2026-05-24", "mnt_end": "2026-08-24"},
}

_MTV_FALLBACK: dict[str, dict] = {
    "2.7":  {"ga": "2024-09-22", "fs_end": "2025-07-10", "mnt_end": "2025-12-04"},
    "2.8":  {"ga": "2025-03-31", "fs_end": "2025-11-04", "mnt_end": "2026-03-23"},
    "2.9":  {"ga": "2025-07-10", "fs_end": "2026-02-23", "mnt_end": "2026-07-16"},
    "2.10": {"ga": "2025-11-04", "fs_end": "2026-06-16", "mnt_end": "2026-11-01"},
    "2.11": {"ga": "2026-02-23", "fs_end": "2026-10-01", "mnt_end": "2027-02-01"},
    "2.12": {"ga": "2026-06-16", "fs_end": "2027-01-15"},
}

_LOKI_FALLBACK: dict[str, dict] = {
    "6.1": {"ga": "2024-10-01", "fs_end": "2025-05-01", "mnt_end": "2025-11-13"},
    "6.2": {"ga": "2025-03-12", "fs_end": "2025-08-16", "mnt_end": "2026-08-25",
            "eus1_end": "2028-10-21"},
    "6.3": {"ga": "2025-07-16", "fs_end": "2025-12-13", "mnt_end": "2026-04-01"},
    "6.4": {"ga": "2025-11-13", "fs_end": "2026-05-01"},
    "6.5": {"ga": "2026-04-01", "fs_end": "2026-10-01"},
}

_KMM_FALLBACK: dict[str, dict] = {
    "2.3": {"ga": "2025-03-06", "fs_end": "2025-08-06", "mnt_end": "2026-03-06"},
    "2.4": {"ga": "2025-06-26", "fs_end": "2025-11-26", "mnt_end": "2026-06-26"},
    "2.5": {"ga": "2025-12-08", "fs_end": "2026-05-03", "mnt_end": "2027-04-21"},
    "2.6": {"ga": "2026-03-24", "fs_end": "2026-06-24", "mnt_end": "2026-10-24"},
}

_RHDH_FALLBACK: dict[str, dict] = {
    "1.7":  {"ga": "2025-08-20", "fs_end": "2025-11-11", "mnt_end": "2026-03-04"},
    "1.8":  {"ga": "2025-11-11", "fs_end": "2026-03-04", "mnt_end": "2026-06-10"},
    "1.9":  {"ga": "2026-03-04", "fs_end": "2026-06-10", "mnt_end": "2026-10-10"},
    "1.10": {"ga": "2026-06-10", "fs_end": "2026-10-10", "mnt_end": "2027-02-11"},
}

_MTC_FALLBACK: dict[str, dict] = {
    "1.7": {"ga": "2022-03-01", "fs_end": "2024-07-01", "mnt_end": "2025-07-01"},
    "1.8": {"ga": "2023-10-02", "fs_end": "2026-07-31", "mnt_end": "2026-12-31"},
}

_WEBTERMINAL_FALLBACK: dict[str, dict] = {
    "1.11": {"ga": "2024-08-13", "fs_end": "2025-01-01", "mnt_end": "2025-12-27"},
    "1.12": {"ga": "2024-10-01", "fs_end": "2025-05-25", "mnt_end": "2026-04-01"},
    "1.13": {"ga": "2025-06-02", "fs_end": "2025-09-17", "mnt_end": "2026-08-25"},
    "1.14": {"ga": "2025-09-25", "fs_end": "2026-01-21", "mnt_end": "2026-12-17"},
    "1.15": {"ga": "2025-11-27", "fs_end": "2026-05-03", "mnt_end": "2027-04-21"},
}

_MCE_FALLBACK: dict[str, dict] = {
    "2.7":  {"ga": "2024-11-05", "fs_end": "2026-01-06", "mnt_end": "2026-06-02"},
    "2.8":  {"ga": "2025-03-12", "fs_end": "2026-04-17", "mnt_end": "2026-09-18"},
    "2.9":  {"ga": "2025-08-01", "fs_end": "2026-10-02", "mnt_end": "2027-02-24"},
    "2.10": {"ga": "2025-12-03", "fs_end": "2027-01-08", "mnt_end": "2027-06-01"},
    "2.11": {"ga": "2026-03-10", "fs_end": "2027-04-09", "mnt_end": "2027-09-10"},
    "2.17": {"ga": "2026-06-18", "fs_end": "2026-12-31", "mnt_end": "2027-12-31"},
}

_KIALI_FALLBACK: dict[str, dict] = {
    "2.4":  {"ga": "2025-03-12", "fs_end": "2025-09-12", "mnt_end": "2026-10-31"},
    "2.11": {"ga": "2025-08-06", "fs_end": "2026-01-31", "mnt_end": "2027-07-27"},
    "2.17": {"ga": "2025-11-14", "fs_end": "2026-05-14", "mnt_end": "2027-08-25"},
    "2.22": {"ga": "2026-03-19", "fs_end": "2026-09-21", "mnt_end": "2028-02-25"},
}

_GATEKEEPER_FALLBACK: dict[str, dict] = {
    "3.17": {"ga": "2024-11-19", "fs_end": "2025-08-01", "mnt_end": "2025-12-04"},
    "3.18": {"ga": "2025-03-20", "fs_end": "2025-12-04", "mnt_end": "2026-04-23"},
    "3.19": {"ga": "2025-08-01", "fs_end": "2026-04-23", "mnt_end": "2026-08-01"},
    "3.20": {"ga": "2025-12-04", "fs_end": "2026-08-01", "mnt_end": "2026-12-01"},
    "3.21": {"ga": "2026-04-23", "fs_end": "2026-12-01", "mnt_end": "2027-04-01"},
}

_SUBMARINER_FALLBACK: dict[str, dict] = {
    "0.18": {"ga": "2024-07-18", "fs_end": "2025-08-15", "mnt_end": "2026-01-16"},
    "0.19": {"ga": "2024-11-06", "fs_end": "2025-12-08", "mnt_end": "2026-06-09"},
    "0.20": {"ga": "2025-03-19", "fs_end": "2026-04-17", "mnt_end": "2026-09-11"},
    "0.22": {"ga": "2025-12-04", "fs_end": "2027-01-05", "mnt_end": "2027-09-10"},
}

_QUAY_FALLBACK: dict[str, dict] = {
    "3.13": {"ga": "2025-01-22", "fs_end": "2025-07-07", "mnt_end": "2026-04-01"},
    "3.14": {"ga": "2025-04-02", "fs_end": "2025-10-07", "mnt_end": "2026-08-25"},
    "3.15": {"ga": "2025-07-07", "fs_end": "2026-03-18", "mnt_end": "2026-12-17"},
    "3.16": {"ga": "2025-12-18", "fs_end": "2026-06-24", "mnt_end": "2027-04-21"},
    "3.17": {"ga": "2026-03-24", "fs_end": "2026-10-01", "mnt_end": "2027-08-03"},
}

_ODF_MULTICLUSTER_FALLBACK: dict[str, dict] = {
    "4.16": {"ga": "2024-06-27", "fs_end": "2025-01-01", "mnt_end": "2025-12-27"},
    "4.17": {"ga": "2024-10-30", "fs_end": "2025-06-11", "mnt_end": "2026-04-01"},
    "4.18": {"ga": "2025-03-11", "fs_end": "2025-10-28", "mnt_end": "2026-08-25"},
    "4.19": {"ga": "2025-07-28", "fs_end": "2026-02-18", "mnt_end": "2026-12-17"},
    "4.20": {"ga": "2025-11-18", "fs_end": "2026-06-09", "mnt_end": "2027-04-21"},
}

_DR_CLUSTER_FALLBACK: dict[str, dict] = _ODF_MULTICLUSTER_FALLBACK

_CONNECTIVITY_LINK_FALLBACK: dict[str, dict] = {
    "1.1": {"ga": "2025-05-26", "fs_end": "2025-10-01", "mnt_end": "2026-06-11"},
    "1.2": {"ga": "2025-10-01", "fs_end": "2026-02-26", "mnt_end": "2026-10-01"},
    "1.3": {"ga": "2026-02-26", "fs_end": "2026-06-11", "mnt_end": "2026-10-01"},
    "1.4": {"ga": "2026-06-11", "fs_end": "2026-10-01", "mnt_end": "2027-02-01"},
}

_GLOBAL_HUB_FALLBACK: dict[str, dict] = {
    "1.4": {"ga": "2025-03-20", "fs_end": "2026-04-17"},
    "1.5": {"ga": "2025-07-21", "fs_end": "2026-10-02"},
    "1.6": {"ga": "2025-12-04", "fs_end": "2027-02-12"},
    "1.7": {"ga": "2026-03-10", "fs_end": "2027-04-09"},
}

# Ceph lifecycle: single support tier mapped to fs_end (same label/colors as Full Support).
_CEPH_FALLBACK: dict[str, dict] = {
    "4": {"ga": "2020-01-31", "fs_end": "2023-03-31",
          "els_end": "2025-04-30", "els2_end": "2027-04-30"},
    "5": {"ga": "2021-08-31", "fs_end": "2024-08-31", "els_end": "2027-07-31"},
    "6": {"ga": "2023-03-21", "fs_end": "2026-03-20", "els_end": "2028-03-20"},
    "7": {"ga": "2023-12-13", "fs_end": "2026-12-12", "els_end": "2029-08-31"},
    "8": {"ga": "2024-11-25", "fs_end": "2027-11-24", "els_end": "2029-11-24"},
    "9": {"ga": "2026-01-29", "fs_end": "2029-01-28", "els_end": "2031-01-28"},
}

_SATELLITE_FALLBACK: dict[str, dict] = {
    "6.10": {"ga": "2021-11-16", "fs_end": "2022-06-30", "mnt_end": "2023-05-31"},
    "6.11": {"ga": "2022-07-05", "fs_end": "2022-11-30", "mnt_end": "2024-01-31"},
    "6.12": {"ga": "2022-11-16", "fs_end": "2023-05-31", "mnt_end": "2024-05-31"},
    "6.13": {"ga": "2023-05-03", "fs_end": "2023-11-30", "mnt_end": "2024-11-30"},
    "6.14": {"ga": "2023-11-08", "fs_end": "2024-05-31", "mnt_end": "2025-05-30"},
    "6.15": {"ga": "2024-04-23", "fs_end": "2024-11-30", "mnt_end": "2025-11-30"},
    "6.16": {"ga": "2024-11-05", "fs_end": "2025-05-31", "mnt_end": "2026-05-31",
             "eus1_end": "2027-05-31"},
    "6.17": {"ga": "2025-05-06", "fs_end": "2025-11-30", "mnt_end": "2026-11-28"},
    "6.18": {"ga": "2025-11-04", "fs_end": "2026-05-06", "mnt_end": "2027-05-01"},
    "6.19": {"ga": "2026-05-06", "fs_end": "2026-11-01", "mnt_end": "2027-11-01",
             "eus1_end": "2028-11-01"},
}

# ── Date parsing ─────────────────────────────────────────────────────────────

_MONTHS: dict[str, str] = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
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
    return None


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
    "rhoai": {
        "api_name": "Red Hat OpenShift AI Self-Managed",
        "title":    "RHOAI Lifecycle",
        "phase_map": {
            "General availability":           "ga",
            "Full support":                   "fs_end",
            "Extended update support":        "eus1_end",
            "Extended update support Term 2": "eus2_end",
        },
        "fallback":   _RHOAI_FALLBACK,
        "parse_ver":  _parse_rhoai,
        "min_filter": lambda v: _parse_rhoai(v) >= (2, 19) and "." in v.rstrip("*"),
        "eus_check":  None,
    },
    "ceph": {
        "api_name": "Red Hat Ceph Storage",
        "title":    "Ceph Lifecycle",
        "phase_map": {
            "General availability":                              "ga",
            "End of Life":                                       "fs_end",
            "Extended life cycle support (ELS) add-on":         "els_end",
            "Extended life cycle support (ELS) Term 2 add-on":  "els2_end",
        },
        "fallback":        _CEPH_FALLBACK,
        "parse_ver":       lambda v: int(v) if v.isdigit() else 0,
        "name_transform":  lambda n: n.replace("Red Hat Ceph Storage ", "").replace("Inktank Ceph Enterprise ", "").strip(),
        "min_filter":      lambda v: v.isdigit() and int(v) >= 4,
        "eus_check":       None,
    },
    "satellite": {
        "api_name": "Red Hat Satellite Server",
        "title":    "Satellite Lifecycle",
        "phase_map": {
            "General availability":    "ga",
            "Full support":            "fs_end",
            "Maintenance support":     "mnt_end",
            "Extended update support": "eus1_end",
        },
        "fallback":   _SATELLITE_FALLBACK,
        "parse_ver":  _parse_xy,
        "min_filter": lambda v: (
            "." in v and v.startswith("6.")
            and len(v.split(".")) == 2
            and all(p.isdigit() for p in v.split(".")[:2])
            and _parse_xy(v) >= (6, 10)
        ),
        "eus_check":  None,
    },
}

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

OPERATOR_CONFIGS: dict[str, dict] = {
    "pipelines": {
        "api_name": "Red Hat OpenShift Pipelines", "title": "OpenShift Pipelines",
        "phase_map": _OP_PHASE_MAP, "fallback": _PIPELINES_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 14) and "." in v,
    },
    "gitops": {
        "api_name": "Red Hat OpenShift GitOps", "title": "OpenShift GitOps",
        "phase_map": _OP_PHASE_MAP, "fallback": _GITOPS_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 12) and "." in v,
    },
    "service-mesh": {
        "api_name": "Red Hat OpenShift Service Mesh", "title": "OpenShift Service Mesh",
        "phase_map": _OP_PHASE_MAP, "fallback": _SERVICE_MESH_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 4) and "." in v,
    },
    "virtualization": {
        "api_name": "Red Hat OpenShift Virtualization", "title": "OpenShift Virtualization",
        "phase_map": _OP_PHASE_MAP, "fallback": _VIRT_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "odf": {
        "api_name": "Red Hat OpenShift Data Foundation", "title": "OpenShift Data Foundation",
        "phase_map": _ODF_PHASE_MAP, "fallback": _ODF_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "logging": {
        "api_name": "logging for Red Hat OpenShift", "title": "Logging for OpenShift",
        "phase_map": _OP_PHASE_MAP, "fallback": _LOGGING_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (6, 0) and "." in v,
    },
    "oadp": {
        "api_name": "OpenShift APIs for Data Protection", "title": "OADP",
        "phase_map": _OP_PHASE_MAP, "fallback": _OADP_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 3) and "." in v,
    },
    "builds": {
        "api_name": "builds for Red Hat OpenShift", "title": "Builds for OpenShift",
        "phase_map": _OP_PHASE_MAP, "fallback": _BUILDS_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 3) and "." in v,
    },
    "dr-hub": {
        "api_name": "Openshift DR Hub Operator", "title": "OpenShift DR Hub",
        "phase_map": _OP_PHASE_MAP, "fallback": _DR_HUB_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "cert-manager": {
        "api_name": "cert-manager operator for Red Hat OpenShift", "title": "cert-manager",
        "phase_map": _OP_PHASE_MAP, "fallback": _CERTMGR_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 12) and "." in v,
    },
    # ── Additional operators ──────────────────────────────────────────────────
    "rhacm": {
        "api_name": "Red Hat Advanced Cluster Management for Kubernetes", "title": "RHACM",
        "phase_map": _OP_PHASE_MAP, "fallback": _RHACM_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 10) and "." in v,
    },
    "rhacs": {
        "api_name": "Red Hat Advanced Cluster Security for Kubernetes", "title": "RHACS",
        "phase_map": _OP_PHASE_MAP, "fallback": _RHACS_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (4, 5) and "." in v,
    },
    "serverless": {
        "api_name": "Red Hat OpenShift Serverless", "title": "OpenShift Serverless",
        "phase_map": _OP_PHASE_MAP, "fallback": _SERVERLESS_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 30) and "." in v,
    },
    "mtv": {
        "api_name": "migration toolkit for virtualization", "title": "Migration Toolkit for Virtualization",
        "phase_map": _OP_PHASE_MAP, "fallback": _MTV_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 6) and "." in v,
    },
    "loki": {
        "api_name": "Loki operator", "title": "Loki Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _LOKI_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (6, 0) and "." in v,
    },
    "kmm": {
        "api_name": "Kernel Module Management operator for Red Hat OpenShift (Hub)", "title": "KMM",
        "phase_map": _OP_PHASE_MAP, "fallback": _KMM_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 1) and "." in v,
    },
    "rhdh": {
        "api_name": "Red Hat Developer Hub", "title": "Red Hat Developer Hub",
        "phase_map": _OP_PHASE_MAP, "fallback": _RHDH_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 5) and "." in v,
    },
    "sriov": {
        "api_name": "SR-IOV network operator", "title": "SR-IOV Network Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "nfd": {
        "api_name": "node feature discovery operator", "title": "Node Feature Discovery",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "nmstate": {
        "api_name": "Kubernetes NMState Operator", "title": "Kubernetes NMState",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "lso": {
        "api_name": "local storage operator", "title": "Local Storage Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "metallb": {
        "api_name": "MetalLB operator", "title": "MetalLB Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "vpa": {
        "api_name": "vertical pod autoscaler operator", "title": "Vertical Pod Autoscaler",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "numaresources": {
        "api_name": "numaresources-operator", "title": "NUMAresources Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "winc": {
        "api_name": "Red Hat OpenShift support for Windows Containers", "title": "Windows Containers",
        "phase_map": _OP_PHASE_MAP, "fallback": _WINC_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (10, 14) and "." in v,
    },
    "mtc": {
        "api_name": "migration toolkit for containers", "title": "Migration Toolkit for Containers",
        "phase_map": _OP_PHASE_MAP, "fallback": _MTC_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 7) and "." in v,
    },
    "web-terminal": {
        "api_name": "OpenShift Web Terminal", "title": "Web Terminal",
        "phase_map": _OP_PHASE_MAP, "fallback": _WEBTERMINAL_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 10) and "." in v,
    },
    "mce": {
        "api_name": "Multicluster Engine for Kubernetes", "title": "Multicluster Engine",
        "phase_map": _OP_PHASE_MAP, "fallback": _MCE_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 7) and "." in v,
    },
    "kiali": {
        "api_name": "Kiali", "title": "Kiali",
        "phase_map": _OP_PHASE_MAP, "fallback": _KIALI_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (2, 4) and "." in v,
    },
    "gatekeeper": {
        "api_name": "Gatekeeper operator", "title": "Gatekeeper",
        "phase_map": _OP_PHASE_MAP, "fallback": _GATEKEEPER_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (3, 17) and "." in v,
    },
    "submariner": {
        "api_name": "Submariner", "title": "Submariner",
        "phase_map": _OP_PHASE_MAP, "fallback": _SUBMARINER_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (0, 17) and "." in v,
    },
    "ptp": {
        "api_name": "PTP Operator", "title": "PTP Operator",
        "phase_map": _OP_PHASE_MAP, "fallback": _OCP_ALIGNED_OP_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": lambda v: int(v.split(".")[1]) % 2 == 0,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 14,
    },
    "quay": {
        "api_name": "Red Hat Quay", "title": "Red Hat Quay",
        "phase_map": _OP_PHASE_MAP, "fallback": _QUAY_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (3, 12) and "." in v,
    },
    "odf-multicluster": {
        "api_name": "ODF Multicluster Orchestrator", "title": "ODF Multicluster Orchestrator",
        "phase_map": _OP_PHASE_MAP, "fallback": _ODF_MULTICLUSTER_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": None,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 16,
    },
    "dr-cluster": {
        "api_name": "Openshift DR Cluster Operator", "title": "OpenShift DR Cluster",
        "phase_map": _OP_PHASE_MAP, "fallback": _DR_CLUSTER_FALLBACK,
        "parse_ver": _parse_ocp, "eus_check": None,
        "min_filter": lambda v: "." in v and v.startswith("4.") and v.split(".")[1].isdigit() and int(v.split(".")[1]) >= 16,
    },
    "global-hub": {
        "api_name": "multicluster global hub", "title": "Multicluster Global Hub",
        "phase_map": _OP_PHASE_MAP, "fallback": _GLOBAL_HUB_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 4) and "." in v,
    },
    "connectivity-link": {
        "api_name": "Red Hat Connectivity Link", "title": "Red Hat Connectivity Link",
        "phase_map": _OP_PHASE_MAP, "fallback": _CONNECTIVITY_LINK_FALLBACK,
        "parse_ver": _parse_xy, "eus_check": None,
        "min_filter": lambda v: _parse_xy(v) >= (1, 1) and "." in v,
    },
}

# ── Phase palette (PatternFly-aligned) ───────────────────────────────────────
PHASES: dict[str, dict] = {
    "sup":  {"label": "Support",       "bg": "#bde5b8", "border": "#1e4f18", "text": "#1e4f18"},
    "fs":   {"label": "Full Support",  "bg": "#bde5b8", "border": "#1e4f18", "text": "#1e4f18"},
    "mnt":  {"label": "Maintenance",   "bg": "#f9e0a2", "border": "#795600", "text": "#795600"},
    "mnt2": {"label": "Maintenance 2", "bg": "#f4b678", "border": "#8f4700", "text": "#8f4700"},
    "eus1": {"label": "EUS-1",         "bg": "#bee1f4", "border": "#004080", "text": "#004080"},
    "eus2": {"label": "EUS-2",         "bg": "#e7d4ff", "border": "#40199a", "text": "#40199a"},
    "eus3": {"label": "EUS-3",         "bg": "#f2c4ff", "border": "#6a0080", "text": "#6a0080"},
    "els":  {"label": "ELS",           "bg": "#f5b8b4", "border": "#c9190b", "text": "#a30000"},
    "els2": {"label": "ELS-2",         "bg": "#e88080", "border": "#8b0000", "text": "#fff"},
    "elp":  {"label": "Ext. Life",     "bg": "#e4e4e4", "border": "#6a6e73", "text": "#3c3f42"},
}

# Chronological order — segments built and phase status detected in this order.
# sup/els/els2 are Ceph-specific; eus3 is ODF-specific. Other products skip these keys.
PHASE_KEYS = [
    ("sup",  "sup_end"),   # Ceph: single-tier support (no fs/mnt split)
    ("fs",   "fs_end"),
    ("mnt",  "mnt_end"),
    ("mnt2", "mnt2_end"),
    ("eus1", "eus1_end"),
    ("eus2", "eus2_end"),
    ("eus3", "eus3_end"),  # ODF: Extended Update Support Term 3
    ("els",  "els_end"),
    ("els2", "els2_end"),  # Ceph: ELS Term 2 add-on
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
    name_transform = cfg.get("name_transform")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lifecycle-graph/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        product = data["data"][0]
        result: dict[str, dict] = {}
        for ver_data in product["versions"]:
            raw = ver_data["name"]
            name = name_transform(raw) if name_transform else raw
            if not name_transform and " " in raw:
                continue
            if not min_filter(name):
                continue
            dates: dict[str, str] = {}
            for phase in ver_data["phases"]:
                key = phase_map.get(phase["name"])
                if key:
                    parsed = _parse_api_date(phase.get("end_date", ""))
                    if parsed:
                        dates[key] = parsed
            if name in fallback:
                for _k in ("fs_end", "mnt_end", "eus1_end", "eus2_end", "sup_end", "els_end"):
                    if _k not in dates and _k in fallback[name]:
                        dates[_k] = fallback[name][_k]
            if "ga" in dates and any(k in dates for k in ("fs_end", "mnt_end", "sup_end")):
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
        for key, field in PHASE_KEYS:
            val = lc.get(field)
            if not val:
                continue
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
  :root {
    --card-px: 24px;
    --label-w: 130px;
    --days-col: 48px;
    --chart-top: 64px;
    --row-h: 48px;
    --bar-h: 34px;
    --ver-font: 15px;
    /* theme – light defaults */
    --bg-page: #f5f5f5;
    --bg-card: #fff;
    --bg-card-header: #f0f0f0;
    --bg-controls: #f8f8f8;
    --bg-row-alt: #fafafa;
    --border-base: #d2d2d2;
    --border-controls: #e8e8e8;
    --text-primary: #151515;
    --text-secondary: #6a6e73;
    --text-controls: #3c3f42;
    --link-color: #0066cc;
    --grid-line: #d2d2d2;
    --today-label-bg: rgba(255,255,255,0.9);
    --today-label-border: rgba(163,0,0,0.25);
    --input-bg: #fff;
    --red: #a30000;
  }
  [data-theme="dark"] {
    --bg-page: #111;
    --bg-card: #1e1e1e;
    --bg-card-header: #252525;
    --bg-controls: #1a1a1a;
    --bg-row-alt: #191919;
    --border-base: #383838;
    --border-controls: #383838;
    --text-primary: #e8e8e8;
    --text-secondary: #8a8e93;
    --text-controls: #c8cacc;
    --link-color: #5b9bd5;
    --grid-line: #333;
    --today-label-bg: rgba(30,30,30,0.95);
    --today-label-border: rgba(220,80,80,0.5);
    --input-bg: #1e1e1e;
    --red: #e05050;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg-page: #111;
      --bg-card: #1e1e1e;
      --bg-card-header: #252525;
      --bg-controls: #1a1a1a;
      --bg-row-alt: #191919;
      --border-base: #383838;
      --border-controls: #383838;
      --text-primary: #e8e8e8;
      --text-secondary: #8a8e93;
      --text-controls: #c8cacc;
      --link-color: #5b9bd5;
      --grid-line: #333;
      --today-label-bg: rgba(30,30,30,0.95);
      --today-label-border: rgba(220,80,80,0.5);
      --input-bg: #1e1e1e;
      --red: #e05050;
    }
  }
  @media (max-width: 600px) {
    :root {
      --card-px: 8px;
      --label-w: 56px;
      --days-col: 32px;
      --chart-top: 44px;
      --row-h: 36px;
      --bar-h: 24px;
      --ver-font: 10px;
    }
    .page-header {
      grid-template-columns: 1fr auto;
      grid-template-rows: auto;
      gap: 4px;
      padding: 8px 12px;
    }
    .header-left { display: none; }
    .header-right { grid-column: 2; grid-row: 1; }
    .page-nav {
      grid-column: 1; grid-row: 1;
      flex-wrap: nowrap; overflow-x: auto;
      justify-content: flex-start;
      scrollbar-width: none;
    }
    .page-nav::-webkit-scrollbar { display: none; }
    .page-nav a { flex-shrink: 0; font-size: 11px; padding: 3px 8px; }
    a.gh-contribute { font-size: 11px; padding: 3px 8px; }
    .chart-inner { min-width: var(--mobile-min-width, 480px); }
    .chart-row-bar span { display: none; }
    .card-header-legend { flex-wrap: wrap; gap: 4px; }
    .page-content { padding: 12px 8px 32px; gap: 14px; }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Red Hat Text","Red Hat Display","Open Sans",system-ui,sans-serif;
    background: var(--bg-page);
    color: var(--text-primary);
    padding: 0;
    margin: 0;
  }
  .page-header {
    background: #151515;
    color: #fff;
    padding: 14px 20px;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 8px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .header-left { display: flex; align-items: center; justify-content: flex-start; }
  .header-right { display: flex; align-items: center; justify-content: flex-end; }
  .header-title { font-size: 13px; font-weight: 700; color: #e0e0e0; letter-spacing: -0.01em; white-space: nowrap; }
  .page-nav { display: flex; gap: 6px; flex-wrap: wrap; justify-content: center; }
  .page-nav a {
    color: #e0e0e0;
    text-decoration: none;
    font-size: 12px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid #444;
  }
  .page-nav a:hover { background: #333; color: #fff; }
  a.gh-contribute {
    display: inline-flex; align-items: center; gap: 5px;
    color: #fff; background: #1a7f37; border: 1px solid #1a7f37;
    text-decoration: none; font-size: 12px; font-weight: 600;
    padding: 3px 10px; border-radius: 4px;
  }
  a.gh-contribute:visited { color: #fff; }
  a.gh-contribute:hover { background: #24a148; border-color: #24a148; color: #fff; }
  .page-content {
    max-width: 1148px;
    margin: 0 auto;
    padding: 20px 12px 48px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  @media (min-width: 700px) {
    .page-header { padding: 14px 32px; }
    .header-title { font-size: 15px; }
    .page-nav a { font-size: 13px; padding: 4px 12px; }
    .page-content { padding: 28px 24px 48px; gap: 28px; }
  }
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border-base);
    border-radius: 8px;
    width: 100%;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    overflow: hidden;
  }
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px var(--card-px);
    background: var(--bg-card-header);
    border-bottom: 1px solid var(--border-base);
    flex-wrap: wrap;
    gap: 8px;
  }
  .card-title {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
  .legend { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .legend span { font-size: 11px !important; }
  .chart-area {
    background: var(--bg-card);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .chart-inner {
    position: relative;
    padding: var(--chart-top) var(--card-px) 20px;
    min-width: 100%;
  }
  .chart-grid {
    position: absolute;
    top: var(--chart-top);
    bottom: 20px;
    left: calc(var(--card-px) + var(--label-w));
    right: calc(var(--card-px) + var(--days-col) + 8px);
    pointer-events: none;
  }
  .chart-rows {
    position: relative; z-index: 1;
    display: flex; flex-direction: column; gap: 6px;
  }
  .chart-rows > div:nth-child(even) { background: var(--bg-row-alt); }
  .chart-row {
    display: flex;
    align-items: center;
    height: var(--row-h);
  }
  .chart-row-label {
    width: var(--label-w);
    flex-shrink: 0;
    padding-right: 8px;
    overflow: hidden;
    display: flex;
    align-items: center;
  }
  .chart-row-bar {
    flex: 1;
    position: relative;
    height: var(--bar-h);
  }
  .chart-row-days {
    width: var(--days-col);
    flex-shrink: 0;
    text-align: right;
    padding-left: 4px;
  }
  .eol-warn { position: relative; cursor: pointer; display: inline-block; }
  .eol-tip {
    display: none;
    position: absolute;
    right: 0; top: calc(100% + 4px);
    background: #151515; color: #fff;
    font-size: 11px; font-weight: 400; line-height: 1.4;
    padding: 7px 10px; border-radius: 5px;
    white-space: normal; width: 280px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.35);
    z-index: 300;
  }
  .eol-tip::before {
    content: ""; position: absolute;
    right: 8px; top: -5px;
    border: 5px solid transparent;
    border-top: 0; border-bottom-color: #151515;
  }
  .eol-warn:hover .eol-tip,
  .eol-warn.pinned .eol-tip { display: block; }
  #phase-tooltip {
    display: none; position: fixed; z-index: 400; pointer-events: none;
    background: #151515; color: #fff;
    font-size: 11px; line-height: 1.6;
    padding: 6px 10px; border-radius: 5px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.35);
    white-space: nowrap;
  }
  .ver-code {
    font-family: "Red Hat Mono","Courier New",monospace;
    font-size: var(--ver-font);
    color: var(--text-primary);
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .card-controls {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px var(--card-px);
    background: var(--bg-controls);
    border-bottom: 1px solid var(--border-controls);
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--text-controls);
  }
  .card-controls label { display: flex; align-items: center; gap: 5px; cursor: pointer; white-space: nowrap; }
  .card-controls select {
    font-size: 12px;
    padding: 2px 4px;
    border: 1px solid var(--border-base);
    border-radius: 3px;
    background: var(--input-bg);
    color: var(--text-primary);
    font-family: inherit;
    max-width: 90px;
  }
  .card-controls .ctrl-label { color: var(--text-secondary); margin-right: -4px; }
  .footer {
    padding: 8px var(--card-px) 12px;
    font-size: 11px; color: var(--text-secondary);
    border-top: 1px solid var(--border-base); background: var(--bg-card-header);
    word-break: break-word;
  }
  .footer a { color: var(--link-color); text-decoration: none; }
  .footer a:hover { text-decoration: underline; }
  .section-heading {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    padding-bottom: 10px;
    border-bottom: 2px solid var(--border-base);
    margin-bottom: 4px;
  }
  .op-section { display: flex; flex-direction: column; gap: 8px; }
  .op-details {
    background: var(--bg-card);
    border: 1px solid var(--border-base);
    border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    overflow: hidden;
  }
  .op-summary {
    cursor: pointer;
    padding: 10px var(--card-px);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    background: var(--bg-card-header);
    list-style: none;
    user-select: none;
  }
  .op-summary::-webkit-details-marker { display: none; }
  .op-summary::marker { display: none; }
  .op-details[open] > .op-summary { border-bottom: 1px solid var(--border-base); }
  .op-name {
    font-size: 13px;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .op-name::before { content: "▶"; font-size: 9px; color: var(--text-secondary); transition: transform 0.15s; }
  .op-details[open] .op-name::before { transform: rotate(90deg); }
  .op-meta { font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
  .theme-btn {
    background: transparent;
    border: 1px solid #444;
    color: #e0e0e0;
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 14px;
    line-height: 1.4;
    cursor: pointer;
  }
  .theme-btn:hover { background: #333; }
  .op-details .card { border: none; border-radius: 0; box-shadow: none; }
"""


def _render_card(versions: list[dict], chart_label: str, anchor: str = "",
                 show_footer: bool = True, show_controls: bool = False) -> str:
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
        f'<div style="position:absolute;left:{today_pct:.3f}%;top:0;bottom:0;'
        f'border-left:1.5px dashed var(--red);opacity:0.7;z-index:2"></div>'
        f'<div style="position:absolute;left:{today_pct:.3f}%;top:calc(-1 * var(--chart-top) + 12px);'
        f'font-size:11px;color:var(--red);transform:translateX(-50%);'
        f'font-weight:700;white-space:nowrap;background:var(--today-label-bg);'
        f'padding:1px 4px;border-radius:2px;border:1px solid var(--today-label-border)">Today</div>'
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

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_html = " ".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--text-primary)">'
        f'<span style="display:inline-block;width:14px;height:12px;border-radius:2px;'
        f'background:{PHASES[k]["bg"]};border:1.5px solid {PHASES[k]["border"]}"></span>'
        f'{PHASES[k]["label"]}</span>'
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
            f'</div>'
        )
    else:
        controls_html = ""

    return f"""<div class="card"{anchor_attr}>
  <div class="card-header">
    <span class="card-title">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
      </svg>
      {chart_label}
    </span>
    <div class="legend">
      {legend_html}
      <span style="font-size:11px;color:var(--red);opacity:0.85">┆ Today ({today.isoformat()})</span>
    </div>
  </div>
  {controls_html}
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


def _render_operator_section(operators_data: list[tuple[str, list[dict]]]) -> str:
    if not operators_data:
        return ""
    items = []
    for label, versions in operators_data:
        if not versions:
            continue
        n_active = sum(1 for v in versions if not v["is_eol"])
        meta = f"{len(versions)} version{'s' if len(versions) != 1 else ''}"
        if n_active:
            meta += f" · {n_active} active"
        card = _render_card(versions, label, show_footer=False, show_controls=True)
        items.append(
            f'<details class="op-details">'
            f'<summary class="op-summary">'
            f'<span class="op-name">{label}</span>'
            f'<span class="op-meta">{meta}</span>'
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
        f'<div class="section-heading">OpenShift Operators</div>'
        f'{search}'
        f'<div class="op-section">'
        + "\n".join(items)
        + "</div></div>"
    )


def _page_wrap(title: str, body: str, nav_links: str = "", contribute_html: str = "") -> str:
    nav_html = f'<nav class="page-nav">{nav_links}</nav>' if nav_links else ""
    left_html = f'<span class="header-title">{title}</span>'
    _theme_btn = '<button id="theme-toggle" class="theme-btn" title="Toggle dark/light mode"></button>'
    _right_content = contribute_html if contribute_html else ""
    right_html = f'<div style="display:flex;align-items:center;gap:8px">{_theme_btn}{_right_content}</div>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
{_PAGE_CSS}
</style>
<script>
(function(){{
  var s=localStorage.getItem('lifecycle-theme');
  var d=s?s==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme',d?'dark':'light');
}})();
</script>
</head>
<body>
<header class="page-header">
  <div class="header-left">{left_html}</div>
  {nav_html}
  <div class="header-right">{right_html}</div>
</header>
<div class="page-content">
{body}
</div>
<script>
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
    row.style.display = (i >= fromIdx && i <= toIdx && (showEol || !eol)) ? '' : 'none';
  }});
}}
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.card').forEach(function(card) {{ filterCard(card); }});
}});
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
(function() {{
  var root = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  var stored = localStorage.getItem('lifecycle-theme');
  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  var isDark = stored !== null ? stored === 'dark' : prefersDark;
  function apply(dark) {{
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    btn.textContent = dark ? '☀' : '🌙';
    btn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
  }}
  apply(isDark);
  btn.addEventListener('click', function() {{
    isDark = !isDark;
    localStorage.setItem('lifecycle-theme', isDark ? 'dark' : 'light');
    apply(isDark);
  }});
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {{
    if (localStorage.getItem('lifecycle-theme') === null) {{ isDark = e.matches; apply(isDark); }}
  }});
}})();
</script>
</body>
</html>"""


def render_html(versions: list[dict], chart_label: str, show_footer: bool = True) -> str:
    card = _render_card(versions, chart_label, show_footer=show_footer, show_controls=True)
    return _page_wrap(chart_label, card)


def render_combined_html(
    product_list: list[tuple[str, list[dict]]],
    title: str = "Red Hat Product Lifecycle",
    operators_data: list[tuple[str, list[dict]]] | None = None,
) -> str:
    nav_links = "".join(
        f'<a href="#{label.lower().replace(" ", "-")}">{label}</a>'
        for label, _ in product_list
    )
    if operators_data:
        nav_links += '<a href="#operators">Operators</a>'
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
                     show_footer=False, show_controls=True)
        for label, versions in product_list
    )
    operators_section = _render_operator_section(operators_data or [])
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
    body = cards + ("\n" + operators_section if operators_section else "") + "\n" + footer
    return _page_wrap(title, body, nav_links, contribute_html)


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


def _fetch_all(
    args: argparse.Namespace,
) -> tuple[list[tuple[str, list[dict]]], list[tuple[str, list[dict]]]]:
    """Return (product_list, operators_data) with ALL versions (incl. EOL) for HTML.

    Callers must filter by is_eol themselves when generating SVG/PNG.
    """
    product_list: list[tuple[str, list[dict]]] = []
    for product in ["ocp", "rhel", "aap", "rhoai", "ceph", "satellite"]:
        cfg = PRODUCT_CONFIGS[product]
        lifecycle = fetch_lifecycle(cfg)
        label = cfg["title"]
        versions = build_versions(
            lifecycle, cfg,
            versions_filter=args.versions,
            from_version=args.from_version,
            to_version=args.to_version,
            include_eol=True,  # always; HTML controls filter via JS
        )
        if versions:
            product_list.append((label, versions))
        else:
            print(f"No versions matched for {product}.", file=sys.stderr)

    operators_data: list[tuple[str, list[dict]]] = []
    for op_cfg in OPERATOR_CONFIGS.values():
        lifecycle = fetch_lifecycle(op_cfg)
        versions = build_versions(lifecycle, op_cfg, include_eol=True)
        if versions:
            operators_data.append((op_cfg["title"], versions))

    operators_data.sort(key=lambda t: t[0].lower())
    return product_list, operators_data


def _svg_versions(versions: list[dict], include_eol: bool) -> list[dict]:
    """Filter version list for SVG/PNG output (EOL hidden unless explicitly requested)."""
    return versions if include_eol else [v for v in versions if not v["is_eol"]]


def _generate_product(
    product: str,
    out_html: Path,
    args: argparse.Namespace,
) -> None:
    cfg = PRODUCT_CONFIGS[product]
    lifecycle = fetch_lifecycle(cfg)
    chart_label = args.title if args.title else cfg["title"]

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

    html = render_html(versions_html, chart_label)
    out_html.write_text(html, encoding="utf-8")
    print(f"HTML: {out_html}  ({len(versions_html)} versions)")

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


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Red Hat product lifecycle Gantt charts as HTML + PNG")
    ap.add_argument("-o", "--output", default=None,
                    help="Output HTML file (default: lifecycle-{product}.html; all: lifecycle.html + index.html)")
    ap.add_argument("--product", default="ocp", choices=["ocp", "rhel", "aap", "rhoai", "ceph", "satellite", "all"],
                    help="Product to chart: ocp, rhel, aap, rhoai, ceph, satellite, or all (default: ocp)")
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
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)

    if args.product == "all":
        product_list, operators_data = _fetch_all(args)
        page_title = args.title or "Red Hat Product Lifecycle"
        combined = render_combined_html(product_list, title=page_title, operators_data=operators_data)
        lifecycle_out = (out_dir / "lifecycle.html").resolve()
        index_out = (out_dir / "index.html").resolve()
        lifecycle_out.write_text(combined, encoding="utf-8")
        index_out.write_text(combined, encoding="utf-8")
        print(f"HTML: {lifecycle_out}  (all products)")
        print(f"HTML: {index_out}  (GitHub Pages index)")
        if args.png:
            svg_combined = (out_dir / "lifecycle.svg").resolve()
            png_combined = (out_dir / "lifecycle.png").resolve()
            svg_list = [(lbl, _svg_versions(vers, args.include_eol)) for lbl, vers in product_list]
            svg_combined.write_text(render_combined_svg(svg_list, args.width), encoding="utf-8")
            print(f"SVG:  {svg_combined}  (combined)")
            ok = export_png(svg_combined, png_combined)
            if ok:
                print(f"PNG:  {png_combined}  (combined)")
        for cfg_key, (label, versions) in zip(
            ["ocp", "rhel", "aap", "rhoai", "ceph", "satellite"], product_list
        ):
            out = (out_dir / f"lifecycle-{cfg_key}.html").resolve()
            html = render_html(versions, label)
            out.write_text(html, encoding="utf-8")
            print(f"HTML: {out}  ({len(versions)} versions)")
            if args.png:
                svg_out = out.with_suffix(".svg")
                png_out = out.with_suffix(".png")
                svg_out.write_text(render_svg(_svg_versions(versions, args.include_eol), label, args.width), encoding="utf-8")
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
