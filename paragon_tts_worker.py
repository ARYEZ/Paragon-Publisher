#!/usr/bin/env python3
"""Paragon TTS worker.

Runs under a SIDE Python 3.11-3.13 environment that has PyTorch + coqui-tts
installed, and synthesizes cloned-voice speech to a wav file. Paragon Publisher
(which runs on Python 3.14, where torch has no wheels) calls this as a
subprocess so voice cloning still works, locally and on the GPU.

Set up the side environment once, e.g. with Python 3.12:

    py -3.12 -m venv C:\\ttsenv
    C:\\ttsenv\\Scripts\\pip install coqui-tts
    C:\\ttsenv\\Scripts\\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
    # (nvidia-cublas-cu12 / nvidia-cudnn-cu12 are pulled in by torch's CUDA build)

Then point Paragon's Narration panel at:  C:\\ttsenv\\Scripts\\python.exe

Usage:
    python paragon_tts_worker.py --check
    python paragon_tts_worker.py --text-file in.txt --speaker voice.wav \
           --language en --out out.wav
"""
import argparse
import glob
import os
import sys

# XTTS shows an interactive "agree to the (non-commercial) ToS" prompt on first
# download. We run headless as a subprocess, so auto-agree to avoid a hang.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


def _add_cuda_dll_dirs():
    """On Windows, register the pip CUDA wheels' DLL folders so the GPU is found."""
    if not sys.platform.startswith("win"):
        return
    try:
        import nvidia  # namespace package the cu12 wheels install into
        for root in getattr(nvidia, "__path__", []):
            for bindir in glob.glob(os.path.join(root, "*", "bin")):
                if os.path.isdir(bindir):
                    try:
                        os.add_dll_directory(bindir)
                    except Exception:
                        pass
    except Exception:
        pass


def _allowlist_xtts():
    """torch >= 2.6 defaults to weights_only=True, which rejects XTTS's config
    classes on load. Register them as safe globals so the model loads."""
    try:
        import torch.serialization as _ts
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
        from TTS.config.shared_configs import BaseDatasetConfig
        _ts.add_safe_globals([XttsConfig, XttsAudioConfig, XttsArgs, BaseDatasetConfig])
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Paragon TTS worker (XTTS-v2)")
    ap.add_argument("--check", action="store_true",
                    help="verify torch + TTS import and print the device")
    ap.add_argument("--text-file", help="UTF-8 file with the text to narrate")
    ap.add_argument("--speaker", help="reference voice clip (wav/mp3) to clone")
    ap.add_argument("--language", default="en")
    ap.add_argument("--out", help="output wav path")
    ap.add_argument("--model", default=XTTS_MODEL)
    a = ap.parse_args()

    _add_cuda_dll_dirs()

    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"ERROR: PyTorch not available: {e}", file=sys.stderr)
        return 3

    if a.check:
        try:
            import TTS  # noqa: F401
        except Exception as e:
            print(f"ERROR: coqui-tts not available: {e}", file=sys.stderr)
            return 4
        print(f"OK device={dev} torch={torch.__version__}")
        return 0

    if not (a.text_file and a.speaker and a.out):
        print("ERROR: --text-file, --speaker and --out are required", file=sys.stderr)
        return 2
    try:
        with open(a.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception as e:
        print(f"ERROR: can't read text file: {e}", file=sys.stderr)
        return 2
    if not text:
        print("ERROR: empty text", file=sys.stderr)
        return 2
    if not os.path.isfile(a.speaker):
        print(f"ERROR: speaker file not found: {a.speaker}", file=sys.stderr)
        return 2

    try:
        _allowlist_xtts()
        from TTS.api import TTS as _TTS
        model = _TTS(a.model)
        try:
            model = model.to(dev)
        except Exception:
            dev = "cpu"
        model.tts_to_file(text=text, speaker_wav=a.speaker,
                          language=a.language, file_path=a.out)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"OK device={dev} out={a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
