# Service Assembly Studio

Assemble church service recordings and worship videos into one YouTube-ready MP4.

## Run from source

```powershell
cd "C:\Users\user\My Programs\Service Assembly Studio"
pip install -r requirements.txt
python main.py
```

Requires **FFmpeg** (`ffmpeg.exe` and `ffprobe.exe`) on your PATH.

## Workflow

1. **Import** — add your section recordings (drag-and-drop or File → Import)
2. **Arrange** — drag items or use Move Up / Move Down
3. **Insert worship videos** — import them and mark type as *Worship Video*
4. **Trim / rename** — adjust each section as needed
5. **Export** — choose output path and export one completed MP4

Projects are saved as `.sasproj` JSON files. Original recordings are never modified.

## Build Windows executable

```powershell
.\build.ps1
```

The packaged app will be in `dist\Service Assembly Studio\`.
