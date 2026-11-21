"""Command line interface.

pazufa-pdf-parser [extract] INPUT... [-f FORMAT[,FORMAT]] [-o OUTDIR|-] [options]
pazufa-pdf-parser formats
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import PageSource, PazufaError, __version__, parse
from ._options import Ocr, OcrMode, ParseOptions
from ._pipeline.render import available_formats, get_renderer

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
SUBCOMMANDS = ("extract", "formats")


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
    g.add_argument(
        "--ocr",
        choices=[m.value for m in OcrMode],
        default="auto",
        help="OCR mode (default: auto = only pages without usable text)",
    )
    g.add_argument("--lang", default="deu", help="tesseract languages, e.g. deu or deu+eng (default: deu)")
    g.add_argument("--dpi", type=int, default=300, help="render resolution for OCR (default: 300)")
    g.add_argument("--jobs", "-j", type=int, default=None, help="tesseract processes at a time")
    g.add_argument("--no-osd", action="store_true", help="disable orientation detection for scans")
    g.add_argument("--password", default=None, help="password for encrypted PDFs")
    g.add_argument("--pages", type=_page_range, default=None, metavar="RANGE", help="page range, e.g. 1-3")
    g.add_argument("--strict", action="store_true", help="fail on the first step error instead of recording it")
    g.add_argument("--tesseract", default="tesseract", help="tesseract executable")


def _options(args: argparse.Namespace) -> ParseOptions:
    engine = dict(
        languages=args.lang,
        dpi=args.dpi,
        detect_orientation=not args.no_osd,
        tesseract_cmd=args.tesseract,
    )
    if args.jobs:
        engine["max_parallel"] = max(1, args.jobs)
    kw = dict(ocr=OcrMode(args.ocr), ocr_engine=Ocr(**engine), strict=args.strict, password=args.password)
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
    ap = argparse.ArgumentParser(
        prog="pazufa-pdf-parser", description="Extract clean text and layout from PDF documents."
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command")

    ex = sub.add_parser("extract", help="extract and render documents (default command)")
    ex.add_argument("inputs", nargs="+", help="PDF files or directories")
    ex.add_argument(
        "-f",
        "--format",
        action="append",
        help=f"output format(s), comma separated or repeated: {', '.join(available_formats())} (default: txt)",
    )
    ex.add_argument(
        "-o",
        "--output",
        default=None,
        help="output directory, or '-' for stdout (default: stdout for a single input and format)",
    )
    ex.add_argument("-r", "--recursive", action="store_true", help="recurse into directories")
    ex.add_argument("--overwrite", action="store_true", help="overwrite existing output files")
    ex.add_argument("-q", "--quiet", action="store_true", help="no progress output on stderr")
    ex.add_argument("-v", "--verbose", action="store_true", help="print issues recorded during processing")
    _add_parse_options(ex)

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
    return _cmd_extract(args, ap)


def _output_stem(f: Path, extensions: list[str], used: set[str]) -> str:
    """The file name for this input's outputs. Inputs of the same name from different directories get
    their directory name, then a counter, so none overwrites another; names are compared case-folded
    for macOS and Windows disks, and per output file ("x.pdf" as raw and "x.raw.pdf" as txt clash)."""

    def taken(stem: str) -> bool:
        return any(f"{stem}.{ext}".casefold() in used for ext in extensions)

    stem = f.stem if not taken(f.stem) else f"{f.parent.name}_{f.stem}"
    base, n = stem, 1
    while taken(stem):
        n += 1
        stem = f"{base}_{n}"
    used.update(f"{stem}.{ext}".casefold() for ext in extensions)
    return stem


def _cmd_extract(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    fmts = _formats(args.format)
    unknown = [f for f in fmts if f not in available_formats()]
    if unknown:
        print(
            f"error: unknown format(s): {', '.join(unknown)}; available: {', '.join(available_formats())}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    # fail fast: the first failing input ends the run, before any later one is parsed
    files, missing = _collect(args.inputs, args.recursive)
    for m in missing:
        print(f"{m}: no such file or directory", file=sys.stderr)
    if missing:
        return EXIT_FAILED
    if not files:
        print("error: no PDF files found", file=sys.stderr)
        return EXIT_FAILED
    to_stdout = args.output == "-" or (args.output is None and len(files) == 1 and len(fmts) == 1)
    if args.output is None and not to_stdout:
        print("error: several inputs or formats need an output directory (-o DIR)", file=sys.stderr)
        return EXIT_USAGE
    try:
        opts = _options(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    outdir = None if to_stdout else Path(args.output)
    try:
        if outdir is not None:
            outdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{outdir}: error: {e}", file=sys.stderr)
        return EXIT_FAILED
    used_names: set[str] = set()
    for f in files:
        t0 = time.perf_counter()
        try:
            doc = parse(f, opts)
        except PazufaError as e:
            print(f"{f}: error: {e}", file=sys.stderr)
            return EXIT_FAILED
        except Exception as e:  # noqa: BLE001 - a message, not a traceback
            print(f"{f}: unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            return EXIT_FAILED
        written = []
        stem = _output_stem(f, [get_renderer(fmt).extension for fmt in fmts], used_names)
        for fmt in fmts:
            r = get_renderer(fmt)
            try:
                content = r.func(doc)
            except Exception as e:  # noqa: BLE001
                print(f"{f}: rendering {fmt} failed: {type(e).__name__}: {e}", file=sys.stderr)
                return EXIT_FAILED
            if outdir is None:
                sys.stdout.write(content)
                if len(files) > 1 or len(fmts) > 1:
                    sys.stdout.write("\n")
                continue
            target = outdir / f"{stem}.{r.extension}"
            if target.exists() and not args.overwrite:
                print(f"{target}: exists (use --overwrite)", file=sys.stderr)
                return EXIT_FAILED
            tmp = target.with_suffix(target.suffix + ".part")
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(target)
            except OSError as e:  # a full disk or read-only directory
                tmp.unlink(missing_ok=True)
                print(f"{target}: error: {e}", file=sys.stderr)
                return EXIT_FAILED
            written.append(str(target))
        errors = [i for i in doc.report.issues if i.severity == "error"]
        if not args.quiet:
            ocr = sum(p.source is PageSource.OCR for p in doc.pages)
            info = f"{f}: {len(doc.pages)} page(s)" + (f", {ocr} OCR" if ocr else "")
            info += f", {time.perf_counter() - t0:.1f}s"
            if errors:
                info += f", {len(errors)} error(s)"
            if written:
                info += " -> " + ", ".join(written)
            print(info, file=sys.stderr)
        if args.verbose:
            for i in doc.report.issues:
                where = f" p{i.page}" if i.page else ""
                print(f"  [{i.severity}] {i.step}{where}: {i.message}", file=sys.stderr)
        if errors:  # the outputs are written, but their text is likely incomplete
            if not args.verbose:
                for i in errors:
                    print(f"{f}: error: {i.step}: {i.message}", file=sys.stderr)
            return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
