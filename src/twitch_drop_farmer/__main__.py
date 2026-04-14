from __future__ import annotations


def main() -> int:
    try:
        from .ui import run
    except ModuleNotFoundError as exc:
        if exc.name in {"PySide6", "requests"}:
            raise SystemExit(
                f"Falta a dependência '{exc.name}'. "
                "Instala tudo com `python -m pip install -r requirements.txt` "
                "e arranca a app com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
                "na raiz do repositório."
            ) from exc
        raise

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
