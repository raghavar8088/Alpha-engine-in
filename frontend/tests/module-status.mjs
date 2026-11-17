// Module switch store: which modules a page header shows, and reading an older server.
// Run: node tests/module-status.mjs
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

// Next resolves extensionless imports ('./api'); plain Node needs the .ts spelled out.
registerHooks({
  resolve(spec, ctx, next) {
    try { return next(spec, ctx); } catch (e) {
      if (spec.startsWith('.') && !spec.endsWith('.ts')) return next(spec + '.ts', ctx);
      throw e;
    }
  },
});

const { modulesForPath, fromSnapshot, stateText, offConsequence } = await import('../lib/moduleStatus.ts');

const row = (over) => ({ label: 'x', href: '/x', hrefs: [], enabled: true, state: 'active', open_positions: null,
  drains: true, real_money: false, group: 'Trading', shared: false, api_prefixes: [], ...over });
const map = {
  semantics: 'drain', states: { active: 'Active', stopping: 'Stopping — managing open positions', paused: 'Paused' },
  modules: {
    intraday_lab: row({ href: '/intraday-stocks' }),
    pattern: row({ href: '/intraday-stocks' }),
    intraday_focus: row({ href: '/intraday-stocks/focus-five' }),
    live_paper: row({ href: '/live' }),
    live_trading: row({ href: '/live-trading', real_money: true }),
    stock_desk: row({ href: '/stock-prelive-buying', hrefs: ['/stock-prelive-selling'] }),
    market_data: row({ href: '/dashboard', shared: true }),
    desk_history: row({ href: '/dashboard', group: 'System', shared: true }),
  },
};

assert.deepEqual(modulesForPath(map, '/intraday-stocks').sort(), ['intraday_lab', 'pattern']);
assert.deepEqual(modulesForPath(map, '/intraday-stocks/focus-five').sort(), ['intraday_focus', 'intraday_lab', 'pattern']);
assert.deepEqual(modulesForPath(map, '/live-trading'), ['live_trading'], '/live must not claim /live-trading');
assert.deepEqual(modulesForPath(map, '/live/'), ['live_paper'], 'trailing slash');
assert.deepEqual(modulesForPath(map, '/stock-prelive-selling'), ['stock_desk'], 'extra hrefs');
assert.deepEqual(modulesForPath(map, '/dashboard'), ['market_data'], 'System shared services stay in Main Control');
assert.deepEqual(modulesForPath(map, '/main-control'), [], 'Main Control page has no module switch');

assert.equal(stateText(row({ state: 'stopping', open_positions: 3 }), map.states), 'Stopping — managing 3 open positions');
assert.equal(stateText(row({ state: 'stopping', open_positions: 1 }), map.states), 'Stopping — managing 1 open position');
assert.equal(stateText(row({ state: 'paused' }), map.states), 'Paused');
assert.match(offConsequence(row({ drains: true }), 'drain'), /keep being managed/);
assert.match(offConsequence(row({ drains: false }), 'drain'), /NOT managed/);
assert.match(offConsequence(row({ drains: true }), 'freeze'), /NOT managed/, 'an older server never promises a drain');

// An older server: no state, no semantics -> derived from enabled, and never claims to drain.
const old = fromSnapshot({ modules: [
  { module: 'swing_trading', label: 'Swing', href: '/swing-trading', enabled: false, drains: true },
  { module: 'live_trading', label: 'Live', href: '/live-trading', enabled: true },
], total: 2, on: 1, off: 1, note: '' });
assert.equal(old.semantics, 'freeze');
assert.equal(old.modules.swing_trading.state, 'paused');
assert.equal(old.modules.swing_trading.drains, false);
assert.equal(old.modules.live_trading.real_money, true);

console.log('Module switch page matching, state text and older-server fallback: all checks passed.');
