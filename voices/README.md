# Voice models

Piper voice models go here — a `.onnx` and its matching `.onnx.json`.

They are downloads, not source, so they are not committed. Each is around
60 MB.

```bash
cd voices
../.venv/bin/python -m piper.download_voices en_US-lessac-medium
```

Any model in this directory appears in the **Voice** menu automatically, named
from its filename: `en_US-lessac-medium` is listed as "Lessac (medium)".

Browse what is available at <https://huggingface.co/rhasspy/piper-voices>.

For lower-powered hardware, prefer a `low` or `x_low` quality voice — the
latency difference is substantial and the quality difference is smaller than
you would expect.

espeak-ng needs nothing here; it carries its own voice data.
