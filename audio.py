import os
import sys
import argparse
from common import (
    find_ffmpeg, init_log, write_log, prompt_folders,
    get_files, pick_format, run_batch, validate_io_folders
)

FORMATS = {
    "mp3":  ("libmp3lame", "192k"),
    "aac":  ("aac",        "192k"),
    "wav":  ("pcm_s16le",  None),
    "opus": ("libopus",    "128k"),
    "flac": ("flac",       None),
    "m4a":  ("aac",        "192k"),
    "ogg":  ("libvorbis",  "160k"),
}

FORMAT_KEYS = list(FORMATS.keys())

INPUT_EXTS = {".flac", ".mp3", ".wav", ".aac", ".opus", ".m4a", ".wma", ".ogg", ".m4b"}


def build_cmd(ffmpeg_path, input_file, output_file):
    ext = os.path.splitext(output_file)[1].lstrip(".")
    codec, bitrate = FORMATS[ext]
    cmd = [
        ffmpeg_path, "-y",
        "-i", input_file,
        "-map_metadata", "0",
        "-codec:a", codec,
    ]
    if bitrate:
        cmd.extend(["-b:a", bitrate])
    cmd.append(output_file)
    return cmd


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch audio converter (wraps ffmpeg).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python audio.py                              # fully interactive\n"
            "  python audio.py --input /music --output /out --format mp3\n"
            "  python audio.py -i /music -o /out -f flac\n"
        ),
    )
    p.add_argument("-i", "--input",  default=None,
                   help="Input folder path (skips interactive prompt)")
    p.add_argument("-o", "--output", default=None,
                   help="Output folder path (skips interactive prompt)")
    p.add_argument("-f", "--format", default=None,
                   choices=FORMAT_KEYS,
                   help=f"Output format: {', '.join(FORMAT_KEYS)} (skips interactive prompt)")
    p.add_argument("--recursive", action="store_true",
                   help="Recurse into subfolders (output mirrors the input tree)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ffmpeg commands that would run, without converting")
    return p.parse_args()


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    args = parse_args()

    if args.input and args.output:
        input_folder, output_folder = validate_io_folders(args.input, args.output)
    else:
        input_folder, output_folder = prompt_folders()
    if not input_folder:
        sys.exit(1)

    log_file = os.path.join(output_folder, "logs_audio.txt")
    init_log(log_file, "Batch Audio Converter")

    ffmpeg_path = find_ffmpeg(script_dir)
    if not ffmpeg_path:
        print("ERROR: ffmpeg not found. Install it or put it in ./ffmpeg/")
        sys.exit(1)
    write_log(log_file, f"ffmpeg: {ffmpeg_path}")
    write_log(log_file, f"Input:  {input_folder}")
    write_log(log_file, f"Output: {output_folder}")

    files = get_files(input_folder, INPUT_EXTS, recursive=args.recursive)
    if not files:
        print("No audio files found in input folder.")
        sys.exit(0)
    print(f"Found {len(files)} audio file(s).")
    write_log(log_file, f"Files: {files}")

    if args.format:
        output_ext = args.format
        write_log(log_file, f"Output format: .{output_ext}")
        print(f"Output format: {output_ext}")
    else:
        output_ext = pick_format(FORMATS, log_file)
        if not output_ext:
            sys.exit(1)

    run_batch(ffmpeg_path, build_cmd, files, input_folder, output_folder, output_ext, log_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
