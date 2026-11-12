import argparse
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

import audio
import common
import image
import video

FAKE_CONVERT = "import sys, shutil; shutil.copyfile(sys.argv[1], sys.argv[2])"
FAKE_FAILURE = "import sys; open(sys.argv[2], 'w').write('partial'); sys.exit(1)"


def fake_build_cmd(script):
    def build_cmd(ffmpeg_path, input_file, output_file):
        return [sys.executable, "-c", script, input_file, output_file]
    return build_cmd


@pytest.fixture
def folders(tmp_path):
    source = tmp_path / "in"
    target = tmp_path / "out"
    (source / "sub").mkdir(parents=True)
    target.mkdir()
    for name in ("a.wav", "b.wav", "c.wav", os.path.join("sub", "d.wav")):
        (source / name).write_text(name)
    return source, target


def run(folders, script=FAKE_CONVERT, **options):
    source, target = folders
    files = common.get_files(str(source), {".wav"}, recursive=True)
    log_file = str(target / "log.txt")
    common.init_log(log_file, "test")
    common.run_batch("ffmpeg", fake_build_cmd(script), files, str(source), str(target), "mp3", log_file, **options)
    return target, open(log_file).read()


@pytest.mark.parametrize("jobs", [1, 3])
def test_every_file_is_converted(folders, jobs, capsys):
    target, _ = run(folders, jobs=jobs)
    assert (target / "sub" / "d.mp3").read_text() == os.path.join("sub", "d.wav")
    assert sorted(os.listdir(target)) == ["a.mp3", "b.mp3", "c.mp3", "log.txt", "sub"]
    assert "4 converted, 0 skipped" in capsys.readouterr().out


def test_existing_outputs_are_skipped(folders, capsys):
    _, target = folders
    (target / "a.mp3").write_text("keep")
    run(folders, jobs=2)
    assert (target / "a.mp3").read_text() == "keep"
    assert "3 converted, 1 skipped" in capsys.readouterr().out


def test_failures_remove_partial_output(folders, capsys):
    target, log = run(folders, script=FAKE_FAILURE, jobs=4)
    assert sorted(os.listdir(target)) == ["log.txt", "sub"]
    assert "0 converted, 0 skipped (already existed), 4 failed" in capsys.readouterr().out
    assert log.count("ERROR") == 4


def test_dry_run_converts_nothing(folders, capsys):
    target, _ = run(folders, dry_run=True, jobs=2)
    assert os.listdir(target) == ["log.txt"]
    assert "Dry run: 4 command(s)" in capsys.readouterr().out


def preset_args(presets, **given):
    defaults = {"preset": None, "format": None, "quality": None, "crf": None}
    return common.apply_preset(argparse.Namespace(**{**defaults, **given}), presets)


def test_preset_fills_in_unset_options():
    args = preset_args(video.PRESETS, preset="phone")
    assert (args.format, args.quality) == ("mp4", "2")


def test_explicit_flags_win_over_the_preset():
    args = preset_args(video.PRESETS, preset="phone", format="mkv", quality="5")
    assert (args.format, args.quality) == ("mkv", "5")


def test_every_preset_uses_a_known_format():
    for module in (audio, video):
        assert all(values["format"] in module.FORMATS for values in module.PRESETS.values())


def test_jobs_must_be_positive():
    with pytest.raises(argparse.ArgumentTypeError):
        common.positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError):
        common.positive_int("two")
    assert common.positive_int("4") == 4


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_audio_conversion_in_parallel(tmp_path, capsys):
    source = tmp_path / "in"
    target = tmp_path / "out"
    source.mkdir()
    target.mkdir()
    for index in range(3):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=0.2",
                        str(source / f"tone{index}.wav")], check=True)
    files = common.get_files(str(source), audio.INPUT_EXTS)
    log_file = str(target / "log.txt")
    common.init_log(log_file, "test")
    common.run_batch(shutil.which("ffmpeg"), audio.build_cmd, files, str(source), str(target), "flac", log_file, jobs=3)
    assert sorted(os.listdir(target)) == ["log.txt", "tone0.flac", "tone1.flac", "tone2.flac"]
    assert "3 converted" in capsys.readouterr().out


def test_inputs_sharing_a_name_get_separate_outputs():
    planned = common.plan_jobs(["song.flac", "song.wav", os.path.join("sub", "song.wav")], "in", "out", "mp3")
    outputs = [output_file for _, _, output_file in planned]
    assert outputs == [os.path.join("out", "song.mp3"), os.path.join("out", "song_wav.mp3"),
                       os.path.join("out", "sub", "song.mp3")]


def test_inputs_sharing_a_name_are_both_converted(tmp_path, capsys):
    source = tmp_path / "in"
    target = tmp_path / "out"
    source.mkdir()
    target.mkdir()
    (source / "song.flac").write_text("from flac")
    (source / "song.wav").write_text("from wav")
    files = common.get_files(str(source), {".flac", ".wav"})
    log_file = str(target / "log.txt")
    common.init_log(log_file, "test")
    common.run_batch("ffmpeg", fake_build_cmd(FAKE_CONVERT), files, str(source), str(target), "mp3", log_file, jobs=2)
    assert (target / "song.mp3").read_text() == "from flac"
    assert (target / "song_wav.mp3").read_text() == "from wav"
    assert "2 converted" in capsys.readouterr().out


def stream_types(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                           check=True, capture_output=True, text=True)
    return sorted(probe.stdout.split())


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")
def test_real_ffmpeg_handles_cover_art_for_every_audio_format(tmp_path):
    cover = tmp_path / "cover.png"
    plain = tmp_path / "plain.flac"
    with_art = tmp_path / "art.flac"
    quiet = ["ffmpeg", "-loglevel", "error", "-f", "lavfi"]
    subprocess.run([*quiet, "-i", "testsrc=size=65x65", "-frames:v", "1", str(cover)], check=True)
    subprocess.run([*quiet, "-i", "anullsrc=r=44100:cl=mono", "-t", "0.2", str(plain)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(plain), "-i", str(cover), "-map", "0:a", "-map", "1:v",
                    "-c", "copy", "-disposition:v", "attached_pic", str(with_art)], check=True)
    for extension in audio.FORMATS:
        output = tmp_path / f"out.{extension}"
        common.convert_one(audio.build_cmd(shutil.which("ffmpeg"), str(with_art), str(output)))
        assert "audio" in stream_types(output), extension
    assert stream_types(tmp_path / "out.ogg") == ["audio"]
    assert stream_types(tmp_path / "out.m4a") == ["audio", "video"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_turns_an_animated_gif_into_a_still_image(tmp_path):
    animation = tmp_path / "anim.gif"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5",
                    "-frames:v", "5", str(animation)], check=True)
    for extension in ("jpg", "png", "bmp", "tiff", "webp"):
        output = tmp_path / f"still.{extension}"
        common.convert_one(image.build_cmd_factory(None)(shutil.which("ffmpeg"), str(animation), str(output)))
        assert output.stat().st_size > 0, extension


def test_run_batch_returns_the_number_of_failures(folders, capsys):
    source, target = folders
    files = common.get_files(str(source), {".wav"}, recursive=True)
    log_file = str(target / "log.txt")
    common.init_log(log_file, "test")
    assert common.run_batch("ffmpeg", fake_build_cmd(FAKE_FAILURE), files, str(source), str(target), "mp3", log_file) == 4
    assert common.run_batch("ffmpeg", fake_build_cmd(FAKE_CONVERT), files, str(source), str(target), "mp3", log_file) == 0


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_script(script, *arguments, cwd=None, answers=None):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    stdin = {"input": answers} if answers is not None else {"stdin": subprocess.DEVNULL}
    return subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, script), *arguments], cwd=cwd, env=environment,
                          capture_output=True, text=True, timeout=120, **stdin)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_script_exits_with_an_error_when_a_conversion_fails(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    (source / "broken.wav").write_text("not audio")
    result = run_script("audio.py", "-i", str(source), "-o", str(tmp_path / "out"), "-f", "mp3")
    assert "1 failed" in result.stdout
    assert result.returncode == 1


RECORD_OUTPUT_NAME = ("import sys, shutil; shutil.copyfile(sys.argv[1], sys.argv[2]); "
                      "open(sys.argv[2] + '.name', 'w').close()")


def test_ffmpeg_writes_to_a_part_file_that_is_renamed_on_success(folders, capsys):
    target, _ = run(folders, script=RECORD_OUTPUT_NAME)
    written = sorted(name for name in os.listdir(target) if name.endswith(".name"))
    assert written == ["a.part.mp3.name", "b.part.mp3.name", "c.part.mp3.name"]
    assert (target / "a.mp3").read_text() == "a.wav"
    assert not (target / "a.part.mp3").exists()


def test_failed_conversion_leaves_no_part_file(folders, capsys):
    target, _ = run(folders, script=FAKE_FAILURE)
    assert sorted(os.listdir(target)) == ["log.txt", "sub"]
    assert os.listdir(target / "sub") == []


SLOW_CONVERT = ("import os, sys, time; open(sys.argv[2], 'w').write('partial'); "
                "open(os.path.join(sys.argv[3], str(os.getpid())), 'w').close(); time.sleep(60)")

BATCH_DRIVER = """
import sys
import time
sys.path.insert(0, sys.argv[5])
import common
def build_cmd(ffmpeg_path, input_file, output_file):
    return [sys.executable, "-c", sys.argv[4], input_file, output_file, sys.argv[6]]
files = common.get_files(sys.argv[1], {".wav"})
common.init_log(sys.argv[3], "test")
common.run_batch("ffmpeg", build_cmd, files, sys.argv[1], sys.argv[2], "mp3", sys.argv[3], jobs=2)
"""


def is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_until(condition, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def test_sigterm_stops_ffmpeg_and_removes_partial_outputs(tmp_path):
    source = tmp_path / "in"
    target = tmp_path / "out"
    pids = tmp_path / "pids"
    for folder in (source, target, pids):
        folder.mkdir()
    for name in ("a.wav", "b.wav"):
        (source / name).write_text(name)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    driver = subprocess.Popen([sys.executable, "-c", BATCH_DRIVER, str(source), str(target), str(target / "log.txt"),
                               SLOW_CONVERT, SCRIPTS_DIR, str(pids)],
                              env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pids = []
    try:
        assert wait_until(lambda: len(os.listdir(pids)) == 2, 20)
        child_pids = [int(name) for name in os.listdir(pids)]
        driver.send_signal(signal.SIGTERM)
        driver.wait(timeout=20)
        assert wait_until(lambda: not any(is_running(pid) for pid in child_pids), 10)
        assert sorted(os.listdir(target)) == ["log.txt"]
    finally:
        for pid in child_pids:
            if is_running(pid):
                os.kill(pid, signal.SIGKILL)
        if driver.poll() is None:
            driver.kill()


def make_media(path, *source_arguments):
    subprocess.run(["ffmpeg", "-loglevel", "error", *source_arguments, str(path)], check=True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_video_run_with_folders_and_format_needs_no_terminal(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    make_media(source / "clip.mp4", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5", "-t", "0.4")
    result = run_script("video.py", "-i", str(source), "-o", str(tmp_path / "out"), "-f", "mkv")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Using quality 3 (CRF 20)" in result.stdout
    assert (tmp_path / "out" / "clip.mkv").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_only_the_missing_folder_is_asked_for(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    make_media(source / "tone.wav", "-f", "lavfi", "-i", "sine=duration=0.2")
    result = run_script("audio.py", "-i", str(source), "-f", "flac", answers=str(tmp_path / "out") + "\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Input folder path" not in result.stdout
    assert (tmp_path / "out" / "tone.flac").exists()


def make_two_track_mkv(tmp_path):
    subtitles = tmp_path / "lines.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:00,400\nhello\n")
    source = tmp_path / "tracks.mkv"
    make_media(source, "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5", "-f", "lavfi", "-i", "sine=frequency=440",
               "-f", "lavfi", "-i", "sine=frequency=880", "-i", str(subtitles), "-i", str(subtitles), "-t", "0.4",
               "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3", "-map", "4", "-c:s", "srt")
    return source


def convert_video(source, output):
    common.convert_one(video.build_cmd_factory(False, video.CRF_MAP[4])(shutil.which("ffmpeg"), str(source), str(output)))


needs_ffprobe = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                   reason="ffmpeg not installed")


@needs_ffprobe
def test_mkv_output_keeps_every_audio_and_subtitle_track(tmp_path):
    source = make_two_track_mkv(tmp_path)
    assert stream_types(source) == ["audio", "audio", "subtitle", "subtitle", "video"]
    convert_video(source, tmp_path / "archive.mkv")
    assert stream_types(tmp_path / "archive.mkv") == ["audio", "audio", "subtitle", "subtitle", "video"]


@needs_ffprobe
def test_mkv_output_keeps_subtitles_from_an_mp4_source(tmp_path):
    source = tmp_path / "with_text.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(make_two_track_mkv(tmp_path)), "-map", "0", "-c:v", "copy",
                    "-c:a", "copy", "-c:s", "mov_text", str(source)], check=True)
    convert_video(source, tmp_path / "from_mp4.mkv")
    assert stream_types(tmp_path / "from_mp4.mkv") == ["audio", "audio", "subtitle", "subtitle", "video"]


@needs_ffprobe
@pytest.mark.parametrize("extension", ["mp4", "mov", "avi", "webm"])
def test_other_containers_keep_every_audio_track(tmp_path, extension):
    convert_video(make_two_track_mkv(tmp_path), tmp_path / f"out.{extension}")
    assert stream_types(tmp_path / f"out.{extension}") == ["audio", "audio", "video"]


def test_dropped_subtitles_are_announced_for_containers_that_cannot_hold_them():
    assert "subtitle" in video.dropped_streams_note("mp4")
    assert video.dropped_streams_note("mkv") is None


def video_format(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=pix_fmt,width,height", "-of", "csv=p=0", str(path)],
                           check=True, capture_output=True, text=True)
    return probe.stdout.strip()


@needs_ffprobe
@pytest.mark.parametrize("pixel_format", ["yuv444p", "yuv420p10le"])
def test_h264_output_is_widely_playable_from_odd_sources(tmp_path, pixel_format):
    source = tmp_path / f"{pixel_format}.mkv"
    make_media(source, "-f", "lavfi", "-i", "testsrc=size=65x33:rate=5", "-t", "0.4", "-c:v", "ffv1",
               "-pix_fmt", pixel_format)
    convert_video(source, tmp_path / "phone.mp4")
    assert video_format(tmp_path / "phone.mp4") == "64,32,yuv420p"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_relative_folders_starting_with_a_dash_convert(tmp_path):
    source = tmp_path / "-in"
    source.mkdir()
    make_media(source / "tone.wav", "-f", "lavfi", "-i", "sine=duration=0.2")
    result = run_script("audio.py", "--input=-in", "--output=-out", "-f", "flac", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "-out" / "tone.flac").exists()


def test_an_empty_folder_answer_is_refused(tmp_path):
    assert common.validate_io_folders(str(tmp_path), "  ") == (None, None)
    assert common.validate_io_folders("", str(tmp_path / "out")) == (None, None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("source_name", ["100%d.png", "50%.jpg", "frame%03d.tga", "spin%d.gif"])
def test_image_names_holding_a_printf_pattern_convert(tmp_path, source_name):
    source = tmp_path / source_name
    make_media(source, "-f", "lavfi", "-i", "testsrc=size=32x32", "-frames:v", "1", "-update", "1")
    for extension in image.FORMATS:
        output = tmp_path / f"{os.path.splitext(source_name)[0]}.{extension}"
        common.convert_one(image.build_cmd_factory(None)(shutil.which("ffmpeg"), str(source), str(output)))
        assert output.stat().st_size > 0, extension


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_dry_run_leaves_the_output_folder_and_log_alone(tmp_path):
    source = tmp_path / "in"
    kept = tmp_path / "kept"
    source.mkdir()
    kept.mkdir()
    (source / "a.wav").write_text("a")
    (kept / "logs_audio.txt").write_text("previous run")
    for target in (kept, tmp_path / "new"):
        result = run_script("audio.py", "-i", str(source), "-o", str(target), "-f", "mp3", "--dry-run")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "a.part.mp3" in result.stdout
    assert (kept / "logs_audio.txt").read_text() == "previous run"
    assert not (tmp_path / "new").exists()


def test_success_without_an_output_file_counts_as_a_failure(folders, capsys):
    source, target = folders
    files = common.get_files(str(source), {".wav"}, recursive=True)
    log_file = str(target / "log.txt")
    common.init_log(log_file, "test")
    assert common.run_batch("ffmpeg", fake_build_cmd("pass"), files, str(source), str(target), "mp3", log_file) == 4
    assert "0 converted, 0 skipped (already existed), 4 failed" in capsys.readouterr().out
