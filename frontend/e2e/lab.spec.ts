import { expect, test, type Browser, type Page } from '@playwright/test'

/** End-to-end checks on the local public stack (see playwright.config.ts). Every test opens
 * fresh browser contexts: no cookies, no storage, no session, like an anonymous window. */

const API = 'http://127.0.0.1:8000/api'

async function overflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
}

async function freshPage(browser: Browser, info: { project: { use: Record<string, unknown> } }) {
  const ctx = await browser.newContext({ ...(info.project.use as object), storageState: undefined })
  return { ctx, page: await ctx.newPage() }
}

test('landing renders the approved identity and opens the lab', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/DARK POOL/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DARK POOL')
  await expect(page.getByText('Explore o mercado além dos gráficos.')).toBeVisible()
  await expect(page.locator('#funcionalidades')).toBeAttached()
  await expect(page.locator('#metodologia')).toBeAttached()
  await expect(page.getByText('Desenvolvido por')).toBeAttached()
  await expect(page.getByText(/Entrar$|Recuperar senha|Acesso por convite/)).toHaveCount(0)
  expect(await overflow(page)).toBeLessThanOrEqual(16)
  await page.getByRole('link', { name: 'Abrir laboratório' }).first().click()
  await expect(page).toHaveURL(/\/app$/)
  await expect(page.getByRole('heading', { level: 1, name: /Bom dia|Boa tarde|Boa noite/ })).toBeVisible()
})

test('the lab opens without a session; old account paths lead to it', async ({ browser }, info) => {
  const { ctx, page } = await freshPage(browser, info)
  for (const path of ['/login', '/reset-password']) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/app$/)
  }
  await page.goto('/app')
  await expect(page.getByRole('heading', { level: 1, name: /Bom dia|Boa tarde|Boa noite/ })).toBeVisible()
  const text = await page.locator('body').innerText()
  expect(text).not.toMatch(/Proprietário|Membro|Sair\b|Lorenzo|Lipe|@/)
  if (info.project.name === 'desktop') {
    await expect(page.getByRole('complementary').getByText('Laboratório compartilhado')).toBeVisible()
  } else {
    await page.getByRole('button', { name: 'Mais' }).click()
    await expect(page.getByRole('dialog', { name: 'Mais opções' })).toContainText('Laboratório compartilhado')
    await expect(page.getByRole('dialog', { name: 'Mais opções' }).getByRole('button', { name: 'Sair' })).toHaveCount(0)
  }
  await ctx.close()
})

test('every lab area opens directly and survives a reload', async ({ browser }, info) => {
  const { ctx, page } = await freshPage(browser, info)
  for (const [path, heading] of [
    ['/app', /Bom dia|Boa tarde|Boa noite/],
    ['/app/scanner', 'Market Scanner'],
    ['/app/strategies', 'Strategy Lab'],
    ['/app/time-machine', 'Time Machine'],
    ['/app/analytics', 'Analytics'],
    ['/app/journal', 'Trading Journal'],
    ['/app/congress', 'Congresso'],
    ['/app/settings', 'Configurações'],
  ] as const) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    expect(await overflow(page), `${path} overflows horizontally`).toBeLessThanOrEqual(16)
  }
  await ctx.close()
})

test('congress page follows the server policy in the public lab (off, no House Clerk call)', async ({ page }) => {
  const congress: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/congress/')) congress.push(r.url())
  })
  await page.goto('/app/congress')
  await expect(page.getByRole('heading', { level: 1, name: 'Congresso' })).toBeVisible()
  await expect(page.getByText(/5 U\.S\.C\. §13107\(c\)/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Abrir o eFD do Senado' })).toBeVisible()
  expect(congress).toEqual([])
  const r = await page.request.get(`${API}/congress/ptrs?year=2026`)
  expect(r.status()).toBe(403)
  expect((await r.json()).detail.code).toBe('display_policy')
})

test('settings keep preferences in this browser and list no accounts', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  await page.goto('/app/settings')
  await expect(page.getByRole('heading', { name: 'Laboratório compartilhado' })).toBeVisible()
  await expect(page.getByText(/Senha|Nome de exibição|Gerenciamento de acesso|invite_member/)).toHaveCount(0)
  await page.getByLabel('Seed padrão').fill('7')
  await page.getByRole('button', { name: 'Salvar preferências' }).click()
  await expect(page.getByText('Salvas neste navegador.')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Seed padrão')).toHaveValue('7')
})

test('two visitors share strategies, and a backtest is followed everywhere', async ({ browser }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  const a = await freshPage(browser, info)
  const b = await freshPage(browser, info)

  // A creates a strategy; B sees it.
  await a.page.goto('/app/strategies/new?symbol=TSLA')
  const next = a.page.getByRole('button', { name: 'Continuar' })
  await next.click()
  await a.page.getByLabel(/Rompimento da faixa de abertura/).check()
  for (let i = 0; i < 4; i++) await next.click()
  const name = `E2E compartilhada ${Date.now()}`
  await a.page.getByLabel('Nome da estratégia').fill(name)
  await a.page.getByRole('button', { name: 'Salvar estratégia' }).click()
  await expect(a.page.getByRole('heading', { level: 1, name })).toBeVisible()
  const strategyUrl = a.page.url()
  await b.page.goto('/app/strategies')
  await expect(b.page.getByText(name)).toBeVisible()

  // A starts a backtest on the frozen reference snapshot, closes the dialog and leaves the page.
  await a.page.getByRole('button', { name: 'Rodar backtest' }).click()
  const dlg = a.page.getByRole('dialog', { name: 'Rodar backtest' })
  const option = dlg.locator('option', { hasText: 'de referência' }).first()
  await dlg.getByLabel('Dados').selectOption((await option.getAttribute('value')) ?? '')
  await dlg.getByRole('button', { name: 'Iniciar' }).click()
  await expect(dlg.getByRole('progressbar')).toBeVisible()
  await dlg.getByRole('button', { name: 'Fechar' }).click()
  await a.page.getByRole('link', { name: 'Trading Journal' }).first().click()
  await expect(a.page.getByRole('heading', { level: 1, name: 'Trading Journal' })).toBeVisible()

  // B, in another browser, sees the same run and its end, without reloading.
  await b.page.goto('/app')
  const bDone = b.page.getByRole('link', { name: 'Ver em Analytics' })
  const aDone = a.page.getByRole('link', { name: 'Ver em Analytics' })
  await expect(aDone).toBeVisible({ timeout: 90_000 })
  await expect(bDone).toBeVisible({ timeout: 30_000 })
  await expect(a.page.getByRole('status').filter({ hasText: 'Concluído' })).toContainText(name)

  // The link leads to that experiment; the strategy page lists it without F5.
  await aDone.click()
  await expect(a.page).toHaveURL(/\/app\/analytics\?exp=/)
  await expect(a.page.getByRole('heading', { level: 1, name: 'Analytics' })).toBeVisible()
  await a.page.goto(strategyUrl)
  await expect(a.page.getByText(/Backtest ·/).first()).toBeVisible()

  // Clean up the shared lab.
  await a.page.getByRole('button', { name: 'Excluir estratégia' }).click()
  await a.page.getByRole('button', { name: 'Excluir', exact: true }).click()
  await expect(a.page).toHaveURL(/\/app\/strategies$/)
  await a.ctx.close()
  await b.ctx.close()
})

test('a failed run started by someone else shows its error without a reload', async ({ page, request }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  await page.goto('/app/analytics')
  await expect(page.getByRole('heading', { level: 1, name: 'Analytics' })).toBeVisible()
  // Another visitor asks for a session the frozen data does not have: the engine refuses it.
  const snaps = await (await request.get(`${API}/snapshots?symbol=TSLA&interval=5m`)).json()
  const snap = snaps.find((s: { is_fixture: boolean }) => s.is_fixture).id
  const r = await request.post(`${API}/timemachine`, {
    data: { symbol: 'TSLA', date: '2026-01-05', entry: 364.18, stop: 358.32, target: 370.04, entry_time: '10:15', replays: 500, seed: 3, snapshot_id: snap },
  })
  expect(r.status()).toBe(202)
  const alert = page.getByRole('alert').filter({ hasText: 'Falhou' })
  await expect(alert).toBeVisible({ timeout: 60_000 })
  await expect(alert.getByRole('link', { name: 'Ver simulação' })).toBeVisible()
})

test('Time Machine reference run reproduces the engine numbers', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'one run is enough; the mobile layout is covered above')
  await page.goto('/app/time-machine')
  await page.getByRole('button', { name: 'Exemplo de referência' }).click()
  await expect(page.getByLabel('Entrada (US$)')).toHaveValue('364.18')
  await page.getByRole('button', { name: /Rodar 10\.000 replays/ }).click()
  await expect(page.getByText('Alvo primeiro').first()).toBeVisible({ timeout: 60_000 })
  const main = page.locator('main')
  await expect(main).toContainText('29,4 %')
  await expect(main).toContainText('25,5 %')
  await expect(main).toContainText('45,1 %')
  await expect(main).toContainText('51,7 %')
  await expect(main).toContainText('US$ 364,36')
  await expect(main).toContainText('355,54 e 373,54')
  await expect(main).toContainText('disparou 33 vezes, 13 alvo, 15 stop, 5 nenhum')
  await expect(main).toContainText('Close to a coin flip: target first 29.4 % vs stop first 25.5 %.')
})

test('journal entry is persisted, searchable and deletable (with confirmation)', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  await page.goto('/app/journal')
  const title = `Hipótese E2E ${Date.now()}`
  await page.getByRole('button', { name: 'Novo registro' }).click()
  await page.getByLabel('Título').fill(title)
  await page.getByLabel('Tipo', { exact: true }).selectOption('hypothesis')
  await page.getByLabel('Tags').fill('e2e, orb')
  await page.getByRole('button', { name: 'Salvar', exact: true }).click()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await page.reload()
  await page.getByLabel('Pesquisar registros').fill('E2E')
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await page.getByRole('button', { name: `Excluir ${title}` }).click()
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  await expect(page.getByRole('heading', { name: title })).toHaveCount(0)
})

test('the API refuses too many job requests from one visitor', async ({ request }, info) => {
  test.skip(info.project.name === 'mobile', 'server behaviour, once is enough')
  const bad = { symbol: 'TSLA', date: '2026-10-19', entry: 364.18, stop: 358.32, target: 370.04, entry_time: '10:15', replays: 1, seed: 1 }
  const codes: number[] = []
  for (let i = 0; i < 70; i++) codes.push((await request.post(`${API}/timemachine`, { data: bad })).status())
  expect(codes).toContain(422)
  expect(codes).toContain(429)
})
