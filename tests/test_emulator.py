import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from xhs_scout.emulator import (
    AdbDevice,
    ScreenshotCaptureError,
    select_device_serial,
    select_mdns_connect_address,
)


def _valid_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_adb_monkey_launch_is_disabled():
    device = AdbDevice(adb=Path("adb"), serial="device")
    with pytest.raises(RuntimeError, match="monkey"):
        device.launch("com.xingin.xhs")


def test_open_url_quotes_query_and_limits_intent_to_xiaohongshu():
    device = AdbDevice(adb=Path("adb"), serial="device")
    captured = {}

    def fake_cmd(*args, timeout):
        captured["args"] = args
        captured["timeout"] = timeout
        return SimpleNamespace(stdout="opened")

    device._cmd = fake_cmd
    url = "https://www.xiaohongshu.com/goods-detail/abc?x=1&y=2"

    assert device.open_url(url) == "opened"
    assert captured == {
        "args": (
            "shell",
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.VIEW",
            "-p",
            "com.xingin.xhs",
            "-d",
            "'https://www.xiaohongshu.com/goods-detail/abc?x=1&y=2'",
        ),
        "timeout": 30,
    }


def test_bluestacks_launcher_exit_code_is_verified_by_later_page_probe(
    monkeypatch,
):
    device = AdbDevice(adb=Path("adb"), serial="device")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=114, stdout="", stderr="")

    monkeypatch.setattr("xhs_scout.emulator.subprocess.run", fake_run)

    result = device.launch_with_bluestacks_player(
        Path("C:/BlueStacks/HD-Player.exe"),
        "Rvc64",
        "com.xingin.xhs",
    )

    assert result.returncode == 114
    assert captured["command"][-4:] == [
        "--cmd",
        "launchApp",
        "--package",
        "com.xingin.xhs",
    ]
    assert captured["kwargs"]["check"] is False


def test_pidof_normalizes_multiple_process_ids():
    device = AdbDevice(adb=Path("adb"), serial="device")
    device._cmd = lambda *_args, **_kwargs: SimpleNamespace(stdout="22  11\n")

    assert device.pidof("com.xingin.xhs") == "11 22"


def test_pidof_returns_none_when_android_process_is_absent():
    device = AdbDevice(adb=Path("adb"), serial="device")

    def missing(*_args, **_kwargs):
        raise __import__("subprocess").CalledProcessError(1, ["adb", "pidof"])

    device._cmd = missing
    assert device.pidof("com.xingin.xhs") is None


def test_shell_returns_stdout_through_selected_device_command():
    device = AdbDevice(adb=Path("adb"), serial="phone")
    calls = []

    def fake_cmd(*args, timeout):
        calls.append((args, timeout))
        return SimpleNamespace(stdout="value\n")

    device._cmd = fake_cmd

    assert device.shell("getprop", "ro.product.model") == "value\n"
    assert calls == [(("shell", "getprop", "ro.product.model"), 15)]


def test_screenshot_never_leaves_a_truncated_png_at_the_final_path(
    tmp_path, monkeypatch
):
    """Regression test: a real run truncated mid-capture (738422 bytes, PNG
    IEND missing) was written straight to ``current.png`` and later handed to
    the OCR worker, which crashed with ``OSError: image file is truncated``.
    The destination path must only ever hold a fully decodable PNG."""

    device = AdbDevice(adb=Path("adb"), serial="phone")
    destination = tmp_path / "current.png"

    def truncated_capture(command, *, stdout, stderr, timeout, check):
        stdout.write(_valid_png_bytes()[:50])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "xhs_scout.emulator.subprocess.run", truncated_capture
    )

    with pytest.raises(ScreenshotCaptureError):
        device.screenshot(destination)

    assert not destination.exists()
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"temp capture files were not cleaned up: {leftovers}"


def test_screenshot_writes_atomically_via_temp_file_then_replace(
    tmp_path, monkeypatch
):
    device = AdbDevice(adb=Path("adb"), serial="phone")
    destination = tmp_path / "current.png"
    seen_paths_while_writing = []

    def good_capture(command, *, stdout, stderr, timeout, check):
        # The destination must not exist yet while the capture is still
        # in flight; only the atomic replace should create it.
        seen_paths_while_writing.append(destination.exists())
        stdout.write(_valid_png_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("xhs_scout.emulator.subprocess.run", good_capture)

    result = device.screenshot(destination)

    assert result == destination
    assert destination.exists()
    with Image.open(destination) as img:
        img.load()
    assert seen_paths_while_writing == [False]
    leftovers = [p for p in tmp_path.iterdir() if p != destination]
    assert leftovers == [], f"temp capture files were not cleaned up: {leftovers}"


def test_screenshot_retries_once_after_a_transient_truncated_capture(
    tmp_path, monkeypatch
):
    device = AdbDevice(adb=Path("adb"), serial="phone")
    destination = tmp_path / "current.png"
    attempts = []

    def flaky_capture(command, *, stdout, stderr, timeout, check):
        attempts.append(1)
        if len(attempts) == 1:
            stdout.write(_valid_png_bytes()[:50])
        else:
            stdout.write(_valid_png_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("xhs_scout.emulator.subprocess.run", flaky_capture)

    result = device.screenshot(destination)

    assert result == destination
    assert len(attempts) == 2
    with Image.open(destination) as img:
        img.load()


def test_window_focus_uses_bounded_display_dump():
    device = AdbDevice(adb=Path("adb"), serial="phone")
    calls = []

    def fake_cmd(*args, timeout):
        calls.append((args, timeout))
        return SimpleNamespace(stdout="mCurrentFocus=Window{abc u0 package/.Activity}\n")

    device._cmd = fake_cmd

    assert "mCurrentFocus=" in device.window_focus()
    assert calls == [
        (("shell", "dumpsys", "window", "displays"), 15),
    ]


def test_select_device_serial_by_unique_model():
    output = """List of devices attached
127.0.0.1:5555 device product:Rvc64 model:BlueStacks device:Rvc64
192.168.110.182:43217 device product:lime model:M2010J19SC device:lime
"""
    assert select_device_serial(output, model="M2010J19SC") == "192.168.110.182:43217"


def test_select_device_serial_prefers_exact_mdns_identity_for_duplicate_transport():
    output = """List of devices attached
192.168.110.182:43217 device product:lime model:M2010J19SC device:lime transport_id:12
adb-741da30b0920-cvuER5._adb-tls-connect._tcp device product:lime model:M2010J19SC device:lime transport_id:13
"""

    assert select_device_serial(
        output,
        model="M2010J19SC",
        service_name="adb-741da30b0920-cvuER5",
    ) == "adb-741da30b0920-cvuER5._adb-tls-connect._tcp"


def test_select_device_serial_preserves_windows_mdns_suffix_with_space():
    output = """List of devices attached
adb-741da30b0920-cvuER5 (2)._adb-tls-connect._tcp device product:lime model:M2010J19SC device:lime transport_id:1
"""

    assert select_device_serial(
        output,
        model="M2010J19SC",
        service_name="adb-741da30b0920-cvuER5",
    ) == "adb-741da30b0920-cvuER5 (2)._adb-tls-connect._tcp"


def test_select_mdns_connect_address_uses_exact_paired_service():
    output = """List of discovered mdns services
adb-other _adb-tls-connect._tcp 192.168.1.9:40000
adb-741da30b0920-cvuER5 _adb-tls-connect._tcp 192.168.110.182:43217
"""
    assert (
        select_mdns_connect_address(output, service_name="adb-741da30b0920-cvuER5")
        == "192.168.110.182:43217"
    )


def test_launch_android_package_resolves_launcher_activity():
    device = AdbDevice(adb=Path("adb"), serial="phone")
    calls = []

    def fake_cmd(*args, timeout):
        calls.append((args, timeout))
        if args[:5] == ("shell", "cmd", "package", "resolve-activity", "--brief"):
            return SimpleNamespace(stdout="com.xingin.xhs/.index.v2.IndexActivityV2\n")
        return SimpleNamespace(stdout="started")

    device._cmd = fake_cmd
    assert device.launch_android_package("com.xingin.xhs") == "started"
    assert calls[-1][0] == (
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        "com.xingin.xhs/.index.v2.IndexActivityV2",
    )
