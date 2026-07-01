from __future__ import annotations

import ctypes
import sys


def _dependency_help(module_name: str) -> str:
    return (
        f"Falta a dependência '{module_name}'. "
        "Instala tudo com `python -m pip install -r requirements.txt` "
        "e arranca a app com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
        "na raiz do repositório."
    )


def _qt_import_help(exc: ImportError) -> str:
    base = (
        "O PySide6 foi instalado, mas o Qt falhou ao carregar no Windows. "
        "Isto costuma acontecer quando a virtualenv foi criada com o Python do Anaconda. "
    )
    if "Anaconda" in sys.version:
        return (
            base
            + "Recomendo recriar a `.venv` com um Python oficial do python.org/Microsoft Store, "
            "ou usar um ambiente Conda e instalar `pyside6` via `conda-forge` em vez de `pip`."
        )
    return (
        base
        + "Se não estiveres a usar Anaconda, instala o Microsoft Visual C++ Redistributable "
        "mais recente e recria a `.venv`."
    )


def _install_hooks() -> None:
    """Instala unraisablehook e threading.excepthook para registar excepções
    não apanhadas no crash.log, filtrando KeyboardInterrupt."""
    import threading
    import traceback as _tb
    from datetime import datetime
    from pathlib import Path

    _log_path = Path.home() / ".twitch-drop-farmer" / "crash.log"

    def _write(header: str, fmt_exc: str) -> None:
        try:
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            with _log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}] {header}\n")
                f.write(fmt_exc)
                f.write("\n")
        except Exception:
            pass

    _orig_unraisable = getattr(sys, "unraisablehook", None)

    def _unraisable(item) -> None:  # type: ignore[no-untyped-def]
        if item.exc_value is not None and not isinstance(item.exc_value, KeyboardInterrupt):
            fmt = "".join(_tb.format_exception(type(item.exc_value), item.exc_value, item.exc_tb))
            _write(f"Unraisable em {item.object!r}", fmt)
        if _orig_unraisable is not None:
            try:
                _orig_unraisable(item)
            except Exception:
                pass

    sys.unraisablehook = _unraisable

    _orig_threading = getattr(threading, "excepthook", None)

    def _thread_exc(args) -> None:  # type: ignore[no-untyped-def]
        if args.exc_type not in (None, KeyboardInterrupt, SystemExit):
            fmt = "".join(_tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            _write(f"Excepção não apanhada em thread {args.thread!r}", fmt)
        if _orig_threading is not None:
            try:
                _orig_threading(args)
            except Exception:
                pass

    threading.excepthook = _thread_exc


def main() -> int:
    _install_hooks()
    # Set AppUserModelID so Windows groups taskbar windows under app identity.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NightmareFTW.TwitchDropFarmer"
            )
        except Exception:
            pass

    try:
        from .ui import run
    except ModuleNotFoundError as exc:
        if exc.name in {"PySide6", "requests"}:
            raise SystemExit(_dependency_help(exc.name)) from exc
        raise
    except ImportError as exc:
        if "QtCore" in str(exc) or "PySide6" in str(exc):
            raise SystemExit(_qt_import_help(exc)) from exc
        raise

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
