# Mapa de componentes aprovados

**Situação do código-fonte:** em 29/10/2026 todos os 28 endereços de registro do 21st.dev
(`https://21st.dev/r/<autor>/<slug>`) responderam **HTTP 403 "Authentication required"**. O código original
desses componentes não foi obtido. Nenhuma conta foi criada e nenhum login foi feito em nome do usuário.

Por isso, os componentes do 21st.dev abaixo são **implementações próprias**, construídas a partir da descrição
oficial de cada componente (devolvida pelo próprio registro) e adaptadas à identidade DARK POOL. Estão marcadas
como **provisórias**: se o código original for obtido (login no 21st.dev → "Copy prompt"/instalador), cada um pode
ser substituído no arquivo indicado sem mudar as telas.

As exceções são o **Woven Light Hero**, cujo código veio no kit, e os três **React Bits**, instalados a partir do
registro público oficial.

| # | Componente | Origem do código | Arquivo | Onde é usado | Situação |
|---|---|---|---|---|---|
| 01 | Woven Light Hero (Dhileep Kumar) | Código original do kit | `frontend/src/components/landing/WovenLightHero.tsx` | Landing (hero) | Original, otimizado (ver cabeçalho do arquivo) |
| 02 | Morphing Island Navbar | Própria (403) | `frontend/src/components/landing/IslandNavbar.tsx` | Landing | Provisório |
| 03 | Morphing Scroll Navbar | Própria (403), combinada com a 02 | mesmo arquivo | Landing | Provisório |
| 04 | Interactive Hover Button | Própria (403) | `frontend/src/components/ui/interactive-hover-button.tsx` | CTAs da landing | Provisório |
| 05 | Cybernetic Bento Grid | Própria (403) | `frontend/src/components/landing/FeatureBento.tsx` | Landing · Funcionalidades | Provisório |
| 06 | Financial Platform Feature Grid | — | — | — | Não usado: redundante com 05 e 07 na mesma página |
| 07 | Feature Grid Spotlight Cards | Própria (403) | `frontend/src/components/landing/SpotlightCards.tsx` | Landing · Princípios | Provisório |
| 08 | Stats Bento | Própria (403), como composição | `frontend/src/pages/app/Dashboard.tsx` (visão geral) | Dashboard | Provisório |
| 09 | Financial Bento Grid | Própria (403), como composição | `frontend/src/pages/app/Dashboard.tsx` | Dashboard | Provisório |
| 10 | Progress Metric Card | Própria (403) | `ProgressMetric` em `frontend/src/pages/app/Analytics.tsx` | Analytics | Provisório |
| 11 | Stock Card | Própria (403) | cabeçalho de `AssetDetail` em `frontend/src/pages/app/Scanner.tsx` | Market Scanner | Provisório |
| 12 | Crypto Dashboard | Referência de densidade apenas | — | Laboratório | Sem carteira/depósito, por definição |
| 13 | App Dashboard Layout | Própria (403) | `frontend/src/components/app/AppShell.tsx` | Laboratório | Provisório |
| 14 | Animated Sidebar (unlumen) | Própria (403) | `AppShell.tsx` (barra lateral) | Laboratório | Provisório |
| 15 | Sidebar — Andrew Luo | Própria (403) | `AppShell.tsx` (modo recolhido) | Laboratório | Provisório |
| 16 | Radar Score Chart | Própria (403), Recharts | `RadarScore` em `frontend/src/components/charts/charts.tsx` | Analytics | Provisório |
| 17 | Chart Area | Própria (403), Recharts | `PeriodArea` em `charts.tsx` | Analytics | Provisório |
| 18 | Area Chart with Glowing Dots | Própria (403), Recharts | `EquityChart` em `charts.tsx` | Dashboard, Analytics | Provisório |
| 19 | Candlestick Chart | Própria (403), TradingView Lightweight Charts | `frontend/src/components/charts/CandlestickChart.tsx` | Scanner, Time Machine (replay) | Biblioteca OHLC dedicada |
| 20 | Analytics Bento | Própria (403), como composição | grade de KPIs em `Analytics.tsx` | Analytics | Provisório |
| 21 | KPI Tile | Própria (403) | `frontend/src/components/app/KpiTile.tsx` | Dashboard, Analytics | Provisório |
| 22 | Stock Market Tracker Chart | Própria (403), combinada | seleção de período + máx./mín. em `Scanner.tsx` | Market Scanner | Provisório |
| 23 | Financial Markets Table | Própria (403) | `frontend/src/components/app/DataTable.tsx` | Market Scanner | Provisório |
| 24 | Inline Analytics Table | Própria (403) | tabela de comparação em `Analytics.tsx` | Analytics | Provisório |
| 25 | Resizable Table | Própria (403) | `DataTable.tsx` (redimensionar colunas) | Scanner, Time Machine | Provisório |
| 26 | Price Range Slider | Própria (403), Radix Slider | `frontend/src/components/ui/range-slider.tsx` | Market Scanner (filtros) | Provisório |
| 27 | Segmented Control — two segments | Própria (403) | `frontend/src/components/ui/segmented-control.tsx` | Time Machine, Scanner, Analytics, Dashboard | Provisório |
| 28 | Footer 7 (Shadcnblocks) | Própria (403) | `frontend/src/components/landing/Footer.tsx` | Landing | Provisório, com "Desenvolvido por Or7" |
| 29 | Animated Content (React Bits) | Registro oficial (`AnimatedContent-TS-TW`) | `frontend/src/components/reactbits/AnimatedContent.tsx` | Entrada das seções da landing | Original |
| 30 | Stepper (React Bits) | Registro oficial (`Stepper-TS-TW`) | `frontend/src/components/reactbits/Stepper.tsx` | Strategy Lab (6 etapas) | Original, tema via variáveis CSS |
| 31 | Counter (React Bits) | Registro oficial (`Counter-TS-TW`) | `frontend/src/components/reactbits/Counter.tsx` | KPI Tile | Original; dígitos ocultos de leitores de tela, valor lido em texto |

## Identidade

- `frontend/src/brand/Wordmark.tsx`: wordmark reconstruído em vetor a partir da prancha
  `06_IDENTIDADE_FINAL_APROVADA.png` (geometria larga, traços uniformes, cortes entre hastes e bojos, A aberto
  com triângulo laranja). **Provisório até o arquivo vetorial do designer.** Não é o nome digitado em fonte.
- `frontend/src/brand/EclipseMark.tsx` e `frontend/public/favicon.svg`: eclipse (núcleo escuro, aro laranja,
  brilho no quadrante superior direito, linha de horizonte).
- A prancha é uma imagem rasterizada gerada; para produção é necessário o vetor original do logo.
