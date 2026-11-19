"""Offline unit tests for lifecycle-graph.py.

Run with:  python3 -m unittest discover -s tests -v

No network access: everything that fetches (errata search, docs repos, docs
index) is monkeypatched. Importing the module loads lifecycle-config.yaml, so
PyYAML must be installed (same requirement as the build itself).
"""

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "lifecycle_graph", Path(__file__).resolve().parent.parent / "lifecycle-graph.py"
)
lg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lg)


class TestSmallHelpers(unittest.TestCase):
    def test_parse_zstream(self):
        self.assertEqual(lg._parse_zstream("OpenShift Container Platform 4.19.38 bug fix", "4.19"), "4.19.38")
        self.assertIsNone(lg._parse_zstream("OpenShift Container Platform 4.19 GA", "4.19"))
        # anchored to the minor: 4.1 must not match 4.19.x
        self.assertIsNone(lg._parse_zstream("OpenShift Container Platform 4.19.3", "4.1"))
        self.assertEqual(lg._parse_zstream("Satellite 6.17.9 Async Update", "6.17"), "6.17.9")
        self.assertEqual(lg._parse_zstream("Red Hat Ceph Storage 8.1 update", "8"), "8.1")

    def test_advisory_kind(self):
        self.assertEqual(lg._advisory_kind("Security Advisory"), "security")
        self.assertEqual(lg._advisory_kind("Bug Fix Advisory"), "bugfix")
        self.assertEqual(lg._advisory_kind("Product Enhancement Advisory"), "enhancement")
        self.assertEqual(lg._advisory_kind("Whatever"), "other")

    def test_fmt_minor(self):
        self.assertEqual(lg._fmt_minor("{minor}|{minor_dash}|{minor_nodot}|{major}", "4.19"),
                         "4.19|4-19|419|4")
        self.assertEqual(lg._fmt_minor("v{major}", "9.6"), "v9")

    def test_extract_bullets(self):
        text = ("Intro line.\n\n"
                "* first fix (CVE-2026-1)\n"
                "* second fix\n  continued on next line\n\n"
                "Outro.")
        self.assertEqual(lg._extract_bullets(text),
                         ["first fix (CVE-2026-1)", "second fix continued on next line"])
        self.assertEqual(lg._extract_bullets("no bullets here"), [])


class TestAdocInline(unittest.TestCase):
    def test_attribute_resolution(self):
        attrs = lg._parse_adoc_attributes(":a: Alpha\n:b: {a} Beta\n:c: {b} Gamma\n")
        self.assertEqual(attrs["c"], "Alpha Beta Gamma")

    def test_clean_inline(self):
        attrs = {"product-title": "OpenShift Container Platform", "nbsp": " "}
        s = lg._clean_adoc_inline(
            "{product-title} adds link:https://x[a link] and `code` with *bold*", attrs)
        self.assertEqual(s, "OpenShift Container Platform adds a link and code with bold")
        # attr value containing another attr ref resolves on the second pass
        attrs2 = {"rh": "Red{nbsp}Hat", "nbsp": " "}
        self.assertEqual(lg._clean_adoc_inline("{rh} build", attrs2), "Red Hat build")
        # unresolved attrs keep the name, drop the braces
        self.assertEqual(lg._clean_adoc_inline("{unknown-attr} here", {}), "unknown-attr here")


_BOOK_ADOC = """\
== About this release

Intro.

== New features and enhancements

[id="area-auth"]
=== Authentication

==== Feature one
First paragraph of feature one.

Second paragraph is ignored.

==== Feature two (Technology Preview)
Desc two.

=== Networking

==== Feature three
Desc three.

== Notable technical changes

Not parsed.
"""

_MODULE_DEFLIST_ADOC = """\
[id="new-features"]
= New features and enhancements

This release adds improvements:

== API server

Dynamic updates to storage::
+
Storage description here.

== Console

Email links::
+
Console description here.
"""

_FLAT_ADOC = """\
= New features and enhancements

== Chatbot goes GA
The chatbot is now generally available with lots of goodies.

== Self-service portal
Portal description.

== Empty area heading

= Next section
"""

_BULLET_ADOC = """\
== New features and enhancements

* First bullet feature
* Second bullet feature

== Technology Preview

skip
"""


class TestAdocFeatures(unittest.TestCase):
    def test_book_format(self):
        groups = lg._parse_adoc_features(_BOOK_ADOC, {})
        self.assertEqual([g["area"] for g in groups], ["Authentication", "Networking"])
        auth = groups[0]["items"]
        self.assertEqual(auth[0]["t"], "Feature one")
        self.assertEqual(auth[0]["d"], "First paragraph of feature one.")
        self.assertEqual(auth[1]["t"], "Feature two (Technology Preview)")
        self.assertEqual(groups[1]["items"][0]["t"], "Feature three")

    def test_module_definition_lists(self):
        groups = lg._parse_adoc_features(_MODULE_DEFLIST_ADOC, {})
        self.assertEqual([g["area"] for g in groups], ["API server", "Console"])
        self.assertEqual(groups[0]["items"][0]["t"], "Dynamic updates to storage")
        self.assertEqual(groups[0]["items"][0]["d"], "Storage description here.")

    def test_flat_mode_skips_empty_headings(self):
        groups = lg._parse_adoc_features(_FLAT_ADOC, {}, flat=True)
        self.assertEqual(len(groups), 1)
        titles = [i["t"] for i in groups[0]["items"]]
        self.assertEqual(titles, ["Chatbot goes GA", "Self-service portal"])
        self.assertEqual(groups[0]["area"], "General")

    def test_upgrade_sections_are_not_features(self):
        text = ("= New features and enhancements\n\n"
                "== Real feature\nDesc.\n\n"
                "== Upgrade paths\nTable of upgrades.\n\n"
                "== Upgrading from 2.5 to 2.6\nSteps.\n\n"
                "== Migration paths\nMore tables.\n")
        groups = lg._parse_adoc_features(text, {}, flat=True)
        self.assertEqual([i["t"] for i in groups[0]["items"]], ["Real feature"])

    def test_bullet_only_section(self):
        groups = lg._parse_adoc_features(_BULLET_ADOC, {})
        self.assertEqual(len(groups), 1)
        self.assertEqual([i["t"] for i in groups[0]["items"]],
                         ["First bullet feature", "Second bullet feature"])

    def test_bullets_discarded_when_titles_exist(self):
        text = _BOOK_ADOC.replace(
            "[id=\"area-auth\"]", "* stray bullet before areas\n\n[id=\"area-auth\"]")
        groups = lg._parse_adoc_features(text, {})
        self.assertEqual([g["area"] for g in groups], ["Authentication", "Networking"])

    def test_comment_blocks_and_fences_skipped(self):
        text = ("== New features and enhancements\n\n"
                "////\n=== Fake area\n==== Fake feature\nfake\n////\n\n"
                "=== Real\n\n==== Real feature\nreal desc\n\n"
                "----\n==== code fence heading\n----\n")
        groups = lg._parse_adoc_features(text, {})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["items"][0]["t"], "Real feature")


class TestChapterAbstractSplit(unittest.TestCase):
    def test_numbered_split_and_boilerplate(self):
        abstract = ("This part describes new features in Red Hat Enterprise Linux 10.0. "
                    "6.1. Installer and image creation Review new features for installer "
                    "in Red Hat Enterprise Linux 10.0. bootc-image-builder now supports "
                    "advanced partitioning With this enhancement you gain options. "
                    "6.2. Security Review new features for security in RHEL 10.0.")
        items = lg._split_chapter_abstract("New features", abstract)
        titles = [i["t"] for i in items]
        self.assertEqual(titles[0], "Installer and image creation")
        self.assertIn("Security", titles)
        # boilerplate "Review …" sentence stripped from descriptions
        self.assertFalse(items[0]["d"].startswith("Review"))
        # template: no per-item URLs
        self.assertTrue(all("u" not in i for i in items))

    def test_colon_splits_title_from_desc(self):
        abstract = ("Lead. 1.1.1. Key highlights for RHEL installer: The newly created "
                    "users will have administrative privileges by default.")
        items = lg._split_chapter_abstract("Overview", abstract)
        self.assertEqual(items[0]["t"], "Key highlights for RHEL installer")
        self.assertTrue(items[0]["d"].startswith("The newly created users"))

    def test_title_capped_at_word_boundary(self):
        long_title = "word " * 40 + "end."
        items = lg._split_chapter_abstract("C", f"Lead. 2.1. {long_title}")
        self.assertLessEqual(len(items[0]["t"]), 91)
        self.assertTrue(items[0]["t"].endswith("…"))

    def test_fallback_single_item(self):
        items = lg._split_chapter_abstract("Overview", "Just a plain abstract.")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["t"], "Overview")

    def test_noise_titles_dropped(self):
        abstract = ("Lead. 7.1. For information on support scope, see docs. "
                    "7.2. Security Review new TP features. Something real.")
        items = lg._split_chapter_abstract("TP", abstract)
        self.assertEqual([i["t"] for i in items], ["Security"])
        self.assertEqual(items[0]["d"], "Something real.")


def _mk_doc(id_, synopsis, kind="Bug Fix Advisory", severity="", date="2026-01-02T00:00:00Z",
            description=""):
    return {"id": id_, "portal_synopsis": synopsis, "portal_advisory_type": kind,
            "portal_severity": severity, "portal_publication_date": date,
            "view_uri": f"https://access.redhat.com/errata/{id_}",
            "portal_description": description}


class TestBuildDetailsData(unittest.TestCase):
    def setUp(self):
        self._orig_fetch = lg.fetch_errata_for_minor
        self._orig_search = lg.fetch_features_docs_search
        self._orig_release = lg.fetch_release_features
        lg.fetch_features_docs_search = lambda details, minor: None
        lg.fetch_release_features = lambda details, minor: None

    def tearDown(self):
        lg.fetch_errata_for_minor = self._orig_fetch
        lg.fetch_features_docs_search = self._orig_search
        lg.fetch_release_features = self._orig_release

    def test_per_minor_grouping_and_unversioned(self):
        lg.fetch_errata_for_minor = lambda q: [
            _mk_doc("RHSA-1", "Prod 1.2.3 security update", "Security Advisory", "Important",
                    description="Fixes:\n\n* CVE fix one\n"),
            _mk_doc("RHBA-2", "Prod 1.2.3 bug fix update"),
            _mk_doc("RHBA-3", "Prod 1.2 operator metadata"),
        ]
        cfg = {"details": {"errata_query": "Prod {minor}"}, "title": "Prod"}
        data = lg.build_details_data("prod", cfg, [{"version": "1.2"}])
        minor = data["minors"][0]
        self.assertEqual(len(minor["zstreams"]), 1)
        z = minor["zstreams"][0]
        self.assertEqual(z["version"], "1.2.3")
        self.assertEqual(z["date"], "2026-01-02")
        self.assertEqual(len(z["errata"]), 2)
        self.assertEqual(len(minor["unversioned"]), 1)
        sec = [e for e in z["errata"] if e["kind"] == "security"][0]
        self.assertEqual(sec["items"], ["CVE fix one"])

    def test_shared_query_drops_unmatched(self):
        lg.fetch_errata_for_minor = lambda q: [
            _mk_doc("A-1", "RHX 2.5.1 - update"),
            _mk_doc("A-2", "RHX 3.0-ea preview"),
        ]
        cfg = {"details": {"errata_query": "RHX"}, "title": "RHX"}
        data = lg.build_details_data("rhx", cfg, [{"version": "2.5"}])
        minor = data["minors"][0]
        self.assertEqual([z["version"] for z in minor["zstreams"]], ["2.5.1"])
        self.assertEqual(minor["unversioned"], [])

    def test_errata_fetch_failure_is_fatal(self):
        lg.fetch_errata_for_minor = lambda q: None
        cfg = {"details": {"errata_query": "Prod {minor}"}, "title": "Prod"}
        self.assertIsNone(lg.build_details_data("prod", cfg, [{"version": "1.2"}]))

    def test_feature_only_product_without_errata_query(self):
        lg.fetch_features_docs_search = lambda details, minor: [
            {"area": "New features", "items": [{"t": "T", "d": "D"}]}
        ]
        cfg = {"details": {"features_search": "*x*{minor}*"}, "title": "Prod"}
        data = lg.build_details_data("prod", cfg, [{"version": "9.6"}])
        minor = data["minors"][0]
        self.assertEqual(minor["zstreams"], [])
        self.assertEqual(minor["features"][0]["items"][0]["t"], "T")

    def test_rhel_minors_source(self):
        lg.fetch_features_docs_search = lambda details, minor: [
            {"area": "New features", "items": [{"t": "x", "d": ""}]}
        ]
        cfg = {"details": {"minors_from": "rhel_minors",
                           "features_search": "*{minor}*"}, "title": "RHEL"}
        data = lg.build_details_data("rhel", cfg, [{"version": "9"}])
        minors = [m["minor"] for m in data["minors"]]
        self.assertNotIn("9", minors)          # chart majors ignored
        self.assertTrue(any(m.startswith("9.") for m in minors))
        self.assertTrue(any(m.startswith("7.") for m in minors))  # full history
        # newest first
        parsed = [tuple(int(p) for p in m.split(".")) for m in minors]
        self.assertEqual(parsed, sorted(parsed, reverse=True))

    def test_empty_minors_skipped(self):
        # no errata, no features → the minor gets no section at all
        cfg = {"details": {"features_search": "*{minor}*"}, "title": "P"}
        data = lg.build_details_data("p", cfg, [{"version": "1.0"}])
        self.assertEqual(data["minors"], [])

    def test_errata_scope_major_groups_by_major_not_minor(self):
        # RHEL-style: errata aren't tied to one minor, so query per major and
        # attach as an unversioned feed keyed by the bare major number.
        calls = []

        def fake_fetch(query, cap=1000, extra_fq=()):
            calls.append((query, extra_fq))
            if "9" in query:
                return [_mk_doc("RHSA-1", "kernel security update")]
            return []

        lg.fetch_errata_for_minor = fake_fetch
        cfg = {"details": {"errata_query": "Red Hat Enterprise Linux {minor}",
                            "errata_scope": "major"}, "title": "RHEL"}
        data = lg.build_details_data("rhel", cfg, [{"version": "9.4"}, {"version": "9.2"}])
        minors = {m["minor"]: m for m in data["minors"]}
        self.assertIn("9", minors)                        # major bucket present
        self.assertNotIn("9.4", minors)                    # no per-minor errata
        self.assertEqual(minors["9"]["zstreams"], [])      # no fake z-stream parsing
        self.assertEqual(len(minors["9"]["unversioned"]), 1)
        self.assertEqual(data["errata_window_days"], 365)
        self.assertTrue(any("NOW-365DAYS" in fq for _, fqs in calls for fq in fqs))

    def test_extra_minors_extend_coverage(self):
        lg.fetch_errata_for_minor = lambda q: (
            [_mk_doc("A-1", "Prod 1.1.5 update")] if "1.1" in q else []
        )
        cfg = {"details": {"errata_query": "Prod {minor}",
                           "extra_minors": ["1.1"]}, "title": "Prod"}
        data = lg.build_details_data("prod", cfg, [{"version": "1.2"}])
        minors = [m["minor"] for m in data["minors"]]
        self.assertEqual(minors, ["1.1"])  # 1.2 empty → skipped; 1.1 from extras


class TestRendering(unittest.TestCase):
    def _data(self, zstreams=True, features=None):
        minor = {"minor": "1.2", "release_notes_url": "https://rn",
                 "zstreams": [], "unversioned": []}
        if zstreams:
            minor["zstreams"] = [{
                "version": "1.2.3", "date": "2026-01-02",
                "errata": [{"id": "RHSA-1", "synopsis": "Prod 1.2.3 security update",
                            "kind": "security", "severity": "Important",
                            "date": "2026-01-02", "url": "https://e",
                            "items": ["CVE fix one"]}],
            }]
        if features:
            minor["features"] = features
        return {"product": "prod", "title": "Prod", "generated": "2026-01-01T00:00:00Z",
                "minors": [minor]}

    def test_details_page_with_zstreams(self):
        html = lg.render_details_html(self._data(), "prod", {"title": "Prod Lifecycle"})
        self.assertIn("delta-from", html)
        self.assertIn('data-zver="1.2.3"', html)
        self.assertIn("note-card--security", html)
        self.assertIn("CVE fix one", html)
        self.assertIn('id="details-index"', html)

    def test_feature_only_page_has_no_delta(self):
        features = [{"area": "New features", "items": [{"t": "T", "d": "D"}]}]
        html = lg.render_details_html(self._data(zstreams=False, features=features),
                                      "prod", {"title": "Prod Lifecycle"})
        self.assertNotIn("delta-from", html)
        self.assertNotIn('id="details-index"', html)

    def test_features_card_has_no_links(self):
        # RELEASE_NOTE_TEMPLATE.md: plain titles only inside the card
        card = lg._render_features_card(
            [{"area": "Networking", "items": [{"t": "Feature", "d": "Desc"}]}], "1.2")
        self.assertNotIn("<a ", card)
        self.assertIn("<b>Feature</b> — Desc", card)

    def test_trunc_word_boundary(self):
        self.assertEqual(lg._trunc("short", 20), "short")
        out = lg._trunc("alpha beta gamma delta", 16)
        self.assertEqual(out, "alpha beta gamma…")
        self.assertFalse(out[:-1].endswith(" "))

    def test_general_area_heading_hidden(self):
        card = lg._render_features_card(
            [{"area": "General", "items": [{"t": "T", "d": "D"}]}], "1.2")
        self.assertNotIn("features-card__area", card)
        card2 = lg._render_features_card(
            [{"area": "Networking", "items": [{"t": "T", "d": "D"}]}], "1.2")
        self.assertIn(">Networking</h4>", card2)

    def test_timeline_page(self):
        html = lg.render_timeline_html(self._data(), "prod", {"title": "Prod Lifecycle"})
        self.assertIn("timeline-entry", html)
        self.assertIn("January 2026", html)
        self.assertIn("tl-minor", html)

    def test_timeline_includes_unversioned_advisories(self):
        data = self._data(zstreams=False)
        data["minors"][0]["unversioned"] = [{
            "id": "RHBA-9", "synopsis": "Prod 1.2 operator bundle update",
            "kind": "bugfix", "severity": "", "date": "2026-02-03", "url": "https://e",
        }]
        html = lg.render_timeline_html(data, "prod", {"title": "Prod Lifecycle"})
        self.assertIn("timeline-entry", html)
        self.assertIn("operator bundle update", html)
        self.assertIn("February 2026", html)

    def test_minor_meta(self):
        minor = self._data()["minors"][0]
        self.assertEqual(lg._minor_meta(minor, 1), "1 z-streams · 1 advisories")
        fminor = {"zstreams": [], "unversioned": [],
                  "features": [{"area": "A", "items": [{"t": "x", "d": ""}] * 3}]}
        self.assertEqual(lg._minor_meta(fminor, 0), "3 features")


class TestMarkdownExport(unittest.TestCase):
    @staticmethod
    def _ver(version, segs, phase_key, **extra):
        d = lg.date.fromisoformat
        segments = [{"key": k, "start": d(s), "end": d(e), **x} for k, s, e, *rest in segs
                    for x in [rest[0] if rest else {}]]
        return {"version": version, "ga": segments[0]["start"], "segments": segments,
                "is_eol": phase_key == "eol", "phase_key": phase_key, **extra}

    def test_table_columns_and_cells(self):
        versions = [
            self._ver("4.20", [("fs", "2025-10-21", "2026-04-21"),
                               ("mnt", "2026-04-21", "2027-04-21"),
                               ("eus1", "2027-04-21", "2027-10-21")], "mnt"),
            self._ver("4.19", [("fs", "2025-06-17", "2025-11-21"),
                               ("mnt", "2025-11-21", "2026-12-17")], "eol"),
        ]
        lines = lg.render_markdown_table(versions).splitlines()
        self.assertEqual(
            lines[0], "| Version | GA | Full Support ends | Maintenance ends | EUS-1 ends | Status |")
        self.assertEqual(lines[1], "|---|---|---|---|---|---|")
        self.assertEqual(
            lines[2], "| 4.20 | 2025-10-21 | 2026-04-21 | 2027-04-21 | 2027-10-21 | Maintenance |")
        self.assertEqual(lines[3], "| 4.19 | 2025-06-17 | 2025-11-21 | 2026-12-17 | - | EOL |")

    def test_open_ended_phases_read_ongoing(self):
        versions = [
            # build_versions: open phase is drawn up to today, flagged phase_open
            self._ver("2.0", [("fs", "2025-01-01", "2026-01-01")], "fs", phase_open=True),
            # RHEL major: Long Life carries an explicit end_label
            self._ver("10", [("rhel_std", "2025-05-20", "2035-05-31"),
                             ("rhel_ll", "2035-05-31", "2038-05-30", {"end_label": "Ongoing"})],
                      "rhel_std"),
        ]
        lines = lg.render_markdown_table(versions).splitlines()
        self.assertEqual(lines[2], "| 2.0 | 2025-01-01 | Ongoing | - | - | Full Support |")
        self.assertEqual(lines[3], "| 10 | 2025-05-20 | - | 2035-05-31 | Ongoing | Standard |")

    def test_doc_sections_and_source(self):
        v = [self._ver("1.0", [("fs", "2025-01-01", "2026-01-01")], "fs")]
        doc = lg.render_markdown_doc("T", [("", v), ("Sub", v), ("Empty", [])], "https://x/y")
        self.assertTrue(doc.startswith("# T\n\n| Version |"))
        self.assertIn("\n## Sub\n\n| Version |", doc)
        self.assertNotIn("Empty", doc)
        self.assertIn("Source: <https://x/y>", doc)

    def test_products_have_md_url(self):
        for key, cfg in lg.PRODUCT_CONFIGS.items():
            self.assertEqual(cfg["md_url"], f"lifecycle-{key}-markdown.html")

    def test_view_page_and_toggle(self):
        page = lg.render_markdown_view_html("| a | <b> |", "OCP Lifecycle", "lifecycle-ocp.md",
                                            key="ocp", has_details=True)
        self.assertIn('href="lifecycle-ocp.md"', page)
        self.assertIn("| a | &lt;b&gt; |", page)
        self.assertIn('href="lifecycle-ocp-details.html"', page)
        # No details pages (e.g. --skip-details): toggle keeps Chart + Markdown only
        toggle = lg._view_toggle("chart", "ocp", has_details=False)
        self.assertNotIn("details.html", toggle)
        self.assertIn("lifecycle-ocp-markdown.html", toggle)


class TestReuseCache(unittest.TestCase):
    """--reuse-cache: same-day sidecar JSON is used without fetching."""

    def _run(self, generated, reuse):
        import tempfile
        calls = []
        orig = lg.build_details_data
        fresh = {"generated": "fresh", "key": "ocp", "minors": []}
        lg.build_details_data = lambda key, cfg, versions: calls.append(key) or dict(fresh)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                sidecar = out / "lifecycle-ocp-details.json"
                sidecar.write_text(lg.json.dumps({"generated": generated, "key": "ocp", "minors": []}))
                lg._generate_details_page(out, "ocp", lg.PRODUCT_CONFIGS["ocp"], [], reuse_cache=reuse)
                return calls, lg.json.loads(sidecar.read_text())["generated"]
        finally:
            lg.build_details_data = orig

    def test_same_day_cache_skips_fetch(self):
        today = lg.datetime.now(lg.timezone.utc).strftime("%Y-%m-%dT00:00:01Z")
        calls, generated = self._run(today, reuse=True)
        self.assertEqual(calls, [])
        self.assertEqual(generated, today)

    def test_older_cache_is_refetched(self):
        calls, generated = self._run("2020-01-01T00:00:00Z", reuse=True)
        self.assertEqual(calls, ["ocp"])
        self.assertEqual(generated, "fresh")

    def test_off_by_default(self):
        today = lg.datetime.now(lg.timezone.utc).strftime("%Y-%m-%dT00:00:01Z")
        calls, _ = self._run(today, reuse=False)
        self.assertEqual(calls, ["ocp"])


_RELEASE_PAGE = """
<h2 id="RHEL10">Red Hat Enterprise Linux 10</h2><table><tbody>
<tr>
<td>RHEL 10.3</td>
<td>2026-11-10</td>
<td>2026-11-10</td>
</tr>
<tr><td>RHEL 10.2</td><td>2026-05-19</td><td>2026-05-19</td></tr>
</tbody></table>
<table><tbody>
<tr><td>RHEL 8.1</td><td>2019-11-05</td></tr>
<tr><td>RHEL 8</td><td>2019-05-07</td></tr>
<tr><td>RHEL 7.0 GA</td><td>2014-06-09</td></tr>
<tr><td>RHEL 7.0 Beta</td><td>2013-12-11</td></tr>
<tr><td>RHEL 4 Update 9</td><td>2011-02-16</td></tr>
</tbody></table>
"""


class TestRhelReleaseDates(unittest.TestCase):
    def test_parse_rows(self):
        self.assertEqual(lg.parse_rhel_release_dates(_RELEASE_PAGE), {
            "10": {"10.3": "2026-11-10", "10.2": "2026-05-19"},
            "8": {"8.1": "2019-11-05", "8.0": "2019-05-07"},
            "7": {"7.0": "2014-06-09"},
        })

    def test_new_minor_added_and_previous_std_end_follows(self):
        minors = {"10": {"10.2": {"ga": "2026-05-19", "std_end": "2026-11-12",
                                  "eus_end": "2028-05-31", "elc_end": "2032-05-19"}}}
        changes = lg.apply_rhel_release_dates({"10": {"10.2": "2026-05-19", "10.3": "2026-11-10"}},
                                              minors, {})
        self.assertEqual(minors["10"]["10.3"], {"ga": "2026-11-10", "std_end": "2027-05-11"})
        self.assertEqual(minors["10"]["10.2"]["std_end"], "2026-11-10")
        self.assertEqual(minors["10"]["10.2"]["elc_end"], "2032-05-19")  # YAML kept
        self.assertIn("RHEL 10.3 added (GA 2026-11-10)", changes)

    def test_changed_ga_replaces_yaml(self):
        minors = {"9": {"9.6": {"ga": "2025-04-29", "std_end": "2025-11-04"},
                        "9.7": {"ga": "2025-11-04", "std_end": "2026-05-19"}}}
        changes = lg.apply_rhel_release_dates({"9": {"9.6": "2025-05-20", "9.7": "2025-11-11"}}, minors, {})
        self.assertEqual(minors["9"]["9.6"], {"ga": "2025-05-20", "std_end": "2025-11-11"})
        self.assertEqual(minors["9"]["9.7"]["std_end"], "2026-05-19")  # newest keeps YAML std_end
        self.assertIn("RHEL 9.6 GA 2025-04-29 -> 2025-05-20", changes)

    def test_even_and_final_minors_derive_policy_dates(self):
        minors = {"9": {}}
        lg.apply_rhel_release_dates({"9": {"9.8": "2026-05-19", "9.10": "2027-05-18"}}, minors,
                                    {"9": {"std_end": "2032-05-31", "elc_end": "2036-05-31"}})
        self.assertEqual(minors["9"]["9.8"], {"ga": "2026-05-19", "eus_end": "2028-05-31",
                                              "elc_end": "2032-05-19", "std_end": "2027-05-18"})
        self.assertEqual(minors["9"]["9.10"], {"ga": "2027-05-18", "eus_end": "2029-05-31",
                                               "elc_end": "2033-05-18", "std_end": "2032-05-31",
                                               "elcp_end": "2036-05-31"})

    def test_majors_not_in_yaml_are_ignored(self):
        minors = {"10": {}}
        lg.apply_rhel_release_dates({"7": {"7.0": "2014-06-09"}}, minors, {})
        self.assertEqual(minors, {"10": {}})

    def test_refresh_failure_keeps_yaml(self):
        before = {k: {v: dict(f) for v, f in d.items()} for k, d in lg._RHEL_MINOR_DATA.items()}
        orig = lg._fetch_text
        for fake in (lambda url: (_ for _ in ()).throw(lg.urllib.error.URLError("down")),
                     lambda url: "<html>no table</html>"):
            lg._fetch_text = fake
            try:
                lg.refresh_rhel_minors()
            finally:
                lg._fetch_text = orig
            self.assertEqual(lg._RHEL_MINOR_DATA, before)

    def test_url_loaded_from_yaml(self):
        self.assertEqual(lg.RHEL_RELEASE_DATES_URL,
                         "https://access.redhat.com/kb/red-hat-enterprise-linux-release-dates")


class TestConfigWiring(unittest.TestCase):
    def test_details_products_have_urls(self):
        for key, cfg in lg.PRODUCT_CONFIGS.items():
            if "details" in cfg:
                self.assertEqual(cfg["details_url"], f"lifecycle-{key}-details.html")

    def test_ocp_and_rhel_configured(self):
        self.assertIn("details", lg.PRODUCT_CONFIGS["ocp"])
        self.assertIn("features_url", lg.PRODUCT_CONFIGS["ocp"]["details"])
        rhel = lg.PRODUCT_CONFIGS["rhel"]["details"]
        self.assertEqual(rhel["errata_scope"], "major")
        self.assertEqual(rhel["minors_from"], "rhel_minors")


if __name__ == "__main__":
    unittest.main()
