import argparse
import os
import shutil
import subprocess
import sys

import pytest

import audio
import common
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
