import { expect, test, type Page } from '@playwright/test'

/** End-to-end checks on the local demo stack. The Time Machine run uses the
 * skill's frozen TSLA file, so the expected numbers are exact. */

async function enterDemo(page: Page) {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Entrar no modo demonstração' }).click()
  await expect(page).toHaveURL(/\/app(\/|$)/)
}

test('landing renders the approved identity and navigates', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/DARK POOL/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DARK POOL')
  await expect(page.getByText('Explore o mercado além dos gráficos.')).toBeVisible()
  await expect(page.locator('#funcionalidades')).toBeAttached()
  await expect(page.locator('#metodologia')).toBeAttached()
  await expect(page.getByText('Desenvolvido por')).toBeAttached()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(16)
})

test('private routes redirect to login, and logout ends the session', async ({ page, isMobile }) => {
  await page.goto('/app/analytics')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByRole('button', { name: 'Entrar no modo demonstração' }).click()
  await expect(page, 'returns to the page that was asked for').toHaveURL(/\/app\/analytics$/)
  await page.goto('/app/settings')
  await expect(page.getByRole('heading', { name: 'Configurações' })).toBeVisible()
  if (isMobile) {
    await page.getByRole('button', { name: 'Mais' }).click()
    await page.getByRole('dialog', { name: 'Mais opções' }).getByRole('button', { name: 'Sair' }).click()
  } else {
    await page.getByRole('button', { name: 'Sair' }).click()
  }
  await page.goto('/app')
  await expect(page).toHaveURL(/\/login$/)
})

test('all six lab areas are reachable', async ({ page }) => {
  await enterDemo(page)
  for (const [path, heading] of [
    ['/app', /Bom dia|Boa tarde|Boa noite/],
    ['/app/scanner', 'Market Scanner'],
    ['/app/strategies', 'Strategy Lab'],
    ['/app/time-machine', 'Time Machine'],
    ['/app/analytics', 'Analytics'],
    ['/app/journal', 'Trading Journal'],
  ] as const) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `${path} overflows horizontally`).toBeLessThanOrEqual(16)
  }
})

test('Time Machine reference run reproduces the engine numbers', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'one run is enough; the mobile layout is covered above')
  await enterDemo(page)
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

test('strategy can be created, versioned and deleted', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  await enterDemo(page)
  await page.goto('/app/strategies/new?symbol=TSLA')
  const next = page.getByRole('button', { name: 'Continuar' })
  await next.click()
  await page.getByLabel(/Rompimento da faixa de abertura/).check()
  await next.click()
  await next.click()
  await next.click()
  await next.click()
  const name = `E2E ORB ${Date.now()}`
  await page.getByLabel('Nome da estratégia').fill(name)
  await page.getByRole('button', { name: 'Salvar estratégia' }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  await expect(page.getByText('Configuração atual · v1')).toBeVisible()
  await page.getByRole('link', { name: 'Editar' }).click()
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByLabel('Alvo (R)').fill('1.5')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: 'Salvar nova versão' }).click()
  await expect(page.getByText('Configuração atual · v2')).toBeVisible()
  await expect(page.getByRole('table', { name: 'Diferenças entre versões' })).toContainText('exit.target_r')
  await page.getByRole('button', { name: 'Excluir estratégia' }).click()
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  await expect(page).toHaveURL(/\/app\/strategies$/)
  await expect(page.getByText(name)).toHaveCount(0)
})

test('journal entry is persisted, searchable and deletable', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'covered on desktop')
  await enterDemo(page)
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
