# Twitch Drop Farmer (Desktop)

Ferramenta local (sem Docker e sem Web UI) para automatizar farming de drops da Twitch com UI desktop.

## Funcionalidades

- Streamless orchestration: o motor decide automaticamente o melhor canal por campanha (prioridade para drops + viewers).
- Descoberta automatica de campanhas e atualizacao periodica.
- Auto-switch entre canais com base em regras.
- OAuth persistido em cookies locais em `~/.twitch-drop-farmer/cookies.json`.
- Ajuda contextual na UI para copiares exatamente o valor do cookie `auth-token`.
- Campanhas nao ligadas continuam visiveis e podem abrir o link de ligacao da conta diretamente a partir da app.
- Filtros avancados:
  - whitelist de jogos
  - blacklist de jogos (ignora completamente)
  - whitelist de canais com prioridade
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

### Arranque direto por duplo clique (sem CMD)

- Podes abrir a app diretamente com duplo clique em `TwitchDropFarmer.pyw`.
- Este launcher usa o codigo da app em `src/` e tenta mostrar erros em janela popup, sem consola.

### Gerar .exe (Windows)

Na raiz do projeto, corre uma vez:

```powershell
.\build_exe.ps1
```

Depois abre por duplo clique:

- `dist\TwitchDropFarmer.exe`

## Observacoes

- A Twitch altera frequentemente o schema GraphQL. Este projeto usa parsing defensivo e pode requerer ajuste dos hashes `persistedQuery` no futuro.
- O token a colar na UI e o valor do cookie `auth-token` da tua sessao Twitch, sem o nome do cookie e sem o prefixo `OAuth `.

## Troubleshooting

- Se aparecer `ImportError: DLL load failed while importing QtCore` no Windows, evita criar a `.venv` com o Python do Anaconda. O caminho mais estavel e usar um Python oficial do python.org ou Microsoft Store para criar a virtualenv.
- Se quiseres ficar no ecossistema Conda, cria um ambiente Conda e instala `pyside6` via `conda-forge` em vez de usar a wheel do `pip`.
- Se o erro persistir mesmo fora do Anaconda, instala o Microsoft Visual C++ Redistributable mais recente e recria a `.venv`.
