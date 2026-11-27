"""Check complete and partial historical ODP gzip members without network access."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import runpy

import pytest


extract = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "dmoz_snapshot.py"))["extract"]
HEADER = b"""<?xml version="1.0" encoding="UTF-8"?>
<RDF xmlns:r="http://www.w3.org/TR/RDF/">
<!-- Generated at 2000-08-07 08:00:40 GMT -->
<Topic r:id="Top/Test">
<link r:resource="http://one.example.org/home"/>
</Topic>
"""


def receipt(source):
    data = source.read_bytes()
    return {"sha256":hashlib.sha256(data).hexdigest(), "url":"https://archive.example.org/replay",
            "capture":{"statuscode":"200","timestamp":"20000815053618",
                       "digest":base64.b32encode(hashlib.sha1(data).digest()).decode("ascii")}}


@pytest.mark.parametrize("partial", [False, True])
def test_historical_member_coverage_and_identity(tmp_path, partial):
    source = tmp_path / "content.rdf.gz"
    tail = (b'<Topic r:id="Top/Cut">\n<link r:resource="http://two.example.org/"/>\n'
            b'<link r:resource="http://unfinished.example.org/' if partial else b"</RDF>\n")
    data = gzip.compress(HEADER + tail)
    source.write_bytes(data[:-8] if partial else data)
    records = {source.name:receipt(source)}
    out = tmp_path / "extracted"
    extract([source], records, out, 65536)
    audit, = json.loads((out / "node-audit.json").read_text())
    assert audit["gzip_eof"] == audit["xml_complete"] == (not partial)
    clue = json.loads((out / (source.name + ".rows.jsonl")).read_text())
    assert (clue["hostname"], clue["year"], clue["source_line"]) == ("one.example.org", 2000, 4)
    extra = [json.loads(line) for line in (out / "boundary-attributes.jsonl").read_text().splitlines()]
    assert [row["hostname"] for row in extra] == (["two.example.org"] if partial else [])
    if partial:
        assert extra[0]["parent_closed"] is False
    records[source.name]["capture"]["digest"] = "A" * 32
    with pytest.raises(ValueError, match="unverified bytes"):
        extract([source], records, tmp_path / "invalid", 65536)
    assert not (tmp_path / "invalid").exists()
