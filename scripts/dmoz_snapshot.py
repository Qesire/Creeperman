"""Read intact, individually parseable records from digest-verified historical DMOZ members."""
import argparse
import base64
import hashlib
import json
import re
import zlib
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.parsers import expat

from creeperman.core import sha, timestamp_year, url_host
from creeperman.source_precheck import new_output


def inflated_lines(path, stats):
    inflater = zlib.decompressobj(31)
    xml = expat.ParserCreate()
    carry = b""
    size = 0
    with path.open("rb") as src:
        while chunk := src.read(65536):
            try:
                part = inflater.decompress(chunk)
            except zlib.error as e:
                stats["gzip_error"] = str(e)
                break
            if inflater.unused_data:
                raise ValueError("unexpected bytes after gzip member")
            if xml is not None:
                try:
                    xml.Parse(part, False)
                except expat.ExpatError as err:
                    stats["xml_error"] = str(err)
                    xml = None
            size += len(part)
            lines = (carry + part).split(b"\n")
            carry = lines.pop()
            yield from lines
    if carry:
        yield carry
    stats.update(uncompressed_bytes=size, gzip_eof=inflater.eof)
    if inflater.eof and xml is not None:
        try:
            xml.Parse(b"", True)
        except expat.ExpatError as err:
            stats["xml_error"] = str(err)
    stats["xml_complete"] = inflater.eof and "xml_error" not in stats


def attr(element, local):
    return next((v for k,v in element.attrib.items() if k.rsplit("}",1)[-1]==local),None)


def generated_year(path):
    inflater = zlib.decompressobj(31)
    with path.open("rb") as src:
        head = inflater.decompress(src.read(65536))
    m = re.search(br"<!--\s*Generated at (\d{4})-\d\d-\d\d .*? GMT", head)
    if m is None:
        raise ValueError(f"{path}: no Generated-at comment in header; cannot bind observation year")
    return int(m.group(1))


def write_rows(path, receipt, out, year_basis="capture"):
    with path.open("rb") as stream:
        payload_digest = base64.b32encode(hashlib.file_digest(stream, "sha1").digest()).decode("ascii")
    if (receipt["capture"]["digest"] != payload_digest or receipt["capture"]["statuscode"] != "200"
            or sha(path) != receipt["sha256"]):
        raise ValueError(f"unverified bytes: {path}")
    stats = {"source_file":path.name, "source_sha256":receipt["sha256"], "capture_url":receipt["url"],
             "year_basis":year_basis}
    counters = Counter()
    stamp = receipt["capture"]["timestamp"]
    year = generated_year(path) if year_basis == "generated" else timestamp_year(stamp)
    output = out / (path.name + ".rows.jsonl")
    tmp = output.with_suffix(".tmp")
    block = None
    xml_decl, root_header = b"", b""
    in_header = False
    all_hosts = set()
    with tmp.open("w", encoding="utf-8", newline="\n") as sink:
        for n, line in enumerate(inflated_lines(path, stats),1):
            if n == 1 and line.startswith(b"<?xml"):
                xml_decl = line
            if line.startswith(b"<RDF ") or in_header:
                root_header += line + b"\n"
                in_header = b">" not in line
                continue
            generated = re.search(br"<!--\s*Generated at (.*?) GMT", line)
            if generated:
                stats["generated_gmt"] = generated.group(1).decode("ascii")
            starts = re.match(br"^<(Topic|ExternalPage)(?:\s|>)",line)
            if starts:
                if block is not None:
                    counters["unfinished_nodes"] += 1
                block, tag, first_line = [], starts.group(1), n
            if block is None:
                continue
            block.append(line)
            if not line.rstrip().endswith(b"</" + tag + b">"):
                continue
            counters["closed_nodes_seen"] += 1
            fragment = xml_decl + b"\n" + root_header + b"\n".join(block) + b"\n</RDF>"
            block = None
            try:
                root = ElementTree.fromstring(fragment)
                if len(root)!=1:
                    raise ValueError("multiple roots")
                node = root[0]
            except (ElementTree.ParseError,ValueError):
                counters["closed_nodes_invalid_xml"] += 1
                continue
            name = node.tag.rsplit("}",1)[-1]
            if name == "Topic":
                catid = node.findtext("{*}catid")
                topic = attr(node, "id")
                rows = [(child.tag.rsplit("}",1)[-1], attr(child,"resource"), i, {}) for i,child in enumerate(node,1)
                        if child.tag.rsplit("}",1)[-1] in ("link","link1")]
            elif name == "ExternalPage":
                catid, topic = None, node.findtext("{*}topic")
                desc = {key:node.findtext("{*}"+key) for key in ("Title","Description")}
                rows = [(name, attr(node,"about"), 0, desc)]
            else:
                continue
            for kind, url, child_number, extra in rows:
                try:
                    host = url_host(url)
                except (ValueError,TypeError,AttributeError):
                    counters["not_http_or_invalid_hostname"] += 1
                    continue
                row = dict(source_file=path.name, source_sha256=receipt["sha256"], source_line=first_line,
                           end_line=n, node=kind, child_ordinal=child_number, original_url=url, hostname=host,
                           year=year, capture_timestamp=stamp, topic=topic, catid=catid, **extra)
                sink.write(json.dumps(row, ensure_ascii=False, separators=(",",":"))+"\n")
                counters[kind] += 1
                all_hosts.add(host)
        if block is not None:
            counters["unfinished_nodes"] += 1
    tmp.replace(output)
    stats.update(capture_year=timestamp_year(stamp), observation_year=year, counts=dict(counters),
                 unique_hosts=len(all_hosts), rows_file=output.name, rows_sha256=sha(output))
    return stats


# Skip XML comments and CDATA. A URL-bearing tag must end outside quoted
# strings. A cut-off attribute or a partial final start tag never matches.
TOKENS = re.compile(br"""<!--.*?(?:-->|\Z)|<!\[CDATA\[.*?(?:\]\]>|\Z)|(?m:^[ \t]*)<(/?)(Topic|ExternalPage|link1?)(?=[\s/>])(?:[^<>"']|"[^"<]*"|'[^'<]*')*>""", re.S)
ROOT = re.compile(br"<RDF\s+[^>]+>")


def start_field(raw, root, name, key):
    tag = raw.strip()
    if not tag.endswith(b"/>"):
        tag = tag[:-1] + b"/>"
    fragment = root + tag + b"</RDF>"
    try:
        node = ElementTree.fromstring(fragment)[0]
        mode = "strict_xml"
    except ElementTree.ParseError:
        # Legacy ODP bytes may have a non-UTF-8 path. Latin-1 is only a
        # reversible byte view. Accept solely a literal, unambiguous ASCII
        # authority; preserve raw attribute bytes when using this view.
        try:
            node = ElementTree.fromstring(b'<?xml version="1.0" encoding="iso-8859-1"?>'+fragment)[0]
        except ElementTree.ParseError:
            return None, "invalid_xml"
        mode = "legacy_octets_ascii_authority"
    if node.tag.rsplit("}",1)[-1] != name:
        return None, "wrong_tag"
    value = attr(node,key)
    return value, mode


def recover_attributes(source, out, meta):
    original = Counter()
    with (out / meta["rows_file"]).open(encoding="utf8") as verified:
        for line in verified:
            row = json.loads(line)
            original[row["source_line"], row["node"], row["original_url"]] += 1
    with source.open("rb") as stream:
        data = zlib.decompressobj(31).decompress(stream.read(), meta["uncompressed_bytes"]+1)
    if len(data) != meta["uncompressed_bytes"]:
        raise ValueError("source changed during boundary audit")
    root_match = ROOT.search(data)
    if root_match is None:
        raise ValueError("missing historical RDF root declaration")
    root = root_match.group()
    extra = []
    counts = Counter()
    ends = {}
    group = None
    last, n = 0,1
    for match in TOKENS.finditer(data):
        n += data.count(b"\n",last,match.start())
        last=match.start()
        if match[1] is None:
            continue
        name=match[2].decode("ascii")
        if match[1]:
            if group and group[0]==name:
                ends[group[1]]=n
                group=None
            continue
        tag = match.group().strip()
        if name=="Topic":
            category,_=start_field(tag,root,name,"id")
            group=(name,n,category)
            continue
        if name=="ExternalPage":
            group=(name,n,None)
        elif not group or group[0]!="Topic" or not group[2]:
            counts["category_unresolved"]+=1
            continue
        original_url, mode=start_field(tag,root,name,"about" if name=="ExternalPage" else "resource")
        if not original_url:
            counts[mode]+=1
            continue
        try:
            host=url_host(original_url)
            if mode=="legacy_octets_ascii_authority":
                authority=urlsplit(original_url).netloc
                if not authority.isascii() or not re.match(br"https?://",tag.split(b'="',1)[-1],re.I):
                    raise ValueError("authority encoding uncertain")
        except (TypeError, ValueError,AttributeError):
            counts["unusable_identity"]+=1
            continue
        key=group[1],name,original_url
        if original[key]:
            original[key]-=1
            counts["also_in_closed_nodes"]+=1
            continue
        rec=dict(source_file=source.name,source_sha256=meta["source_sha256"],source_line=group[1],
                 attribute_line=n,byte_offset=match.start(),node=name,topic=group[2],
                 year=meta.get("observation_year",meta["capture_year"]),
                 hostname=host,attribute_mode=mode)
        if mode=="strict_xml":
            rec["original_url"]=original_url
        else:
            rec["raw_tag_hex"]=tag.hex()
            rec["original_url_octet_view"]=original_url
        extra.append(rec)
    if any(original.values()):
        raise ValueError("historical line-oriented XML layout differs from the subtree export")
    for record in extra:
        record["parent_end_line"]=ends.get(record["source_line"])
        record["parent_closed"]=record["parent_end_line"] is not None
    return extra, dict(counts)


def extract(sources, receipts, output, boundary_limit, year_basis="capture"):
    if boundary_limit < 0:
        raise ValueError("expected a non-negative boundary byte limit")
    if len({p.name for p in sources}) != len(sources):
        raise ValueError("each source must have a distinct receipt filename")
    with new_output(output) as stage:
        results = []
        with (stage / "boundary-attributes.jsonl").open("w", encoding="utf8") as sink:
            for source in sources:
                stats = write_rows(source, receipts[source.name], stage, year_basis)
                if stats["xml_complete"]:
                    stats["boundary_status"] = "complete_xml"
                elif max(stats["uncompressed_bytes"],source.stat().st_size) > boundary_limit:
                    stats["boundary_status"] = "outside_boundary_budget"
                else:
                    extra, counts = recover_attributes(source, stage, stats)
                    for record in extra:
                        print(json.dumps(record, ensure_ascii=False), file=sink)
                    stats.update(boundary_status="checked", extra_attributes=len(extra), attribute_checks=counts)
                if sha(source) != stats["source_sha256"]:
                    raise ValueError("source changed during extraction")
                results.append(stats)
        (stage / "node-audit.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, nargs="+", help="locally saved, line-oriented ODP .rdf.gz snapshots")
    parser.add_argument("--receipts", type=Path, required=True, help="JSON capture receipts keyed by input filename")
    parser.add_argument("--out", type=Path, required=True, help="new directory for local observations and coverage")
    parser.add_argument("--boundary-limit", type=int, default=64 << 20,
                        help="byte limit for the in-memory recovery pass on damaged XML (default: 64 MiB)")
    parser.add_argument("--year-basis", choices=("capture", "generated"), default="capture",
                        help="observation year from capture timestamp (default) or the header Generated-at date")
    args = parser.parse_args()
    extract(args.sources, json.loads(args.receipts.read_bytes()), args.out, args.boundary_limit, args.year_basis)
