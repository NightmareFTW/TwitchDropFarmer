# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

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
  `TwitchDropFarmer.exe` raiz, subfolder `TwitchDropFarmer/`, `ruvector.db`, `build/`,
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