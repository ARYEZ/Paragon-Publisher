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
    C:\\ttsenv\\Scripts\\pip install "transformers<5"   # XTTS needs the 4.x API (isin_mps_friendly)
    # (nvidia-cublas-cu12 / nvidia-cudnn-cu12 are pulled in by torch's CUDA build)

    # For the Chatterbox engine (MIT, faster) use a SEPARATE venv (it needs
    # transformers 5 and torch==2.6.0, which conflict with XTTS):
    py -3.12 -m venv C:\\cbenv
    C:\\cbenv\\Scripts\\pip install chatterbox-tts
    C:\\cbenv\\Scripts\\pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124

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


def _builtin_speakers(model):
    """Return XTTS's built-in (studio) speaker names, or [] if unavailable."""
    try:
        spk = getattr(model, "speakers", None)
        if spk:
            return list(spk)
    except Exception:
        pass
    try:
        return list(model.synthesizer.tts_model.speaker_manager.speaker_names)
    except Exception:
        return []


def _synth_chatterbox(model, req, out):
    """Synthesize one request with Chatterbox and save to `out`."""
    import torchaudio as ta
    text = (req.get("text") or "").strip()
    spk_wav = (req.get("speaker_wav") or "").strip()
    gkw = {}
    if spk_wav and os.path.isfile(spk_wav):
        gkw["audio_prompt_path"] = spk_wav   # clone; omitted => built-in default voice
    if req.get("temperature") is not None:
        gkw["temperature"] = float(req["temperature"])
    if req.get("exaggeration") is not None:
        gkw["exaggeration"] = float(req["exaggeration"])
    if req.get("cfg") is not None:
        gkw["cfg_weight"] = float(req["cfg"])
    try:
        wav = model.generate(text, **gkw)
    except TypeError:
        wav = model.generate(text, **{k: v for k, v in gkw.items()
                                      if k in ("audio_prompt_path",)})
    try:
        wav = wav.detach().cpu()
    except Exception:
        pass
    if hasattr(wav, "dim") and wav.dim() == 1:
        wav = wav.unsqueeze(0)
    ta.save(out, wav, model.sr)


def _synth_xtts(model, req, out):
    """Synthesize one request with XTTS and save to `out`."""
    text = (req.get("text") or "").strip()
    builtin = (req.get("speaker") or "").strip()      # built-in voice name
    spk_wav = (req.get("speaker_wav") or "").strip()  # clone reference clip
    lang = req.get("language") or "en"
    kwargs = {"text": text, "language": lang, "file_path": out}
    if builtin:
        kwargs["speaker"] = builtin
    elif os.path.isfile(spk_wav):
        kwargs["speaker_wav"] = spk_wav
    else:
        raise ValueError("no built-in voice selected and no valid sample")
    extra = {}
    if req.get("temperature") is not None:
        extra["temperature"] = float(req["temperature"])
    if req.get("speed") is not None:
        extra["speed"] = float(req["speed"])
    if req.get("split") is not None:
        extra["enable_text_splitting"] = bool(req["split"])
    try:
        model.tts_to_file(**kwargs, **extra)
    except TypeError:
        model.tts_to_file(**kwargs)   # older coqui-tts: drop unsupported kwargs


def serve(engine="xtts", model_name=XTTS_MODEL):
    """Persistent mode: load the chosen engine once, then read one JSON request
    per line from stdin and reply with one JSON line on stdout. All library
    chatter is routed to stderr so stdout carries only the JSON protocol.

    Reply:  {"ready": true, "device": "cuda", "engine": "...", "speakers": [...]}
            {"ok": true, "device": "cuda", "out": "out.wav"}  (per request)
            {"ok": false, "error": "..."}"""
    import json as _json
    _add_cuda_dll_dirs()
    real_out = sys.stdout
    sys.stdout = sys.stderr  # keep the protocol stream clean

    def respond(obj):
        try:
            real_out.write(_json.dumps(obj) + "\n")
            real_out.flush()
        except Exception:
            pass

    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        respond({"ready": False, "error": f"PyTorch not available: {e}"})
        return 3

    speakers = []
    try:
        if engine == "chatterbox":
            from chatterbox.tts import ChatterboxTTS
            model = ChatterboxTTS.from_pretrained(device=dev)
        else:
            _allowlist_xtts()
            from TTS.api import TTS as _TTS
            model = _TTS(model_name)
            try:
                model = model.to(dev)
            except Exception:
                dev = "cpu"
            speakers = _builtin_speakers(model)
    except Exception as e:
        respond({"ready": False, "error": f"{type(e).__name__}: {e}"})
        return 1

    respond({"ready": True, "device": dev, "engine": engine, "speakers": speakers})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = _json.loads(line)
        except Exception:
            respond({"ok": False, "error": "bad request json"})
            continue
        if req.get("cmd") == "quit":
            break
        try:
            if not (req.get("text") or "").strip():
                raise ValueError("empty text")
            out = req.get("out") or ""
            if not out:
                raise ValueError("no output path")
            if engine == "chatterbox":
                _synth_chatterbox(model, req, out)
            else:
                _synth_xtts(model, req, out)
            respond({"ok": True, "device": dev, "out": out})
        except Exception as e:
            respond({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return 0


def main():
    ap = argparse.ArgumentParser(description="Paragon TTS worker (XTTS-v2)")
    ap.add_argument("--check", action="store_true",
                    help="verify torch + TTS import and print the device")
    ap.add_argument("--serve", action="store_true",
                    help="persistent mode: keep the model loaded and take JSON requests on stdin")
    ap.add_argument("--engine", default="xtts", choices=["xtts", "chatterbox"],
                    help="which TTS engine to load")
    ap.add_argument("--text-file", help="UTF-8 file with the text to narrate")
    ap.add_argument("--speaker", help="reference voice clip (wav/mp3) to clone")
    ap.add_argument("--language", default="en")
    ap.add_argument("--out", help="output wav path")
    ap.add_argument("--model", default=XTTS_MODEL)
    a = ap.parse_args()

    if a.serve:
        return serve(a.engine, a.model)

    _add_cuda_dll_dirs()

    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"ERROR: PyTorch not available: {e}", file=sys.stderr)
        return 3

    if a.check:
        try:
            if a.engine == "chatterbox":
                import chatterbox  # noqa: F401
            else:
                import TTS  # noqa: F401
        except Exception as e:
            pkg = "chatterbox-tts" if a.engine == "chatterbox" else "coqui-tts"
            print(f"ERROR: {pkg} not available: {e}", file=sys.stderr)
            return 4
        print(f"OK device={dev} engine={a.engine} torch={torch.__version__}")
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
