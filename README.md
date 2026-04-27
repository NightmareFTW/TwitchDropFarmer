# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

Aplicacao desktop em Python + PySide6 para automatizar Twitch Drops, com controlo local, filtros de campanhas e rotacao automatica de canais.

Versao atual: `2.0.24`

## Sobre o projeto

Twitch Drop Farmer evoluiu para um cliente de farming mais robusto e previsivel:

- Dashboard com estados reais de campanha (ativa, nao iniciada, sem stream, completa, perdida e subscricao requerida).
- Selecao manual de alvo por jogo com comportamento sticky e menos trocas inesperadas.
- Filtros organizados em sub-abas com pesquisa, contadores e acoes em lote.
- Modo streamless e fallback de campanhas mais tolerantes a respostas parciais da Twitch.
- Diagnostico e verificacao de atualizacoes mais estaveis, com relatorio resumido por teste.

## Funcionalidades

- Descoberta automatica de campanhas ativas e futuras.
- Selecao automatica do melhor alvo de farm por regras de campanha, elegibilidade e stream disponivel.
- Troca automatica de jogo/canal com intervalo configuravel.
- Filtros por lista branca e lista negra de jogos e canais.
- Botao manual para resgatar drops.
- Opcao de redencao automatica periodica.
- Estado de farming em tempo real (jogo, campanha, canal, progresso e ETA).
- Suporte a multiplos temas na interface.
- Persistencia local de sessao e configuracoes.
- Modo de sessao duradoura por JSON (import/export de sessao).

## Novidades da 2.0.24

- Correcao de falso critico no diagnostico OAuth para utilizadores em modo de sessao duradoura.
- Diagnostico executado em modo seguro (sem fallback renderizado em background), evitando crash da janela.
- Relatorio de diagnostico com tabela compacta (Test | Status | Time | Message).
- Dashboard hide sub-only melhorado para campanhas sem metadados acionaveis.
- Grelha de jogos reorganizada apos ocultacao para eliminar espacos em branco.
- Alvo manual por jogo corrigido para manter selecao consistente.

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
- Notas de release desta versao: `docs/releases/v2.0.24.pt-PT.md` e `docs/releases/v2.0.24.en.md`.

## Como autenticar

1. Inicia sessão na Twitch no teu browser.
2. Abre a app e vai a Conta.
3. Cola o valor do cookie `auth-token` (apenas o valor).
4. Guarda e valida.

Alternativa (sessao duradoura):

1. Exporta a sessao JSON no browser/perfil onde tens login ativo.
2. Importa esse JSON na aba Conta.
3. Guarda e faz refresh.

Notas:

- Não coloques o nome do cookie, apenas o valor.
- Não adiciones o prefixo `OAuth`.

## Privacidade e segurança

- Credenciais e sessão ficam guardadas localmente.
- Dados sensíveis não devem ser enviados para o GitHub.
- O projecto inclui regras de `.gitignore` para evitar exposição de dados locais.
- O repositorio nao inclui `cookies.json`, `campaign_cache.json` nem ficheiros de sessao do utilizador.
- Politica de seguranca e divulgacao responsavel: `SECURITY.md`.

## Capturas de ecrã

### Dashboard

![Dashboard](docs/images/ui-dashboard.png)

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
- Ícone da app continua desatualizado no Windows:
  - Corre `tools\refresh_icon_cache.ps1` em PowerShell para limpar cache de ícones e reiniciar o Explorer.
  - Em alternativa não interativa: `powershell -ExecutionPolicy Bypass -File .\tools\refresh_icon_cache.ps1 -Force`

## Aviso

Este projecto depende de endpoints e comportamentos da Twitch que podem mudar sem aviso.
Se algum fluxo deixar de funcionar, pode ser necessário actualizar queries GraphQL e adaptadores de parsing.

## Licença

Este projecto está licenciado sob a licença MIT. Consulta o ficheiro LICENSE.
