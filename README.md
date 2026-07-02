# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

Aplicação desktop em Python + PySide6 para automatizar Twitch Drops, com controlo local, filtros de campanhas e rotação automática de canais.

Versão actual: `2.2.39`

## Sobre o projecto

O Twitch Drop Farmer evoluiu para um cliente de farming mais robusto e previsível:

- Dashboard com estados reais de campanha (activa, não iniciada, sem stream, completa, perdida e subscrição requerida).
- Selecção manual de alvo por jogo com comportamento persistente e menos trocas inesperadas.
- Filtros organizados em sub-abas com pesquisa, contadores e acções em lote.
- Modo streamless e fallback de campanhas mais tolerantes a respostas parciais da Twitch.
- Diagnóstico e verificação de actualizações mais estáveis, com relatório resumido por teste.

## Funcionalidades

- Descoberta automática de campanhas activas e futuras.
- Selecção automática do melhor alvo de farm por regras de campanha, elegibilidade e stream disponível.
- Troca automática de jogo/canal com intervalo configurável.
- Filtros por lista branca e lista negra de jogos e canais.
- Botão manual para resgatar drops.
- Opção de redenção automática periódica.
- Estado de farming em tempo real (jogo, campanha, canal, progresso e ETA).
- Suporte a múltiplos temas na interface.
- Persistência local de sessão e configurações.
- Modo de sessão duradoura por JSON (importação/exportação de sessão).

## Novidades da 2.2.39

- Aviso no dashboard e tooltip no botão «Actualizar dashboard» a explicar o que fazer quando os drops de um jogo não carregam.
- Revisão completa das traduções PT-PT (acordo ortográfico pré-1990) e EN, com acentuação corrigida.
- Corrigida a janela «Sobre» que mostrava `\n-` como texto literal; texto reescrito e actualizado.

## Novidades da 2.2.38

- Novo contador "A mostrar X/Y jogos da whitelist" no dashboard.

## Novidades da 2.2.37

- Botão "Atualizar dashboard" passa a fazer um scan completo de detalhe por-drop a toda a whitelist, em vez de só 8 campanhas por ciclo.

## Novidades da 2.2.36

- Obtenção de detalhe por-drop passa a priorizar o jogo seleccionado/a ser farmado, em vez de seguir só a ordem de data de fim mais próxima.

## Novidades da 2.2.35

- Corrigida regressão da 2.2.34: o perfil persistente em disco fazia o fallback do browser deixar de encontrar campanhas após muitos reinícios. Revertido para um perfil em memória (reutilizado dentro da mesma execução).

## Novidades da 2.2.34

- Perfil de browser persistente e partilhado entre chamadas de fallback (em vez de um novo a cada vez).
- Reaproveitamento do token Client-Integrity capturado do browser em pedidos directos, durante alguns minutos.
- "Circuit breaker" que evita repetir o `DropCampaignDetails` quando já se sabe, no mesmo ciclo, que a integrity check está bloqueada.

## Novidades da 2.2.33

- Timestamps `[HH:MM:SS]` em cada linha do log.
- Cache de campanhas com merge em vez de substituição — jogos da whitelist fora do alvo activo passam a preencher-se ao longo do tempo.

## Novidades da 2.2.32

- Corrigida inundação de log no fallback de browser (chamadas assíncronas sobrepostas) e reduzido o custo da obtenção de detalhe por-campanha para deixar de atrasar o heartbeat streamless.

## Novidades da 2.2.31

- O fallback invisível de browser (sem qualquer janela) passa a visitar também a página de detalhe de cada campanha activa, obtendo progresso real por-drop em vez de apenas dados-resumo.

## Novidades da 2.2.30

- **[CRÍTICO]** Corrigido `Client-Id` vazio em todos os pedidos GraphQL directos (Inventory, ViewerDropsDashboard, DropCampaignDetails), que fazia o integrity check da Twitch falhar sempre e forcava o fallback lento por browser. Restaurados os Client-IDs publicos reais da Twitch — a app deve agora funcionar sem precisar de abrir qualquer browser.

## Novidades da 2.2.29

- Corrigido o painel "Drops activos" a mostrar "Sem drops activos" mesmo com uma campanha activamente a ser farmada — passa a mostrar o progresso agregado quando a Twitch nao devolve detalhe por-drop.

## Novidades da 2.2.28

- Corrigido falso positivo generalizado de "exige subscricao" no dashboard, na lista de drops activos e na contagem da checkbox "ocultar sub-only" — campanhas sem metadados por-drop (fallback do browser) deixam de ser confundidas com sub-only.

## Novidades da 2.2.27

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
- Notas de release desta versão: `docs/releases/v2.2.39.pt-PT.md` e `docs/releases/v2.2.39.en.md`.

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
