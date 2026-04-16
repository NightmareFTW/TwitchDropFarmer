# Twitch Drop Farmer

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-2ea44f)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Aplicação desktop para farm de Twitch Drops com foco em controlo local, filtros de campanhas e automação de troca de canal.

Sem Docker, sem browser embutido para visualização contínua, e com configuração guardada localmente.

English quick version: [README.en.md](README.en.md)

## Screenshots

### Vista de Farming

![Vista de Farming](docs/images/ui-farming.png)

### Vista de Campanhas

![Vista de Campanhas](docs/images/ui-campaigns.png)

### Vista de Definicoes

![Vista de Definicoes](docs/images/ui-settings.png)

## Funcionalidades

- Descoberta automática de campanhas ativas e futuras.
- Seleção automática do melhor alvo de farm por regras (campanha, elegibilidade e stream disponível).
- Auto-switch de jogo/canal com intervalo configurável.
- Filtros por whitelist e blacklist de jogos e canais.
- Botão manual para redimir drops.
- Opção de redenção automática periódica.
- Estado de farming em tempo real (jogo, campanha, canal, progresso e ETA).
- Suporte multi-tema na UI.
- Persistência local de sessão e configurações.

## Requisitos

- Python 3.10+
- pip
- Windows, Linux ou macOS

## Instalação

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Arranque

### Via módulo Python

Windows (PowerShell):

```powershell
$env:PYTHONPATH="src"
python -m twitch_drop_farmer
```

Linux/macOS:

```bash
PYTHONPATH=src python -m twitch_drop_farmer
```

### Via duplo clique (Windows)

- Executa o ficheiro `TwitchDropFarmer.pyw`.
- Este launcher evita abrir a janela de consola por defeito.

## Build para EXE (Windows)

```powershell
.\build_exe.ps1
```

Depois, abre:

- `dist\TwitchDropFarmer.exe`

## Como autenticar

1. Inicia sessão na Twitch no teu browser.
2. Abre a app e vai a Conta.
3. Cola o valor do cookie `auth-token` (apenas o valor).
4. Guarda e valida.

Notas:

- Não coloques o nome do cookie, apenas o valor.
- Não adiciones o prefixo `OAuth`.

## Privacidade e segurança

- Credenciais e sessão ficam guardadas localmente.
- Dados sensíveis não devem ser commitados para GitHub.
- O projeto inclui regras de .gitignore para evitar leak de dados locais.

## Estrutura do projeto

```text
src/twitch_drop_farmer/
  __main__.py
  config.py
  farmer.py
  models.py
  twitch_client.py
  ui.py
  assets/
build_exe.ps1
TwitchDropFarmer.pyw
requirements.txt
```

## Troubleshooting

- Erro QtCore DLL no Windows:
  - Evita criar o ambiente virtual com Python do Anaconda.
  - Usa Python oficial (python.org) para criar a .venv.
- Se usares Conda:
  - Instala PySide6 via conda-forge.
- Se persistir:
  - Reinstala Microsoft Visual C++ Redistributable e recria a .venv.

## Aviso

Este projeto depende de endpoints e comportamentos da Twitch que podem mudar sem aviso.
Se algum fluxo deixar de funcionar, pode ser necessário atualizar queries GraphQL e adaptadores de parsing.

## Licença

Este projeto está licenciado sob a licença MIT. Consulta o ficheiro LICENSE.
