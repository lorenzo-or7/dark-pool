import type { RuleType, StrategyConfig } from './types'

export const RULES: { type: RuleType; label: string; interval: '5m' | '1d'; summary: string }[] = [
  { type: 'orb', label: 'Rompimento da faixa de abertura (ORB)', interval: '5m', summary: 'Entrada no primeiro candle de 5 min que fecha acima da máxima dos primeiros minutos do pregão.' },
  { type: 'breakout_20d', label: 'Rompimento de máxima de N dias', interval: '1d', summary: 'Fechamento acima de todos os fechamentos das N sessões anteriores.' },
  { type: 'bull_flag', label: 'Bandeira de alta', interval: '1d', summary: 'Alta forte seguida de consolidação estreita dos fechamentos.' },
  { type: 'reclaim_ma20', label: 'Retomada da média móvel', interval: '1d', summary: 'Fechamento volta para cima da média móvel simples após fechar abaixo dela.' },
  { type: 'oversold', label: 'Sobrevenda (RSI)', interval: '1d', summary: 'RSI de Wilder cruza para baixo do limite.' },
  { type: 'oversold_bounce', label: 'Repique de sobrevenda', interval: '1d', summary: 'RSI abaixo do limite ontem e fechamento em alta hoje.' },
  { type: 'sma_cross', label: 'Cruzamento de médias', interval: '1d', summary: 'Média rápida cruza para cima da média lenta.' },
  { type: 'macd_cross', label: 'Cruzamento do MACD', interval: '1d', summary: 'Linha do MACD cruza para cima da linha de sinal.' },
]

export const PARAMS: Record<RuleType, { key: string; label: string; min: number; max: number; step: number; def: number; unit?: string }[]> = {
  orb: [{ key: 'or_minutes', label: 'Faixa de abertura', min: 5, max: 60, step: 5, def: 15, unit: 'min' }],
  breakout_20d: [{ key: 'lookback', label: 'Sessões anteriores', min: 5, max: 120, step: 1, def: 20 }],
  bull_flag: [
    { key: 'pole_pct', label: 'Alta mínima do mastro', min: 3, max: 50, step: 1, def: 10, unit: '%' },
    { key: 'flag_days', label: 'Dias de bandeira', min: 3, max: 15, step: 1, def: 5 },
    { key: 'flag_range_pct', label: 'Faixa máxima da bandeira', min: 1, max: 15, step: 0.5, def: 5, unit: '%' },
  ],
  reclaim_ma20: [{ key: 'period', label: 'Período da média', min: 5, max: 200, step: 1, def: 20 }],
  oversold: [
    { key: 'rsi_period', label: 'Período do RSI', min: 2, max: 50, step: 1, def: 14 },
    { key: 'threshold', label: 'Limite de sobrevenda', min: 5, max: 50, step: 1, def: 30 },
  ],
  oversold_bounce: [
    { key: 'rsi_period', label: 'Período do RSI', min: 2, max: 50, step: 1, def: 14 },
    { key: 'threshold', label: 'Limite de sobrevenda', min: 5, max: 50, step: 1, def: 30 },
  ],
  sma_cross: [
    { key: 'fast', label: 'Média rápida', min: 2, max: 100, step: 1, def: 20 },
    { key: 'slow', label: 'Média lenta', min: 5, max: 300, step: 1, def: 50 },
  ],
  macd_cross: [
    { key: 'fast', label: 'EMA rápida', min: 2, max: 50, step: 1, def: 12 },
    { key: 'slow', label: 'EMA lenta', min: 5, max: 100, step: 1, def: 26 },
    { key: 'signal', label: 'Sinal', min: 2, max: 50, step: 1, def: 9 },
  ],
}

export const STOP_LABEL: Record<string, string> = {
  pct: 'Percentual abaixo da entrada',
  atr: 'Múltiplo do ATR 14',
  or_mid: 'Meio da faixa de abertura',
  or_low: 'Mínima da faixa de abertura',
}

export function ruleLabel(t: string) {
  return RULES.find((r) => r.type === t)?.label ?? t
}

export function defaultConfig(symbol = '', type: RuleType = 'breakout_20d'): StrategyConfig {
  return {
    symbol,
    rule: { type, params: Object.fromEntries(PARAMS[type].map((p) => [p.key, p.def])) },
    exit: { stop_type: type === 'orb' ? 'or_mid' : 'pct', stop_value: type === 'orb' ? 0 : 3, target_r: 2, max_hold_bars: 10, flat_by: '15:55' },
    filters: { min_price: 5, min_avg_volume: 0 },
    risk: { account_size: 10000, max_loss_per_trade: 100, max_position_pct: 50, daily_loss_limit: 300, max_trades_per_day: 3, min_reward_risk: 1 },
  }
}

export function describe(c: StrategyConfig) {
  const p = c.rule.params
  const stop =
    c.exit.stop_type === 'pct'
      ? `stop ${c.exit.stop_value}% abaixo da entrada`
      : c.exit.stop_type === 'atr'
        ? `stop a ${c.exit.stop_value}× ATR`
        : c.exit.stop_type === 'or_mid'
          ? 'stop no meio da faixa de abertura'
          : 'stop na mínima da faixa de abertura'
  const exit = c.rule.type === 'orb' ? `saída até ${c.exit.flat_by} ET` : `saída em até ${c.exit.max_hold_bars} sessões`
  const params = PARAMS[c.rule.type].map((d) => `${d.label.toLowerCase()} ${p[d.key]}${d.unit ? ` ${d.unit}` : ''}`).join(', ')
  return `${ruleLabel(c.rule.type)} em ${c.symbol} (${params}); ${stop}; alvo de ${c.exit.target_r}R; ${exit}.`
}

/** Field-by-field differences between two configs, for version comparison. */
export function diffConfig(a: StrategyConfig, b: StrategyConfig) {
  const flat = (o: unknown, pre = ''): Record<string, unknown> =>
    o && typeof o === 'object' && !Array.isArray(o)
      ? Object.fromEntries(Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => Object.entries(flat(v, pre ? `${pre}.${k}` : k))))
      : { [pre]: o }
  const fa = flat(a)
  const fb = flat(b)
  return [...new Set([...Object.keys(fa), ...Object.keys(fb)])].filter((k) => JSON.stringify(fa[k]) !== JSON.stringify(fb[k])).map((k) => ({ key: k, a: fa[k], b: fb[k] }))
}

const BOUND: Record<string, string> = {
  'max loss': 'perda máxima por operação',
  'position cap': 'teto de posição',
  'max order': 'valor máximo da ordem',
  cash: 'caixa disponível',
}

/** trader-budget names the limit that decided the size in English. */
export function boundLabel(b: string) {
  return BOUND[b] ?? b
}
