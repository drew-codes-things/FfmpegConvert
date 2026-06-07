import os
import sys
import argparse
from common import (
    find_ffmpeg, init_log, write_log, prompt_folders,
    get_files, pick_format, run_batch, validate_io_folders
)

FORMATS = {
    "jpg":  "mjpeg",
    "png":  "png",
    "bmp":  "bmp",
    "tiff": "tiff",
    "webp": "webp",
    "avif": "libaom-av1",
}

INPUT_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif", ".ppm", ".tga", ".avif"}


def build_cmd_factory(quality):
    """Return a build_cmd. `quality` is 1-100 (higher = better), or None for codec defaults."""
    def build_cmd(ffmpeg_path, input_file, output_file):
        ext = os.path.splitext(output_file)[1].lstrip(".")
        codec = FORMATS[ext]
        cmd = [ffmpeg_path, "-y", "-i", input_file, "-vcodec", codec]
        if quality is not None:
            if codec == "mjpeg":
                qv = max(2, min(31, round(31 - (quality / 100) * 29)))
                cmd += ["-q:v", str(qv)]
            elif ext == "webp":
                cmd += ["-quality", str(max(0, min(100, quality)))]
            elif codec == "libaom-av1":
                crf = max(0, min(63, round((100 - quality) / 100 * 63)))
                cmd += ["-crf", str(crf)]
        cmd.append(output_file)
        return cmd
    return build_cmd


def parse_args():
    p = argparse.ArgumentParser(description="Batch image converter (wraps ffmpeg).")
    p.add_argument("-i", "--input",  default=None, help="Input folder path (skips prompt)")
    p.add_argument("-o", "--output", default=None, help="Output folder path (skips prompt)")
    p.add_argument("-f", "--format", default=None, choices=list(FORMATS.keys()),
                   help=f"Output format: {', '.join(FORMATS.keys())} (skips prompt)")
    p.add_argument("--quality", type=int, default=None,
                   help="Quality 1-100 (higher = better) for jpg/webp/avif; lossless formats ignore it")
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

    log_file = os.path.join(output_folder, "logs_image.txt")
    init_log(log_file, "Batch Image Converter")

    ffmpeg_path = find_ffmpeg(script_dir)
    if not ffmpeg_path:
        print("ERROR: ffmpeg not found. Install it or put it in ./ffmpeg/")
        sys.exit(1)
    write_log(log_file, f"ffmpeg: {ffmpeg_path}")
    write_log(log_file, f"Input:  {input_folder}")
    write_log(log_file, f"Output: {output_folder}")

    files = get_files(input_folder, INPUT_EXTS, recursive=args.recursive)
    if not files:
        print("No image files found in input folder.")
        sys.exit(0)
    print(f"Found {len(files)} image file(s).")
    write_log(log_file, f"Files: {files}")

    if args.format:
        output_ext = args.format
        write_log(log_file, f"Output format: .{output_ext}")
        print(f"Output format: {output_ext}")
    else:
        output_ext = pick_format(FORMATS, log_file)
        if not output_ext:
            sys.exit(1)

    if args.quality is not None:
        write_log(log_file, f"Quality: {args.quality}/100")
        print(f"Quality: {args.quality}/100")

    build_cmd = build_cmd_factory(args.quality)
    run_batch(ffmpeg_path, build_cmd, files, input_folder, output_folder, output_ext, log_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
