# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

## [3.0.1] - 2026-11-14

### Fixed

- **Dois textos ficavam em português com a interface em inglês**: o texto de ajuda do campo de importação da
  sessão («Colas aqui o JSON da sessão exportada do browser...», na aba Conta) e os *tooltips* dos perfis de
  energia («Perfil: ...»). Passaram para a tabela de traduções e mudam com o idioma. Um teste falha se algum
  `setText`, `setToolTip`, `setPlaceholderText` ou `setTitle` voltar a receber um texto escrito à mão.

### Changed

- **README com galeria de capturas de ecrã**, em PT-PT e em inglês (cada README mostra a interface no seu
  idioma): as quatro vistas principais, a janela «Iniciar sessão» e os três temas. `tools/take_screenshots.py`
  gera agora os dois conjuntos (em `docs/images/` e `docs/images/en/`), sempre com dados fictícios.

## [3.0.0] - 2026-11-14

Primeira release pública desde a 2.2.39. Resume o que mudou nas versões 2.2.40 a 2.2.72, cujo detalhe
está nas entradas abaixo. As definições existentes continuam a ser lidas; as opções novas arrancam com os
valores por omissão.

### Destaques

- **Um farm que se mantém e recupera sozinho.** Deixa de saltar de jogo em jogo; segue o fluxo do canal em
  segundo plano para a Twitch creditar os minutos; um monitor detecta campanhas que não creditam, reinicia, muda
  de canal e, no limite, desiste. Lembra-se das campanhas já concluídas, do último jogo e, ao abrir, retoma o
  farm que estava a correr.
- **Muito menos pedidos à Twitch.** Os perfis de energia (Económico, Balanceado, Agressivo) fazem mesmo o que
  dizem, e as consultas que a Twitch rejeita com «failed integrity check» já não se repetem a cada ciclo.
- **Funciona com a verificação de integridade.** O registo público é a alternativa quando a Twitch recusa o
  dashboard, e os drops que exigem subscrição são reconhecidos e podem ser ocultados.
- **Iniciar sessão sem esforço**: um botão com uma janela que explica cada passo, e a opção de lembrar a
  sessão neste computador.
- **Dashboard** com fitas de estado em cada cartão (`FARMING`, `LIVE`, `CONCLUÍDO`, `SEM CANAIS`...) cujo texto
  cabe sempre inteiro, também no Windows, filtros para ocultar jogos só de subscrição ou inactivos, capas
  fiáveis e uma mensagem de espera para um jogo que acabou de começar.
- **Alertas que funcionam**: «Drop pronto», campanha a expirar, farm sem progresso, canal desligado, sessão
  inválida.
- **Redimir drops automaticamente vem desligado**, com um «?» a explicar porquê: a Twitch costuma rejeitar o
  *claim* feito pela app, e cada tentativa falhada só atrai atenção.
- **Guardar log** grava um ficheiro com tokens e cookies removidos, e o diagnóstico do sistema passou a dizer
  a verdade.
- **Definições guardadas automaticamente**, botões auditados um a um, e texto que já não é cortado.
- **Projecto**: README em PT-PT e EN, capturas de ecrã com dados fictícios, mais de 600 testes automáticos
  (incluindo um que impede dados pessoais no repositório) e um fluxo de testes no GitHub Actions, que passa
  também no Windows (antes falhavam dois testes: um das fitas e o do arranque sem consola), e o *script* que
  constrói o pacote Windows, que rebentava num checkout limpo (como o do GitHub Actions) por listar uma pasta
  `dist` que ainda não existia. O fluxo de publicação passa a verificar o pacote antes de o publicar: confirma o
  conteúdo do `.zip`, extrai-o numa pasta limpa e arranca a app com `--smoke-test` (constrói a janela sem sessão
  e sem rede, numa pasta pessoal descartável) e só publica se isso funcionar.

### Conhecido

- O claim feito pela app é frequentemente rejeitado pela Twitch: reivindica em twitch.tv/drops/inventory.
- «Procurar actualizações» só avisa que há uma versão nova; não a instala.
- O pacote Windows não está assinado, por isso o SmartScreen pode avisar na primeira execução.

## [2.2.72] - 2026-11-14

### Fixed

- **O botão «Sessão: …» continuava encostado às linhas do layout.** A 2.2.69 encolheu-o e centrou-o na
  barra dos separadores, mas no Windows (letra e escala do ecrã maiores) a barra é tão alta como o botão e
  ele voltava a tocar na linha de baixo e na da direita. Nenhum *padding* resolve isto em todas as máquinas,
  porque a altura da barra depende do tipo de letra e da escala. O botão deixou de ser o «canto» da barra:
  tem agora **uma linha própria acima dos separadores**, alinhada à direita, com a altura normal dos outros
  botões e o espaçamento do layout à volta. Os testes medem o espaço livre até à linha dos separadores, nos
  dois estados (com e sem sessão), em PT e EN e com um tipo de letra maior, e falham se o botão voltar ao canto.
- Removido o ajuste de altura que só existia por causa do canto (`_fit_button_height`). Capturas de ecrã
  do README refeitas.

## [2.2.71] - 2026-11-14

Preparação para tornar o repositório público: nada de pessoal no código, README novo e capturas de ecrã
com dados fictícios.

### Added

- **Teste que procura dados pessoais** (`tests/test_no_personal_data.py`): falha se algum ficheiro seguido
  pelo git tiver endereços de email (fora os de *no-reply* e de exemplo), caminhos de pasta de utilizador
  reais (`C:\Users\<nome>`, `/home/<nome>`), valores com forma de token da Twitch ou IDs de conta reais.
  Termos específicos de cada pessoa (o nome de utilizador, por exemplo) não ficam no repositório: lêem-se,
  se existir, de `tests/.private_terms`, que o git ignora. Verificado por mutação (um email plantado no
  README faz o teste falhar).
- `.gitignore` passa a cobrir os ficheiros que contêm dados da conta (`config.json`, `session*.json`,
  caches, `logs/`, `log-*.txt`, `.env`, `*.pem`, `*.key`, `*.har`).

### Changed

- **README (PT-PT e EN) reescrito** para reflectir a aplicação de hoje: o que faz e como funciona, instalação
  (pacote Windows e código-fonte), primeiros passos, porque é que o *claim* automático vem desligado, que
  ficheiros ficam no computador e com quem a app fala, limitações conhecidas, resolução de problemas,
  desenvolvimento e aviso. Já não fixa um número de versão nem repete o histórico (que está no CHANGELOG).
- **Capturas de ecrã novas**, com jogos, canais e drops fictícios. `tools/take_screenshots.py` corre agora
  com uma pasta pessoal temporária e sem rede, por isso nunca lê nem mostra a conta de quem a corre (antes
  usava a configuração real e fotografava ecrãs vazios da 2.0.24).
- `SECURITY.md`: deixa de indicar `2.0.x` como a versão suportada e lista os ficheiros de sessão actuais.

### Fixed

- **As fitas de estado dos cartões cortavam o texto.** «CONCLUÍDO», «SEM CANAIS», «LIGAR CONTA» e outras
  perdiam a primeira e a última letra por não caberem na faixa diagonal. A fita passou de 58 para 70 px e o
  tipo de letra ajusta-se ao texto (de 8 px até 6 px, medido com as métricas reais da máquina).
- Nome de utilizador, ID de conta e nome de um canal reais que estavam em testes foram substituídos por
  valores neutros.

## [2.2.70] - 2026-11-14

### Changed

- **«Drops activos» já não diz «Sem drops activos» a um jogo que acabou de começar a farmar.** Um jogo
  novo não aparece no Inventory enquanto a Twitch não creditar os primeiros minutos (cerca de 2-3 min
  nos logs), e o painel mostrava «Sem drops activos para mostrar» como se o jogo não tivesse drops.
  Agora mostra «A aguardar a informação dos drops…» (com a razão) durante 15 minutos. Se passado esse
  tempo continuar sem dados, aí sim diz «Sem drops activos para mostrar». Os 15 min coincidem com o
  momento em que o monitor de bloqueios (tempo limite de 30 min) muda de canal.
  - Só espera com o farm a correr; parado, não há nada a chegar e diz logo que não há drops.
  - Cada jogo tem o seu relógio, e o relógio recomeça se o farm for parado e iniciado de novo.
  - Assim que aparece qualquer informação (um drop, ou só os minutos da campanha) a mensagem é
    substituída; e o painel é redesenhado ao fim da espera mesmo que nada tenha chegado.

## [2.2.69] - 2026-11-14

### Changed

- **O botão «Sessão: …» já não fica por cima das linhas do layout.** Era mais alto do que a barra dos
  separadores (29 px numa barra de 27 px) e invadia, por cima e por baixo, a linha de topo do painel.
  Passou a ter um *padding* mais fino e a ficar centrado na altura da barra (dentro de um contentor),
  seja qual for o tipo de letra da máquina. O texto continua sem ser cortado.
- **«Redimir drops automaticamente» tem agora um «?» ao lado do texto** que explica porque é que vem
  desligado e que problemas pode causar se for ligado: a Twitch costuma rejeitar o *claim* feito pela
  app («failed integrity check») e o mesmo clique no site ou no telemóvel funciona; falha quase sempre
  e o drop fica por reivindicar (a app tenta até 3 vezes, com pausas crescentes, e desiste); cada
  tentativa falhada é uma rajada de pedidos que a Twitch pode ver como automação; e pode dar a ideia de
  que o drop está tratado quando não está. Os números do texto vêm das constantes reais. O antigo
  *tooltip* da caixa foi substituído por este.
- A opção continua **desligada por omissão** (já estava na configuração); fica agora garantido por
  testes. Quem a ligou de propósito mantém-na ligada.

### Fixed

- **Contagem de «sem avanço» arrastada entre campanhas.** O contador de heartbeats sem progresso (ao 3.º
  seguido força-se uma actualização completa) não era reposto ao mudar de campanha, e a campanha nova
  herdava os heartbeats parados da anterior: no log da 2.2.66, um único heartbeat parado depois de uma
  mudança já forçava a actualização completa. Passa a recomeçar do zero em cada campanha; três
  heartbeats parados seguidos na mesma campanha continuam a forçá-la.

## [2.2.68] - 2026-11-14

Auditoria completa (logs reais, análise estática, *fuzz* e simulação longa). O que se encontrou e corrigiu:

### Fixed

- **«Campanha Concluída» repetia-se de hora a hora** para cada campanha concluída (no log da noite,
  Where Winds Meet às 05h, 06h, 07h, 08h e 09h). O motor vê a campanha concluída em todos os ciclos
  e o gestor de alertas só trava repetições durante uma hora. Agora cada campanha é anunciada **uma
  vez por execução**, e uma que conclua mais tarde continua a ser anunciada.
- **120 pedidos a falhar numa noite.** O `ViewerDropsDashboard` é rejeitado («failed integrity check»)
  em todas as tentativas e a app repetia-o 2 vezes a cada ciclo de 10 min, sem nunca obter dados.
  Depois da primeira rejeição, o pedido não se repete durante 1 hora (cerca de 10 pedidos por noite
  em vez de 120; o resto do ciclo corre exactamente como antes, com a mesma resposta). Volta a
  perguntar logo se: carregas em «Actualizar dashboard», se iniciares sessão com outro token, ou se o
  browser tiver apanhado um token de integridade.
- **Duas escritas ao mesmo tempo estragavam ficheiros.** A memória de campanhas concluídas é escrita
  pela *thread* do motor e pela da janela, e a cache de campanhas por duas chamadas de
  `fetch_campaigns` (a de fundo e a de uma actualização manual), que partilham o mesmo ficheiro
  temporário: sem trava, a segunda gravação perdia-se em silêncio (4 de 24 numa experiência) e o
  ficheiro ficava inválido enquanto se sobrepunham. Ambas têm agora um *lock*; os testes falham sem
  ele.
- Imports sem uso retirados do `ui.py`.

### Verified (sem alterações)

- Logs das 2.2.64 e 2.2.65 (cerca de 14 h): 667 heartbeats com mediana de 59 s; o único buraco foi
  uma falha da tua ligação (6 min, 02:55–03:01), de que a app recuperou sozinha e avisou; os 404 de
  *playlists* eram canais que acabaram, e a farm passou a outro.
- Análise estática (`pyflakes`): nenhum nome indefinido.
- *Fuzz*: 4 000 páginas do registo mutadas, 3 000 JSONs de sessão, 500 ficheiros de memória e de
  cache corrompidos e nomes de jogos extremos: nenhuma excepção inesperada.
- Simulação de 3 600 ciclos do motor e da janela (6 sementes, campanhas que terminam e voltam como
  «fantasmas» do registo): nunca se escolheu uma campanha concluída, nunca houve um salto de jogo
  com a campanha ainda farmável, e nunca mais de 14 consultas de canais num ciclo.

## [2.2.67] - 2026-11-14

### Fixed

- **«Drop completado!» passa a «todos os drops concluídos!»** no alerta «Campanha Concluída». A
  palavra «completado» não se usa: diz-se «concluído» (ou «completo»). Um teste falha se a palavra
  voltar a aparecer em qualquer ficheiro da app ou em qualquer tradução.

## [2.2.66] - 2026-11-12

Da análise do log da noite: das 06:00 às 10:11 a farm esteve **mais de 4 horas** no MARVEL SNAP, uma
campanha que já estava concluída e reivindicada, sem receber um único minuto de crédito.

### Fixed

- **Uma campanha concluída voltava como «nova» e entrava no conjunto de escolha.** Quando todos os
  drops são obtidos e reivindicados, a Twitch deixa de a listar em «em progresso». O registo público,
  que não sabe nada sobre ti, continua a listá-la como activa e sem dados (0/0 min), e a app não tinha
  como a distinguir de uma campanha a sério. Agora a app **lembra, em disco**
  (`completed_campaigns.json`), as campanhas que viu concluídas no Inventory, e o cartão do registo
  que corresponde a uma delas (mesmo jogo, mesma data de fim, e não mais drops do que os concluídos)
  fica com a etiqueta **CONCLUÍDO** e fora das escolhas da farm. **Uma campanha nova do mesmo jogo
  não é escondida**: tem outra data de fim, ou mais drops, e volta a ser escolhível.
- **A farm podia ficar horas numa campanha que não rende nada.** O monitor de estagnação só era
  alimentado quando o Inventory reconhecia a campanha; no caso contrário («Heartbeat sem campanha
  reconciliada no Inventory», 256 vezes nessa noite) o ramo só escrevia no log. Agora também conta:
  se a recuperação completa (reiniciar a vigilância aos 20 % do tempo limite, trocar de canal aos
  50 %, desistir aos 100 %) não vê **nenhum** crédito, a farm desiste da campanha. Não conta como
  estagnação se o próprio Inventory falhou (aí não se sabe nada) nem se o `CurrentDrop` da Twitch
  mostra que há crédito a ser ganho.
- Quando a farm desiste de uma campanha **do registo que nunca teve progresso**, guarda-a também como
  concluída («sem crédito»), pelo mesmo critério de data e de drops. Isto é uma **dedução** (o registo
  não diz o que fizeste), por isso só dura 48 h e **«Actualizar dashboard» volta a tentá-las**; as que a
  app viu concluídas mesmo, essas duram até a campanha acabar. Uma campanha real que estagna continua
  só a ser posta de parte, nunca é dada como concluída.
- O texto do «?» do dashboard explica a nova etiqueta CONCLUÍDO e o novo comportamento do botão.

## [2.2.65] - 2026-11-11

### Added

- **«Ocultar jogos inactivos (N)»** no cabeçalho dos jogos da whitelist, ao lado do filtro de
  subscrição. Esconde os jogos cuja etiqueta é INATIVO (campanha já terminada ou que ainda não
  começou) e o número diz quantos jogos da whitelist estão assim, com o filtro ligado ou não.
  Fica guardado como as restantes opções.

### Changed

- **Cabeçalho reorganizado:** a primeira linha tem o «?», a contagem («A mostrar 83/83 jogos») e
  os dois botões de actualizar; a segunda tem os dois filtros. Os dois textos soltos («Clica num
  jogo…» e a nota cinzenta com o «ℹ») passaram para o balão do **«?»**, que agora também explica
  **todas** as etiquetas dos cartões (FARMING, LIVE, A VERIFICAR, SEM CANAIS, LIGAR CONTA,
  SUBSCRIÇÃO, CONCLUÍDO, INATIVO — um teste falha se uma etiqueta nova não for explicada). Os
  balões têm as linhas quebradas, porque o Qt não o faz sozinho e um parágrafo comprido dava um
  balão tão largo como o ecrã.
- **O texto foi revisto contra o que a app faz hoje**, e duas frases estavam desactualizadas:
  - «pode mostrar 0/0 min durante uns segundos»: um jogo que ainda não começaste a farmar mostra
    isso **até a Twitch registar o primeiro minuto** de visualização (sem os detalhes da Twitch,
    que ficam bloqueados pela verificação de integridade, não há mais dados antes disso);
  - «scan completo de todos os jogos»: os dois botões fazem o mesmo — recarregam as campanhas e
    tentam obter os drops detalhados com o browser invisível, **com a janela parada** e a pedir
    mais pedidos à Twitch — e só diferem em que o «Actualizar dashboard» também descarrega as
    capas outra vez e o «Actualizar drops» põe o jogo farmado à frente. Se a Twitch os bloquear,
    não trazem mais detalhe. As dicas dos botões e dos filtros dizem agora isto.

### Fixed

- **O contador «Ocultar jogos com drops de subscrição (N)» contava campanhas e o filtro esconde
  jogos**: um jogo com duas campanhas só de subscrição contava 2 e escondia 1. Passa a contar jogos.
- Quando os filtros escondem **todos** os jogos, a mensagem já não diz «Adiciona jogos na
  whitelist» (que só faz sentido sem jogos): diz que estão ocultos pelos filtros.

## [2.2.64] - 2026-11-11

### Added

- **A farm continua no último jogo em que estava, em vez de ir para «The Quinfall».** Ao
  arrancar não havia alvo manual nem campanha em curso, por isso a app usava o primeiro da
  ordenação — com a prioridade «Terminam mais cedo», sempre o «The Quinfall», cujo fim aparece
  como «0 minutos». Agora a app lembra o jogo e repõe-no:
  - **o que fica lembrado é onde a farm realmente está**, não só o que escolheste: se clicas
    num jogo, fica esse; se esse terminar e a farm passar sozinha a outro, passa a ficar o
    outro. O simples facto de a janela mostrar o alvo por omissão antes de a farm arrancar
    **não** apaga o que estava lembrado;
  - **o jogo lembrado tem o canal verificado logo no primeiro ciclo** (até 2 das suas campanhas,
    e só se a farm ainda não estiver nesse jogo; o total de pedidos não aumenta). Sem isto ele
    ficava «por verificar», não era farmável e a farm caía outra vez no primeiro da fila;
  - se o jogo lembrado já não tiver nada para farmar (terminou, sem canais, só subscrição),
    cai na escolha normal, e uma escolha manual tua continua a mandar sobre ele.
- **Retomar a farm ao abrir a app** (opção no separador Definições → Básico, ligada por
  omissão): se a farm estava a correr quando fechaste a app, volta a arrancar sozinha nesse
  jogo, desde que haja sessão. Se carregares em «Parar farm» antes de fechar, não arranca.
  Fechar a janela não conta como parar. O log diz quando retoma.

## [2.2.63] - 2026-11-11

### Fixed

- **O texto de dois botões aparecia cortado em baixo** (o pé do «g»): «Guardar log» e o
  botão «Sessão: …» do canto superior direito. O primeiro tinha um limite de altura de 24 px
  que eu pus (o tema dá 7 px de enchimento por cima e por baixo, e a letra já não cabia); o
  segundo, por ser um *corner widget* do `QTabWidget`, era espremido à altura da barra de
  separadores, 3 px abaixo do que precisa. Agora o «Guardar log» não tem limite de altura e o
  botão da sessão pede ao Qt a altura de que o tipo de letra **da tua máquina** precisa, em vez
  de um número fixo. Um teste novo falha se qualquer botão visível, em qualquer separador,
  tema ou idioma, ficar mais baixo do que o seu texto precisa.

## [2.2.62] - 2026-11-11

### Fixed

- **Uma janela de cmd abria com a app e ficava aberta até ela fechar** (e fechá-la matava a
  app). O `TwitchDropFarmer.pyw` corre sem consola, mas relançava a app com `python.exe`, um
  programa de consola, e o Windows abre sempre uma consola nova para esses. O processo filho
  passa a ser lançado sem janela (`CREATE_NO_WINDOW`), a saída continua a ser capturada para
  mostrar um erro de arranque se houver, e o mesmo vale para a instalação automática de
  dependências. Se o `.pyw` for aberto por um `python.exe` com uma consola criada só para ele,
  o launcher fecha-a; um terminal teu (partilhado com a shell) nunca é tocado.
  Correr `python -m twitch_drop_farmer` à mão num terminal continua a mostrar esse terminal.

## [2.2.61] - 2026-11-11

### Fixed

- **A opção «Lembrar a sessão neste computador» não era alcançável com a sessão iniciada.**
  A janela de sessão só abria quando não havia nada utilizável, por isso quem já tinha uma
  sessão válida nunca a via — e era essa pessoa que queria ligar a opção. A aba **Conta**
  passa a ter o botão «Abrir janela de sessão».

## [2.2.60] - 2026-11-11

Tudo isto vem da análise do log da noite (9 horas a farmar) e de um censo ao registo
público (twitchdrops.app), com dados reais.

### Fixed

- **Os drops de subscrição não eram reconhecidos.** Com a Twitch a bloquear os detalhes das
  campanhas em todos os ciclos (integrity check, visto no log), as campanhas vêm do registo
  público, que só dá o nome do jogo: nenhuma chegava a ser marcada como «só subscrição» (o
  contador «Ocultar jogos com drops de subscrição» ficava sempre a 0) e a app tentava farmar
  esses jogos à espera de um progresso que nunca viria. O código que devia tratar disto
  nunca era chamado e procurava um HTML (`reward-card`) que o site não tem. Agora a app lê a
  página de cada jogo — onde cada drop diz «Watch 1h» ou «1 sub» —, devagar e em segundo
  plano (1,5 s entre páginas, nunca bloqueia a lista), guarda o resultado em disco
  (`registry_rewards.json`) e só volta a ler um jogo quando o cartão dele muda (ou ao fim de 3
  dias). Um jogo é «só subscrição» quando **todos** os drops activos são «N sub»; um jogo com
  drops de tempo e de subscrição **continua farmável**, e uma formulação desconhecida nunca
  conta como subscrição. Medido no registo real (111 jogos): 2 só-subscrição — Call of Duty:
  Modern Warfare 4 e ELDEN RING — e 8 mistos (Cyberpunk 2077, League of Legends, Legion TD 2,
  World of Warcraft, PAYDAY 3, FELLOWSHIP, Hunt Club On Stream, Marbles on Stream). Ao arrancar
  demora cerca de 2 a 3 minutos a ler tudo; o resultado aparece no poll seguinte e o log diz
  quais são.
- **Jogos expirados ou por lançar eram tratados como activos.** Todos os cartões do registo
  eram marcados `ACTIVE` por 30 dias, incluindo os de «Campaign history» (Dead by Daylight,
  Fortnite, Escape from Tarkov…) e os «Coming Soon» (GTA VI). O log mostra a app a procurar
  canais para Dead by Daylight (9×), GTA VI (9×) e Fortnite (6×): se as campanhas em progresso
  acabassem, o motor podia escolher um deles e ficar a «farmar» sem campanha nenhuma. Agora
  são `EXPIRED` / `UPCOMING`. Dos 111 cartões: 88 activos, 3 por começar, 20 expirados.
  As campanhas do registo passam também a usar as datas reais do cartão (antes tinham todas
  «daqui a 30 dias», por isso a prioridade «Terminam mais cedo» não as distinguia).
- **511 pesquisas de imagens repetidas numa noite** para um único jogo («LEGO Batman…», que
  não tem categoria na Twitch): quando nenhuma fonte tinha a capa, o resultado nunca era
  guardado e, a cada refresh do dashboard, repetia-se a cadeia toda (pedido GraphQL e página
  da categoria na Twitch, Steam e Google) — mais tráfego da tua rede para a Twitch sem
  nenhum proveito. Agora «ninguém a tem» fica lembrado 6 horas; uma falha causada pela rede
  só 5 minutos, para um corte de Wi-Fi ao arrancar não deixar as capas em branco horas. O
  botão «Actualizar dashboard» volta a tentar logo.
- **Alertas «Campanha a expirar» repetidos.** Eram separados pelo texto: «The Quinfall —
  termina em 0 minutos» (campanha já terminada) repetia-se de hora a hora e a contagem
  decrescente do Albion Online gerava um alerta novo a cada poll. Agora há um alerta por
  campanha e nenhum para campanhas já terminadas.

### Removed

- `_extract_game_rewards_from_page` e `_apply_game_page_reward_metadata`: nunca eram chamadas
  e o teste que as cobria usava HTML inventado.

## [2.2.59] - 2026-11-11

### Added

- **Botão «Iniciar sessão»** no canto superior direito (ao lado de «A farmar agora» /
  «Campanhas»). Um clique usa o que já existe e só pergunta quando não há nada utilizável,
  por esta ordem: (1) confirma o token que a app já tem (se já estás com a sessão iniciada
  só confirma, sem refazer a actualização das campanhas); (2) se aprovaste guardar a
  sessão, restaura-a sozinho em **3 passos seguidos** — ler, importar e validar — e
  escreve cada passo no log; (3) se nada disto funcionar, abre a janela abaixo com o
  motivo. Sem ligação à internet diz isso mesmo e não deita fora os dados. Quando a sessão
  está iniciada o botão mostra o nome da conta.
- **Janela «Iniciar sessão na Twitch»** com os dois métodos explicados passo a passo para
  quem nunca usou a app:
  - *Sessão Duradoura*, na ordem certa: **1 Importar** (só carrega os dados), **2 Validar**
    (confirma junto da Twitch; só aqui a sessão fica iniciada), **3 Exportar** (opcional,
    cópia de segurança; fica também na área de transferência, com o aviso de que quem
    tiver o texto entra na conta);
  - *Token Rápido*, com o caminho completo para encontrar o `auth-token` (F12 →
    Application/Storage → Cookies → twitch.tv), o que **não** copiar (o nome do cookie, o
    prefixo `OAuth`, o `api_token`), um botão que abre o twitch.tv e o token escondido
    até pedires para o ver. O token não fica na janela depois de a usares.
  Os erros aparecem dentro da janela, não em pop-ups; cada separador tem scroll para
  caber em ecrãs de 768 px de altura.
- **«Lembrar a sessão neste computador»** (opção do utilizador, desligada por omissão):
  só depois de confirmares num aviso que explica que o ficheiro
  (`~/.twitch-drop-farmer/session.json`) fica em texto simples com o teu token, a app
  guarda o JSON da sessão — e actualiza-o sempre que a sessão é confirmada, para os
  cookies que a Twitch renova não ficarem velhos. Desligar a opção apaga o ficheiro. O
  token nunca é escrito no log.

### Fixed

- **«Portugues (Portugal)» sem acento** no seletor de idioma → «Português (Portugal)».
- **Importar sessão** aceitava só o JSON exportado pela própria app e rebentava com a lista
  de cookies que uma extensão do browser exporta. Passa a aceitar as duas formas e, para
  tudo o que não seja uma sessão, devolve um erro claro em vez de uma excepção. Também
  deixou de apagar o `device_id` quando o JSON não o traz, e um token já confirmado pela
  Twitch deixou de ser substituído por engano (um por confirmar é).
- A aba «Conta» e a janela novas partilham o mesmo código; as mensagens «Sessão importada»
  e «Tens de colar o JSON» passaram a respeitar o idioma. Exportar sem haver sessão diz
  que não há nada para exportar (antes dava um JSON vazio).

## [2.2.58] - 2026-11-11

### Fixed

- **O perfil de energia (Económico / Balanceado / Agressivo) não fazia nada.** Os três botões
  só gravavam o nome na configuração e ninguém o lia — a dica prometia «menos pedidos» e
  «mais pedidos» e a app fazia sempre o mesmo. Agora o perfil controla o que a dica diz:
  - **de quanto em quanto tempo a app verifica** (300 s / 120 s / 60 s);
  - **durante quanto tempo reutiliza a lista de campanhas** antes de a pedir de novo
    (30 min / 10 min / 5 min);
  - **durante quanto tempo reutiliza a consulta dos canais** de cada jogo (os próximos da
    fila 10 min / 5 min / 2 min; os restantes 2 h / 1 h / 30 min);
  - **ao fim de quanto tempo sem progresso** o guarda de estagnação reage (45 / 30 / 20 min).
  Em regime estável, com 100 jogos em directo, isto dá cerca de **69 / 144 / 298 pedidos por
  hora** (medido por simulação com relógio simulado; o Balanceado é exactamente o que a app
  já fazia, por isso quem não mexe nos botões não nota diferença). A troca de perfil aplica-se
  logo, mesmo com a quinta a correr, e fica escrita no log.
  O que o perfil **não** muda: o *heartbeat* e o leitor de vídeo (é isso que credita o
  tempo, por isso não se poupa); o custo do Económico é detectar mais tarde que um canal
  ficou offline ou que há uma campanha nova.
- A dica do perfil passa a ser gerada a partir dos próprios valores, para nunca mais poder
  dizer uma coisa e fazer outra.

### Removed

- Campos de perfil que nada lia (`polling_interval_sec`, `api_timeout_sec`,
  `stream_check_timeout_sec`, `log_level`, `enable_aggressive_retry`) e a opção
  `auto_switch_interval_sec` da configuração. Um `config.json` antigo que ainda a tenha
  continua a abrir sem problema.

## [2.2.57] - 2026-11-11

### Fixed

- **O diagnóstico dava sempre «Twitch API Connectivity: FAILED»** (e «1 critical issue»)
  mesmo com tudo a funcionar — apanhado ao testar o botão. O teste enviava de propósito
  uma consulta inventada (`GetUser` com um hash de 32 zeros; um SHA-256 tem 64), a Twitch
  respondia HTTP 400 e a app tratava essa resposta como «API unreachable», quando uma
  resposta, mesmo uma recusa, prova que o servidor está acessível. Agora faz uma pergunta
  real e barata (o *slug* da categoria «Just Chatting») e distingue: **a funcionar**
  (SUCCESS, com a latência), **acessível mas a recusar** (FAILED com o código HTTP) e
  **inacessível** (FAILED); uma resposta com erros GraphQL (por exemplo
  `PersistedQueryNotFound`, que quer dizer que a Twitch mudou uma consulta interna) é um
  aviso que o explica.
- **O teste «Heartbeat System» não verificava nada** — dizia «Heartbeat system ready» em
  0,0 ms, sempre. Passa a «Watch Pipeline (HLS)»: faz o que a vigilância faz, de forma
  passiva e anónima — obtém o token de reprodução de um canal em directo, lê a playlist e
  pede um segmento — e falha com o motivo se algum passo não responder. Não envia nenhum
  evento de visualização, por isso não credita tempo ao canal escolhido.

## [2.2.56] - 2026-11-10

### Fixed

- **As selecções dos Filtros só eram guardadas ao carregar em «Guardar definições», que
  fica noutro separador** — marcar jogos nos Filtros mudava o dashboard mas o motor do farm
  continuava a usar a lista antiga até se guardar, e fechar a app perdia as alterações.
  Agora os filtros (e as restantes definições) são **guardados automaticamente** 0,7 s
  depois da última alteração feita pelo utilizador, também ao fechar a janela, e a lista
  nova passa logo a valer para o farm. A gravação nunca apaga uma lista que ainda não foi
  construída.
- **A «demora do auto-update» nunca chegava à configuração.** E, mais importante, **as
  opções de actualização automática não faziam nada**: o `UpdateManager` nunca é arrancado
  (a app só verifica versões quando carregas em «Verificar actualizações» e nunca transfere
  nem instala nada sozinha). A caixa e a demora ficam desactivadas, desmarcadas, com a dica
  «ainda não implementado», e o valor por omissão passa a desligado.
- **As caixas de alerta «Canal offline» e «Erro de API» não controlavam nada** — nada no
  código as accionava. Agora há um aviso quando o canal em farm fica offline (diz para onde
  o farm passou, ou que não há alternativa; não avisa quando o canal foi deixado de
  propósito) e quando 3 heartbeats seguidos falham (uma vez por sequência).

### Added

- **Mensagem «Definições guardadas ✓» / «Filtros guardados ✓»** ao fundo da janela:
  aparece, fica 3 s e desvanece (não é um popup, não rouba o foco nem apanha o rato), e
  também confirma o botão «Guardar definições». Se a gravação falhar, aparece a laranja com
  o motivo.
- **Auditoria dos botões** (`tests/test_buttons.py`): a janela real, sem rede, sem
  diálogos e sem browser, com um teste por botão (conta, filtros ×16, guardar, iniciar/parar,
  seguinte, redimir, ligar conta, abrir página de drops, actualizar dashboard, guardar log,
  cartões do dashboard), caixas, perfis de energia e seleccionadores. Um teste falha se um
  botão novo não tiver nada ligado ou não for testado.

## [2.2.55] - 2026-11-10

### Fixed

- **O auto-claim disparava dezenas de pedidos de claim falhados por tentativa** — num log
  de 3 h 25 min (2.2.53) houve **255 cliques em botões «Claim» em 16 tentativas** (até 33
  numa só). A marca «já cliquei» era posta no elemento, mas a Twitch recria o botão quando
  o claim falha, por isso cada recriação parecia um botão novo e era clicado outra vez a
  cada 1,5 s durante até 35 s. Cada clique é um pedido `ClaimDropRewards` que a verificação
  de integridade rejeita. O script passa a contar em vez de marcar: cada botão é clicado
  uma vez por abertura da página (desconta os que desaparecem, por terem tido sucesso, e
  continua a apanhar um que apareça mais tarde), com um máximo de 5 cliques, e a tentativa
  acaba logo que deixa de haver botões novos (~6 s em vez de 35 s).
- **As tentativas passam a recuar** — para o mesmo drop: 15 min, 1 h, 4 h e desiste (com um
  aviso a dizer para reivindicar em twitch.tv/drops/inventory). Antes repetia de 15 em 15
  minutos para sempre. Quando o drop é reivindicado, o contador é esquecido.
- **O «Drops page fallback» já não bloqueia a actualização 20 s** — com o dashboard
  bloqueado por integridade, a página de drops responde com a ligação reposta (12 de 25
  actualizações no mesmo log, cada uma a adiar o heartbeat) ou com IDs que nunca eram
  usados, porque as consultas de detalhe são saltadas nesse caso. Deixa de ser pedida nesse
  caso, e o tempo limite do pedido desce de 20 s para (5 s, 10 s).

### Changed

- A opção «Redimir drops automaticamente» tem agora uma explicação (dica ao passar o rato):
  a Twitch costuma rejeitar o claim feito pela app e cada tentativa falhada são pedidos
  suspeitos; o mais fiável é deixá-la desligada e reivindicar no site ou no telemóvel.

## [2.2.54] - 2026-11-10

### Fixed

- **Imagens erradas ou em falta nos cartões** — o Black Desert mostrava a capa da
  biblioteca da Steam e o Chaos Zero Nightmare o ícone genérico de comando. Nenhuma das
  consultas que a app faz à Twitch (directório, redirecionamento) devolve o URL da imagem,
  só o ID da categoria, por isso a imagem oficial nunca era obtida e a app caía na Steam,
  no Google ou em adivinhações. A imagem oficial é determinística a partir do ID
  (`ttv-boxart/<id>_IGDB-144x192.jpg`) e passa a ser a primeira escolha, sem pedidos
  extra. A Steam só é usada se a entrada da loja tiver o mesmo nome (antes aceitava o
  primeiro resultado, que podia ser outro jogo ou um DLC), e as imagens genéricas «sem
  capa» que a CDN da Twitch devolve com HTTP 200 são reconhecidas e deixam de ser
  mostradas como se fossem a capa (o cartão fica com o placeholder com o nome do jogo).
- **Cartões duplicados («Blue Protocol Star Resonance» INATIVO ao lado de «Blue Protocol:
  Star Resonance» LIVE)** — a Twitch só reconhece o nome exacto, e o registry escreve-o
  sem a pontuação, por isso a procura do jogo falhava («Could not resolve a Twitch
  directory slug…») e a app tratava-o como um segundo jogo. Agora, se o nome exacto falha,
  usa-se a procura de categorias da própria Twitch (só se aceita um resultado com o mesmo
  nome, ignorando maiúsculas, acentos e pontuação). Resolveu «Honkai Star Rail»,
  «GODDESS OF VICTORY NIKKE» e «Blue Protocol Star Resonance» que antes ficavam sem
  canais. As duas grafias passam a ser um só cartão, com a grafia da Twitch, e a whitelist
  e a blacklist comparam os nomes sem pontuação. Ao carregar a configuração as grafias
  duplicadas da whitelist fundem-se numa só.
- Os jogos que não existem como categoria na Twitch («Legion TD», «LEGO Batman…») continuam
  sem canais; ficam com o cartão com o nome.

## [2.2.53] - 2026-11-10

### Added

- **Recuperação real quando o progresso pára** (substitui o watchdog que nunca disparava
  e cuja «recuperação» só escrevia uma mensagem). O monitor recebe, a cada heartbeat, o
  progresso da campanha que está mesmo a ser farmada e, se deixar de subir, tenta por
  ordem: **(1)** reiniciar a vigilância do canal (novo token, nova playlist), a 1/5 do
  tempo limite; **(2)** mudar para outro canal da mesma campanha (o actual fica de parte
  45 min), a metade; **(3)** desistir da campanha durante 30 min e farmar outra, ao fim do
  tempo limite. Com o valor por omissão de 30 min são 6, 15 e 30 minutos. Cada passo
  dispara uma vez por bloqueio; mudar de canal não adia a desistência da campanha. Os
  passos 2 e 3 geram um aviso «Farm sem progresso» e, quando o progresso volta, «Farm
  recuperado». O tempo em que a app esteve parada ou sem rede não conta como bloqueio. O
  «Tempo limite sem progresso» das Definições passa a ter efeito (antes não era guardado).
- **O log do ecrã tem um limite de 5000 linhas** (antes crescia sem fim numa farm de
  vários dias).

### Changed

- **O canal em farm mantém-se** enquanto for válido: já não se muda só porque outro canal
  passou a ter mais espectadores (cada mudança reinicia a sessão de vigilância). Um canal
  da lista de canais preferidos continua a ter prioridade, e um canal sem drops activos não
  é mantido.

### Fixed

- **O watchdog antigo era alimentado com o progresso de todas as campanhas com canal**, por
  isso o relógio de «sem progresso» reiniciava a cada campanha e nunca detectava nada.
  Removido (`watchdog.py`).

## [2.2.52] - 2026-11-10

### Fixed

- **Já não há uma actualização completa por cada minuto de atraso do Inventory** — o
  Inventory da Twitch acompanha a sessão de drops com ~1 minuto de atraso, e quando o
  CurrentDrop estava 1 minuto à frente a app reconstruía tudo, incluindo a chamada ao
  dashboard que a Twitch rejeita por integridade (duas vezes, uma por perfil). Agora um
  avanço de 1–2 minutos é tratado como atraso normal (o log diz-o) e só uma diferença de
  3 minutos ou mais, que indica um Inventory parado, força a actualização.
- **Nomes de jogos com o texto de estado do cartão do registry** — nomes como «HITMAN
  World of Assassination 1 drop · in 4 days», «Epic Seven Expired 15» ou «Grand Theft
  Auto VI Coming Soon Releases Nov 19 2026 ·», guardados por versões antigas, ficavam na
  whitelist e na cache de campanhas. A Twitch não tem jogos com esses nomes, por isso cada
  um gastava uma procura de directório e duas procuras de imagem falhadas em todos os
  arranques, e uma entrada da whitelist com o ruído nunca coincidia com a campanha real.
  Agora os nomes são limpos ao carregar a configuração (e as duplicações resultantes
  fundidas), ao ler os cartões do registry e no dashboard, e as entradas sujas da cache em
  disco são descartadas (o registry traz o mesmo jogo com o nome certo).

## [2.2.51] - 2026-11-10

### Added

- **Botão «Guardar log»** (canto superior direito da zona do log) — grava o log num
  ficheiro em `~/.twitch-drop-farmer/logs/` (`log-<versão>-<data>-<hora>.txt`, no
  Windows `C:\Users\<utilizador>\.twitch-drop-farmer\logs\`) e **copia o caminho
  do ficheiro para a área de transferência**, para o colares num explorador de ficheiros
  e anexares o ficheiro em vez de copiar e colar o log todo. O ficheiro começa com um
  cabeçalho (versão, sistema, se está a farmar, jogo e canal) e os tokens são mascarados
  (`<redacted>`) antes de gravar. Ficam guardados os 20 ficheiros mais recentes.

## [2.2.50] - 2026-11-10

### Fixed

- **Jogos em «A VERIFICAR» que não dava para iniciar** (2.2.49) — o Marvel Snap, com
  61 % de progresso, ficava por verificar: a lista guardada em disco traz dados de
  drops de muitas campanhas e ele ficava atrás delas na fila das consultas de canais.
  A fila passa a ser: o jogo em farm, depois as campanhas **já em progresso**, depois as
  que têm dados de drops e só então o resto.
- **Clicar num jogo do dashboard consulta o canal nessa hora**, mesmo que nunca tivesse
  sido verificado ou não tivesse canal na última vez (até 3 consultas por clique). Antes
  só se podia escolher jogos que já tivessem um canal conhecido.

## [2.2.49] - 2026-11-10

### Changed

- **A app passa a pedir muito menos à Twitch** — o `fetch_streams` perguntava ao
  directório por *todos* os jogos da whitelist (~100 pedidos seguidos) em cada volta, e
  havia duas voltas por minuto (temporizadores de 90 s e de 120 s), além de refazer a
  lista de campanhas (Inventory, dashboard, página de drops, registry) de cada vez.
  Numa simulação de 2 h com 100 jogos: **7000 → ~140 consultas ao directório por hora**
  e **70 → 6 buscas da lista de campanhas por hora**.
  - A lista de campanhas é reutilizada durante 10 minutos (o botão «Actualizar», a
    recuperação sem progresso, um claim e a validação da sessão forçam uma busca nova,
    no máximo de 2 em 2 minutos). Se a busca falhar, mantém-se a lista anterior em vez
    de esvaziar o dashboard. Isto inclui a chamada ao dashboard que a Twitch rejeita
    por integridade, que antes era repetida a cada volta.
  - Os canais são consultados só onde faz falta: o jogo em farm em cada volta; os dois
    primeiros candidatos com canal (que são as próximas escolhas) de 5 em 5 minutos; os
    restantes de hora a hora, 8 por volta. As campanhas com dados reais de drops são
    consultadas antes das que só vêm do registry. O resto mantém a última resposta.
  - Um só temporizador de actualização (era dois).
  - Limitador global de pedidos GraphQL (≥ 0,3 s entre pedidos, em todas as threads).
    Um HTTP 429 pausa todos os pedidos durante o `Retry-After` pedido (por omissão 60 s,
    máximo 15 min) e já não é repetido com o outro perfil de cliente.
  - Ao escolher um jogo no dashboard (ou «próximo jogo») o canal é consultado de novo,
    porque a resposta guardada pode ser antiga.

### Added

- Estado **A VERIFICAR** (cinzento) no dashboard para jogos cujos canais ainda não foram
  consultados; passam a LIVE ou SEM CANAIS à medida que são verificados (cerca de 25
  minutos depois de iniciar, para 100 jogos). O log mostra em cada volta quantas
  consultas foram feitas.

## [2.2.48] - 2026-11-10

### Fixed

- **O farm deixa de saltar de jogo em jogo** — com «Redimir drops automaticamente»
  ligado, cada botão «Claim» clicado na página do inventário era contado como drop
  reivindicado e a app forçava logo o jogo seguinte. A Twitch rejeita o claim feito
  pela app (verificação de integridade), por isso o drop continuava por reivindicar
  e, de 2 em 2 minutos, o ciclo repetia-se: nenhum jogo chegava ao fim. Agora um
  clique nunca muda o alvo, e o auto-claim só é tentado quando há mesmo um drop a
  100 % por reivindicar, no máximo uma vez a cada 15 minutos por drop.
- **O alvo deixa de mudar só porque a lista foi reordenada** — a cada actualização as
  campanhas são reordenadas e a app farmava a primeira da lista, por isso qualquer
  reordenação (ou uma consulta de streams que falhou numa volta) trocava de jogo. A
  campanha em curso mantém-se enquanto tiver canal e tempo por ver; só muda quando
  deixa de ser farmável ou por escolha manual. Isto significa que uma campanha nova
  com prioridade mais alta já não interrompe a que está a decorrer.

### Changed

- **As mensagens de claim deixam de dizer «redimidos»** — um clique não é um claim.
  O log diz agora quantos botões foram clicados e lembra que a Twitch pode rejeitar o
  pedido (confirma no inventário).
- **Cada troca de alvo fica registada** — «Alvo alterado: A -> B (motivo: …)», com o
  motivo (sem canal, campanha concluída, selecção manual…), para que qualquer salto
  futuro se perceba logo no log.

### Removed

- `_auto_advance_after_claim` (o salto forçado para o jogo seguinte depois de um clique).

## [2.2.47] - 2026-11-10

### Added

- **Medições de tempo na vigilância HLS** — um episódio de ~90 s em que a vigilância
  pediu apenas 1 segmento (sem erros) e o heartbeat ficou parado ainda não tem causa
  conhecida. O watcher passa a medir cada ciclo e, quando um demora 8 s ou mais,
  escreve no log «ciclo lento de X s (playlist Y s, segmentos Z s)» (no máximo uma
  vez por 30 s). O resumo de cada minuto inclui agora o ciclo mais lento e quantos
  foram lentos, para se ver exactamente que chamada bloqueou.

### Changed

- **Timeouts HLS mais curtos** — os pedidos do watcher (playlist e segmento) passam a
  ter `(4 s ligação, 8 s leitura)`; um pedido pendurado é cortado e repetido no
  ciclo seguinte (2 s) em vez de bloquear a vigilância durante 10 s ou mais.
- **O heartbeat deixa de repetir o ping HLS** — depois do `sendSpadeEvents`, o
  heartbeat fazia mais 2–3 pedidos HLS bloqueantes (até 20 s cada) numa thread de
  trabalho. Com o watcher a pedir já todos os segmentos desse canal, o reforço é
  redundante e só é feito quando o watcher não está activo no canal.

## [2.2.46] - 2026-11-10

### Fixed

- **Os alertas nunca eram mostrados** — o gestor de alertas registava-os no
  logger, mas nada na interface escutava (`register_callback` nunca era chamado) e
  `show_desktop_notification` nunca era usado: «token inválido», «campanha a
  expirar» e «farm concluída» nunca chegaram a ser vistos. Passam a aparecer no log
  e como notificação do Windows (via sinal, porque nascem em threads de trabalho).
  Como o motor levanta alguns alertas a cada actualização, um alerta idêntico só é
  entregue uma vez por hora.

### Added

- **Aviso «Drop pronto a reivindicar»** — quando um drop chega a 100% e ainda não
  foi reivindicado, a app avisa uma vez por drop (log e notificação) com o jogo, o
  nome do drop e o endereço do inventário. A reivindicação automática não é viável
  para esta app: a mutação de claim responde `failed integrity check` (mesmo sem
  token), tal como o dashboard, por isso o claim tem de ser feito no browser normal.
  Tem opção própria nas definições de alertas (`alert_drop_ready`).

### Maintenance

- **Bump de versão** — atualização para `2.2.46`.

## [2.2.45] - 2026-11-10

### Fixed

- **O progresso real voltava a 0/0 a cada actualização** — quando o dashboard da
  Twitch está bloqueado a app usa o registry público (só nome do jogo, nº de drops
  e tempo restante) e **ignorava o Inventory** que acabara de ler, mesmo com uma
  campanha em progresso (ex.: 22/360 min). O progresso só aparecia nos instantes a
  seguir a cada heartbeat e desaparecia na actualização seguinte («Sem drops activos
  para mostrar»). Agora as campanhas do Inventory entram sempre e substituem a
  entrada do registry do mesmo jogo, com os drops e minutos reais.

### Maintenance

- **Bump de versão** — atualização para `2.2.45`.

## [2.2.44] - 2026-11-10

### Fixed

- **Nomes de jogo errados no fallback do registry público** — quando a Twitch
  bloqueia a listagem por `integrity check`, a app usa o `twitchdrops.app`, mas o
  nome do jogo era extraído achatando o cartão inteiro em texto e cortando na
  primeira palavra "drop(s)", pelo que a contagem de drops ficava colada ao nome
  (ex.: "Planet Zoo 2 1", "VAIL 4"). A Twitch não resolve esses nomes para nenhum
  jogo, por isso nunca se encontrava nenhum stream e nada era farmável. O nome é
  agora lido do elemento próprio do cartão (com o `alt` da imagem como segunda
  opção); a heurística antiga fica só como último recurso. A lista passa de ~199
  entradas duplicadas para um registo por jogo.
- **Token de integridade do browser ignorado no mesmo ciclo** — o browser
  invisível podia obter um token de integridade e mesmo assim não capturar
  campanhas; a app caía logo para o registry (sem dados de drops) e o token só
  era tentado no ciclo seguinte. Agora o `ViewerDropsDashboard` é repetido uma
  vez, por pedido directo, com esse token antes de desistir para o registry.

- **`CurrentDrop` falhava sempre a validação** — a query declarava `$channelID`
  como `String!` e o schema da Twitch espera `ID`, pelo que cada pedido devolvia
  `Variable "$channelID" of type "String!" used in position expecting type "ID"`
  e o progresso da sessão de drop actual nunca chegava à app (o log mostrava
  `Heartbeat sem campanha reconciliada`). Corrigido para `ID!`, validado contra a
  API real.

- **«Actualizar drops» fazia uma sondagem completa por cada jogo** — com 98 jogos
  na whitelist eram 98 × `poll(full_scan=True)` seguidos, na thread da interface
  (~13 s cada, 20+ minutos): a janela ficava «Não responde» e o temporizador do
  heartbeat quase não corria (16 heartbeats em 22 min, com ~2 min de intervalo em
  vez de 1). Uma única sondagem completa já percorre toda a whitelist; passa a
  fazer-se só uma, com o jogo em farming à frente.
- **O auto-claim nunca terminava e contava drops que não existiam** — o script
  clicava de 1,5 em 1,5 s nos mesmos botões cujo texto *continha* claim/redeem/
  collect, nunca via uma ronda «vazia», batia sempre no timeout de 35 s (bloqueando
  a interface) e reportava ~20 «drops» por execução. Agora só conta texto que
  *começa* por um verbo de claim (não «Claimed»), clica uma vez por elemento, pára
  ao fim de 3 rondas sem botões novos e regista os botões clicados no log.

### Changed

- **O browser invisível deixa de esperar por um resultado impossível** — quando a
  própria página recebe `failed integrity check` no `ViewerDropsDashboard` (o
  browser embutido é que está a ser recusado, não os cookies), a espera é
  abortada logo, a análise do HTML renderizado é dispensada (usa os mesmos dados
  bloqueados) e o fallback do browser fica suspenso ~15 min. Antes cada ciclo
  gastava ~75 s nisto. O "Actualizar dashboard" (scan completo) continua a
  tentar sempre.

### Added

- **Vigilância contínua de segmentos HLS (a testar)** — num teste real o
  heartbeat `sendSpadeEvents` era aceite (`204`) durante 8 minutos e o Inventory
  da Twitch continuava sem progresso, enquanto ver o mesmo jogo no browser
  creditava minutos. A app só tocava **um** segmento por minuto; um player pede
  **todos** os segmentos novos. Passa a existir uma thread própria
  (`stream_watcher.py`) que, enquanto há um canal alvo, lê a playlist a cada ~2 s e
  pede só os segmentos novos (primeiros 4 KB, uns poucos KB/s). Usa uma sessão HTTP
  dedicada ao vídeo, sem o cabeçalho `Authorization` da conta (antes seguia também
  para os servidores de vídeo). Ainda **não** está confirmado que isto faça a
  Twitch creditar os minutos: é a hipótese a validar pelo Inventory.

- **Diagnóstico do browser invisível** — quando não captura campanhas, o log
  inclui uma linha `Browser probe:` com o URL final, o título, se há botão de
  login, se existe o cookie `twilight-user`, as operações GraphQL pedidas pela
  página e os erros recebidos. Só nomes e contagens: nunca tokens nem valores de
  cookies.

### Maintenance

- **Bump de versão** — atualização para `2.2.44`. A partir daqui cada alteração
  publicada sobe o número da versão (rodapé da app: `v2.2.44`), para se saber
  sempre que build está em uso; um teste obriga o topo deste ficheiro e
  `__version__` a coincidirem.

## [2.2.43] - 2026-09-04

### Fixed

- **Normalização de nomes de jogo no dashboard** — a lista de jogos da whitelist
  agora deduplicada de nomes sintéticos com sufixo numérico (ex.: "Game 3").
- **Botão de refresh de drops por jogo** — adicionado botão ao lado do
  "Actualizar dashboard" para percorrer os jogos da whitelist e recarregar os
  drops activos de cada um.

### Maintenance

- **Bump de versão** — atualização para `2.2.43`.

## [2.2.42] - 2026-09-04

### Fixed

- **Fallback público do registry restaurado** — o parser do `twitchdrops.app` e a
  extração de recompensas do site do jogo regressaram a estar disponíveis, para
  que a aplicação possa recuperar campanhas e metadados quando a Twitch falha a
  listagem do dashboard ou bloqueia a resposta por `integrity check`.
- **Metadados mistos de watch/sub restaurados** — campanhas com recompensas de
  watch e sub continuam a ficar farmáveis enquanto houver drops normais por
  completar, sem serem tratadas como "sub-only" só porque alguma recompensa do
  jogo expõe um requisito de subscrição.

### Maintenance

- **Bump de versão** — atualização para `2.2.42`.

## [2.2.41] - 2026-07-02

### Fixed

- **A whitelist de jogos escondia jogos já seleccionados** — a lista dos Filtros
  era construída apenas a partir de `snapshot.available_games` (jogos com
  campanha no momento). Quando a Twitch limita o catálogo completo (integrity
  check), só aparecem os jogos em progresso no Inventory — por isso um
  utilizador com dezenas de jogos na whitelist só via os que estavam a ser
  farmados nesse instante; os restantes ficavam invisíveis e nem podiam ser
  desmarcados. A lista de jogos passa a ser a **união** do catálogo actual
  (snapshot ou cache em disco), dos jogos já na whitelist/blacklist e dos
  adicionados manualmente — por isso todos os jogos configurados aparecem
  sempre, independentemente de terem campanha activa nesse momento.

### Added

- **Adicionar jogos manualmente à whitelist** — novo campo de texto + botão
  «Adicionar» na aba de Filtros. Como a Twitch por vezes retém a lista completa
  de campanhas (e nesses períodos nem o browser a consegue obter), o utilizador
  pode agora escrever o nome exacto de qualquer jogo e adicioná-lo à whitelist
  na mesma; o jogo fica seleccionado e é guardado ao Guardar definições.

### Maintenance

- **Bump de versão** — atualização para `2.2.41`.

## [2.2.40] - 2026-07-02

### Fixed

- **Aba de Filtros só mostrava os jogos já na whitelist** — a lista de jogos
  (para escolher a whitelist) era construída a partir de `snapshot.available_games`,
  que vem do resultado de `fetch_campaigns`. A cache de campanhas era só em
  memória, pelo que a cada reinício da app ficava vazia: até um fetch do fallback
  de browser ter sucesso, só apareciam os jogos com campanhas em progresso no
  Inventory — que são precisamente os que já estavam a ser farmados/na whitelist.

### Added

- **Cache de campanhas persistida em disco** — `TwitchClient` passa a guardar o
  catálogo de campanhas (apenas metadados públicos: nomes, IDs, datas, progresso;
  sem credenciais) em `~/.twitch-drop-farmer/campaign_cache.json`, com escrita
  atómica e poda de campanhas expiradas ao carregar. Assim, o catálogo completo
  de jogos sobrevive a reinícios e a aba de Filtros mostra logo todos os jogos
  para escolher a whitelist, sem depender de um novo fetch do browser. A lista de
  jogos é também semeada a partir desta cache no arranque, antes do primeiro poll.

### Maintenance

- **Bump de versão** — atualização para `2.2.40`.

## [2.2.39] - 2026-07-02

### Added

- **Aviso no dashboard sobre drops que não carregam** — nova nota discreta por
  baixo dos controlos do dashboard a explicar que um jogo recém-seleccionado
  pode mostrar «0/0 min» ou «Sem drops activos» durante uns segundos, e que
  basta clicar em «Actualizar dashboard» para forçar um scan completo de toda
  a whitelist. O botão «Actualizar dashboard» ganhou também um tooltip a
  explicar o que faz e que pode demorar alguns minutos.

### Changed

- **Revisão completa das traduções PT-PT (acordo ortográfico pré-1990) e EN** —
  uniformizadas todas as strings da interface e mensagens de log visíveis ao
  utilizador para o acordo ortográfico antigo em PT-PT (ex.: `actual`,
  `activo`, `selecção`, `detectar`, `actualizar`), com acentuação corrigida em
  vários avisos e tooltips que estavam sem acentos (`concluído`, `rastreáveis`,
  `começou`, `válida`, `Não iniciada`, `CONCLUÍDO`). O texto inglês foi também
  revisto e uniformizado (`behaviour`).

### Fixed

- **Janela «Sobre» mostrava `\n-` como texto literal** — o corpo do diálogo
  usava `\\n` (barra invertida escapada) em vez de quebras de linha reais, pelo
  que aparecia tudo numa linha com `\n-` visível. Corrigido para quebras de
  linha reais e reescrito o texto para reflectir as funcionalidades actuais
  (modo streamless, alvo manual persistente, scan completo do dashboard,
  filtros/diagnóstico/sessão JSON) — em ambos os idiomas.

### Maintenance

- **Verificação de segurança para release** — confirmado que nenhum dado
  privado (token, cookies, login, e-mail, IDs de utilizador ou caminhos locais)
  está presente nos ficheiros do repositório.
- **Bump de versão** — atualização para `2.2.39`.

## [2.2.38] - 2026-07-01

### Added

- **Contador de jogos no dashboard** — nova label junto à checkbox "Ocultar
  jogos com drops de subscrição" mostrando "A mostrar X/Y jogos da
  whitelist" (ou "A mostrar X jogo(s)." quando não há whitelist configurada
  e a app mostra todos os jogos disponíveis). `Y` é o número de entradas
  configuradas na whitelist; `X` é quantas efectivamente aparecem como
  cartões — a diferença cobre tanto jogos ainda sem nenhuma campanha
  conhecida (nome não encontrado nos dados da Twitch) como jogos escondidos
  pelo filtro de subscrição. Actualizada automaticamente sempre que o
  dashboard é redesenhado.

### Maintenance

- **Bump de versão** — atualização para `2.2.38`.

## [2.2.37] - 2026-07-01

### Added

- **Scan completo da whitelist no botão "Atualizar dashboard"** — este botão
  só limpava caches de imagens e disparava um poll normal (sujeito ao limite
  habitual de 8 campanhas com detalhe por ciclo). Passa agora a fazer um
  pedido explícito de scan completo (`full_scan=True`) que levanta esse
  limite e tenta obter detalhe por-drop real para *todas* as campanhas da
  whitelist em falta, não só as 8 prioritárias. Corre de forma síncrona na
  thread principal (obrigatório para o fallback do browser) e pode demorar
  alguns minutos com uma whitelist grande — o botão fica desactivado
  entretanto e o log mostra início/fim do scan. Depois disto, mudar de jogo
  no dashboard deve mostrar dados reais imediatamente em vez de "0/0 min".
  Verificado com teste isolado: 19/20 campanhas processadas num scan
  completo, contra 8/20 num ciclo normal.

### Maintenance

- **Bump de versão** — atualização para `2.2.37`.

## [2.2.36] - 2026-07-01

### Added

- **Detalhe por-drop prioritizado para o jogo seleccionado/a ser farmado**
  — `_select_browser_detail_candidate_ids` (twitch_client.py) escolhia até 8
  campanhas por ciclo do browser priorizando só por data de fim mais próxima,
  sem qualquer noção do que o utilizador estava realmente a ver ou a farmar.
  Com 115 campanhas na whitelist e só 8 detalhadas por ciclo bem-sucedido, um
  jogo recém-seleccionado podia ficar dezenas de ciclos sem
  `next_drop_name`/`required_minutes` reais — daí o "Progresso da campanha:
  0/0 min" e "Sem drops ativos" mesmo com o jogo escolhido como alvo.
  Adicionado `TwitchClient.set_priority_game()`, chamado pela UI sempre que
  o utilizador selecciona manualmente um jogo (`_select_dashboard_game`) ou
  quando o motor escolhe automaticamente um alvo (`_refresh_farming_now`).
  Esse jogo passa agora à frente da fila de detalhe, mesmo que termine mais
  tarde do que os outros. Confirmado com teste isolado: uma campanha que
  termina daqui a 10 dias passa a ser buscada primeiro assim que marcada
  como prioritária, ultrapassando campanhas que terminam em horas.

### Maintenance

- **Bump de versão** — atualização para `2.2.36`.

## [2.2.35] - 2026-07-01

### Fixed

- **[REGRESSÃO 2.2.34] Fallback do browser deixou de encontrar campanhas**
  — o perfil persistente em disco (`QWebEngineProfile("TwitchDropFarmer", app)`)
  introduzido na 2.2.34 acumula cookies/cache entre *todos* os reinícios da
  app. Depois de várias dezenas de reinícios no mesmo dia de testes, o
  fallback passou a devolver "não encontrou campanhas adicionais" em vez das
  ~100+ campanhas habituais — plausivelmente estado de sessão da Twitch
  desactualizado/conflituoso a confundir o próprio JavaScript da página.
  Revertido para um perfil `isOffTheRecord=True` (sem gravação em disco,
  confirmado com teste real offscreen), mantendo apenas o benefício de baixo
  risco da 2.2.34: reutilizar a mesma instância de perfil dentro de uma única
  execução da app, em vez de criar uma nova a cada ciclo de polling.

### Maintenance

- **Bump de versão** — atualização para `2.2.35`.

## [2.2.34] - 2026-07-01

### Added

- **Perfil de browser persistente** — `_get_browser_profile` (twitch_client.py)
  cria uma única `QWebEngineProfile` nomeada e persistente (`isOffTheRecord=False`,
  com armazenamento em disco), partilhada por todas as chamadas de fallback do
  browser (listagem, detalhe por-campanha, scraper DOM, resgate de drops) em vez
  de uma perfil anónimo novo a cada chamada. Cookies/local storage passam a
  sobreviver entre chamadas e reinícios da app. Validado directamente com um
  `QApplication` offscreen: perfil não-efémero, com caminho de armazenamento em
  disco, reutilizado entre chamadas.
- **Reaproveitamento do token `Client-Integrity` do browser** — o script de
  interceção de GQL (já existente) passa também a capturar o header
  `Client-Integrity` que a própria Twitch envia nos seus pedidos `/gql` dentro
  do browser invisível, e a devolvê-lo ao Python. Esse token passa a ser
  anexado automaticamente (`_gql_headers`) aos pedidos HTTP directos durante
  ~4 minutos, ou até um pedido voltar a falhar com "failed integrity check"
  (nesse caso é limpo de imediato). Isto permite que vários ciclos de polling
  sucessivos usem o caminho directo sem precisar do browser, só voltando a
  acordá-lo quando o token expira ou é rejeitado.
- **"Circuit breaker" para `DropCampaignDetails`** — quando o
  `ViewerDropsDashboard` já confirma, no mesmo ciclo, que a integrity check
  está bloqueada, e não há token de integridade capturado para tentar, o
  ciclo de `DropCampaignDetails` (até 2 identidades × 2 perfis de header ×
  chunk, ou seja, até ~8 pedidos e 16 linhas de log desperdiçadas por ciclo)
  passa a ser saltado por completo em vez de repetir a mesma falha já
  confirmada.

### Investigado

- **Servir a listagem de drops via HTML simples (sem GraphQL)** — testado
  directamente com um pedido HTTP simples a `twitch.tv/drops/campaigns`: a
  página não embute dados de campanhas no HTML (0 ocorrências de
  "dropCampaign"), é 100% renderizada por JavaScript no cliente. Não há forma
  de contornar a necessidade de executar JS para obter dados reais de drops.

### Maintenance

- **Bump de versão** — atualização para `2.2.34`.

## [2.2.33] - 2026-07-01

### Added

- **Timestamp em cada linha do log** — `_log` (ui.py) passa a prefixar cada
  mensagem com `[HH:MM:SS]`, para se distinguir facilmente spam real de
  mensagens legítimas repetidas ao longo do tempo.
- **Cache persistente de campanhas com merge** — `fetch_campaigns`
  (twitch_client.py) devolvia apenas as campanhas descobertas nessa chamada
  específica. Como a maioria dos ciclos corre fora da thread principal (não
  pode usar o fallback de browser) e só vê 1-2 campanhas via Inventory, a
  lista rica de um ciclo anterior era sempre substituída por essa lista
  fraca — por isso só o jogo activamente a ser farmado parecia actualizar-se.
  Adicionada `TwitchClient._campaign_cache`, com merge (`dict` protegido por
  `Lock`) em vez de substituição: cada chamada actualiza a cache com o que
  encontrou e devolve sempre a vista completa acumulada, com poda de
  campanhas expiradas. Os objectos devolvidos são cópias (`dataclasses.replace`)
  para isolar chamadas concorrentes entre threads. Resultado: todos os jogos
  da whitelist vão sendo preenchidos ao longo do tempo, mesmo que lentamente,
  em vez de só o alvo activo.

### Maintenance

- **Bump de versão** — atualização para `2.2.33`.

## [2.2.32] - 2026-07-01

### Fixed

- **Log inundado por "Browser fallback stopped after repeated empty campaign
  extraction polls."** — `_campaigns_from_browser_page` (twitch_client.py) usa
  `runJavaScript` assíncrono num loop de polling; quando o motor de
  renderização está ocupado, várias chamadas ficam pendentes em simultâneo e
  cada uma, ao regressar, via a mesma condição de paragem já ultrapassada e
  repetia o log e o `finish()`. Adicionada flag `finished` idempotente que
  ignora callbacks tardios e pára o timer de polling de imediato (em vez de
  só depois do `loop.exec()` regressar), tanto aqui como nas duas fases do
  intercept de GQL por browser.
- **Ciclos de actualização lentos a atrasar o heartbeat streamless** — a
  fase de detalhe por-campanha introduzida na 2.2.31 (até 40 páginas × 9s)
  estava a atrasar significativamente os heartbeats que realmente avançam o
  progresso dos drops (visível em "Heartbeat streamless adiado: atualização
  de campanhas ainda em curso" e "Sem avanço após heartbeat"). Reduzido o
  limite para 8 campanhas por ciclo e o tempo-limite por página para 6s.

### Maintenance

- **Bump de versão** — atualização para `2.2.32`.

## [2.2.31] - 2026-07-01

### Added

- **Detalhe real por-drop via Chromium invisível** — a Twitch tem tido falhas
  intermitentes e prolongadas no próprio sistema de integrity check para
  pedidos GraphQL directos (confirmado externamente pelo mantenedor do
  DevilXD/TwitchDropsMiner, incluindo no browser real dele), pelo que o
  fallback de browser (já invisível — sem qualquer janela, confirmado por
  ausência de `.show()` no código) continua a ser necessário para obter
  campanhas. Até agora esse fallback só visitava a página de listagem
  (dados-resumo, sem `timeBasedDrops`), deixando o painel "Drops activos" e o
  progresso da campanha vazios/desconhecidos para muitas campanhas activas.
  `_campaigns_via_browser_gql_intercept` (twitch_client.py) passa agora a
  visitar também a página de detalhe de cada campanha activa em falta
  (`/drops/campaigns?dropID=<id>`), na mesma página invisível, capturando o
  `DropCampaignDetails` real que a própria Twitch dispara — sem nunca abrir
  uma janela de browser. Limitado a 40 campanhas por ciclo, priorizando as
  que terminam mais cedo. Isto torna o ciclo de actualização mais lento
  quando este caminho é usado, aceite explicitamente pelo utilizador em
  troca de dados de progresso reais.

### Maintenance

- **Bump de versão** — atualização para `2.2.31`.

## [2.2.30] - 2026-07-01

### Fixed

- **[CRÍTICO] `Client-Id` vazio em todos os pedidos GraphQL directos** —
  `WEB_CLIENT_ID` e `ANDROID_APP_CLIENT_ID` (twitch_client.py) estavam
  definidas como string vazia, fazendo com que **todo** o tráfego GQL directo
  (Inventory, ViewerDropsDashboard, DropCampaignDetails, etc.) enviasse
  `Client-Id: ""`. A Twitch rejeita imediatamente o integrity check de
  qualquer query protegida sem um Client-Id válido — o que forçava a app a
  cair constantemente no fallback do browser (lento, e contrário ao
  objectivo de operação 100% streamless). Restauradas as constantes públicas
  reais da Twitch (`kimne78kx3ncx6brgo4mv6wki5h1ko` para web,
  `kd1unb4b3q4t58fwlpcbzcbnm76a8fp` para a app Android) — o resto da
  infraestrutura de headers (device-id, session-id, retries) já estava
  correcta, confirmado por comparação directa com o `DevilXD/TwitchDropsMiner`
  (que usa as mesmas queries protegidas sem qualquer browser). Isto deve
  eliminar a necessidade do fallback de browser na maioria dos casos.

### Maintenance

- **Bump de versão** — atualização para `2.2.30`.

## [2.2.29] - 2026-07-01

### Fixed

- **Painel "Drops activos" vazio para campanhas sem detalhe por-drop** — quando
  o fallback do browser só consegue capturar a listagem de campanhas (não os
  detalhes `timeBasedDrops`, bloqueados por integrity check da Twitch e só
  obtidos ao navegar para cada página de campanha individualmente), o painel
  "Drops activos" não tinha itens para mostrar e caía sempre na mensagem
  genérica "Sem drops activos para mostrar" — mesmo com a campanha
  activamente a ser farmada em segundo plano. Corrigido:
  `_refresh_active_drops_panel` (ui.py) agora mostra o progresso agregado da
  campanha (`next_drop_name` / `required_minutes` / `progress_minutes`, que a
  Twitch devolve mesmo sem o detalhe por-drop) como item único quando não há
  lista de drops discriminada.

### Maintenance

- **Bump de versão** — atualização para `2.2.29`.

## [2.2.28] - 2026-07-01

### Fixed

- **Falso positivo generalizado de "subscrição obrigatória" no dashboard** —
  `_campaign_matches_hide_sub_only` (ui.py) tratava qualquer campanha sem
  metadados de drop por-drop (`required_minutes`, `drops`, `next_drop_name`)
  como se exigisse subscrição. Isto acontece sempre que a app cai no fallback
  do browser (bloqueio de integrity check da Twitch às queries
  `DropCampaignDetails`/`ViewerDropsDashboard`), fazendo com que
  praticamente todas as campanhas — incluindo as normais e farmáveis —
  fossem marcadas com o aviso de subscrição na checkbox "Ocultar jogos com
  drops de subscrição", na lista de drops activos e na label de contagem.
  A deteção real de farming (`farmer.py`, `_decision_is_farmable_now`) nunca
  teve este problema; só a camada de aviso na UI é que confundia "sem dados"
  com "exige subscrição". Corrigido: `_campaign_matches_hide_sub_only` passa
  a delegar apenas em `_campaign_is_known_subscription_locked` (sinais
  explícitos), removendo a heurística `_campaign_has_actionable_drop_data`.

### Maintenance

- **Bump de versão** — atualização para `2.2.28`.
=======
## [2.2.29] - 2026-09-04

### Fixed

- **Indicador de carregamento no dashboard** — o utilizador passa a ver um aviso
  explícito enquanto as campanhas e streams estão a ser actualizadas no arranque,
  reduzindo a sensação de que a aplicação ficou bloqueada.
- **Estado de conta não ligada separado do “inativo”** — campanhas com ligação à
  conta por fazer deixam de ser categorizadas como inactivas gerais; passam a
  mostrar um ribbon específico e uma causa clara no painel.
- **Correção de falsos “inativos / sem canais”** — activas sem canais válidos ou
  com ligação pendente deixam de ser mascaradas por um estado genérico de
  inactivas quando a causa real é mais específica.

### Maintenance

- **Bump de versão e novo artefacto zip** — atualização para `2.2.29`.

## [2.2.28] - 2026-09-04

### Fixed

- **Deteção de sub-only consolidada** — campanhas com sinal explícito de
  subscrição continuam a ser escondidas do farming, mas campanhas sem sinal
  estrutural e sem dados watcháveis permanecem acessíveis.
- **Heurística conservadora** — o fechar de campanhas como sub-only não usa mais
  metadados incompletos como prova; só sinaliza quando há evidência explícita ou
  vários drops conhecidos a zero.
- **Flag `requires_subscription` propagada no `poll()`** — o estado da campanha
  é preservado no snapshot e nas decisões para o dashboard/pipeline.

### Maintenance

- **Testes de regressão reforçados** para evitar falsos positivos e falsos
  negativos na classificação de sub-only.
- **Bump de versão e novo artefacto zip** — atualização para `2.2.28`.
>>>>>>> d048d36 (Fix dashboard state classification and campaign deduplication)

## [2.2.27] - 2026-07-01

### Fixed

- **Classificação sub-only corrigida de forma definitiva** — campanhas com dados
  incompletos de drops (sem `requiredMinutesWatched`) deixam de ser inferidas como
  "subscrição obrigatória" por defeito.
- **Regra de inferência endurecida** — sub-only só é inferido quando há sinal
  explícito (flags estruturadas) ou quando todos os drops têm requisitos
  conhecidos e explicitamente a zero.
- **Campanhas mistas** (com drop watchable e metadados de subscrição) deixam de
  ser marcadas globalmente como sub-only.

### Maintenance

- **Testes de regressão adicionados** para prevenir o cenário de falso positivo
  global de subscrição no dashboard.
- **Bump de versão e novo artefacto zip** — atualização para `2.2.27`.

## [2.2.26] - 2026-07-01

### Fixed

- **Falso positivo de subscrição no dashboard** — endurecida a classificação de
  campanhas sub-only para evitar marcar campanhas normais como
  "exige subscrição para resgatar".
- **Heurísticas de fallback do browser** — removidos matches genéricos de texto
  de subscrição; ficam apenas frases explícitas para reduzir classificações
  incorrectas.

### Maintenance

- **Bump de versão e novo artefacto zip** — atualização para `2.2.26` com novo
  pacote gerado.

## [2.2.25] - 2026-07-01

### Fixed

- **Deteção de campanhas de subscrição mais robusta** — reforçadas variantes de
  texto PT-PT com e sem acentos (`subscrição necessária` / `subscricao necessaria`)
  nos caminhos de parsing para reduzir falsos negativos em campanhas bloqueadas
  por subscrição.
- **Wording PT-PT em alerta de expiração** — texto ajustado para
  "Campanha a expirar".

### Maintenance

- **Bump de versão e artefacto de distribuição** — atualização do número da
  aplicação para `2.2.25` e geração do novo zip de build.

## [2.2.24] - 2026-06-08

### Fixed

- **Reconciliação de progresso streamless mais robusta** — adicionado sinal
  complementar via query `CurrentDrop` após heartbeat para detectar cenários em que
  `sendSpadeEvents` é aceite mas o Inventory ainda não reflecte os minutos mais
  recentes; quando detectado progresso mais novo, a UI força refresh imediato para
  evitar falsos ciclos de "sem avanço".
- **Mapeamento interno de drop em reconciliação** — os itens de progresso dos drops
  passam a incluir `id`, permitindo cruzamentos mais fiáveis durante diagnóstico de
  campanhas sem reconciliação imediata.
- **Warning de runtime em regex JS embebida** — corrigidos escapes `\d` em scripts de
  fallback do browser para eliminar `SyntaxWarning: invalid escape sequence` no
  arranque/testes.

### Maintenance

- **Higiene de artefactos de release** — adicionado padrão de ignore para zips
  versionados gerados localmente (`TwitchDropFarmer-v*.zip`).

## [2.2.23] - 2026-06-04

### Fixed

- **Fallback do browser ainda limitado a poucas campanhas** — adicionada extração
  estruturada de linhas de campanha diretamente do DOM renderizado (título +
  janela temporal), com clique explícito na tab *All Campaigns* e deduplicação
  robusta, reduzindo a dependência de parsing global de texto da página.
- **Maior robustez sob integrity checks** — o fallback mantém scroll/espera
  progressivos e usa os blocos estruturados recolhidos para construir campanhas
  ativas/upcoming mesmo quando o GraphQL de detalhe falha por integridade.

## [2.2.22] - 2026-06-04

### Fixed

- **Campanhas activas incompletas sob integrity checks** — reforçado o fallback do
  browser para clicar explicitamente na tab *All Campaigns*, usar scroll mais
  robusto no contentor com maior área deslocável e esperar estabilização de
  conteúdo antes de terminar a recolha.
- **IDs inválidos em DropCampaignDetails** — normalização endurecida para UUID
  estrito em toda a extração/filtro de IDs de campanha, eliminando pedidos com
  IDs malformados que poluíam o ciclo de detalhe.

## [2.2.21] - 2026-06-04

### Fixed

- **Progresso de drops desactualizado no painel** — reforçada a reconciliação de
  campanhas para usar o inventário da Twitch como fonte autoritativa de
  `timeBasedDrops` e `self.currentMinutesWatched` sempre que disponível, evitando
  estados antigos/incorrectos vindos de `DropCampaignDetails`.

## [2.2.20] - 2026-06-04

### Changed

- **Limpeza completa do código de cache de campanhas** — removidos atributos,
  constantes e métodos mortos relacionados com `campaign_cache.json` no cliente
  Twitch, para garantir coerência com a política de dados sempre frescos.
- **Descoberta de campanhas simplificada** — o conjunto de IDs para
  `DropCampaignDetails` passa a depender apenas de inventário + IDs da página de
  drops, sem qualquer caminho de merge/fallback por cache persistida.

## [2.2.19] - 2026-06-04

### Fixed

- **Listagem reduzida de campanhas (ex.: apenas 4)** — corrigida a detecção de
  limitação por integrity checks no ciclo UI->poll: o enriquecimento no thread
  principal volta a ser activado quando o fallback de browser é bloqueado em
  background, permitindo recuperar campanhas adicionais.
- **Drops misturados entre campanhas do mesmo jogo** — removido o merge por nome
  de jogo no fallback de browser; o merge é agora feito apenas por ID de campanha,
  evitando associação incorrecta de progresso/lista de drops.

### Changed

- **Sem cache para campanhas/drops** — a listagem passa a ser sempre obtida da
  Twitch em cada arranque/actualização; removidos os caminhos de fallback/merge
  baseados em cache persistida de campanhas.

## [2.2.18] - 2026-06-04

### Changed

- **Escrita atómica de ficheiros JSON** — `config.json`, `cookies.json` e
  `campaign_cache.json` são agora escritos via padrão write-to-temp + `os.replace()`,
  eliminando o risco de corrupção de dados em caso de crash ou falha de energia a
  meio da escrita.  Alinhado com a melhoria `more robust JSON save-load cycle` do
  projecto de referência DevilXD/TwitchDropsMiner (commit de 25 mai 2026).

### Added

- **Constante `SPECIAL_GAME_SLUGS`** — define os slugs de jogos "especiais" da Twitch
  (`irl`, `special-events`) cujas campanhas podem ser farmadas em qualquer stream com
  drops activos.  Alinhado com o commit "Add 'IRL' as another special game" do
  DevilXD/TwitchDropsMiner (31 mai 2026).  Log informativo emitido quando uma
  campanha deste tipo é detectada.

## [2.2.7] - 2026-05-23

### Fixed

- **Ribbons INATIVO incorrectos para campanhas activas sem dados de timing** —
  a verificação `no_actionable_drop_data` era aplicada a TODAS as campanhas com
  `required_minutes=0` e `drops=[]`, incluindo campanhas activas cujos detalhes de
  timing não foram devolvidos pelo `DropCampaignDetails` GQL.  Estas campanhas
  passam agora à detecção de streams: mostram LIVE se houver streams disponíveis,
  SEM CANAIS se não houver — em vez de INATIVO.
- **Reparação de timestamps sintéticos alargada** — campanhas com `status="ACTIVE"`
  (conforme a API) mas sem datas `startAt`/`endAt` também têm os seus timestamps
  reparados, evitando que `campaign.active` retorne `False` e o ribbon INATIVO seja
  mostrado incorrectamente.

## [2.2.6] - 2026-05-23

### Fixed

- **[BUG CRÍTICO] Minutos de watch não avançavam no modo streamless (v2.2.5 regressão)** —
  a v2.2.5 corrigiu os headers extra no POST ao `spade.twitch.tv/track` passando a usar
  `requests.post()` directamente.  Porém, isso removeu também o cookie `auth-token` da
  sessão, que é obrigatório para a atribuição correcta de drops pelo servidor Twitch.
  A implementação de referência (TwitchDropsMiner) envia o cookie `auth-token` com o
  POST.  Corrigido: usa-se agora `self.session.post()` (que inclui o cookie jar) mas
  com `Authorization`, `Client-Id`, `Origin` e `Referer` explicitamente removidos
  desta chamada (`None` na merge de headers do requests), garantindo apenas
  `User-Agent` + cookie `auth-token`.
- **Diagnóstico do heartbeat melhorado** — o log do spade agora apresenta
  `uid`, `broadcast_id` e `canal_id` para facilitar a detecção de problemas futuros.
- **Guard para `user_id` vazio** — heartbeat é ignorado se o token ainda não foi
  validado e `user_id` não está resolvido.



### Fixed

- **[BUG CRÍTICO] Minutos de watch não avançavam no modo streamless** — o POST ao
  endpoint `spade.twitch.tv/track` era feito via `self.session.post()`, o que
  adicionava automaticamente os headers `Authorization: OAuth …`, `Client-Id`,
  `Origin` e `Referer` da sessão HTTP. A implementação de referência
  (TwitchChannelPointsMiner) usa apenas `User-Agent`; os headers extra podem impedir
  a atribuição correcta do evento pelo servidor Twitch.  Agora usa-se
  `requests.post()` directamente (sem session), garantindo que só `User-Agent` é
  enviado — o utilizador é identificado pelo campo `user_id` no payload.
- **[BUG] Cache da spade URL nunca expirava** — a URL `spade.twitch.tv/…` é rotada
  periodicamente pela Twitch; a cache anterior era indefinida.  Adicionado TTL de
  30 minutos: ao expirar, a URL é re-obtida da página `m.twitch.tv/{canal}`.
- **Payload `minute-watched` incompleto** — adicionado o campo `game` ao payload
  quando o nome do jogo está disponível, em paridade com a implementação de
  referência (necessário para a atribuição de drops pelo servidor).

## [2.2.4] - 2026-05-22

### Fixed

- **[BUG] Watchdog nunca disparava** — `check_stall` media o tempo desde a última chamada
  a `update_progress` (sempre ≤ 120 s, o intervalo de polling), pelo que o limiar de 30
  minutos nunca era atingido. Agora o watchdog rastreia quando o valor de
  `total_progress_minutes` avançou pela última vez; o temporizador de stall só conta
  enquanto o progresso está parado.  `recovery_attempts` é também resetado apenas quando
  o progresso realmente avança, não em cada poll.
- **[BUG] ETA do próximo drop inflacionado com precondições reclamadas** — em
  `_next_drop_info`, a função recursiva `remaining_with_preconditions` não verificava
  `isClaimed` ao traversar a cadeia de precondições. Um drop precondição com
  `isClaimed=True` mas `currentMinutesWatched` stale (= 0) era tratado como por fazer,
  inflacionando o tempo restante dos drops dependentes. O mesmo padrão da correcção
  aplicada em `_drop_totals` (v2.2.2) foi agora aplicado aqui.
- **[UI] Duplicação de `setTabText`** — `_retranslate_ui` chamava `setTabText` 4 vezes
  duas vezes consecutivas para os tabs principais; as 4 chamadas duplicadas foram removidas.
- **[PT-PT] Cedilha em falta em strings de subscrição** — as chaves de tradução
  `dashboard_badge_subscription_required`, `dashboard_subscription_required_tooltip`,
  `dashboard_ribbon_subscription_required`, `active_drops_subscription_hint` e
  `reason_subscription_required` usavam "Subscricao" sem cedilha; corrigido para
  "Subscrição" (PT-PT correcto).

### Maintenance

- Limpeza do directório raiz: removidos artefactos antigos de build (`_internal/`,
  `TwitchDropFarmer.exe` raiz, subfolder `TwitchDropFarmer/`, `build/`,
  `__pycache__/`, `.pytest_cache/`, `TwitchDropFarmer.spec`).
- `.gitignore` actualizado para excluir `/_internal/` e `/TwitchDropFarmer.exe`.

## [2.2.3] - 2026-05-22

### Fixed

- **[BUG]** Minutos de visualização contados como zero apesar dos heartbeats spade
  retornarem HTTP 204.  Duas correcções:
  1. **Authorization no pedido spade** — o header `Authorization: OAuth <token>` é agora
     incluído no POST ao endpoint spade. Sem ele, o Twitch não conseguia atribuir o evento
     ao utilizador autenticado quando o endpoint spade não está em `spade.twitch.tv`
     (subdomínio que não recebe o cookie `auth-token` automaticamente).
  2. **broadcast_id sempre fresco** — o `broadcast_id` passado ao payload spade era
     reutilizado do último snapshot (até 120 s antigo). Se o streamer reiniciou o stream
     entretanto, o ID ficava stale e o Twitch aceitava o evento (204) mas não creditava
     o tempo de visualização. A função `streamless_watch_heartbeat` chama agora
     `_stream_info` com uma cache TTL de 90 s para garantir um `broadcast_id` fresco.

## [2.2.2] - 2026-05-22

### Fixed

- **[BUG]** Progresso de drops continua a não contar — correcção abrangente em três frentes:
  1. **`_drop_totals`** — drops já reclamados (`isClaimed=True`) agora contribuem com 0
     minutos restantes, independentemente de `currentMinutesWatched` devolver 0 (stale).
     Antes, um drop reclamado com `currentMinutesWatched=0` aparecia como totalmente por
     fazer, inflacionando o tempo restante da campanha.
  2. **Merge de progresso por drop** — em vez de substituir a lista `timeBasedDrops`
     inteira pelo Inventory (perdendo campos estruturais como `benefitEdges`,
     `preconditionDrops`), o código constrói agora um mapa `drop_id → self` a partir do
     Inventory e injecto-o drop-a-drop nos dados estruturais do `DropCampaignDetails`,
     preservando toda a informação de estrutura e garantindo que `currentMinutesWatched`
     e `isClaimed` são sempre os do Inventory.
  3. **Fallback em `_parse_campaign`** — a condição de fallback era `remaining ≥ required`
     (ou seja, só disparava com 0% exacto de progresso).  Agora dispara sempre que o
     `self.currentMinutesWatched` ao nível da campanha (Inventory) mostre MAIS progresso
     do que o calculado pelos drops individuais, cobrindo cenários de stale parcial
     (ex.: campanha a 33% computado vs 70% real no Inventory).

## [2.2.1] - 2026-05-22 *(retirado — fix incompleto)*

### Fixed

- **[BUG]** Drop progress congelado na mesma percentagem durante horas.  A função
  `_merge_data` substitui listas e dicts aninhados dando prioridade à fonte secundária;
  `timeBasedDrops` e `self.currentMinutesWatched` vindos de `ViewerDropsDashboard` /
  `DropCampaignDetails` (com valores desactualizados ou zero) sobrepunham-se ao progresso
  real da query `Inventory`.  Correcção em dois níveis:  restaura `timeBasedDrops` e
  `self.currentMinutesWatched` do `Inventory` após merge; usa o campo de campanha como
  fallback quando drops individuais mostram 0 progresso.

### Fixed

- **[BUG]** Drop progress congelado na mesma percentagem durante horas.  A função
  `_merge_data` substitui listas e dicts aninhados dando prioridade à fonte secundária;
  `timeBasedDrops` e `self.currentMinutesWatched` vindos de `ViewerDropsDashboard` /
  `DropCampaignDetails` (com valores desactualizados ou zero) sobrepunham-se ao progresso
  real da query `Inventory`.  Correcção em dois níveis:
  1. **Merge loop** — após fundir dados estruturais, restaura `timeBasedDrops` e
     `self.currentMinutesWatched` do `Inventory` sempre que este reporte progresso maior.
  2. **`_parse_campaign`** — quando `_drop_totals` retorna zero progresso (drops
     desactualizados) mas o campo `self.currentMinutesWatched` ao nível da campanha tem
     valor real, usa esse valor como fallback para `total_remaining` e `next_drop_remaining`.

## [2.2.0] - 2026-05-21 *(retirado — continha o bug de progresso congelado)*

### Fixed

- **[BUG]** Drop progress frozen at the same percentage for hours.  `_merge_data` replaces
  lists wholesale — `timeBasedDrops` from `ViewerDropsDashboard` / `DropCampaignDetails`
  (which return stale or zero `currentMinutesWatched`) was silently overwriting the correct
  progress from the `Inventory` query.  The merge loop now restores the inventory
  `timeBasedDrops` after structural merging, so the progress counter always reflects the
  real watch-time reported by Twitch.

## [2.1.6] - 2026-05-01

### Fixed

- **[CRASH]** `fetch_campaigns()` no longer triggers Qt WebEngine browser fallback from a
  background thread (`ThreadPoolExecutor`).  `engine.poll()` now passes
  `allow_browser_fallback=False`, eliminating the crash that occurred when Twitch
  returned campaigns but the listing appeared incomplete.
- **[CRASH]** `_streamless_media_playlist` instance attribute (a dict) was shadowing the
  method of the same name, causing `TypeError: 'dict' object is not callable` on every
  HLS heartbeat attempt.  Renamed the cache to `_streamless_media_playlist_cache`.
- **[CRASH]** Alert config fields `alert_stream_offline`, `alert_api_error`, and
  `alert_watchdog_recovered` were missing from `AppConfig` (slots=True dataclass).
  Toggling any of these in the Alerts tab raised `AttributeError`.  All three fields
  are now present with default `True`.
- **[BUG]** `alert_campaign_expiring` was misnamed vs `AlertType.CAMPAIGN_EXPIRING_SOON`
  (`alert_campaign_expiring_soon`), making the campaign-expiring alert impossible to
  disable from the UI.  Field renamed throughout.
- **[BUG]** `_streamless_spade_payload` encoded channel/broadcast/user IDs as JSON
  strings.  Twitch's Spade endpoint requires integer IDs — numeric strings are now
  coerced to `int`; non-numeric values are kept as-is.
- **[BUG]** Inventory campaigns with missing `startAt`/`endAt` timestamps (status=EXPIRED)
  were silently skipped by `poll()` with `reason_code=campaign_not_active`.  `poll()` now
  repairs synthetic timestamps and continues farming such campaigns.
- **[BUG]** Browser-only campaigns (no drop data, `required_minutes=0`) now receive
  `reason_code=no_actionable_drop_data` instead of unexpectedly reaching `fetch_streams`.
- `fetch_streams` refactored into `_fetch_streams_for_slug` (game directory) and
  `_fetch_streams_from_allowed_channels` (per-campaign ACL).  When a campaign restricts
  to specific channels, only those channels are queried — the game directory is never
  used as a fallback.

## [2.0.24] - 2026-04-27

### Added

- Durable diagnostics report formatting with compact per-test table (`Test | Status | Time | Message`).
- Safer diagnostics execution path that disables rendered browser fallback in background threads.
- Unified subscription-only hide matching for dashboard and active-drops cues, including metadata-sparse campaigns.

### Changed

- Manual dashboard target selection now sets and keeps explicit game-level target state.
- Dashboard hide-sub-only flow now compacts visible cards without layout gaps.
- Diagnostics and update checks now provide immediate in-app/log feedback during active operations.

### Fixed

- Fixed a false critical diagnostic failure caused by an invalid OAuth check call (`is_token_valid`).
- Prevented occasional UI shutdown during diagnostics by avoiding Qt WebEngine operations in worker thread diagnostic path.
- Corrected filter tab title/count refresh behavior after recent UI regressions.

### Release Notes

- PT: [docs/releases/v2.0.24.pt-PT.md](docs/releases/v2.0.24.pt-PT.md)
- EN: [docs/releases/v2.0.24.en.md](docs/releases/v2.0.24.en.md)

## [1.2.0] - 2026-04-22

### Added

- Dashboard status coverage for subscription-required and lost campaigns (full and partial), including dedicated badges, ribbons, and tooltips.
- Campaign model flags for `all_drops_claimed` and `requires_subscription` to improve decision quality and UI signaling.
- Search fields and bulk selection actions in filter lists, with tab-level selected/total counters.
- New translated UI labels and reason messages for the expanded dashboard and filtering flows.

### Changed

- Campaign stream selection now tolerates inconsistent ACL channel labels by falling back to drops-enabled streams when needed.
- Active target presentation prefers displayable active decisions, improving dashboard and farming panel continuity.
- Dashboard completion logic now better distinguishes completed, upcoming, offline, subscription-required, and expired-lost states.
- Filter section layout moved to sub-tabs for cleaner left-side navigation and reduced scrolling.

### Fixed

- Prevented subscription-only campaigns from being treated as farmable watch-time targets.
- Corrected account-link fallback parsing for campaigns missing explicit `self` connection payloads.
- Improved channel login extraction from nested ACL payloads using stricter token validation.

### Release Notes

- PT: [docs/releases/v1.2.0.pt-PT.md](docs/releases/v1.2.0.pt-PT.md)
- EN: [docs/releases/v1.2.0.en.md](docs/releases/v1.2.0.en.md)

## [1.1.0] - 2026-04-21

### Added

- Asynchronous game artwork loading in the dashboard and farming view.
- Prioritized image fallback flow using Twitch, Steam, and Google Images.
- Generated game cover placeholders with initials when no real artwork is available.
- Manual dashboard refresh action to clear image caches and reload the current snapshot.
- Release notes in [docs/releases/v1.1.0.pt-PT.md](docs/releases/v1.1.0.pt-PT.md) and [docs/releases/v1.1.0.en.md](docs/releases/v1.1.0.en.md).

### Changed

- Increased the live refresh timer interval to reduce unnecessary churn.
- Improved campaign completion handling for edge cases where Twitch leaves finished campaigns marked active.

### Fixed

- Total timeout handling across GraphQL retry profiles.
- Safer timestamp parsing for malformed Twitch responses.
- Proper Qt browser fallback cleanup.
- Retry behaviour for failed artwork resolution by avoiding permanent empty-cache entries.
- Validation of Steam library artwork URLs before use.

## [1.0.0] - 2026-04-21

- Initial public release tag and documentation refresh.