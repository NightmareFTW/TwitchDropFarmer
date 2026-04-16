from __future__ import annotations

from pathlib import Path
import sys
from tkinter import Tk, messagebox


def _show_error(title: str, message: str) -> None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showerror(title, message)
    root.destroy()


def main() -> int:
    project_root = Path(__file__).resolve().parent
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
