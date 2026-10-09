from __future__ import annotations

import base64
import shutil
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


class ScreenshotCaptureError(RuntimeError):
    """A device screenshot could not be captured as a complete, decodable PNG."""


@dataclass
class AdbDevice:
    adb: Path
    serial: str | None = None

    def _cmd(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        command = [str(self.adb)]
        if self.serial:
            command += ["-s", self.serial]
        command += list(args)
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )

    def devices(self) -> str:
        return self._cmd("devices", "-l").stdout

    def mdns_services(self) -> str:
        return self._cmd("mdns", "services", timeout=15).stdout

    def connect(self, address: str) -> str:
        return self._cmd("connect", address).stdout.strip()

    def shell(self, *args: str, timeout: int = 15) -> str:
        """Run a read-only or caller-authorized Android shell command."""

        return self._cmd("shell", *args, timeout=timeout).stdout

    def launch(self, package: str) -> str:
        raise RuntimeError(
            "不要用 adb shell monkey 启动小红书；BlueStacks 上已验证会导致 ADB/应用卡住。"
        )

    def launch_android_package(self, package: str) -> str:
        """Launch an installed package through its resolved Android activity."""

        resolved = self._cmd(
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            package,
            timeout=15,
        ).stdout.strip().splitlines()
        component = resolved[-1].strip() if resolved else ""
        if "/" not in component:
            raise RuntimeError(f"无法解析应用启动入口：{package}")
        return self._cmd(
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            component,
            timeout=30,
        ).stdout

    def launch_with_bluestacks_player(
        self,
        player: Path,
        instance: str,
        package: str,
    ) -> subprocess.CompletedProcess:
        # A running BlueStacks 5 instance can return a non-zero launcher code
        # even when the requested Android app opens successfully. The only
        # reliable success check is the subsequent Android page probe.
        return subprocess.run(
            [
                str(player),
                "--instance",
                instance,
                "--cmd",
                "launchApp",
                "--package",
                package,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def force_stop(self, package: str, *, timeout: int = 15) -> None:
        self._cmd("shell", "am", "force-stop", package, timeout=timeout)

    def pidof(self, package: str, *, timeout: int = 10) -> str | None:
        """Return the current Android process id(s), or None when not running."""

        try:
            output = self._cmd(
                "shell",
                "pidof",
                package,
                timeout=timeout,
            ).stdout.strip()
        except subprocess.CalledProcessError:
            return None
        if not output:
            return None
        return " ".join(sorted(output.split()))

    def tap(self, x: int, y: int) -> None:
        self._cmd("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 500) -> None:
        self._cmd("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def text(self, value: str) -> None:
        encoded = value.replace(" ", "%s")
        self._cmd("shell", "input", "text", encoded)

    def enter(self) -> None:
        self._cmd("shell", "input", "keyevent", "66")

    def package_path(self, package: str) -> str:
        return self._cmd("shell", "pm", "path", package, timeout=15).stdout.strip()

    def enabled_input_methods(self) -> tuple[str, ...]:
        output = self._cmd("shell", "ime", "list", "-s", timeout=15).stdout
        return tuple(line.strip() for line in output.splitlines() if line.strip())

    def default_input_method(self) -> str:
        return self._cmd(
            "shell",
            "settings",
            "get",
            "secure",
            "default_input_method",
            timeout=15,
        ).stdout.strip()

    def enable_input_method(self, component: str) -> str:
        return self._cmd("shell", "ime", "enable", component, timeout=15).stdout.strip()

    def set_input_method(self, component: str) -> str:
        return self._cmd("shell", "ime", "set", component, timeout=15).stdout.strip()

    def broadcast(self, action: str, *, string_extra: tuple[str, str] | None = None) -> str:
        command = ["shell", "am", "broadcast", "-a", action]
        if string_extra is not None:
            key, value = string_extra
            command.extend(["--es", key, value])
        return self._cmd(*command, timeout=15).stdout.strip()

    def adb_keyboard_clear_text(self) -> str:
        return self.broadcast("ADB_CLEAR_TEXT")

    def adb_keyboard_input_text(self, value: str) -> str:
        payload = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return self.broadcast("ADB_INPUT_B64", string_extra=("msg", payload))

    def adb_keyboard_submit_search(self) -> str:
        return self.broadcast("ADB_ACTION_SEARCH")

    def get_windows_clipboard(self) -> str:
        return subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        ).stdout

    def set_windows_clipboard(self, value: str) -> None:
        env = os.environ.copy()
        env["XHS_SCOUT_CLIPBOARD_TEXT"] = value
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Set-Clipboard -Value $env:XHS_SCOUT_CLIPBOARD_TEXT",
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
        )

    def paste_text_via_windows_clipboard(self, value: str) -> None:
        original = self.get_windows_clipboard()
        try:
            self.set_windows_clipboard(value)
            self._cmd("shell", "input", "keyevent", "279")
        finally:
            self.set_windows_clipboard(original)

    def back(self) -> None:
        self._cmd("shell", "input", "keyevent", "4")

    def open_url(self, url: str, *, package: str = "com.xingin.xhs") -> str:
        return self._cmd(
            "shell",
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.VIEW",
            "-p",
            package,
            "-d",
            shlex.quote(url),
            timeout=30,
        ).stdout

    def activity_dump(self) -> str:
        return self._cmd(
            "shell",
            "dumpsys",
            "activity",
            "activities",
            timeout=30,
        ).stdout

    def screenshot(self, destination: Path, *, max_attempts: int = 2) -> Path:
        """Capture a screenshot as a complete PNG at *destination*.

        The capture is written to a unique temp file first and only decoded
        and ``os.replace``-d into ``destination`` once PIL can fully load it.
        This closes the race where a killed/short-lived ``adb exec-out``
        stream (real 738422-byte truncation with a missing PNG IEND chunk
        was observed in production) left a half-written file at the path the
        OCR worker reads next, crashing it with ``image file is truncated``.
        A transient truncation is retried a bounded number of times; a
        persistent one is raised as ``ScreenshotCaptureError`` rather than
        silently handing OCR a bad file.
        """

        destination.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for _attempt in range(max(1, max_attempts)):
            temp_path = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
            try:
                with temp_path.open("wb") as handle:
                    subprocess.run(
                        [
                            str(self.adb),
                            *(["-s", self.serial] if self.serial else []),
                            "exec-out",
                            "screencap",
                            "-p",
                        ],
                        stdout=handle,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        check=True,
                    )
                with Image.open(temp_path) as image:
                    image.load()
            except Exception as exc:  # noqa: BLE001 - any capture/decode failure retries
                last_error = exc
                temp_path.unlink(missing_ok=True)
                continue
            os.replace(temp_path, destination)
            return destination
        raise ScreenshotCaptureError(
            f"failed to capture a complete screenshot at {destination} after "
            f"{max(1, max_attempts)} attempt(s): {last_error}"
        ) from last_error

    def ui_dump(self) -> str:
        self._cmd("shell", "uiautomator", "dump", "/sdcard/window.xml")
        return self._cmd("shell", "cat", "/sdcard/window.xml").stdout

    def window_focus(self) -> str:
        # The unscoped WindowManager dump includes every window, session,
        # policy and trace section.  On a real phone over wireless ADB it can
        # exceed the safety timeout even though the transport is healthy.
        # The displays section contains the same current-focus/app evidence
        # consumed by probe.py while remaining small and bounded.
        return self._cmd(
            "shell", "dumpsys", "window", "displays", timeout=15
        ).stdout

    def last_anr(self) -> str:
        return self._cmd("shell", "dumpsys", "window", "lastanr", timeout=15).stdout


def discover_adb(configured: str | None = None) -> Path:
    candidates = [
        configured,
        shutil.which("adb"),
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        r"D:\BlueStacks_nxt\HD-Adb.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("尚未找到 ADB。请先完成虚拟机安装。")


def discover_bluestacks_player(configured: str | None = None) -> Path:
    candidates = [
        configured,
        r"C:\Program Files\BlueStacks_nxt\HD-Player.exe",
        r"D:\BlueStacks_nxt\HD-Player.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("尚未找到 BlueStacks HD-Player.exe。")


def select_device_serial(
    devices_output: str,
    *,
    model: str,
    service_name: str | None = None,
) -> str:
    matches: list[str] = []
    marker = f"model:{model}"
    for line in devices_output.splitlines():
        # Windows mDNS may disambiguate duplicate service names by inserting
        # `` (2)`` into the ADB serial.  Splitting on whitespace then mistakes
        # the suffix for the state column.  Parse the explicit ``device``
        # state separator so spaces remain part of the serial.
        parsed = re.match(r"^(?P<serial>.+?)\s+device\s+(?P<details>.+)$", line.strip())
        if parsed and marker in parsed.group("details").split():
            matches.append(parsed.group("serial"))
    if service_name:
        stable_serial = f"{service_name}._adb-tls-connect._tcp"
        stable_matches = [serial for serial in matches if serial == stable_serial]
        if len(stable_matches) == 1:
            return stable_matches[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuntimeError(f"未找到已连接的指定安卓设备：model={model}")
    raise RuntimeError(f"发现多台同型号安卓设备，必须显式指定 serial：{matches}")


def select_mdns_connect_address(services_output: str, *, service_name: str) -> str:
    matches: list[str] = []
    for line in services_output.splitlines():
        parts = line.split()
        if (
            len(parts) >= 3
            and parts[0] == service_name
            and parts[1] == "_adb-tls-connect._tcp"
        ):
            matches.append(parts[2])
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuntimeError(f"未发现指定的无线调试服务：{service_name}")
    raise RuntimeError(f"无线调试服务地址不唯一：{service_name} -> {matches}")


def wait_for_device(device: AdbDevice, timeout_seconds: int = 120) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = ""
    while time.monotonic() < deadline:
        last = device.devices()
        if "\tdevice" in last:
            return last
        time.sleep(2)
    raise TimeoutError(f"等待安卓设备超时：{last}")
