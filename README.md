<div align="center">

# ffmpeg-converters

**Three Python scripts for batch-converting audio, video, and image files using ffmpeg, with interactive prompts and full conversion logs.**

[![Python](https://img.shields.io/badge/python-3.8+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![ffmpeg](https://img.shields.io/badge/ffmpeg-required-007808?style=flat-square&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

</div>

---

Point a script at an input folder, pick an output format, and all matching files are converted in a single batch. ffmpeg handles all encoding; the scripts just wrap it cleanly with prompts, safety checks, and a log file written alongside the output.

---

## Requirements

- Python 3.8+
- ffmpeg installed system-wide (`ffmpeg` on PATH) **or** placed at `./ffmpeg/ffmpeg` next to the scripts

No Python packages are required.

---

## Scripts

### audio.py

Batch-converts audio files. Supports CLI flags or fully interactive mode.

**Input formats:** `.flac` `.mp3` `.wav` `.aac` `.opus` `.m4a` `.wma` `.ogg` `.m4b`

**Output formats and codecs:**

| Format | Codec | Bitrate |
|--------|-------|---------|
| `mp3` | libmp3lame | 192k |
| `aac` | aac | 192k |
| `wav` | pcm_s16le | lossless |
| `opus` | libopus | 128k |
| `flac` | flac | lossless |
| `m4a` | aac | 192k |
| `ogg` | libvorbis | 160k |

Metadata tags (artist, album, title, etc.) are preserved via `-map_metadata 0`.

**CLI usage:**

```
python audio.py --input /music --output /out --format mp3
python audio.py -i /music -o /out -f flac
python audio.py
```

Running without flags drops into interactive mode. A log is written to `<output>/logs_audio.txt`.

---

### video.py

Batch-converts video files with a selectable quality level.

**Input formats:** `.mp4` `.mkv` `.avi` `.mov` `.wmv` `.flv` `.webm` `.m4v` `.ts` `.vob`

**Output formats:**

| Format | Video codec | Audio codec |
|--------|-------------|-------------|
| `mp4` | libx264 | aac |
| `mkv` | libx264 | aac |
| `avi` | libx264 | aac |
| `mov` | libx264 | aac |
| `webm` | libvpx-vp9 | libopus |

**Quality levels (CRF):**

| Option | CRF | Notes |
|--------|-----|-------|
| `s` | 18 | Source bitrate mode, near-lossless |
| `1` | 28 | Smallest file |
| `2` | 24 | |
| `3` | 20 | Balanced (default) |
| `4` | 18 | |
| `5` | 16 | Best quality |

For WebM output, VP9 uses `-b:v 0 -crf <value>` (constrained quality mode). A log is written to `<output>/logs_video.txt`.

**Usage:**

```
python video.py
```

---

### image.py

Batch-converts image files.

**Input formats:** `.jpg` `.jpeg` `.png` `.bmp` `.tiff` `.tif` `.webp` `.gif` `.ppm` `.tga` `.avif`

**Output formats:**

| Format | Codec |
|--------|-------|
| `jpg` | mjpeg |
| `png` | png |
| `bmp` | bmp |
| `tiff` | tiff |
| `webp` | webp |
| `avif` | libaom-av1 |

A log is written to `<output>/logs_image.txt`.

**Usage:**

```
python image.py
```

---

## Common Flags

All three scripts share these flags:

| Flag | Description |
|------|-------------|
| `--recursive` | Recurse into subfolders; the output mirrors the input folder tree |
| `--dry-run` | Print the exact ffmpeg command for each file without converting anything |

`video.py` adds `--crf <n>` (exact CRF, overrides preset) and `--quality s|1-5`.
`image.py` adds `--quality 1-100` (higher = better) for `jpg`/`webp`/`avif`; lossless formats ignore it.
`audio.py`, `video.py`, and `image.py` all accept `-i/--input`, `-o/--output`, and `-f/--format` to skip the prompts.

---

## Safety Checks

- Input and output folders are resolved to real paths before any conversion begins
- The scripts exit with an error if input and output resolve to the same folder, preventing accidental overwrites
- ffmpeg is discovered automatically: system PATH first, then `./ffmpeg/ffmpeg`

---

---

## Install as a command (pipx)

Install this folder as a CLI so it is available on your PATH:

```bash
pipx install .
ffmpeg-convert     # also: ffmpeg-audio, ffmpeg-video, ffmpeg-image
```

Logging: set `LOG_LEVEL` (e.g. `DEBUG`) and `LOG_FILE` to also write logs to a file.


## License

MIT - made by [Drew](https://github.com/drew-codes-things)
