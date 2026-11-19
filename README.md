# HD Poker hand capture

Reads one 6-max HD Poker table from the screen and writes a hand when it ends.
Actions come from the labels under each name: CHECK, BET, CALL, RAISE, ALL IN, and FOLD.
WAITING and SITTING OUT are not actions. `post` is only the 0.5 BB and 1 BB blinds.
Anything that is not on a frame stays `unknown`. The hand-strength bar is ignored, and the program does not suggest a bet.

Python 3.11 or newer. Vision uses [Tesseract](https://github.com/tesseract-ocr/tesseract) and card-corner templates taken from `samples/`.

```bash
pip install -e .
# Linux or macOS, on the seven sample frames:
python -m hdpoker.replay
# Windows, on the live HD Poker window:
python -m hdpoker.capture
```

Capture keeps only the current frame and the previous one in memory. It does not save screenshots.
When a hand ends it writes `hands/<YYYYMMDD_HHMMSS>_<n>.json` and `.txt`.
The Win32 grabber is in `hdpoker/win32cap.py` and is imported only on Windows.

`hdpoker.schema.sample_hand()` is the hand the plan described.
Replay prints what the screenshots actually produced next to that description.
