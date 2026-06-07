"""Shared utilities used by audio.py, video.py, and image.py."""
import os
import shlex
import shutil
import subprocess
import datetime


import logging

_log_handlers = [logging.StreamHandler()]
_log_file = os.environ.get("LOG_FILE")
if _log_file:
    _log_handlers.append(logging.FileHandler(_log_file))
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger("ffmpeg-converters")


def clean_path(path):
    return path.strip().strip('"').strip("'")


def find_ffmpeg(script_dir):
    """Look for ffmpeg bundled next to the script, then fall back to PATH."""
    candidates = [
        os.path.join(script_dir, "ffmpeg", "ffmpeg.exe"),
        os.path.join(script_dir, "ffmpeg", "ffmpeg"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("ffmpeg")


def write_log(path, text):
    with open(path, "a", encoding="utf-8") as log:
        log.write(text + "\n")


def init_log(path, title):
    with open(path, "w", encoding="utf-8") as log:
        log.write(f"=== {title} - Made by Drew ===\n")
        log.write(f"Started: {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}\n\n")


def format_size(num_bytes):
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def print_size_estimate(files, input_folder):
    """Print total input size and a rough estimated output size before converting."""
    total_bytes = sum(
        os.path.getsize(os.path.join(input_folder, f))
        for f in files
        if os.path.isfile(os.path.join(input_folder, f))
    )
    low  = total_bytes * 0.5
    high = total_bytes * 1.1
    print(f"  Total input size :  {format_size(total_bytes)}")
    print(f"  Estimated output :  {format_size(low)} -> {format_size(high)}  (rough range)")
    print()


def print_progress(current, total, filename):
    bar_length = 40
    filled = int(bar_length * current // total)
    bar = "#" * filled + "-" * (bar_length - filled)
    display_name = (filename[:36] + "...") if len(filename) > 39 else filename
    print(f"\r[{bar}] {current}/{total}  {display_name:42}", end="", flush=True)


def get_files(folder, extensions, recursive=False):
    """List matching files. With recursive=True, returns paths relative to `folder`."""
    files = []
    if recursive:
        for root, _, names in os.walk(folder):
            for f in names:
                if os.path.splitext(f)[1].lower() in extensions and os.path.isfile(os.path.join(root, f)):
                    files.append(os.path.relpath(os.path.join(root, f), folder))
        files.sort()
    else:
        for f in sorted(os.listdir(folder)):
            if os.path.isfile(os.path.join(folder, f)) and os.path.splitext(f)[1].lower() in extensions:
                files.append(f)
    return files


def validate_io_folders(input_folder, output_folder):
    """Validate input/output folder paths and create output if needed.

    Returns (input_folder, output_folder), or (None, None) on any problem.
    Shared by interactive (prompt_folders) and CLI flag entry points.
    """
    input_folder = clean_path(input_folder)
    output_folder = clean_path(output_folder)
    if not os.path.isdir(input_folder):
        logger.error(f"Input folder not found: {input_folder}")
        return None, None
    real_in  = os.path.realpath(input_folder)
    real_out = os.path.realpath(output_folder)
    if real_in == real_out:
        print(
            "WARNING: Input and output folders are the same path. "
            "This may overwrite or corrupt your source files. "
            "Please choose a different output folder."
        )
        return None, None
    try:
        nested = os.path.commonpath([real_in, real_out]) in (real_in, real_out)
    except ValueError:
        nested = False
    if nested:
        print(
            "WARNING: One of the input/output folders is nested inside the other. "
            "With --recursive this can feed freshly-converted files back in as input, "
            "or write converted files into the source tree. "
            "Please choose folders that do not contain each other."
        )
        return None, None
    if not os.path.isdir(output_folder):
        print(f"Creating output folder: {output_folder}")
        os.makedirs(output_folder, exist_ok=True)
    return input_folder, output_folder


def prompt_folders(output_folder_override=None):
    """Ask for input/output folders, validate, create output if needed."""
    input_folder = input("Input folder path: ")
    if output_folder_override:
        output_folder = output_folder_override
        print(f"Output folder path: {clean_path(output_folder)} (from override)")
    else:
        output_folder = input("Output folder path: ")
    return validate_io_folders(input_folder, output_folder)


def pick_format(formats, log_file):
    """Print numbered format list and return chosen key, or None on bad input."""
    keys = list(formats.keys())
    print("\nAvailable output formats:")
    for i, k in enumerate(keys, 1):
        print(f"  {i}. {k}")
    raw = input("Choose format number: ").strip()
    try:
        idx = int(raw) - 1
        if not (0 <= idx < len(keys)):
            raise ValueError
        chosen = keys[idx]
        write_log(log_file, f"Output format: .{chosen}")
        return chosen
    except ValueError:
        print("Invalid choice.")
        return None


def run_batch(ffmpeg_path, build_cmd, files, input_folder, output_folder, output_ext, log_file, dry_run=False):
    """Show estimated output size, then run ffmpeg on every file.

    With dry_run=True, prints the ffmpeg command for each file instead of running it.
    """
    print_size_estimate(files, input_folder)

    total = len(files)
    ok = 0
    skipped = 0
    failed = []

    for idx, filename in enumerate(files, 1):
        input_file = os.path.join(input_folder, filename)
        base = os.path.splitext(filename)[0]
        output_file = os.path.join(output_folder, base + "." + output_ext)

        if dry_run:
            cmd = build_cmd(ffmpeg_path, input_file, output_file)
            line = " ".join(shlex.quote(c) for c in cmd)
            print(f"[{idx}/{total}] {line}")
            write_log(log_file, f"[{idx}/{total}] DRY-RUN: {line}")
            continue

        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if os.path.exists(output_file):
            skip_reason = "output already exists"
            write_log(log_file, f"[{idx}/{total}] SKIPPED ({skip_reason}): {output_file}")
            print_progress(idx, total, filename + f" [skip -- {skip_reason}]")
            skipped += 1
            continue

        print_progress(idx, total, filename)
        write_log(log_file, f"[{idx}/{total}] {input_file} -> {output_file}")

        cmd = build_cmd(ffmpeg_path, input_file, output_file)
        try:
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                write_log(log_file, stderr_text)
            write_log(log_file, f"[{idx}/{total}] OK\n")
            ok += 1
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            write_log(log_file, f"[{idx}/{total}] ERROR:\n{err}\n")
            failed.append(filename)
        except Exception as e:
            write_log(log_file, f"[{idx}/{total}] UNEXPECTED: {e}\n")
            failed.append(filename)

    if dry_run:
        print(f"\nDry run: {total} command(s) printed above. Nothing was converted.")
        write_log(log_file, f"\nDry run: {total} command(s) printed. Nothing converted.")
        return

    print()
    print(f"\nDone. {ok} converted, {skipped} skipped (already existed), {len(failed)} failed.")
    if failed:
        print(f"Failed ({len(failed)}):")
        for f in failed:
            print(f"  - {f}")
    write_log(log_file, f"\nFinished: {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}")
    write_log(log_file, f"Result: {ok} converted, {skipped} skipped, {len(failed)} failed")
