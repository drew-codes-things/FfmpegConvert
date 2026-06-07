import os
import sys
import argparse
from common import (
    find_ffmpeg, init_log, write_log, prompt_folders,
    get_files, pick_format, run_batch, validate_io_folders
)

FORMATS = {
    "mp4":  ("libx264",    "aac"),
    "mkv":  ("libx264",    "aac"),
    "avi":  ("libx264",    "aac"),
    "mov":  ("libx264",    "aac"),
    "webm": ("libvpx-vp9", "libopus"),
}

INPUT_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".vob"}

CRF_MAP = {1: 28, 2: 24, 3: 20, 4: 18, 5: 16}

_SOURCE_MODE = object()


def ask_bitrate_mode():
    """
    Ask the user to pick a quality level or source-bitrate mode.

    Returns one of:
      - (_SOURCE_MODE, 18)  when the user picks 's' (near-lossless, CRF 18)
      - (quality_int, crf)  for a numbered quality choice 1-5
      - (3, 20)             as the default / fallback
    """
    print("\nVideo quality:")
    print("  s. Use source bitrate (CRF 18 -- near-lossless)")
    print("  1. Quality 1 -- smallest file  (CRF 28)")
    print("  2. Quality 2                   (CRF 24)")
    print("  3. Quality 3 -- balanced        (CRF 20)")
    print("  4. Quality 4                   (CRF 18)")
    print("  5. Quality 5 -- best quality    (CRF 16)")
    raw = input("Choose [s/1-5] [3]: ").strip().lower() or '3'
    if raw == 's':
        return _SOURCE_MODE, 18
    try:
        q = int(raw)
        if 1 <= q <= 5:
            return q, CRF_MAP[q]
    except ValueError:
        pass
    print("Invalid, using quality 3 (CRF 20).")
    return 3, 20


def build_cmd_factory(use_source_bitrate, crf):
    def build_cmd(ffmpeg_path, input_file, output_file):
        ext = os.path.splitext(output_file)[1].lstrip(".")
        vcodec, acodec = FORMATS[ext]
        is_vp9 = (vcodec == "libvpx-vp9")
        if use_source_bitrate:
            video_args = ["-c:v", vcodec, "-b:v", "0", "-crf", "18"]
        else:
            if is_vp9:
                video_args = ["-c:v", vcodec, "-b:v", "0", "-crf", str(crf)]
            else:
                video_args = ["-c:v", vcodec, "-crf", str(crf)]
        return [
            ffmpeg_path, "-y", "-i", input_file,
            *video_args,
            "-c:a", acodec,
            output_file,
        ]
    return build_cmd


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch video converter (wraps ffmpeg).",
    )
    p.add_argument("-i", "--input",  default=None, help="Input folder path (skips prompt)")
    p.add_argument("-o", "--output", default=None, help="Output folder path (skips prompt)")
    p.add_argument("-f", "--format", default=None, choices=list(FORMATS.keys()),
                   help=f"Output format: {', '.join(FORMATS.keys())} (skips prompt)")
    p.add_argument("--crf", type=int, default=None,
                   help="Exact CRF value to use (lower = higher quality); overrides --quality")
    p.add_argument("--quality", default=None,
                   help="Quality preset: s (source/near-lossless) or 1-5 (skips prompt)")
    p.add_argument("--recursive", action="store_true",
                   help="Recurse into subfolders (output mirrors the input tree)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ffmpeg commands that would run, without converting")
    return p.parse_args()


def resolve_quality(args, log_file):
    """Determine (use_source, crf) from CLI flags, falling back to the interactive prompt."""
    if args.crf is not None:
        write_log(log_file, f"Bitrate mode: explicit CRF {args.crf}")
        print(f"Using CRF {args.crf}.")
        return False, args.crf
    if args.quality is not None:
        raw = str(args.quality).strip().lower()
        if raw == "s":
            write_log(log_file, "Bitrate mode: source (CRF 18)")
            print("Using source bitrate mode (CRF 18).")
            return True, 18
        if raw.isdigit() and 1 <= int(raw) <= 5:
            crf = CRF_MAP[int(raw)]
            write_log(log_file, f"Bitrate mode: quality {raw} (CRF {crf})")
            print(f"Using quality {raw} (CRF {crf}).")
            return False, crf
        print("Invalid --quality; falling back to prompt.")
    q, crf = ask_bitrate_mode()
    use_source = (q is _SOURCE_MODE)
    if use_source:
        print("Using source bitrate mode (CRF 18).")
        write_log(log_file, "Bitrate mode: source (CRF 18)")
    else:
        print(f"Using quality {q} (CRF {crf}).")
        write_log(log_file, f"Bitrate mode: quality {q} (CRF {crf})")
    return use_source, crf


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    args = parse_args()

    if args.input and args.output:
        input_folder, output_folder = validate_io_folders(args.input, args.output)
    else:
        input_folder, output_folder = prompt_folders()
    if not input_folder:
        sys.exit(1)

    log_file = os.path.join(output_folder, "logs_video.txt")
    init_log(log_file, "Batch Video Converter")

    ffmpeg_path = find_ffmpeg(script_dir)
    if not ffmpeg_path:
        print("ERROR: ffmpeg not found. Install it or put it in ./ffmpeg/")
        sys.exit(1)
    write_log(log_file, f"ffmpeg: {ffmpeg_path}")
    write_log(log_file, f"Input:  {input_folder}")
    write_log(log_file, f"Output: {output_folder}")

    files = get_files(input_folder, INPUT_EXTS, recursive=args.recursive)
    if not files:
        print("No video files found in input folder.")
        sys.exit(0)
    print(f"Found {len(files)} video file(s).")
    write_log(log_file, f"Files: {files}")

    if args.format:
        output_ext = args.format
        write_log(log_file, f"Output format: .{output_ext}")
        print(f"Output format: {output_ext}")
    else:
        output_ext = pick_format(FORMATS, log_file)
        if not output_ext:
            sys.exit(1)

    use_source, crf = resolve_quality(args, log_file)

    build_cmd = build_cmd_factory(use_source, crf)
    run_batch(ffmpeg_path, build_cmd, files, input_folder, output_folder, output_ext, log_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
