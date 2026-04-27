from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys

# Set AppUserModelID so Windows taskbar uses the app identity consistently.
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "NightmareFTW.TwitchDropFarmer"
        )
    except Exception:
        pass


def _show_error(title: str, message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10 | 0x1000)
        return
    sys.stderr.write(f"{title}: {message}\n")


def _latest_source_mtime(src_root: Path) -> float:
    latest = 0.0
    if not src_root.exists():
        return latest
    for path in src_root.rglob("*.py"):
        try:
            mtime = path.stat().st_mtime
            if mtime > latest:
                latest = mtime
        except OSError:
            continue
    return latest


def main() -> int:
    project_root = Path(__file__).resolve().parent

    # Prefer packaged EXE when it exists and is up-to-date.
    # This avoids Python default taskbar/file icon behavior when launching from .pyw.
    # Opt-out with TDF_USE_DIST=0.
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        packaged_exe = project_root / "dist" / "TwitchDropFarmer" / "TwitchDropFarmer.exe"
        if packaged_exe.exists() and os.environ.get("TDF_USE_DIST", "1") != "0":
            src_latest = _latest_source_mtime(project_root / "src")
            try:
                exe_mtime = packaged_exe.stat().st_mtime
            except OSError:
                exe_mtime = 0.0

            # Launch the EXE only when it is as recent as source code.
            if exe_mtime >= src_latest:
                subprocess.Popen([str(packaged_exe)], cwd=str(project_root))
                return 0

    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    try:
        from twitch_drop_farmer.__main__ import main as app_main
    except Exception as exc:  # pragma: no cover - launcher safety path
        _show_error(
            "Twitch Drop Farmer",
            (
                "Falha ao iniciar a aplicação.\n\n"
                f"Detalhes: {exc}\n\n"
                "Confirma que instalaste as dependências com\n"
                "python -m pip install -r requirements.txt"
            ),
        )
        return 1

    try:
        return int(app_main())
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code:
            _show_error("Twitch Drop Farmer", str(code))
            return 1
        return 0
    except Exception as exc:  # pragma: no cover - launcher safety path
        _show_error("Twitch Drop Farmer", f"Erro inesperado ao arrancar: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())