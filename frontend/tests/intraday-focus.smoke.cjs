/* UI fixtures only. Never loaded by the application or written to any trading ledger.
   Run after next build/start: node tests/intraday-focus.smoke.cjs */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');

const specs = [
  ['iv2_macd_trend_1h', 'MACD Trend', '1h'],
  ['iv2_donchian_1h', 'Donchian Breakout', '1h'],
  ['iv2_ema_pullback_45m', 'EMA Trend Pullback', '45m'],
  ['iv2_supertrend_1h', 'Supertrend Flip', '1h'],
  ['iv2_keltner_1h', 'Keltner Breakout', '1h'],
];
const fresh = () => new Date().toISOString();
const fixture = () => ({
  mode: 'PAPER', real_orders_enabled: false, initial_capital: 5000000,
  per_strategy_capital: 1000000, slot_notional: 200000, slots_per_strategy: 5,
  started_at: fresh(), updated_at: fresh(), realized_pnl: 0, unrealized_pnl: 0,
  total_pnl: 0, return_pct: 0, equity: 5000000, available_cash: 5000000,
  deployed_capital: 0, fee_reserve: 0, open_positions: 0, closed_trades: 0,
  feed: { source: 'Angel One NSE live stream', status: 'MARKET_CLOSED', last_quote_at: null,
    reason: 'No fresh session quotes. New entries require valid prices received and exchanged within 30 seconds.' },
  engine: { enabled: true, entries_enabled: false, last_tick: fresh(), last_evaluation: null,
    note: 'Waiting for a qualifying closed-bar signal.' },
  strategies: specs.map(([strategy_id, name, timeframe]) => ({strategy_id, name, timeframe,
    description: 'Existing indicator rule; same-day stop, target and time exits.', initial_capital: 1000000,
    equity: 1000000, available_cash: 1000000, deployed_capital: 0, realized_pnl: 0,
    unrealized_pnl: 0, total_pnl: 0, return_pct: 0, trades: 0, win_rate: 0,
    open_positions: 0, status: 'PAPER', last_skip: null })),
  positions: [], trades: [], daily: [], cost_note: 'Estimated charges and slippage; simulated fills.',
  validation_note: 'Research only.',
});

let browser;
(async () => {
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let fail = false, body = fixture();
  await page.route('**/api/**', async route => {
    const url = route.request().url();
    assert.equal(route.request().method(), 'GET', 'the desk must not send mutations');
    if (url.includes('/api/intraday-focus/snapshot')) {
      await route.fulfill({status: fail ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fail ? {detail:'test outage'} : body)});
    } else if (url.includes('/api/intraday')) {
      // The parent desk may load many unrelated resources. An explicit outage
      // keeps its default empty state; {} would be an invalid success payload.
      await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({detail:'unrelated desk not part of this fixture'})});
    } else {
      await route.fulfill({status: 200, contentType: 'application/json', body: '{}'});
    }
  });
  const base = process.env.FOCUS_TEST_URL || 'http://127.0.0.1:3217';
  await page.goto(`${base}/intraday-stocks/focus-five`);
  await page.getByRole('heading', {name: 'Your five strategy accounts'}).waitFor();
  assert.equal(await page.locator('tbody').first().locator('tr').count(), 5);
  assert.ok(await page.getByText('PAPER TRADING · NO BROKER ORDERS').isVisible());
  assert.ok((await page.locator('body').innerText()).includes('₹50,00,000'));
  assert.ok((await page.locator('body').innerText()).includes('0.000%'));
  assert.ok(!(await page.locator('body').innerText()).match(/\b(?:bp|bps)\b/));
  const desktop = path.join(os.tmpdir(), 'intraday-focus-desktop.png');
  await page.screenshot({path: desktop, fullPage: true, animations: 'disabled'});

  await page.getByRole('tab', {name: 'Closed trades'}).click();
  assert.ok(await page.getByText('No closed trades in this view.', {exact:false}).isVisible());
  await page.getByRole('tab', {name: 'Daily returns'}).click();
  assert.ok(await page.getByText('Daily returns appear after the first position closes.').isVisible());
  await page.getByRole('tab', {name: 'Open positions'}).click();
  // Exercise populated records as well as empty states. These deliberately
  // synthetic prices/P&L only exist in this intercepted response.
  const makePosition = (index, symbol, pnl) => ({
    position_id: `fixture-${index}`, strategy_id: specs[index][0], strategy_name: specs[index][1],
    symbol, side: 'BUY', qty: 100, entry_price: 100, ltp: pnl > 0 ? 101 : 99,
    stoploss: 95, target: 105, capital_deployed: 10000, unrealized_pnl: pnl,
    return_pct: pnl / 100, opened_at: fresh(), price_status: 'LIVE',
  });
  body.positions = [makePosition(0, 'TEST-A', 90), makePosition(1, 'TEST-B', -110)];
  body.trades = [{...makePosition(2, 'TEST-C', 0), exit_price: 102, gross_pnl: 200,
    fees: 10, realized_pnl: 190, return_pct: 1.9, closed_at: fresh(), exit_reason: 'target'}];
  body.daily = [{date:'2026-10-15', trades:1, gross_pnl:200, fees:10, realized_pnl:190, return_pct:.0038}];
  await page.getByRole('button', {name:'Refresh', exact:true}).click();
  await page.getByText('TEST-A', {exact:true}).waitFor();
  assert.ok(await page.getByRole('cell', {name:/^\+0\.900%/}).isVisible());
  await page.getByLabel('Strategy', {exact:true}).selectOption(specs[1][0]);
  assert.equal(await page.getByText('TEST-A', {exact:true}).count(), 0);
  assert.ok(await page.getByText('TEST-B', {exact:true}).isVisible());
  await page.getByRole('tab', {name:'Closed trades'}).click();
  assert.ok(await page.getByText('No closed trades in this view.', {exact:false}).isVisible());
  await page.getByLabel('Strategy', {exact:true}).selectOption('all');
  assert.ok(await page.getByText('TEST-C', {exact:true}).isVisible());
  assert.ok(await page.getByRole('cell', {name:/^\+1\.900%/}).isVisible());
  await page.getByRole('tab', {name:'Daily returns'}).click();
  assert.ok(await page.getByText('+0.004%', {exact:true}).isVisible());
  body = fixture();
  await page.getByRole('button', {name:'Refresh', exact:true}).click();
  await page.getByText('Daily returns appear after the first position closes.').waitFor();
  await page.getByRole('tab', {name:'Open positions'}).click();
  fail = true;
  await page.getByRole('button', {name: 'Refresh', exact:true}).click();
  const outageAlert = page.getByRole('alert').filter({has: page.getByRole('button', {name: 'Retry', exact:true})});
  await outageAlert.waitFor();
  assert.equal(await page.locator('tbody').first().locator('tr').count(), 5, 'last good results are retained');
  assert.ok(await page.getByText('DISPLAY DATA STALE').isVisible());
  fail = false;
  await page.getByRole('button', {name: 'Retry', exact:true}).click();
  await outageAlert.waitFor({state:'hidden'});

  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await page.getByRole('heading', {name: 'Five-Strategy Desk', exact:true}).isVisible());
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
  assert.equal(overflow, false, 'only tables should scroll horizontally, not the entire mobile page');
  const mobile = path.join(os.tmpdir(), 'intraday-focus-mobile.png');
  await page.screenshot({path: mobile, fullPage:true, animations:'disabled'});
  assert.deepEqual(errors, [], 'the new page must not throw browser runtime errors');
  await page.goto(`${base}/intraday-stocks`);
  await page.getByRole('link', {name:'Five-Strategy Desk · ₹10 lakh each'}).waitFor();
  await browser.close();
  console.log(JSON.stringify({passed: true, desktop, mobile, checks: [
    'five allocations', 'paper labels', 'percentage returns', 'tabs', 'populated trade records', 'strategy filter',
    'outage retains results', 'retry recovery', 'desktop render', 'mobile width', 'parent navigation'
  ]}));
})().catch(async e => { console.error(e); await browser?.close(); process.exitCode=1; });
