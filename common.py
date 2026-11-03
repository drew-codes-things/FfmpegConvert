import argparse
import os
import shlex
import shutil
import subprocess
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


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
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def print_size_estimate(files, input_folder):
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
    input_folder = input("Input folder path: ")
    if output_folder_override:
        output_folder = output_folder_override
        print(f"Output folder path: {clean_path(output_folder)} (from override)")
    else:
        output_folder = input("Output folder path: ")
    return validate_io_folders(input_folder, output_folder)


def pick_format(formats, log_file):
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


def remove_partial_output(output_file):
    if os.path.exists(output_file):
        os.remove(output_file)


def add_batch_arguments(parser, presets):
    parser.add_argument("--preset", default=None, choices=list(presets),
                        help="Named settings: " + "; ".join(f"{name} = {describe_preset(values)}"
                                                            for name, values in presets.items())
                        + ". Flags you pass yourself win over the preset")
    parser.add_argument("-j", "--jobs", type=positive_int, default=1,
                        help="How many files to convert at the same time (default: 1)")
    parser.add_argument("--recursive", action="store_true",
                        help="Recurse into subfolders (output mirrors the input tree)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the ffmpeg commands that would run, without converting")


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number")
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def describe_preset(values):
    return ", ".join(f"{key} {value}" for key, value in values.items())


def apply_preset(args, presets):
    if not args.preset:
        return args
    for key, value in presets[args.preset].items():
        if getattr(args, key) is None:
            setattr(args, key, value)
    print(f"Preset: {args.preset} ({describe_preset(presets[args.preset])})")
    return args


def plan_jobs(files, input_folder, output_folder, output_ext):
    jobs = []
    for filename in files:
        base = os.path.splitext(filename)[0]
        jobs.append((filename, os.path.join(input_folder, filename),
                     os.path.join(output_folder, base + "." + output_ext)))
    return jobs


def convert_one(cmd):
    result = subprocess.run(
        cmd, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.stderr.decode("utf-8", errors="replace").strip()


def print_dry_run(ffmpeg_path, build_cmd, jobs, log_file):
    total = len(jobs)
    for idx, (_, input_file, output_file) in enumerate(jobs, 1):
        line = " ".join(shlex.quote(c) for c in build_cmd(ffmpeg_path, input_file, output_file))
        print(f"[{idx}/{total}] {line}")
        write_log(log_file, f"[{idx}/{total}] DRY-RUN: {line}")
    print(f"\nDry run: {total} command(s) printed above. Nothing was converted.")
    write_log(log_file, f"\nDry run: {total} command(s) printed. Nothing converted.")


def split_existing(jobs, log_file):
    pending = []
    skipped = 0
    for filename, input_file, output_file in jobs:
        if os.path.exists(output_file):
            write_log(log_file, f"SKIPPED (output already exists): {output_file}")
            skipped += 1
            continue
        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        pending.append((filename, input_file, output_file))
    return pending, skipped


def record_result(future, done, total, output_file, log_file):
    try:
        stderr_text = future.result()
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
        write_log(log_file, f"[{done}/{total}] ERROR:\n{err}\n")
        remove_partial_output(output_file)
        return False
    except Exception as e:
        write_log(log_file, f"[{done}/{total}] UNEXPECTED: {e}\n")
        remove_partial_output(output_file)
        return False
    if stderr_text:
        write_log(log_file, stderr_text)
    write_log(log_file, f"[{done}/{total}] OK\n")
    return True


def run_batch(ffmpeg_path, build_cmd, files, input_folder, output_folder, output_ext, log_file,
              dry_run=False, jobs=1):
    print_size_estimate(files, input_folder)
    planned = plan_jobs(files, input_folder, output_folder, output_ext)
    if dry_run:
        print_dry_run(ffmpeg_path, build_cmd, planned, log_file)
        return

    pending, skipped = split_existing(planned, log_file)
    total = len(pending)
    failed = []
    if skipped:
        print(f"Skipping {skipped} file(s) whose output already exists.")

    results = {}
    pool = ThreadPoolExecutor(max_workers=jobs)
    running = {}
    for job in pending:
        _, input_file, output_file = job
        running[pool.submit(convert_one, build_cmd(ffmpeg_path, input_file, output_file))] = job
    try:
        for done, future in enumerate(as_completed(running), 1):
            filename, input_file, output_file = running[future]
            print_progress(done, total, filename)
            write_log(log_file, f"[{done}/{total}] {input_file} -> {output_file}")
            results[future] = record_result(future, done, total, output_file, log_file)
            if not results[future]:
                failed.append(filename)
    except KeyboardInterrupt:
        for future in running:
            future.cancel()
        pool.shutdown(wait=True)
        for future, (_, _, output_file) in running.items():
            if not results.get(future):
                remove_partial_output(output_file)
        write_log(log_file, "INTERRUPTED\n")
        raise
    pool.shutdown(wait=True)
    ok = sum(1 for succeeded in results.values() if succeeded)

    print()
    print(f"\nDone. {ok} converted, {skipped} skipped (already existed), {len(failed)} failed.")
    if failed:
        print(f"Failed ({len(failed)}):")
        for f in failed:
            print(f"  - {f}")
    write_log(log_file, f"\nFinished: {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}")
    write_log(log_file, f"Result: {ok} converted, {skipped} skipped, {len(failed)} failed")
