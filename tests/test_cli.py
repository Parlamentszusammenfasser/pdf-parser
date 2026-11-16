import json

from pazufa_pdf_parser.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, main


def write(tmp_path, name, data):
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


def test_bad_input_does_not_stop_batch(tmp_path, letter_pdf, capsys):
    good = write(tmp_path, "good.pdf", letter_pdf)
    bad = write(tmp_path, "bad.pdf", b"not a pdf at all")
    out = tmp_path / "out"
    assert main([str(bad), str(good), "-o", str(out), "--ocr", "never"]) == EXIT_FAILED
    assert (out / "good.txt").exists()
    assert "bad.pdf: error" in capsys.readouterr().err


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
