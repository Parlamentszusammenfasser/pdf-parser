"""JSON renderer (structured information)."""

from __future__ import annotations

import json
from typing import Any

from ..model import Document, LegalNode, Region, RegionKind, plain


def legal_to_dict(node: LegalNode) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": node.kind}
    if node.num:
        d["num"] = node.num
    if node.heading:
        d["heading"] = node.heading
    if node.text:
        d["text"] = node.text
    if node.children:
        d["children"] = [legal_to_dict(c) for c in node.children]
    return d


def _region_to_dict(r: Region) -> dict[str, Any]:
    d: dict[str, Any] = {"id": r.id, "kind": str(r.kind), "bbox": r.bbox.to_list()}
    if r.synopsis:
        d["synopsis"] = True
    if r.kind is RegionKind.LEAF:
        d["blocks"] = len(r.blocks)
    else:
        d["children"] = [_region_to_dict(c) for c in r.children]
    return d


def document_to_dict(doc: Document, *, include_layout: bool = False) -> dict[str, Any]:
    cls = doc.classification
    out: dict[str, Any] = {
        "source": doc.source,
        "sha256": doc.sha256,
        "pdf_info": plain(doc.pdf_info),
        "classification": {
            "doc_type": str(cls.doc_type),
            "subtype": cls.subtype,
            "confidence": cls.confidence,
            "scores": cls.scores,
            "evidence": cls.evidence,
            "features": plain(cls.features),
        },
        "fields": plain(doc.fields),
        "entities": plain(doc.entities),
    }
    if doc.legal:
        out["legal_structure"] = [legal_to_dict(n) for n in doc.legal]
    if doc.synopsis:
        out["synopsis"] = [
            {
                "pages": s["pages"],
                "left_label": s["left_label"],
                "right_label": s["right_label"],
                "left": [legal_to_dict(n) for n in s["left"]],
                "right": [legal_to_dict(n) for n in s["right"]],
            }
            for s in doc.synopsis
        ]
    if doc.speeches:
        out["speeches"] = [plain(s) for s in doc.speeches]
    out["stats"] = plain(doc.stats)
    out["issues"] = [plain(i) for i in doc.issues]
    out["timings"] = doc.timings
    pages = []
    for p in doc.pages:
        pd: dict[str, Any] = {
            "number": p.number,
            "width": round(p.width, 2),
            "height": round(p.height, 2),
            "source": str(p.source),
            "stats": plain(p.stats),
        }
        blocks = []
        for b in p.all_blocks:
            bd: dict[str, Any] = {"kind": str(b.kind), "text": b.text}
            if b.level:
                bd["level"] = b.level
            if b.labels:
                bd["labels"] = sorted(b.labels)
            if include_layout:
                bd["bbox"] = b.bbox.to_list()
                bd["region"] = b.region
                bd["column"] = b.column
                bd["raw"] = b.raw_text
                conf = b.confidence
                if conf is not None:
                    bd["confidence"] = round(conf, 1)
            blocks.append(bd)
        pd["blocks"] = blocks
        if include_layout and p.layout is not None:
            pd["layout"] = _region_to_dict(p.layout)
        pages.append(pd)
    out["pages"] = pages
    return out


def render_json(doc: Document) -> str:
    return json.dumps(document_to_dict(doc, include_layout=True), ensure_ascii=False, indent=2) + "\n"
