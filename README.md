# Twitch Drop Farmer (Desktop)

Ferramenta local (sem Docker e sem Web UI) para automatizar farming de drops da Twitch com UI desktop.

## Funcionalidades

- Streamless orchestration: o motor decide automaticamente o melhor canal por campanha (prioridade para drops + viewers).
- Descoberta automatica de campanhas e atualizacao periodica.
- Auto-switch entre canais com base em regras.
- OAuth persistido em cookies locais em `~/.twitch-drop-farmer/cookies.json`.
- Filtros avancados:
  - whitelist de jogos
  - blacklist de jogos (ignora completamente)
  - blacklist de canais
- UI local clean com temas:
  - `twitch`
  - `black_red`
  - `light`

## Instalacao

### Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Execucao

### Windows / PowerShell

```powershell
$env:PYTHONPATH="src"
python -m twitch_drop_farmer
```

### Linux / macOS

```bash
PYTHONPATH=src python -m twitch_drop_farmer
```

Nao executes `src/twitch_drop_farmer/twitch_client.py` diretamente: esse ficheiro e um modulo interno, nao o entrypoint da aplicacao.

## Observacoes

- A Twitch altera frequentemente o schema GraphQL. Este projeto usa parsing defensivo e pode requerer ajuste dos hashes `persistedQuery` no futuro.
- O token OAuth deve ser inserido pelo utilizador na UI.
