# Building Paragon Publisher as a Windows program

This turns `paragon_publisher.py` into a standalone `Paragon Publisher.exe`
that runs like any normal Windows app — double-click to launch, no command
prompt, no Python required on the target machine.

The tool used is [PyInstaller](https://pyinstaller.org).

## Quick start (one click)

1. Make sure **Python 3.10+** is installed and on your PATH
   (tick *"Add Python to PATH"* in the installer).
2. Double-click **`build_windows.bat`**.
3. When it finishes, your program is at **`dist\Paragon Publisher.exe`**.

That's it. You can copy that single `.exe` anywhere and run it.

## What the build does

`build_windows.bat` runs:

```bat
pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean ^
  --name "Paragon Publisher" ^
  --windowed ^
  --onefile ^
  --collect-all customtkinter ^
  --collect-all tkinterdnd2 ^
  --collect-all PIL ^
  paragon_publisher.py
```

Why the flags matter:

- **`--windowed`** — runs as a GUI app with **no console window** behind it.
- **`--onefile`** — bundles everything into one `.exe` (easy to share).
- **`--collect-all customtkinter`** — CustomTkinter loads theme `.json` files
  at runtime; without this the app crashes on start with a missing-theme error.
- **`--collect-all tkinterdnd2`** — bundles the native `tkdnd` binaries that
  power drag-and-drop; without this drag-and-drop silently turns off.
- **`--collect-all PIL`** — safety net so Pillow's image plugins are included.

## Optional: an app icon

Put an `app.ico` file next to `build_windows.bat` and add this flag to the
`pyinstaller` command in the `.bat`:

```
--icon app.ico
```

(You can convert a PNG to `.ico` at many free online converters.)

## ffprobe (for the "Stream Details" tab)

The editor reads codec / resolution / audio-track info by calling **ffprobe**
(part of FFmpeg). This is an *external* program and is **not** bundled.

- Install FFmpeg from <https://ffmpeg.org/download.html> and make sure
  `ffprobe.exe` is on your PATH, **or**
- Drop `ffprobe.exe` in the same folder as `Paragon Publisher.exe`.

Everything else works without it — only the Stream Details fields stay blank.

## `--onefile` vs `--onedir`

- **`--onefile`** (default here): one tidy `.exe`. Starts a little slower
  because it unpacks to a temp folder each launch, and some antivirus tools are
  suspicious of single-file exes.
- **`--onedir`**: produces a `dist\Paragon Publisher\` folder with the `.exe`
  plus its support files. Starts faster and is friendlier to antivirus. To use
  it, change `--onefile` to `--onedir` in `build_windows.bat`, and distribute
  the whole folder (zip it) instead of just the `.exe`.

## Troubleshooting

- **"Failed to execute script" / blank crash on launch** — build once with the
  console visible to see the real error: temporarily change `--windowed` to
  `--console`, rebuild, run from a command prompt, read the traceback.
- **App starts but has no theme / wrong colors** — the
  `--collect-all customtkinter` flag is missing or PyInstaller is out of date
  (`pip install -U pyinstaller`).
- **Drag-and-drop doesn't work** — make sure `tkinterdnd2` installed
  successfully and `--collect-all tkinterdnd2` is present.
- **Antivirus flags the exe** — a known false-positive pattern for one-file
  PyInstaller builds. Prefer `--onedir`, or code-sign the executable.

## Config location

User settings (API keys, saved library folders) live in
`%USERPROFILE%\.pyrenamer_config.json` — outside the app folder, so rebuilding
or replacing the `.exe` never loses your settings.
