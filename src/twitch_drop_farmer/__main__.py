from __future__ import annotations

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


def main() -> int:
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
