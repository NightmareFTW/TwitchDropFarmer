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


def _smoke_report(path: str | None, report: dict) -> None:
    """Write the smoke test's result where the release workflow can read it (the packaged app has no console)."""
    import json

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if path:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass


def _smoke_checks(*, web: bool = False) -> tuple[bool, list[dict[str, object]]]:
    """Everything a first start needs, without a session and without the network: the app's code and resources
    are all in place, the window builds, and (with ``web``) the embedded browser can load a page.

    A bundle that lacks a module, an icon or the browser engine fails here, in the release workflow, instead of on
    someone's computer. Returns (all_ok, steps); it stops at the first failed step."""
    import os
    import tempfile

    steps: list[dict[str, object]] = []

    def run(name: str, check) -> bool:
        try:
            detail = check()
        except BaseException as exc:  # a failing step must be reported, whatever it raises
            steps.append({"step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
            return False
        steps.append({"step": name, "ok": True, "detail": detail or ""})
        return True

    # Nothing real is read or written: the app's data folder is the home folder, and this is a throw-away one.
    home = tempfile.mkdtemp(prefix="tdf-smoke-")
    os.environ["HOME"] = os.environ["USERPROFILE"] = home
    state: dict[str, object] = {}

    def import_app() -> str:
        from . import __version__
        from . import ui

        state["ui"] = ui
        return f"version {__version__}"

    def assets() -> str:
        ui = state["ui"]
        missing = [name for name in ("icon.ico", "icon.png") if not (ui._ASSETS_DIR / name).is_file()]
        if missing:
            raise FileNotFoundError(f"{', '.join(missing)} not found in {ui._ASSETS_DIR}")
        return str(ui._ASSETS_DIR)

    def build_window() -> str:
        import requests
        from PySide6.QtWidgets import QApplication

        ui = state["ui"]

        def offline(*_args, **_kwargs):
            raise requests.ConnectionError("the smoke test runs offline")

        requests.Session.request = offline  # type: ignore[method-assign]

        class NoDialogs:  # a dialog would wait for a click that nobody gives: report it instead
            def __getattr__(self, name):
                def blocked(*_a, **_k):
                    raise RuntimeError(f"a dialog opened at start-up ({name})")

                return blocked

        ui.QMessageBox = NoDialogs()
        app = QApplication.instance() or QApplication([])
        window = ui.MainWindow()
        window.show()
        for _ in range(20):
            app.processEvents()
        title = window.windowTitle()
        if not title:
            raise RuntimeError("the main window has no title")
        state["app"], state["window"] = app, window
        return f"window '{title}', {len(window.findChildren(ui.QPushButton))} buttons"

    def web_page() -> str:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

        app = state["app"]
        profile = QWebEngineProfile(app)
        page = QWebEnginePage(profile, app)
        state["profile"], state["page"] = profile, page
        outcome: list[bool] = []
        loop = QEventLoop()
        page.loadFinished.connect(lambda ok: (outcome.append(bool(ok)), loop.quit()))
        QTimer.singleShot(30_000, loop.quit)
        page.load(QUrl("about:blank"))
        loop.exec()
        if not outcome:
            raise TimeoutError("the browser engine did not load a blank page in 30 s")
        if not outcome[0]:
            raise RuntimeError("the browser engine reported a failed load")
        return "blank page loaded"

    def take_down() -> None:
        """Close things the way the app does when the person closes the window (its closeEvent stops the timers, the
        stream watcher and the thread pools), and release the browser page before its profile. Ending the process with
        Qt objects still alive crashes it (exit code 0xC0000005 on Windows): not what a user's exit looks like."""
        from PySide6.QtCore import QCoreApplication, QEvent

        app = state.get("app")
        if app is None:
            return

        def settle() -> None:
            # deleteLater() objects are only deleted by their own event type, which processEvents() leaves alone
            # unless the event loop that asked for it is running again.
            for _ in range(5):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()

        for name in ("page", "profile"):  # the page first: a profile must not be released while it has a page
            obj = state.pop(name, None)
            if obj is not None:
                obj.deleteLater()
                settle()
        window = state.pop("window", None)
        if window is not None:
            window.timer.stop()
            window.streamless_timer.stop()
            window.close()
            window.deleteLater()
        settle()

    try:
        ok = run("import the app", import_app) and run("resources are in the bundle", assets)
        if ok:
            ok = run("the main window builds", build_window)
        if ok and web:
            ok = run("the embedded browser loads a page", web_page)
    finally:
        try:
            take_down()
        except BaseException as exc:  # reported, but the steps above already say what worked
            steps.append({"step": "close the window", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
            ok = False
    return ok, steps


def _smoke_test(argv: list[str]) -> int:
    """``--smoke-test [FILE]`` (the app) or ``--smoke-test-web [FILE]`` (also the embedded browser); the report is
    written to FILE as JSON. Exit code 0 = everything worked."""
    import os

    web = "--smoke-test-web" in argv
    flag = "--smoke-test-web" if web else "--smoke-test"
    index = argv.index(flag)
    path = argv[index + 1] if index + 1 < len(argv) and not argv[index + 1].startswith("--") else None
    import threading

    # A hang is a failure too: if the process is still here after a minute, end it with a non-zero code.
    watchdog = threading.Timer(60.0, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    ok, steps = _smoke_checks(web=web)
    _smoke_report(path, {"ok": ok, "mode": "web" if web else "app", "steps": steps})
    return 0 if ok else 1  # a normal return: the interpreter then shuts down in order, like a user's exit


def main() -> int:
    if any(arg in sys.argv for arg in ("--smoke-test", "--smoke-test-web")):
        return _smoke_test(sys.argv[1:])
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
