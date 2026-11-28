"""Contract and identity tests; synthetic bytes are not historical evidence."""
import hashlib
import json
from pathlib import Path

import pytest

from creeperman.core import canonical
from creeperman import media_mapping
from creeperman.media_mapping import Members, SyntaxCache, pcpress_mapping, run


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bundle(tmp_path, pages, mapping):
    root = tmp_path / "bundle"
    root.mkdir()
    items = {"/ARCHIVES/TEST.JSON;1": canonical(mapping), **pages}
    members = []
    for index, (member, raw) in enumerate(items.items()):
        local = "member-" + str(index)
        (root / local).write_bytes(raw)
        members.append({"member_path": member, "local_path": local,
                        "sha256": sha(raw), "bytes": len(raw)})
    manifest = {"schema": "media-members-v1", "source_id": "fixture",
                "origin_family": "synthetic-fixture", "container": {
                    "url": "https://example.org/disc.iso", "size": 100000,
                    "declared_sha1": "a" * 40,
                    "partial_identity": {"etag": '"fixture"', "coverage": "partial-container"}},
                "members": members}
    path = root / "members.json"
    path.write_bytes(canonical(manifest))
    return path


def entry(path, url, **kwargs):
    return {"path": path, "url": url, "archived": None, "modified": None,
            "warn": None, "error": False, "broken": False, "skip": False, **kwargs}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def execute(tmp_path, manifest, name="out", **kwargs):
    out = tmp_path / name
    report = run(manifest, "/ARCHIVES/TEST.JSON;1", out, **kwargs)
    return report, rows(out / "observations.jsonl"), rows(out / "review.jsonl")


def freeze_scope(manifest, scope_id, mapping_members=("/ARCHIVES/TEST.JSON;1",),
                 mapping_format="archive95-json", root="", link_mode="local-map"):
    data = json.loads(manifest.read_bytes())
    data["operation_scope"] = {
        "kind": "media-mapping-selected-members-v1", "scope_id": scope_id,
        "mapping_members": list(mapping_members), "mapping_format": mapping_format,
        "mapping_root": root, "link_mode": link_mode,
    }
    manifest.write_bytes(canonical(data))


def test_explicit_identity_and_dates_survive_without_qualification(tmp_path):
    raw = b'<META name="download" content="uninterpreted date"><a href="http://outside.example.org/">Outside</a>'
    manifest = bundle(tmp_path, {"/SITE/INDEX.HTM;1": raw}, [
        entry("site/index.htm", "http://www.Example.org/start", archived="1998-01-01T12:00:00Z", modified="1997-12-20")])
    report, observations, review = execute(tmp_path, manifest)
    source, reference = observations
    assert source["hostname"] == "www.example.org"
    assert source["original_url"] == "http://www.Example.org/start"
    assert reference["hostname"] == "outside.example.org"
    assert all(row["observed_year"] is None for row in observations)
    assert "validation_status" not in source
    p = source["media_provenance"]
    assert p["member_sha256"] == sha(raw) and p["member_path"] == "/SITE/INDEX.HTM;1"
    assert p["mapping_sha256"] and p["manifest_sha256"]
    assert [c["semantics"] for c in p["date_claims"]] == [
        "mapping_archived_unreviewed", "mapping_modified_unreviewed", "raw_download_meta_unreviewed"]
    assert p["container"]["partial_identity"]["coverage"] == "partial-container"
    assert report["eed"] is None and report["qualification"] == "not_run"
    assert "operation" not in report  # Past runs cannot become declared epochs.
    assert report["cost"]["requests"] == 0 and not review


def test_offline_links_need_explicit_mapping_and_keep_target_origin(tmp_path):
    manifest = bundle(tmp_path, {
        "/A/INDEX.HTM;1": b'<a href="../B/INDEX.HTM#section">mapped</a><a href="missing.htm">unknown</a>',
        "/B/INDEX.HTM;1": b"<title>second</title>",
    }, [entry("A/INDEX.HTM", "http://a.example.org/original/"),
        entry("B/INDEX.HTM", "http://b.example.org/exact?query=yes")])
    report, observations, review = execute(tmp_path, manifest)
    references = [r for r in observations if r["kind"] == "html_reference"]
    assert len(references) == 1
    assert references[0]["original_url"] == "http://b.example.org/exact?query=yes#section"
    assert references[0]["source_original_url"] == "http://a.example.org/original/"
    assert references[0]["rewrite"]["basis"] == "offline_member_explicit_mapping"
    assert review[0]["reason"] == "unmapped_local_reference"
    assert report["pages_processed"] == 2


def test_same_body_different_originals_reuse_syntax_not_url_identity(tmp_path):
    raw = b'<base href="../shared/"><a href="next.htm">next</a>'
    manifest = bundle(tmp_path, {"/A.HTM;1": raw, "/B.HTM;1": raw}, [
        entry("a.htm", "http://a.example.org/one/start.htm"),
        entry("b.htm", "http://b.example.org/two/start.htm")])
    cache = tmp_path / "syntax.sqlite"
    report, observations, _ = execute(tmp_path, manifest, link_mode="original", cache_path=cache)
    assert report["syntax_bodies_parsed"] == 1 and report["syntax_cache_hits"] == 1
    assert {r["original_url"] for r in observations if r["kind"] == "html_reference"} == {
        "http://a.example.org/shared/next.htm", "http://b.example.org/shared/next.htm"}
    assert len({r["record_id"] for r in observations}) == 4
    again, reused, _ = execute(tmp_path, manifest, name="again", link_mode="original", cache_path=cache)
    assert again["syntax_bodies_parsed"] == 0 and again["syntax_cache_hits"] == 2
    assert observations == reused


def test_original_protocol_relative_reference_uses_effective_base_scheme(tmp_path):
    raw = (b'<base href="https://base.example.org/assets/">'
           b'<img src="//cdn.example.org/logo.gif">'
           b'<a href="http://absolute.example.org/">literal</a>')
    manifest = bundle(tmp_path, {"/START.HTM;1": raw}, [
        entry("start.htm", "http://page.example.org/index.html")])
    _, observations, _ = execute(tmp_path, manifest, link_mode="original")
    assert {r["original_url"] for r in observations if r["kind"] == "html_reference"} == {
        "https://cdn.example.org/logo.gif", "http://absolute.example.org/"}
    assert observations[0]["original_url"] == "http://page.example.org/index.html"


def test_teleport_restores_each_preceding_attribute_and_excludes_error(tmp_path):
    raw = (b'<a href="a.htm" tppabs="http://www.example.org/original">A</a>'
           b'<img src="a.gif" tppabs="http://img.example.org/a.gif" '
           b'longdesc="b.htm" tppabs="http://info.example.org/details">'
           b'<a href="error.htm" tppabs="error">failed</a>'
           b'<script src="local.js" tppabs="http://scripts.example.org/app.js"></script>'
           b'<a href="wrong.htm" title="x" tppabs="http://unbound.example.org/">unbound</a>')
    manifest = bundle(tmp_path, {"/START.HTM;1": raw}, [entry("start.htm", "http://host.example.org/")])
    report, observations, review = execute(tmp_path, manifest, link_mode="teleport")
    refs = [r for r in observations if r["kind"] == "html_reference"]
    assert {r["hostname"] for r in refs} == {
        "www.example.org", "img.example.org", "info.example.org", "scripts.example.org"}
    assert all(r["rewrite"]["basis"] == "teleport-tppabs-preceding-attribute" for r in refs)
    assert {r["reason"] for r in review} == {"teleport_download_error", "unmapped_local_reference"}
    assert report["pages_processed"] == 1


def test_conflicting_map_and_failed_capture_do_not_become_source_pages(tmp_path):
    manifest = bundle(tmp_path, {
        "/A.HTM;1": b"<p>A</p>", "/ERROR.HTM;1": b"<p>download failed</p>"
    }, [entry("a.htm", "http://one.example.org/"), entry("a.htm", "http://two.example.org/"),
        entry("error.htm", "http://lost.example.org/", error=True)])
    report, observations, review = execute(tmp_path, manifest)
    assert observations == [] and report["pages_processed"] == 0
    assert {r["reason"] for r in review} == {"conflicting_member_identity", "mapping_marks_unusable"}


def test_unmapped_original_cannot_be_guessed_from_filename_or_meta(tmp_path):
    manifest = bundle(tmp_path, {"/WWW_EXAMPLE_ORG.HTM;1": b'<META name="download" content="1996 http://example.org/">'}, [
        entry("www_example_org.htm", None)])
    _, observations, review = execute(tmp_path, manifest)
    assert observations == [] and review[0]["reason"] == "no_valid_explicit_original"


def test_member_hash_and_local_path_boundary_are_verified(tmp_path):
    manifest = bundle(tmp_path, {"/A.HTM;1": b"<p>A</p>"}, [entry("a.htm", "http://a.example.org/")])
    (manifest.parent / "member-1").write_bytes(b"<p>B</p>")
    with pytest.raises(ValueError, match="hash/length"):
        execute(tmp_path, manifest)
    m = json.loads(manifest.read_text())
    m["members"][1]["local_path"] = "../outside"
    manifest.write_bytes(canonical(m))
    with pytest.raises(ValueError, match="inside bundle"):
        Members(manifest)


def test_case_or_version_ambiguous_members_rejected(tmp_path):
    manifest = bundle(tmp_path, {"/A.HTM;1": b"one", "/a.htm;2": b"two"}, [])
    with pytest.raises(ValueError, match="ambiguous"):
        Members(manifest)


def test_partial_processing_bound_is_reported_without_false_zero_reward(tmp_path):
    manifest = bundle(tmp_path, {"/A.HTM;1": b"one", "/B.HTM;1": b"two"}, [
        entry("a.htm", "http://a.example.org/"), entry("b.htm", "http://b.example.org/")])
    report, observations, _ = execute(tmp_path, manifest, max_pages=1)
    assert report["pages_processed"] == 1 and len(observations) == 1
    assert report["complete_selected_scope"] is False
    assert report["stopped_reason"] == "local_processing_bound"
    assert report["eed"] is None


def test_charset_and_parser_version_are_part_of_cache_identity(tmp_path):
    cache = SyntaxCache(tmp_path / "syntax.sqlite")
    try:
        raw = b'<a href="http://example.org/">\xe9</a>'
        one = cache.parse(raw, "windows-1252")
        two = cache.parse(raw, "latin1")
        assert one == two and cache.parsed == 2
        cache.parse(raw, "windows-1252")
        assert cache.hits == 1
    finally:
        cache.close()


def test_pcpress_lis_binds_observed_numbered_sibling_not_namespace(tmp_path):
    root = tmp_path / "real-format-synthetic-content"
    root.mkdir()
    mapping = (b"download.example.org//00000001.htm http://www.example.org/\n"
               b"download.example.org//00000002.gif http://images.example.org/banner.gif\n"
               b"download.example.org//00000003.htm http://www.example.org/links.html\n")
    html = (b'<META name="download" content="Date=Fri Mar 15 05:16:00 1996\n'
            b', Done by operator, Program 1.0 beta4 by Dragan Sretenovic">\n'
            b'<img src="00000002.gif"><a href="00000003.htm">links</a>')
    members = []
    for local, path, raw in [("mapping", "/WORLDWEB/WWW/10/INDEX.LIS;1", mapping),
                             ("page", "/WORLDWEB/WWW/10/00000001.HTM;1", html)]:
        (root / local).write_bytes(raw)
        members.append({"local_path": local, "member_path": path, "sha256": sha(raw), "bytes": len(raw)})
    manifest = root / "members.json"
    manifest.write_bytes(canonical({"schema": "media-members-v1", "source_id": "fixture",
                                    "origin_family": "synthetic", "container": {"coverage": "partial"},
                                    "members": members}))
    out = tmp_path / "out"
    report = run(manifest, members[0]["member_path"], out, mapping_format="pcpress-lis")
    observations = rows(out / "observations.jsonl")
    assert [r["original_url"] for r in observations] == [
        "http://www.example.org/", "http://images.example.org/banner.gif", "http://www.example.org/links.html"]
    assert all(r["hostname"] != "download.example.org" for r in observations)
    assert all(r["observed_year"] is None for r in observations)
    assert observations[2]["rewrite"]["mapping_locator"].endswith(":line:3")
    assert observations[0]["media_provenance"]["date_claims"][0]["value"].startswith("Date=Fri Mar 15")
    assert report["pages_processed"] == 1 and report["mapping_records"] == 3
    assert report["mapped_members_not_extracted"] == 2
    assert report["completion_semantics"] == "selected_mapping_files_and_available_bound_html_classified"
    assert report["complete_selected_scope"] is True
    assert report["unsupported_mapping_rows"] == 0
    assert len(rows(out / "review.jsonl")) == 2  # Both bodies were intentionally not extracted.


def test_pcpress_unknown_path_forms_are_quarantined_not_repaired():
    raw = (b"root//00000001.htm http://www.example.org/\n"
           b"root/path/00000002.htm http://guessed.example.org/\n"
           b"root//../00000003.htm http://escape.example.org/\n"
           b"root//00000004.htm http://with spaces.example.org/\n")
    mappings, rejected = pcpress_mapping(raw, "/SITE/INDEX.LIS;1")
    assert len(mappings) == 1 and mappings[0]["member_path"] == "/SITE/00000001.htm"
    assert len(rejected) == 3
    assert {r["mapping_locator"] for r in rejected} == {
        "/SITE/INDEX.LIS;1:line:2", "/SITE/INDEX.LIS;1:line:3", "/SITE/INDEX.LIS;1:line:4"}


def test_declared_discovery_scope_binds_real_inputs_code_and_outputs(tmp_path):
    manifest = bundle(tmp_path, {"/A.HTM;1": b"one", "/B.HTM;1": b"two"}, [
        entry("a.htm", "http://a.example.org/"), entry("b.htm", "http://b.example.org/")])
    freeze_scope(manifest, "declared-media-scope")
    report, _, _ = execute(tmp_path, manifest, scope_id="declared-media-scope", max_pages=1)
    assert report["operation"] == {
        "kind": "discovery", "scope_id": "declared-media-scope", "complete": False,
        "input_sha256": sha(manifest.read_bytes()),
        "operator_sha256": sha(Path(media_mapping.__file__).read_bytes())}
    for name, digest in report["outputs"].items():
        assert sha((tmp_path / "out" / name).read_bytes()) == digest
    complete, _, _ = execute(tmp_path, manifest, name="complete", scope_id="declared-media-scope")
    assert complete["operation"]["complete"] is True
    assert complete["qualification"] == "not_run" and complete["eed"] is None
    assert complete["inputs"]["operation_scope"] == json.loads(manifest.read_bytes())["operation_scope"]


def test_unscoped_legacy_manifest_cannot_claim_a_production_scope(tmp_path):
    manifest = bundle(tmp_path, {"/A.HTM;1": b"one"}, [entry("a.htm", "http://a.example.org/")])
    with pytest.raises(ValueError, match="operation_scope must be frozen"):
        execute(tmp_path, manifest, scope_id="not-predeclared")
    assert not (tmp_path / "out").exists()
    report, _, _ = execute(tmp_path, manifest, name="legacy")
    assert "operation" not in report and report["complete_selected_scope"] is True


@pytest.mark.parametrize("change", ["missing_member", "reordered_members", "mode", "root", "format", "scope_id"])
def test_frozen_scope_rejects_changed_selection_and_modes(tmp_path, change):
    members = ["/ARCHIVES/TEST.JSON;1", "/ARCHIVES/SECOND.JSON;1"]
    manifest = bundle(tmp_path, {"/A.HTM;1": b"one", members[1]: canonical([])}, [
        entry("a.htm", "http://a.example.org/")])
    freeze_scope(manifest, "two-mappings", members)
    selected = members
    kwargs = {"scope_id": "two-mappings"}
    if change == "missing_member": selected = members[:1]
    elif change == "reordered_members": selected = list(reversed(members))
    elif change == "mode": kwargs["link_mode"] = "original"
    elif change == "root": kwargs["root"] = "different"
    elif change == "format": kwargs["mapping_format"] = "pcpress-lis"
    elif change == "scope_id": kwargs["scope_id"] = "different"
    with pytest.raises(ValueError, match="operation_scope must be frozen"):
        run(manifest, selected, tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()
