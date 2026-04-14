# Twitch Drop Farmer (Desktop)

Ferramenta local (sem Docker e sem Web UI) para automatizar farming de drops da Twitch com UI desktop.

## Funcionalidades

- **Streamless orchestration**: o motor decide automaticamente o melhor canal por campanha (prioridade para drops + viewers).
- **Descoberta automática** de campanhas e atualização periódica.
- **Auto-switch** entre canais com base em regras.
- **OAuth persistido em cookies locais** em `~/.twitch-drop-farmer/cookies.json`.
- **Filtros avançados**:
  - whitelist de jogos
  - blacklist de jogos (ignora completamente)
  - blacklist de canais
- **UI local clean** com temas:
  - `twitch`
  - `black_red`
  - `light`

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução

```bash
PYTHONPATH=src python -m twitch_drop_farmer
```

## Observações

- A Twitch altera frequentemente o schema GraphQL. Este projeto usa parsing defensivo e pode requerer ajuste dos hashes persistedQuery no futuro.
- O token OAuth deve ser inserido pelo utilizador na UI.
