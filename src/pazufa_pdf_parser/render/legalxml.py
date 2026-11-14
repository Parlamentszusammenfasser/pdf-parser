"""Akoma Ntoso 3.0 (OASIS LegalDocML) renderer.

Document type mapping:

* parliamentary bill with recognised law text  -> ``<bill>``
* statute / regulation with structure           -> ``<act>``
* plenary protocol                              -> ``<debate>`` with ``<speech>`` elements
* court decision                                -> ``<judgment>``
* everything else (letter, e-mail, report, contract, generic) -> ``<doc name="...">``

The output validates against the official ``akomantoso30.xsd`` (checked in the
test suite). Extracted structured fields are embedded losslessly as JSON in
``meta/proprietary``.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Iterable

from ..model import Block, BlockKind, DocType, Document, LegalNode, Speech, plain

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
PZ_NS = "urn:pazufa-parser:1.0"
ET.register_namespace("", AKN_NS)
ET.register_namespace("pz", PZ_NS)

_XML_INVALID = re.compile(r"[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")


def _q(tag: str) -> str:
    return f"{{{AKN_NS}}}{tag}"


def _clean(text: str) -> str:
    return _XML_INVALID.sub("", text)


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, _q(tag), {k.rstrip("_"): v for k, v in attrs.items() if v is not None})
    if text:
        el.text = _clean(text)
    return el


def _p(parent: ET.Element, text: str, **attrs: str) -> ET.Element:
    """<p> with line breaks as <br/>."""
    p = _sub(parent, "p", **attrs)
    lines = _clean(text).split("\n")
    p.text = lines[0]
    for ln in lines[1:]:
        br = ET.SubElement(p, _q("br"))
        br.tail = ln
    return p


class _Ids:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def make(self, base: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_\-.]", "", base.replace(" ", "")) or "x"
        if base[0].isdigit():
            base = "n" + base
        self.counts[base] += 1
        n = self.counts[base]
        return base if n == 1 else f"{base}-{n}"


def _slug(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "x"


# --------------------------------------------------------------------------- meta


def _meta(root_doc: ET.Element, doc: Document, akn_type: str, persons: Iterable[tuple[str, str]] = ()) -> None:
    meta = _sub(root_doc, "meta")
    ident = _sub(meta, "identification", source="#pazufa")
    date = doc.fields.get("date") or "1970-01-01"
    number = (doc.fields.get("print") or {}).get("number") or doc.sha256[:12] or "unknown"
    work = f"/akn/de/{akn_type}/{_slug(str(doc.classification.subtype or doc.doc_type))}/{date}/{_slug(number)}"
    lang = {"de": "deu", "en": "eng"}.get(doc.fields.get("language", "de"), "deu")
    expr = f"{work}/{lang}@"
    manif = f"{expr}/!main.xml"
    w = _sub(ident, "FRBRWork")
    _sub(w, "FRBRthis", value=f"{work}/!main")
    _sub(w, "FRBRuri", value=work)
    _sub(w, "FRBRdate", date=date, name="document")
    _sub(w, "FRBRauthor", href="#author")
    _sub(w, "FRBRcountry", value="de")
    if doc.classification.subtype:
        _sub(w, "FRBRsubtype", value=doc.classification.subtype)
    if number:
        _sub(w, "FRBRnumber", value=number)
    e = _sub(ident, "FRBRExpression")
    _sub(e, "FRBRthis", value=f"{expr}/!main")
    _sub(e, "FRBRuri", value=expr)
    _sub(e, "FRBRdate", date=date, name="expression")
    _sub(e, "FRBRauthor", href="#author")
    _sub(e, "FRBRlanguage", language=lang)
    m = _sub(ident, "FRBRManifestation")
    _sub(m, "FRBRthis", value=manif)
    _sub(m, "FRBRuri", value=manif)
    _sub(m, "FRBRdate", date=date, name="transformation")
    _sub(m, "FRBRauthor", href="#pazufa")
    refs = _sub(meta, "references", source="#pazufa")
    _sub(refs, "TLCOrganization", eId="pazufa", href="/ontology/organization/pazufa-parser", showAs="pazufa-parser")
    _sub(refs, "TLCRole", eId="author", href="/ontology/role/author", showAs="author")
    for eid, name in persons:
        _sub(refs, "TLCPerson", eId=eid, href=f"/ontology/person/{_slug(name)}", showAs=name)
    prop = _sub(meta, "proprietary", source="#pazufa")
    data = ET.SubElement(prop, f"{{{PZ_NS}}}data", {"type": "application/json"})
    payload = {
        "classification": {
            "doc_type": str(doc.classification.doc_type),
            "subtype": doc.classification.subtype,
            "confidence": doc.classification.confidence,
        },
        "fields": plain(doc.fields),
        "entities": plain(doc.entities),
        "source": doc.source,
        "sha256": doc.sha256,
    }
    data.text = _clean(json.dumps(payload, ensure_ascii=False))


# --------------------------------------------------------------------------- preface


def _preface(parent: ET.Element, doc: Document) -> None:
    f = doc.fields
    pre = _sub(parent, "preface")
    cls = doc.classification
    p = _sub(pre, "p", class_="docMeta")
    dt = _sub(p, "docType", f.get("print", {}).get("kind") or str(cls.subtype or cls.doc_type))
    dt.tail = " "
    last = dt
    number = (f.get("print") or {}).get("number")
    if number:
        last = _sub(p, "docNumber", number)
        last.tail = " "
    if f.get("date"):
        last = _sub(p, "docDate", f["date"], date=f["date"])
        last.tail = " "
    parl = (f.get("print") or f.get("protocol") or {}).get("parliament")
    if parl:
        _sub(p, "docAuthority", parl)
    if f.get("title"):
        lt = _sub(pre, "longTitle")
        lp = _sub(lt, "p")
        _sub(lp, "docTitle", " ".join(str(f["title"]).split()))
    letter = f.get("letter") or {}
    for key, name in (("sender", "sender"), ("recipient", "recipient")):
        lines = (letter.get(key) or {}).get("lines")
        if lines:
            c = _sub(pre, "container", name=name)
            _p(c, "\n".join(lines))
    email = f.get("email") or {}
    header: list[tuple[str, dict[str, str]]] = []
    if email.get("from"):
        fr = email["from"]
        header.append(
            ("Von: " + " ".join(x for x in (fr.get("name"), f"<{fr['email']}>" if fr.get("email") else None) if x), {})
        )
    if email.get("to"):
        header.append(("An: " + "; ".join(a.get("name") or a.get("email", "") for a in email["to"]), {}))
    if email.get("date_text"):
        header.append(("Datum: " + email["date_text"], {}))
    if email.get("subject"):
        header.append(("Betreff: " + email["subject"], {}))
    header += [("Anlage: " + a, {"class_": "attachment"}) for a in email.get("attachments") or []]
    # a forwarded print may carry only the inner thread, and AKN forbids an empty <container>
    if header:
        c = _sub(pre, "container", name="emailHeader")
        for text, attrs in header:
            _p(c, text, **attrs)


# --------------------------------------------------------------------------- legal hierarchy

_ELEMENT_FOR_KIND = {
    "article": "article",
    "section": "section",
    "paragraph": "paragraph",
    "point": "point",
    "item": "point",
    "subitem": "point",
    "subsubitem": "point",
}
_PART_ELEMENT = {
    "teil": "part",
    "kapitel": "chapter",
    "titel": "title",
    "buch": "book",
    "abschnitt": "division",
    "unterabschnitt": "subdivision",
}
_ID_PREFIX = {
    "article": "art",
    "section": "sec",
    "paragraph": "para",
    "point": "point",
    "part": "part",
    "chapter": "chp",
    "title": "title",
    "book": "book",
    "division": "dvs",
    "subdivision": "subdvs",
    "hcontainer": "hcontainer",
}


def _legal_element(parent: ET.Element, node: LegalNode, ids: _Ids, prefix: str) -> None:
    if node.kind == "text":
        hc = _sub(parent, "hcontainer", name="text", eId=ids.make(f"{prefix}hcontainer_text"))
        content = _sub(hc, "content")
        for t in node.text:
            _p(content, t)
        return
    if node.kind == "part":
        word = node.num.split()[0].lower() if " " in node.num else ""
        tag = _PART_ELEMENT.get(word, "part")
    else:
        tag = _ELEMENT_FOR_KIND.get(node.kind, "hcontainer")
    num_id = re.sub(r"\W", "", node.num.split()[-1] if node.num else "") or "x"
    eid = ids.make(f"{prefix}{_ID_PREFIX.get(tag, tag)}_{num_id}")
    attrs = {"eId": eid}
    if tag == "hcontainer":
        attrs["name"] = node.kind
    el = _sub(parent, tag, **attrs)
    if node.num:
        num = node.num
        if node.kind == "article" and not num.lower().startswith("art"):
            num = f"Artikel {num}"
        elif node.kind == "section" and not num.startswith("§"):
            num = f"§ {num}"
        elif node.kind == "paragraph":
            num = f"({num})"
        elif node.kind in ("item", "subitem", "subsubitem"):
            num = f"{num})"
        elif node.kind == "point":
            num = f"{num}."
        _sub(el, "num", num)
    if node.heading:
        _sub(el, "heading", node.heading)
    if node.children:
        if node.text:
            intro = _sub(el, "intro")
            for t in node.text:
                _p(intro, t)
        for c in node.children:
            _legal_element(el, c, ids, f"{eid}__")
    else:
        content = _sub(el, "content")
        if node.text:
            for t in node.text:
                _p(content, t)
        else:
            _sub(content, "p")


# --------------------------------------------------------------------------- generic flow


def _skip(b: Block, preface_labels: set[str]) -> bool:
    return not b.text.strip() or bool(b.labels & preface_labels)


def _flow(parent: ET.Element, blocks: list[Block], ids: _Ids) -> None:
    """Render blocks; headings open <hcontainer name="section"> groups."""
    current: ET.Element | None = None
    current_content: ET.Element | None = None
    for b in blocks:
        text = b.text.strip()
        if b.kind is BlockKind.HEADING:
            current = _sub(parent, "hcontainer", name=f"level{b.level}", eId=ids.make("hcontainer_sec"))
            _sub(current, "heading", " ".join(text.split()))
            current_content = _sub(current, "content")
            continue
        target = current_content if current_content is not None else parent
        attrs = {"class_": "item"} if b.kind is BlockKind.LIST_ITEM else {}
        if "interjection" in b.labels:
            attrs = {"class_": "interjection"}
        _p(target, text, **attrs)
    for hc in parent.iter(_q("content")):
        if len(hc) == 0:
            _sub(hc, "p")


def _main_body_blocks(doc: Document, exclude: set[str]) -> list[Block]:
    return [b for b in doc.body_blocks if not _skip(b, exclude)]


def _synopsis(parent: ET.Element, doc: Document, ids: _Ids) -> None:
    for i, syn in enumerate(doc.synopsis, 1):
        hc = _sub(parent, "hcontainer", name="synopsis", eId=ids.make(f"hcontainer_synopsis{i}"))
        for side in ("left", "right"):
            ver = _sub(hc, "hcontainer", name=f"version-{side}", eId=ids.make(f"hcontainer_synopsis{i}_{side}"))
            if syn.get(f"{side}_label"):
                _sub(ver, "heading", syn[f"{side}_label"])
            nodes = syn[side]
            if not nodes:
                _sub(_sub(ver, "content"), "p")
            for n in nodes:
                _legal_element(ver, n, ids, f"syn{i}{side[0]}__")


def _synopsis_block_ids(doc: Document) -> set[int]:
    out: set[int] = set()
    for p in doc.pages:
        if p.layout is None:
            continue
        for r in p.layout.iter_regions():
            if r.synopsis:
                out.update(id(b) for b in r.iter_blocks())
    return out


# --------------------------------------------------------------------------- per type


def _doc_name(doc: Document) -> str:
    cls = doc.classification
    if cls.doc_type is DocType.PARLIAMENTARY_PRINT:
        return cls.subtype or "parliamentaryPrint"
    return {
        DocType.LETTER: "letter",
        DocType.EMAIL: "email",
        DocType.CONTRACT: "contract",
        DocType.GENERIC: "document",
        DocType.STATUTE: "statute",
        DocType.COURT_DECISION: "decision",
        DocType.PLENARY_PROTOCOL: "protocol",
    }.get(cls.doc_type, "document")


def _build_doc(root: ET.Element, doc: Document) -> None:
    ids = _Ids()
    d = _sub(root, "doc", name=_doc_name(doc))
    _meta(d, doc, "doc")
    _preface(d, doc)
    exclude = {"recipient", "sender", "return_address", "email_header"}
    syn_ids = _synopsis_block_ids(doc) if doc.synopsis else set()
    closing_from = None
    blocks = [b for b in _main_body_blocks(doc, exclude) if id(b) not in syn_ids]
    for i, b in enumerate(blocks):
        if "closing" in b.labels:
            closing_from = i
    tail: list[Block] = []
    if closing_from is not None:
        blocks, tail = blocks[:closing_from], blocks[closing_from:]
    main = _sub(d, "mainBody")
    if doc.legal and doc.doc_type in (DocType.CONTRACT, DocType.PARLIAMENTARY_PRINT, DocType.GENERIC):
        legal_ids = {id(b) for b in blocks if _in_law(b, doc)}
        pre = [b for b in blocks if id(b) not in legal_ids]
        _flow(main, pre, ids)
        for n in doc.legal:
            _legal_element(main, n, ids, "")
    else:
        _flow(main, blocks, ids)
    if doc.synopsis:
        _synopsis(main, doc, ids)
    if len(main) == 0:
        _sub(main, "p")
    if tail:
        concl = _sub(d, "conclusions")
        for b in tail:
            _p(concl, b.text.strip())


def _in_law(b: Block, doc: Document) -> bool:
    return "legal" in b.labels


def _build_legislation(root: ET.Element, doc: Document, tag: str) -> None:
    ids = _Ids()
    el = _sub(root, tag, name=_doc_name(doc))
    _meta(el, doc, tag)
    _preface(el, doc)
    body = _sub(el, "body")
    for n in doc.legal:
        _legal_element(body, n, ids, "")
    rest = [b for b in doc.body_blocks if b.text.strip() and "legal" not in b.labels]
    if rest:
        hc = _sub(body, "hcontainer", name="otherText", eId=ids.make("hcontainer_other"))
        content = _sub(hc, "content")
        for b in rest:
            _p(content, b.text.strip())


def _build_debate(root: ET.Element, doc: Document) -> None:
    ids = _Ids()
    persons: dict[str, str] = {}
    for s in doc.speeches:
        key = s.speaker
        if key not in persons:
            persons[key] = ids.make(f"person_{_slug(key).replace('-', '_')}")
    deb = _sub(root, "debate", name="plenaryProtocol")
    _meta(deb, doc, "debate", [(eid, name) for name, eid in persons.items()])
    _preface(deb, doc)
    body = _sub(deb, "debateBody")
    sec = _sub(body, "debateSection", name="agendaItem", eId="dbsect_1")
    topic = (doc.fields.get("protocol") or {}).get("topic") or doc.fields.get("title")
    if topic:
        _sub(sec, "heading", topic)
    # narrative before the first speech
    first_turn = next((b for b in doc.body_blocks if "speaker_turn" in b.labels), None)
    if first_turn is not None:
        pre_blocks = []
        for b in doc.body_blocks:
            if b is first_turn:
                break
            if b.text.strip():
                pre_blocks.append(b)
        for b in pre_blocks:
            _sub(sec, "narrative", " ".join(b.text.split()))
    for s in doc.speeches:
        _speech(sec, s, persons[s.speaker], ids)
    if not doc.speeches:
        for b in doc.body_blocks:
            if b.text.strip():
                _sub(sec, "narrative", " ".join(b.text.split()))
    if len(sec) == 0 or all(c.tag == _q("heading") for c in sec):
        _sub(sec, "narrative")


def _speech(parent: ET.Element, s: Speech, person_id: str, ids: _Ids) -> None:
    attrs = {"by": f"#{person_id}", "eId": ids.make("speech")}
    sp = _sub(parent, "speech", **attrs)
    _sub(sp, "from", ", ".join(x for x in (s.speaker, s.role, s.party) if x))
    paragraphs = s.paragraphs or [""]
    for t in paragraphs:
        cls = "interjection" if re.match(r"^\s*\(.*\)\s*$", t, re.S) else None
        _p(sp, t, class_=cls)


_JUDGMENT_SECTIONS = {
    "guiding_principles": "introduction",
    "tenor": "decision",
    "facts": "background",
    "reasons": "motivation",
}


def _build_judgment(root: ET.Element, doc: Document) -> None:
    j = _sub(root, "judgment", name=doc.classification.subtype or "judgment")
    _meta(j, doc, "judgment")
    blocks = [b for b in doc.body_blocks if b.text.strip()]
    first_sec = next(
        (i for i, b in enumerate(blocks) if any(lbl.startswith("section:") for lbl in b.labels)), len(blocks)
    )
    header = _sub(j, "header")
    court = doc.fields.get("court") or {}
    meta_p = _sub(header, "p", class_="docMeta")
    last = None
    for tag, val, attr in (
        ("courtType", court.get("court"), None),
        ("docType", court.get("decision_type"), None),
        ("docNumber", court.get("file_number"), None),
        ("docDate", court.get("date"), court.get("date")),
    ):
        if val:
            last = _sub(meta_p, tag, val, **({"date": attr} if attr else {}))
            last.tail = " "
    for b in blocks[:first_sec]:
        _p(header, b.text.strip())
    body = _sub(j, "judgmentBody")
    current: ET.Element | None = None
    remedies: list[Block] = []
    in_remedies = False
    for b in blocks[first_sec:]:
        sec = next((lbl.split(":", 1)[1] for lbl in b.labels if lbl.startswith("section:")), None)
        if sec == "remedies":
            in_remedies = True
        if in_remedies:
            remedies.append(b)
            continue
        if sec is not None:
            current = _sub(body, _JUDGMENT_SECTIONS.get(sec, "motivation"))
            _p(current, b.text.strip(), class_="heading")
            continue
        if current is None:
            current = _sub(body, "introduction")
        _p(current, b.text.strip())
    if len(body) == 0:
        _sub(_sub(body, "introduction"), "p")
    if remedies:
        concl = _sub(j, "conclusions")
        for b in remedies:
            _p(concl, b.text.strip())


def build_akn(doc: Document) -> ET.Element:
    root = ET.Element(_q("akomaNtoso"))
    t = doc.doc_type
    if t is DocType.PLENARY_PROTOCOL:
        _build_debate(root, doc)
    elif t is DocType.COURT_DECISION:
        _build_judgment(root, doc)
    elif t is DocType.STATUTE and doc.legal:
        _build_legislation(root, doc, "act")
    elif t is DocType.PARLIAMENTARY_PRINT and doc.classification.subtype == "bill" and doc.legal and not doc.synopsis:
        _build_legislation(root, doc, "bill")
    else:
        _build_doc(root, doc)
    return root


def render_legalxml(doc: Document) -> str:
    root = build_akn(doc)
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
