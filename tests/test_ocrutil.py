"""OCR must survive a GBK decode failure and a Windows tessdata miss."""

import subprocess
from pathlib import Path

from PIL import Image

import hdpoker.ocrutil as ocrutil
from hdpoker.ocrutil import ocr_image, ocr_tsv, tessdata_dir, tesseract_executable


def _image():
    return Image.new("L", (8, 8), 255)


def test_ocr_image_decodes_utf8_and_treats_missing_stdout_as_empty(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=None, stderr=None)

    monkeypatch.setattr("hdpoker.ocrutil.tesseract_available", lambda: True)
    monkeypatch.setattr("hdpoker.ocrutil.subprocess.run", fake_run)
    assert ocr_image(_image()) == ""
    assert seen["kwargs"]["encoding"] == "utf-8"
    assert seen["kwargs"]["errors"] == "replace"


def test_ocr_image_swallows_a_decode_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise UnicodeDecodeError("gbk", b"\xff", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("hdpoker.ocrutil.tesseract_available", lambda: True)
    monkeypatch.setattr("hdpoker.ocrutil.subprocess.run", fake_run)
    assert ocr_image(_image()) == ""


def test_ocr_tsv_uses_utf8_and_survives_a_failed_process(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["kwargs"] = kwargs
        raise UnicodeDecodeError("gbk", b"\xff", 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("hdpoker.ocrutil.tesseract_available", lambda: True)
    monkeypatch.setattr("hdpoker.ocrutil.subprocess.run", fake_run)
    assert ocr_tsv(_image()) == []
    assert seen["kwargs"]["encoding"] == "utf-8"
    assert seen["kwargs"]["errors"] == "replace"


def test_failed_tesseract_prints_stderr_once_and_returns_empty(monkeypatch, capsys):
    ocrutil._failure_reported = False

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=(
                "Error opening data file eng.traineddata\n"
                'Please make sure the TESSDATA_PREFIX environment variable is set to your "tessdata" directory.\n'
            ),
        )

    monkeypatch.setattr("hdpoker.ocrutil.tesseract_available", lambda: True)
    monkeypatch.setattr("hdpoker.ocrutil.subprocess.run", fake_run)
    assert ocr_image(_image()) == ""
    assert ocr_image(_image()) == ""
    assert capsys.readouterr().err.count("TESSDATA_PREFIX") == 1


def test_missing_tesseract_does_not_raise(monkeypatch, capsys):
    ocrutil._failure_reported = False
    monkeypatch.setattr("hdpoker.ocrutil.tesseract_available", lambda: False)
    assert ocr_image(_image()) == ""
    assert ocr_tsv(_image()) == []
    err = capsys.readouterr().err
    assert "Tesseract-OCR" in err
    assert err.count("tesseract not found") == 1


def test_mannheim_tessdata_is_passed_to_tesseract(monkeypatch, tmp_path, capsys):
    root = tmp_path / "Tesseract-OCR"
    tess = root / "tessdata"
    tess.mkdir(parents=True)
    (tess / "eng.traineddata").write_bytes(b"trained")
    exe = root / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(ocrutil, "_INSTALL_ROOTS", (root,))
    monkeypatch.setattr(ocrutil.shutil, "which", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "missing-parent"))
    assert tesseract_executable() == str(exe)
    assert tessdata_dir(str(exe)) == tess
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0, stdout="TDawn", stderr="")

    monkeypatch.setattr(ocrutil.subprocess, "run", fake_run)
    assert ocr_image(_image()) == "TDawn"
    command = seen["command"]
    assert command[0] == str(exe)
    assert command[command.index("--tessdata-dir") + 1] == str(tess)
    assert seen["env"]["TESSDATA_PREFIX"] == str(tess)
    assert capsys.readouterr().err == ""


def test_locked_temp_png_does_not_escape(monkeypatch):
    monkeypatch.setattr(ocrutil, "tesseract_available", lambda: True)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="OK", stderr="")

    monkeypatch.setattr(ocrutil.subprocess, "run", fake_run)
    original = Path.unlink

    def locked(self, missing_ok=False):
        if self.suffix == ".png":
            raise PermissionError("locked")
        return original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    assert ocr_image(_image()) == "OK"
