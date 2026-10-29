import { describe as suite, expect, it } from 'vitest'
import { fmt } from './format'
import { boundLabel, defaultConfig, describe, diffConfig, PARAMS } from './strategy'

suite('strategy config', () => {
  it('builds defaults inside the backend limits', () => {
    for (const type of Object.keys(PARAMS) as (keyof typeof PARAMS)[]) {
      const c = defaultConfig('AAPL', type)
      for (const p of PARAMS[type]) {
        expect(c.rule.params[p.key]).toBeGreaterThanOrEqual(p.min)
        expect(c.rule.params[p.key]).toBeLessThanOrEqual(p.max)
      }
      expect(c.exit.stop_type).toBe(type === 'orb' ? 'or_mid' : 'pct')
    }
  })

  it('describes a configuration in plain Portuguese', () => {
    const text = describe(defaultConfig('TSLA', 'orb'))
    expect(text).toContain('TSLA')
    expect(text).toContain('meio da faixa de abertura')
    expect(text).toContain('alvo de 2R')
  })

  it('diffs two versions field by field', () => {
    const a = defaultConfig('TSLA', 'orb')
    const b = { ...a, exit: { ...a.exit, target_r: 1 } }
    expect(diffConfig(a, b)).toEqual([{ key: 'exit.target_r', a: 2, b: 1 }])
    expect(diffConfig(a, a)).toEqual([])
  })

  it('translates trader-budget limits', () => {
    expect(boundLabel('max loss')).toBe('perda máxima por operação')
    expect(boundLabel('unknown')).toBe('unknown')
  })
})

suite('formatting', () => {
  it('formats prices, percentages and R in pt-BR without inventing values', () => {
    expect(fmt.price(364.18)).toBe('US$ 364,18')
    expect(fmt.pct(0.2938)).toBe('29,4 %')
    expect(fmt.r(-0.062)).toBe('−0,062 R')
    expect(fmt.r(0.034)).toBe('+0,034 R')
    expect(fmt.price(null)).toBe('—')
    expect(fmt.pct(undefined)).toBe('—')
  })
})
