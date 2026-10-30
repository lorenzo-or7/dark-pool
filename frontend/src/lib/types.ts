export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export type Job = {
  id: string
  type: string
  status: JobStatus
  progress: number
  stage: string | null
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** GET /api/me: the shared lab's context. No account data in the public mode. */
export type LabInfo = {
  mode: 'public' | 'demo' | 'supabase'
  display_name: string
  role: string
  workspace: { id: string; name: string; is_demo: boolean }
  preferences: Record<string, unknown>
}

/** GET /api/jobs: every active or recent job of the shared workspace. */
export type TrackedJob = {
  id: string
  type: string
  status: JobStatus
  progress: number
  stage: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  cancel_requested: boolean
  title: string | null
  experiment_id: string | null
  scan_id: string | null
  strategy_id: string | null
  symbol: string | null
  result: Record<string, number | string> | null
}

export type RuleType = 'orb' | 'breakout_20d' | 'bull_flag' | 'reclaim_ma20' | 'oversold' | 'oversold_bounce' | 'sma_cross' | 'macd_cross'

export type StrategyConfig = {
  symbol: string
  rule: { type: RuleType; params: Record<string, number> }
  exit: { stop_type: 'pct' | 'atr' | 'or_mid' | 'or_low'; stop_value: number; target_r: number; max_hold_bars: number; flat_by: string }
  filters: { min_price: number; min_avg_volume: number }
  risk: {
    account_size: number
    max_loss_per_trade: number
    max_position_pct: number
    daily_loss_limit: number
    max_trades_per_day: number
    min_reward_risk: number
  }
}

export type StrategyVersion = { id: string; version: number; config: StrategyConfig; note: string | null; created_at: string; created_by: string }

export type Strategy = {
  id: string
  name: string
  description: string | null
  symbol: string | null
  rule_type: RuleType
  current_version: number
  is_demo: boolean
  archived: boolean
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
  experiments?: number
  versions?: StrategyVersion[]
}

export type Summary = {
  trades: number
  wins: number
  losses: number
  flat: number
  win_rate: number | null
  win_rate_ci95: [number, number] | null
  avg_r: number | null
  expectancy_r: number | null
  std_r: number | null
  std_error_r: number | null
  avg_win_r: number | null
  avg_loss_r: number | null
  payoff_ratio: number | null
  profit_factor: number | null
  total_r: number
  max_drawdown_r: number
  equity: { date: string; cum_r: number }[]
  distribution: { from: number; to: number; count: number }[]
  by_month: { month: string; trades: number; sum_r: number; avg_r: number }[]
  positive_months: number
  sample: 'none' | 'insufficient' | 'small' | 'ok'
  sample_note: string
}

export type Trade = {
  id: string
  source: 'backtest' | 'timemachine_history' | 'paper'
  dataset: 'full' | 'development' | 'out_of_sample'
  symbol: string
  entry_date: string
  entry_time: string | null
  entry: number
  stop: number
  target: number | null
  exit_price: number | null
  exit_date: string | null
  outcome: 'target' | 'stop' | 'close' | 'time'
  r_multiple: number
}

export type SnapshotRef = { id: string; sha256: string; source: string; fetched_at: string | null; is_fixture: boolean }

export type MonteCarlo = {
  replays: number
  seed: number
  window: number
  bars_left: number
  p_target: number
  p_stop: number
  p_neither: number
  p_green: number
  median_close: number
  p5_close: number
  p95_close: number
  avg_R: number
  r_at_target: number
  bands: number[][]
  band_times: string[]
  band_paths: number
  hist: { lo: number; hi: number; bins: number[] }
  sample_paths?: number[][]
  until: string
  pool_sessions: number
  pool_from: string
  pool_to: string
}

export type Experiment = {
  id: string
  kind: 'backtest' | 'monte_carlo'
  title: string
  status: JobStatus
  params: Record<string, unknown>
  strategy_id: string | null
  strategy_version: number | null
  dataset: string
  error: string | null
  job_id: string | null
  data_snapshot_id: string | null
  created_by: string
  created_at: string
  updated_at: string
  results?: Record<string, unknown> | null
  trades?: Trade[]
  simulation?: Record<string, unknown> | null
}

export type Snapshot = {
  id: string
  symbol: string
  interval: string
  range: string
  source: string
  sha256: string
  bars: number
  first_bar: string | null
  last_bar: string | null
  fetched_at: string
  is_fixture: boolean
}

export type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number; et?: string }

export type Provenance = {
  source: string
  source_label: string
  fetched_at: string
  from_cache: boolean
  interval: string
  last_bar_time: string | null
  market_time: string | null
  exchange: string | null
  currency: string | null
  timezone: string
  delayed: boolean
  note: string
}

export type JournalEntry = {
  id: string
  title: string
  body: string
  kind: 'note' | 'hypothesis' | 'simulated_trade' | 'lesson' | 'error'
  symbol: string | null
  strategy_id: string | null
  experiment_id: string | null
  tags: string[]
  trade: { side: 'buy'; entry: number; stop: number; exit: number | null; shares: number | null } | null
  entry_date: string
  is_demo: boolean
  created_by: string
  /** Only outside the shared lab (members-only mode). */
  author_name?: string | null
  created_at: string
  updated_at: string
  attachments: { id: string; filename: string; content_type: string; size: number }[]
}

export type Watchlist = {
  id: string
  name: string
  created_by: string
  updated_at: string
  assets: { id: string; symbol: string; note: string | null; added_by: string; created_at: string }[]
}

export type Quote = {
  symbol: string
  name: string | null
  last: number | null
  change_pct: number | null
  volume: number | null
  avg_volume: number | null
  volatility_pct: number | null
  spark: number[]
  as_of: string | null
  fetched_at: string
  /** true when the display policy hid last, volume, avg_volume and spark */
  prices_hidden?: boolean
}
