import json
from pathlib import Path

import pytest

from pazufa_pdf_parser.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, main


def write(tmp_path, name, data):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_single_file_to_stdout(tmp_path, letter_pdf, capsys):
    p = write(tmp_path, "brief.pdf", letter_pdf)
    assert main([str(p), "--ocr", "never", "-q"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Verband der Testbetriebe")
    assert "Sehr geehrte Frau Muster," in out


def test_explicit_extract_and_format(tmp_path, letter_pdf, capsys):
    p = write(tmp_path, "brief.pdf", letter_pdf)
    assert main(["extract", str(p), "-f", "json", "--ocr", "never", "-q"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["pages"][0]["blocks"]


def test_multiple_formats_to_directory(tmp_path, letter_pdf, bill_pdf, capsys):
    indir = tmp_path / "in"
    indir.mkdir()
    write(indir, "brief.pdf", letter_pdf)
    write(indir, "gesetz.pdf", bill_pdf)
    (indir / "notes.txt").write_text("ignore me")
    out = tmp_path / "out"
    assert main([str(indir), "-f", "txt,json", "-f", "html", "-o", str(out), "--ocr", "never"]) == EXIT_OK
    names = sorted(p.name for p in out.iterdir())
    assert names == ["brief.html", "brief.json", "brief.txt", "gesetz.html", "gesetz.json", "gesetz.txt"]
    err = capsys.readouterr().err
    assert "brief.pdf: 2 page(s)" in err and "gesetz.pdf: 2 page(s)" in err


def test_refuses_overwrite(tmp_path, letter_pdf, capsys):
    p = write(tmp_path, "brief.pdf", letter_pdf)
    out = tmp_path / "out"
    assert main([str(p), "-o", str(out), "--ocr", "never", "-q"]) == EXIT_OK
    assert main([str(p), "-o", str(out), "--ocr", "never", "-q"]) == EXIT_FAILED
    assert "exists" in capsys.readouterr().err
    assert main([str(p), "-o", str(out), "--ocr", "never", "-q", "--overwrite"]) == EXIT_OK


def test_multiple_inputs_need_output_dir(tmp_path, letter_pdf, capsys):
    a = write(tmp_path, "a.pdf", letter_pdf)
    b = write(tmp_path, "b.pdf", letter_pdf)
    assert main([str(a), str(b)]) == EXIT_USAGE
    assert "-o DIR" in capsys.readouterr().err


@pytest.mark.parametrize(
    "first,extra,written,error",
    [
        ("not-a-pdf", [], [], "bad.pdf: error: "),
        ("missing", [], [], "bad.pdf: no such file"),
        # forced OCR without tesseract: written, but its text is likely incomplete
        ("error-issue", ["--ocr", "always", "--tesseract", "no-such-tesseract"], ["bad.txt"], "bad.pdf: error: ocr: "),
        # checked before the parse: bad.txt is not written either
        ("exists", ["-f", "txt,json"], ["bad.json"], "bad.json: exists"),
    ],
)
def test_first_failure_stops_the_run(tmp_path, letter_pdf, capsys, first, extra, written, error):
    bad = tmp_path / "bad.pdf"
    if first != "missing":
        bad.write_bytes(b"not a pdf at all" if first == "not-a-pdf" else letter_pdf)
    good = write(tmp_path, "good.pdf", letter_pdf)
    out = tmp_path / "out"
    if first == "exists":
        write(out, "bad.json", b"")
    assert main([str(bad), str(good), "-o", str(out), "-q", *extra]) == EXIT_FAILED
    assert (sorted(p.name for p in out.iterdir()) if out.exists() else []) == written  # good.pdf never parsed
    assert error in capsys.readouterr().err


@pytest.mark.parametrize(
    "flags,prefix",
    [(["-q"], "{f}: error: ocr p"), (["-q", "-v"], "{f}: [error] ocr p")],
    ids=["quiet", "quiet-verbose"],
)
def test_error_issue_lines_name_file_and_page(tmp_path, capsys, flags, prefix):
    from pdfgen import T, make_scanned_pdf
    from test_pipeline import fake_tesseract

    scan = [[T(70, 100, "Seite eins", 14)], [T(70, 100, "Seite zwei", 14)]]
    p = write(tmp_path, "scan.pdf", make_scanned_pdf(scan, dpi=72))
    cmd = fake_tesseract(tmp_path, tmp_path / "runs", exit_code=1)
    assert main([str(p), "-o", str(tmp_path / "out"), "--tesseract", cmd, *flags]) == EXIT_FAILED
    err = capsys.readouterr().err.splitlines()
    failed = [line for line in err if "OCR failed" in line]
    assert len(failed) == 2, err  # once per page, also with -v
    for n, line in enumerate(failed, 1):
        assert line.startswith(f"{prefix.format(f=p)}{n}: OCR failed: tesseract failed (1): "), line
    assert failed[0].endswith(": page image unreadable") and "" not in err  # tesseract's newline stripped


def test_missing_input(tmp_path, capsys):
    assert main([str(tmp_path / "nope.pdf")]) == EXIT_FAILED


def test_unknown_format(tmp_path, letter_pdf, capsys):
    p = write(tmp_path, "brief.pdf", letter_pdf)
    assert main([str(p), "-f", "docx"]) == EXIT_USAGE
    assert "unknown format" in capsys.readouterr().err


def test_formats_command(capsys):
    assert main(["formats"]) == EXIT_OK
    out = capsys.readouterr().out
    for f in ("raw", "txt", "html", "json"):
        assert f in out


def test_no_args_is_usage_error(capsys):
    assert main([]) == EXIT_USAGE


def test_bad_option(capsys):
    assert main(["x.pdf", "--ocr", "sometimes"]) == EXIT_USAGE


def test_verbose_prints_issues(tmp_path, capsys):
    from pdfgen import T, make_scanned_pdf

    p = write(tmp_path, "scan.pdf", make_scanned_pdf([[T(70, 100, "Hallo", 14)]], dpi=72))
    main([str(p), "-v", "--tesseract", "no-such-tesseract-binary", "-o", str(tmp_path / "o")])
    assert "[warning] ocr" in capsys.readouterr().err


@pytest.mark.parametrize(
    "inputs,fmt,outputs",
    [
        # the third "y/doc.pdf" must not overwrite the second
        (["x/doc.pdf", "y/doc.pdf", "z/y/doc.pdf"], "txt", ["doc.txt", "y_doc.txt", "y_doc_2.txt"]),
        # one file on case-insensitive disks (macOS, Windows)
        (["a/Antrag.pdf", "b/antrag.pdf"], "txt", ["Antrag.txt", "b_antrag.txt"]),
        # "x" as raw and "x.raw" as txt both write x.raw.txt
        (["x.pdf", "x.raw.pdf"], "raw,txt", ["in_x.raw.raw.txt", "in_x.raw.txt", "x.raw.txt", "x.txt"]),
    ],
    ids=["same-name", "differ-in-case", "same-output-file"],
)
def test_outputs_never_overwrite_each_other(tmp_path, letter_pdf, bill_pdf, capsys, inputs, fmt, outputs):
    pdfs = [letter_pdf, bill_pdf, letter_pdf]
    paths = [write(tmp_path / "in" / Path(name).parent, Path(name).name, pdf) for name, pdf in zip(inputs, pdfs)]
    out = tmp_path / "out"
    assert main([*map(str, paths), "-f", fmt, "-o", str(out), "--ocr", "never", "-q", "--overwrite"]) == EXIT_OK
    assert sorted(p.name for p in out.iterdir()) == outputs
    assert "Gesetz" in (out / outputs[1]).read_text()


@pytest.mark.parametrize(
    "output,files",
    [("file", None), ("read-only", ["brief.txt"]), ("directory-in-the-way", ["a.txt", "brief.txt"])],
)
def test_unwritable_output(tmp_path, letter_pdf, capsys, output, files):
    a, b = write(tmp_path, "a.pdf", letter_pdf), write(tmp_path, "brief.pdf", letter_pdf)
    out = tmp_path / "out"
    if output == "file":
        out.write_text("")
    else:
        (out / "brief.txt").mkdir(parents=True)  # the rename of brief.txt.part fails
        if output == "read-only":
            out.chmod(0o500)
    try:
        assert main([str(a), str(b), "-o", str(out), "--ocr", "never", "-q", "--overwrite"]) == EXIT_FAILED
    finally:
        out.chmod(0o700)
    # the first failed write ends the run and leaves no .part file
    assert capsys.readouterr().err.count("error:") == 1
    assert files is None or sorted(p.name for p in out.iterdir()) == files


def test_invalid_page_range_is_usage_error(tmp_path, letter_pdf, capsys):
    p = write(tmp_path, "brief.pdf", letter_pdf)
    assert main([str(p), "--pages", "3-1"]) == EXIT_USAGE
    assert "after last_page" in capsys.readouterr().err
