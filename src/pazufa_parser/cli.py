"""Command line interface.

    pazufa-parser [extract] INPUT... [-f FORMAT[,FORMAT]] [-o OUTDIR|-] [options]
    pazufa-parser classify INPUT... [--json]
    pazufa-parser formats
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .api import parse
from .errors import PazufaError
from .options import OcrMode, ParseOptions
from .render import available_formats, get_renderer

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
SUBCOMMANDS = ("extract", "classify", "formats")

CLASSIFY_HEADER = ("file", "type", "confidence", "title")
CLASSIFY_COLUMNS_HELP = """output columns (tab-separated):
  file        path of the input PDF
  type        document type, optionally followed by /subtype:
                letter[/statement|administrative_decision|objection|invoice|reminder|termination]
                email
                parliamentary_print[/bill|report|amendment|motion|inquiry|answer|notice]
                plenary_protocol[/excerpt|full]
                statute[/act|regulation|bylaw]
                court_decision[/judgment|order]
                contract
                generic   (no type scored high enough)
  confidence  0.00-1.00; combines how strongly the winning type scored and how far
              it is ahead of the runner-up (use --json to see all scores)
  title       best-guess title: subject of a letter/e-mail, title of a print,
              agenda topic of a protocol, PDF metadata title or first heading"""


def _page_range(value: str) -> tuple[int | None, int | None]:
    try:
        if "-" in value:
            a, b = value.split("-", 1)
            return (int(a) if a else None, int(b) if b else None)
        n = int(value)
        return n, n
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid page range {value!r} (use e.g. 3, 2-5, 4-)") from None


def _formats(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or ["txt"]:
        for f in v.split(","):
            f = f.strip().lower()
            if f and f not in out:
                out.append(f)
    return out


def _add_parse_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("parsing")
    g.add_argument("--ocr", choices=[m.value for m in OcrMode], default="auto", help="OCR mode (default: auto = only pages without usable text)")
    g.add_argument("--lang", default="deu", help="tesseract languages, e.g. deu or deu+eng (default: deu)")
    g.add_argument("--dpi", type=int, default=300, help="render resolution for OCR (default: 300)")
    g.add_argument("--jobs", "-j", type=int, default=None, help="parallel OCR workers")
    g.add_argument("--no-osd", action="store_true", help="disable orientation detection for scans")
    g.add_argument("--password", default=None, help="password for encrypted PDFs")
    g.add_argument("--pages", type=_page_range, default=None, metavar="RANGE", help="page range, e.g. 1-3")
    g.add_argument("--strict", action="store_true", help="fail on the first step error instead of recording it")
    g.add_argument("--tesseract", default="tesseract", help="tesseract executable")


def _options(args: argparse.Namespace) -> ParseOptions:
    kw = dict(
        ocr=OcrMode(args.ocr),
        languages=tuple(x for x in args.lang.replace(",", "+").split("+") if x),
        dpi=args.dpi,
        detect_orientation=not args.no_osd,
        strict=args.strict,
        password=args.password,
        tesseract_cmd=args.tesseract,
    )
    if args.jobs:
        kw["jobs"] = max(1, args.jobs)
    if args.pages:
        kw["first_page"], kw["last_page"] = args.pages
    return ParseOptions(**kw)


def _collect(inputs: list[str], recursive: bool) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    missing: list[str] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files.extend(sorted(q for q in p.glob(pattern) if q.is_file() and q.suffix.lower() == ".pdf"))
        elif p.is_file():
            files.append(p)
        else:
            missing.append(raw)
    return files, missing


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pazufa-parser", description="Extract structured information and clean text from PDF documents.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command")

    ex = sub.add_parser("extract", help="extract and render documents (default command)")
    ex.add_argument("inputs", nargs="+", help="PDF files or directories")
    ex.add_argument("-f", "--format", action="append", help=f"output format(s), comma separated or repeated: {', '.join(available_formats())} (default: txt)")
    ex.add_argument("-o", "--output", default=None, help="output directory, or '-' for stdout (default: stdout for a single input and format)")
    ex.add_argument("-r", "--recursive", action="store_true", help="recurse into directories")
    ex.add_argument("--overwrite", action="store_true", help="overwrite existing output files")
    ex.add_argument("-q", "--quiet", action="store_true", help="no progress output on stderr")
    ex.add_argument("-v", "--verbose", action="store_true", help="print issues recorded during processing")
    _add_parse_options(ex)

    cl = sub.add_parser(
        "classify",
        help="only print the document classification",
        description="Classify documents. Prints one tab-separated row per input file (after a header row).",
        epilog=CLASSIFY_COLUMNS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cl.add_argument("inputs", nargs="+")
    cl.add_argument("-r", "--recursive", action="store_true")
    cl.add_argument("--json", action="store_true", help="JSON lines output (one object per file, includes all type scores)")
    cl.add_argument("--no-header", action="store_true", help="omit the header row of the tab-separated output")
    _add_parse_options(cl)

    sub.add_parser("formats", help="list output formats")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "extract")
    elif argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "extract")
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code not in (0, None) else EXIT_OK
    if args.command is None:
        ap.print_help(sys.stderr)
        return EXIT_USAGE
    if args.command == "formats":
        for name in available_formats():
            r = get_renderer(name)
            print(f"{name:10} .{r.extension:10} {r.description}")
        return EXIT_OK
    if args.command == "classify":
        return _cmd_classify(args)
    return _cmd_extract(args, ap)


def _cmd_classify(args: argparse.Namespace) -> int:
    files, missing = _collect(args.inputs, args.recursive)
    status = EXIT_OK
    for m in missing:
        print(f"{m}: no such file or directory", file=sys.stderr)
        status = EXIT_FAILED
    opts = _options(args)
    if not args.json and not args.no_header:
        print("\t".join(CLASSIFY_HEADER))
    for f in files:
        try:
            doc = parse(f, opts)
        except PazufaError as e:
            print(f"{f}: error: {e}", file=sys.stderr)
            status = EXIT_FAILED
            continue
        c = doc.classification
        if args.json:
            print(json.dumps({"file": str(f), "doc_type": str(c.doc_type), "subtype": c.subtype, "confidence": c.confidence, "scores": c.scores, "title": doc.fields.get("title")}, ensure_ascii=False))
        else:
            sub = f"/{c.subtype}" if c.subtype else ""
            title = " ".join(str(doc.fields.get("title", "")).split())  # no tabs/newlines inside a cell
            print(f"{f}\t{c.doc_type}{sub}\t{c.confidence:.2f}\t{title}")
    return status


def _cmd_extract(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    fmts = _formats(args.format)
    unknown = [f for f in fmts if f not in available_formats()]
    if unknown:
        print(f"error: unknown format(s): {', '.join(unknown)}; available: {', '.join(available_formats())}", file=sys.stderr)
        return EXIT_USAGE
    files, missing = _collect(args.inputs, args.recursive)
    status = EXIT_OK
    for m in missing:
        print(f"{m}: no such file or directory", file=sys.stderr)
        status = EXIT_FAILED
    if not files:
        if not missing:
            print("error: no PDF files found", file=sys.stderr)
        return EXIT_FAILED
    to_stdout = args.output == "-" or (args.output is None and len(files) == 1 and len(fmts) == 1)
    if args.output is None and not to_stdout:
        print("error: several inputs or formats need an output directory (-o DIR)", file=sys.stderr)
        return EXIT_USAGE
    outdir = None if to_stdout else Path(args.output)
    if outdir is not None:
        outdir.mkdir(parents=True, exist_ok=True)
    opts = _options(args)
    used_names: set[str] = set()
    for f in files:
        t0 = time.perf_counter()
        try:
            doc = parse(f, opts)
        except PazufaError as e:
            print(f"{f}: error: {e}", file=sys.stderr)
            status = EXIT_FAILED
            continue
        except Exception as e:  # noqa: BLE001 - never crash a batch on one file
            print(f"{f}: unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            status = EXIT_FAILED
            continue
        written = []
        stem = f.stem
        if stem in used_names:  # same file name from different directories
            stem = f"{f.parent.name}_{stem}"
        used_names.add(stem)
        for fmt in fmts:
            r = get_renderer(fmt)
            try:
                content = r.func(doc)
            except Exception as e:  # noqa: BLE001
                print(f"{f}: rendering {fmt} failed: {type(e).__name__}: {e}", file=sys.stderr)
                status = EXIT_FAILED
                continue
            if outdir is None:
                sys.stdout.write(content)
                if len(files) > 1 or len(fmts) > 1:
                    sys.stdout.write("\n")
                continue
            target = outdir / f"{stem}.{r.extension}"
            if target.exists() and not args.overwrite:
                print(f"{target}: exists (use --overwrite)", file=sys.stderr)
                status = EXIT_FAILED
                continue
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
            written.append(str(target))
        if not args.quiet:
            c = doc.classification
            sub = f"/{c.subtype}" if c.subtype else ""
            ocr = c.features.get("ocr_pages", 0)
            info = f"{f}: {c.doc_type}{sub} ({c.confidence:.2f}), {len(doc.pages)} page(s)" + (f", {ocr} OCR" if ocr else "")
            info += f", {time.perf_counter() - t0:.1f}s"
            errors = [i for i in doc.issues if i.severity == "error"]
            if errors:
                info += f", {len(errors)} error(s)"
            if written:
                info += " -> " + ", ".join(written)
            print(info, file=sys.stderr)
        if args.verbose:
            for i in doc.issues:
                where = f" p{i.page}" if i.page else ""
                print(f"  [{i.severity}] {i.step}{where}: {i.message}", file=sys.stderr)
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
