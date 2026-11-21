"""Small wrappers around the tesseract binary.

Action labels are accepted only when the text is one of the on-screen words.
Anything else stays unread.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from hdpoker.reading import STATUS_WORDS

_BB_RE = re.compile(r"(\d+(?:\.\d+)?)[.\s]*BB\b", re.IGNORECASE)
_BLINDS_RE = re.compile(r"(\d{2,5})\s*/\s*(\d{2,5})")
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,16}")
_WORD_RE = re.compile(r"[A-Z]+(?:\s+[A-Z]+)?")

# UB Mannheim's Windows installer. ``tesseract --version`` succeeds without
# language data; OCR fails unless this tessdata directory is passed explicitly.
_INSTALL_ROOTS = (
    Path(r"C:\Program Files\Tesseract-OCR"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR"),
)
_failure_reported = False


def tesseract_executable() -> str | None:
    """The tesseract binary on PATH, or the UB Mannheim install."""
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return found
    for root in _INSTALL_ROOTS:
        exe = root / "tesseract.exe"
        if exe.is_file():
            return str(exe)
    return None


def tesseract_available() -> bool:
    return tesseract_executable() is not None


def tessdata_dir(executable: str | None = None) -> Path | None:
    """Directory that contains ``eng.traineddata``.

    Tesseract 5 treats both ``--tessdata-dir`` and ``TESSDATA_PREFIX`` as that
    directory, not its parent. ``--version`` does not check it, so a working
    version command can still mean every OCR call exits 1.
    """
    candidates: list[Path] = []
    if executable:
        candidates.append(Path(executable).resolve().parent / "tessdata")
    for root in _INSTALL_ROOTS:
        candidates.append(root / "tessdata")
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        folder = Path(prefix)
        candidates.append(folder)
        candidates.append(folder / "tessdata")
    for folder in candidates:
        if (folder / "eng.traineddata").is_file():
            return folder
    return None


def _report_tesseract_failure(detail: str) -> None:
    """Print tesseract's own stderr once. Later frames stay quiet."""
    global _failure_reported
    if _failure_reported:
        return
    _failure_reported = True
    text = (detail or "tesseract failed").strip()
    print(text, file=sys.stderr, flush=True)


def _tesseract_invocation(image: str, output: str, psm: int, whitelist: str | None = None) -> tuple[list[str], dict[str, str] | None]:
    executable = tesseract_executable() or "tesseract"
    command = [executable, image, output, "--psm", str(psm), "-l", "eng"]
    data = tessdata_dir(executable)
    env = None
    if data is not None:
        command.extend(["--tessdata-dir", str(data)])
        env = os.environ.copy()
        env["TESSDATA_PREFIX"] = str(data)
    if whitelist:
        command.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
    return command, env


def _run_tesseract(command: list[str], env: dict[str, str] | None = None) -> str:
    """Run tesseract and return stdout as text.

    Chinese Windows defaults to GBK. Forcing UTF-8 avoids UnicodeDecodeError
    in the subprocess reader thread. A missing stdout is empty text. A non-zero
    exit is reported once from stderr and does not propagate.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
    except Exception as exc:
        _report_tesseract_failure(str(exc))
        return ""
    if result.returncode != 0:
        _report_tesseract_failure(result.stderr or f"tesseract exited {result.returncode}")
    return result.stdout or ""


def ocr_image(image: Image.Image, psm: int = 7, whitelist: str | None = None) -> str:
    if not tesseract_available():
        _report_tesseract_failure(
            "tesseract not found. Expected it on PATH or at C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        )
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = Path(handle.name)
        try:
            image.save(path)
            command, env = _tesseract_invocation(str(path), "stdout", psm, whitelist)
            stdout = _run_tesseract(command, env)
        finally:
            # Windows can keep the temp png locked for a moment. That must not
            # abort the frame.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception as exc:
        _report_tesseract_failure(str(exc))
        return ""
    return " ".join(stdout.split())


def ocr_tsv(image: Image.Image, psm: int = 11) -> list[dict]:
    """Word boxes in the image's own pixel coordinates."""
    if not tesseract_available():
        _report_tesseract_failure(
            "tesseract not found. Expected it on PATH or at C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        )
        return []
    try:
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "ocr"
            image.save(stem.with_suffix(".png"))
            command, env = _tesseract_invocation(str(stem.with_suffix(".png")), str(stem), psm)
            command.append("tsv")
            _run_tesseract(command, env)
            tsv_path = stem.with_suffix(".tsv")
            if not tsv_path.exists():
                return []
            rows = []
            for line in tsv_path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) < 12 or not parts[11].strip():
                    continue
                try:
                    conf = float(parts[10])
                except ValueError:
                    continue
                if conf < 35:
                    continue
                rows.append(
                    {
                        "text": parts[11],
                        "left": int(parts[6]),
                        "top": int(parts[7]),
                        "width": int(parts[8]),
                        "height": int(parts[9]),
                        "conf": conf,
                    }
                )
            return rows
    except Exception as exc:
        _report_tesseract_failure(str(exc))
        return []


def match_status(text: str | None) -> str | None:
    """Return a vocabulary status word, or None when the text is not one of them."""
    if not text:
        return None
    cleaned = " ".join(text.upper().split())
    cleaned = re.sub(r"[^A-Z ]", "", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.replace("SITTINGOUT", "SITTING OUT").replace("ALLIN", "ALL IN")
    if cleaned in STATUS_WORDS:
        return cleaned
    for word in sorted(STATUS_WORDS, key=len, reverse=True):
        if word in cleaned and _WORD_RE.fullmatch(cleaned):
            # "CHECK" inside a longer garbage string is not a label.
            if cleaned == word:
                return word
    return None


def parse_bb(text: str | None) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    match = _BB_RE.search(text.replace(",", ""))
    if not match:
        return None, None
    value = float(match.group(1))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return value, f"{text} BB"


def parse_number(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"\d+\.\d+|\d+", text.replace(",", "").replace("-", "."))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_blinds(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    match = _BLINDS_RE.search(text)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_name(text: str | None) -> str | None:
    if not text:
        return None
    # Keep the longest token that looks like a screen name.
    found = _NAME_RE.findall(text)
    if not found:
        return None
    found.sort(key=len, reverse=True)
    return found[0]


def green_mask(image: Image.Image) -> Image.Image:
    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    mask = (green > 130) & (green > red + 25) & (green > blue + 15)
    cleaned = _drop_frame_lines(mask)
    return Image.fromarray(np.where(cleaned, 0, 255).astype(np.uint8))


def white_mask(image: Image.Image, minimum: int = 200) -> Image.Image:
    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    mask = (red >= minimum) & (green >= minimum) & (blue >= minimum - 8)
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))


def _drop_frame_lines(mask: np.ndarray) -> np.ndarray:
    """Remove the nameplate border so it is not read as part of the name."""
    height, width = mask.shape
    out = mask.copy()
    row_fill = out.mean(axis=1)
    col_fill = out.mean(axis=0)
    out[row_fill > 0.55, :] = False
    out[:, col_fill > 0.55] = False
    if height:
        out[: max(1, height // 12), :] = False
        out[-max(1, height // 12) :, :] = False
    if width:
        out[:, : max(1, width // 18)] = False
        out[:, -max(1, width // 14) :] = False
    return out
