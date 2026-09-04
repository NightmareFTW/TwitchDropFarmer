from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
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


def _resolve_python_executable(project_root: Path) -> Path | None:
    candidates = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "Scripts" / "pythonw.exe",
        project_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    for command in ("py", "python", "python3"):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved)
    return None


def _ensure_runtime_dependencies(project_root: Path) -> bool:
    try:
        import PySide6  # noqa: F401
        import requests  # noqa: F401
        return True
    except ModuleNotFoundError:
        pass

    requirements = project_root / "requirements.txt"
    python = _resolve_python_executable(project_root)
    if requirements.exists() and python is not None:
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
            cwd=str(project_root),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        import PySide6  # noqa: F401
        import requests  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _should_launch_packaged_dist(project_root: Path) -> bool:
    packaged_exe = project_root / "dist" / "TwitchDropFarmer" / "TwitchDropFarmer.exe"
    return packaged_exe.exists() and os.environ.get("TDF_USE_DIST", "0") == "1"


def _run_python_module(project_root: Path, python_executable: Path, extra_env: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        [str(python_executable), "-m", "twitch_drop_farmer"],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Sem detalhe do processo.").strip()
        _show_error(
            "Twitch Drop Farmer",
            (
                "Falha ao iniciar a aplicação.\n\n"
                f"Detalhes:\n{detail[:2000]}"
            ),
        )
        return 1
    return 0


def main() -> int:
    project_root = Path(__file__).resolve().parent

    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        venv_python = _resolve_python_executable(project_root)
        if venv_python is not None and Path(sys.executable).resolve() != venv_python.resolve():
            env = os.environ.copy()
            src_path = project_root / "src"
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"
            return _run_python_module(project_root, venv_python, extra_env={"PYTHONPATH": env["PYTHONPATH"]})

        if _should_launch_packaged_dist(project_root):
            packaged_exe = project_root / "dist" / "TwitchDropFarmer" / "TwitchDropFarmer.exe"
            subprocess.Popen([str(packaged_exe)], cwd=str(project_root))
            return 0

    if not _ensure_runtime_dependencies(project_root):
        _show_error(
            "Twitch Drop Farmer",
            (
                "Falta a dependência 'requests' ou 'PySide6'.\n\n"
                "Instala tudo com\n"
                "python -m pip install -r requirements.txt\n\n"
                "ou usa a venv do projecto com\n"
                "$env:PYTHONPATH='src'; python -m twitch_drop_farmer"
            ),
        )
        return 1

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