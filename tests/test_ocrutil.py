"""OCR must survive a GBK decode failure on Chinese Windows."""

import subprocess

from PIL import Image

from hdpoker.ocrutil import ocr_image, ocr_tsv


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
