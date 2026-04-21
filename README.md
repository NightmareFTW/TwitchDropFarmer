# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

Aplicação desktop em Python + PySide6 para automatizar Twitch Drops, com controlo local, filtros de campanhas e rotação automática de canais.

## Funcionalidades

- Descoberta automática de campanhas activas e futuras.
- Selecção automática do melhor alvo de farm por regras de campanha, elegibilidade e stream disponível.
- Troca automática de jogo/canal com intervalo configurável.
- Filtros por lista branca e lista negra de jogos e canais.
- Botão manual para resgatar drops.
- Opção de redenção automática periódica.
- Estado de farming em tempo real (jogo, campanha, canal, progresso e ETA).
- Suporte a vários temas na interface.
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

## Compilação para EXE (Windows)

```powershell
.\build_exe.ps1
```

Depois, abre:

- `dist\TwitchDropFarmer\TwitchDropFarmer.exe`
- `dist\TwitchDropFarmer-win64.zip`

Notas:

- O build usa `onedir` para evitar um executável monolítico demasiado grande com Qt WebEngine.
- O ZIP gerado é o artefacto mais indicado para distribuição em releases.

## Releases GitHub

- Tags `v*` passam a poder gerar automaticamente um build Windows via GitHub Actions.
- A release publica o pacote `TwitchDropFarmer-win64.zip` como asset.

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
- Dados sensíveis não devem ser enviados para o GitHub.
- O projecto inclui regras de `.gitignore` para evitar exposição de dados locais.

## Capturas de ecrã

### Vista de Farming

![Vista de Farming](docs/images/ui-farming.png)

### Vista de Campanhas

![Vista de Campanhas](docs/images/ui-campaigns.png)

### Vista de Definições

![Vista de Definições](docs/images/ui-settings.png)

## Estrutura do projecto

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

## Resolução de problemas

- Erro `QtCore` DLL no Windows:
  - Evita criar o ambiente virtual com Python do Anaconda.
  - Usa Python oficial (python.org) para criar a `.venv`.
- Se usares Conda:
  - Instala `PySide6` via `conda-forge`.
- Se persistir:
  - Reinstala o Microsoft Visual C++ Redistributable e recria a `.venv`.

## Aviso

Este projecto depende de endpoints e comportamentos da Twitch que podem mudar sem aviso.
Se algum fluxo deixar de funcionar, pode ser necessário actualizar queries GraphQL e adaptadores de parsing.

## Licença

Este projecto está licenciado sob a licença MIT. Consulta o ficheiro LICENSE.
