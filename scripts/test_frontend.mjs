// Run with: node scripts/test_frontend.mjs
// Uses synthetic API responses only; never starts the app or opens its database.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test, { beforeEach } from 'node:test';

const staticDir = resolve(dirname(fileURLToPath(import.meta.url)), '../app/static');
const vueSource = await readFile(resolve(staticDir, 'vendor/vue.esm-browser.prod.js'), 'utf8');
const { reactive, watch, effectScope } = await import('data:text/javascript;base64,' + Buffer.from(vueSource).toString('base64'));
const plain = value => JSON.parse(JSON.stringify(value));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let calls, notices, copied, events, get, post, put, del, promptAnswer;
const api = Object.fromEntries(['get', 'post', 'put', 'del'].map(method => [method, (...args) => {
  calls.push([method, ...args]);
  return ({ get, post, put, del })[method](...args);
}]));
beforeEach(() => {
  calls = []; notices = []; copied = []; events = [];
  get = post = put = del = async () => ({});
  promptAnswer = undefined;
});
class CustomEvent { constructor(type) { this.type = type; } }
const windowMock = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  dispatchEvent: event => events.push(event.type),
};
async function load(relative, names, globals = {}) {
  const source = (await readFile(resolve(staticDir, relative), 'utf8'))
    .replace(/^import .*;\r?$/gm, '').replace(/^export /gm, '');
  return vm.runInNewContext(source + '\n;({' + names.join(',') + '})', {
    console, setTimeout, clearTimeout, URL, Blob, Response, Date, CustomEvent,
    window: windowMock, api,
    confirm: () => true,
    prompt: (_message, value) => promptAnswer === undefined ? value : promptAnswer,
    copyText: async text => copied.push(text), expiryInfo: () => null,
    fmtBalance: () => '', fmtTime: value => value,
    ...globals,
  }, { filename: relative });
}
function instance(component, values = {}) {
  const scope = effectScope();
  const o = reactive({ ...component.data(), $toast: text => notices.push(text), $goto() {},
    $nextTick: fn => fn(), ...values });
  for (const [name, fn] of Object.entries(component.methods || {})) o[name] = fn.bind(o);
  for (const [name, fn] of Object.entries(component.computed || {})) Object.defineProperty(o, name, { get: () => fn.call(o) });
  scope.run(() => {
    for (const [name, entry] of Object.entries(component.watch || {})) {
      const config = typeof entry === 'function' ? { handler: entry } : entry;
      watch(() => o[name], (value, old) => config.handler.call(o, value, old), { flush: config.flush || 'sync' });
    }
  });
  o.dispose = () => { component.beforeUnmount?.call(o); scope.stop(); };
  return o;
}
const { ChannelsView, parseModelText } = await load('js/views/channels.js', ['ChannelsView', 'parseModelText']);
const { QuickAddView } = await load('js/views/quickadd.js', ['QuickAddView']);
const { ExportView } = await load('js/views/export.js', ['ExportView']);
const { SettingsView } = await load('js/views/settings.js', ['SettingsView']);
let canvas, chartConfigs, destroyed;
class FakeChart {
  constructor(_canvas, config) { this.config = config; chartConfigs.push(config); }
  destroy() { destroyed++; }
}
const { DashboardView } = await load('js/views/dashboard.js', ['DashboardView'], {
  window: { ...windowMock, Chart: FakeChart }, document: { getElementById: () => canvas },
});

await test('copy configuration uses the key object and keeps the original channel during a request', async () => {
  assert.match(ChannelsView.template, /@click="copyConfig\(k\)"/);
  const waiting = deferred(); post = () => waiting.promise;
  const o = instance(ChannelsView, { detail: { name: 'A', base_url: 'https://a.invalid' }, models: [{ enabled: 1, model_id: 'a-chat' }] });
  const result = o.copyConfig({ id: 7, name: 'A key' });
  o.detail = { name: 'B', base_url: 'https://b.invalid' };
  o.models = [{ enabled: 1, model_id: 'b-chat' }];
  waiting.resolve({ value: 'secret-a' }); await result;
  assert.equal(calls[0][1], '/api/keys/7/reveal');
  assert.match(copied[0], /# A · A key/);
  assert.match(copied[0], /Models: a-chat/);
  assert.doesNotMatch(copied[0], /b\.invalid|b-chat/);
  o.dispose();
});

await test('editing a revealed key clears the old plaintext', async () => {
  const o = instance(ChannelsView, { revealed: { 7: 'old-key' }, keyForm: { id: 7, value: 'new-key' } });
  o.load = async () => {};
  await o.saveKey();
  assert.equal(o.revealed[7], undefined);
  assert.equal(calls[0][2].value, 'new-key');
  o.dispose();
});

await test('late model diff cannot be applied after changing channels, even after returning to the first channel', async () => {
  const waiting = deferred(); post = () => waiting.promise;
  const o = instance(ChannelsView, { selectedId: 1 });
  o.load = async () => {};
  const fetching = o.fetchModels();
  await o.select(2); await o.select(1);
  waiting.resolve({ ok: true, added: ['a-chat'], removed: ['common'], revived: [] });
  await fetching; await o.applySync();
  assert.equal(o.diff, null);
  assert.equal(calls.filter(c => c[1].endsWith('/sync')).length, 0);
  o.dispose();
});

await test('current model diff syncs to its channel and refreshes once', async () => {
  post = async path => path.endsWith('/diff')
    ? { ok: true, added: ['a-chat'], removed: ['old-chat'], revived: [] }
    : { added: 1, removed: 1, revived: 0 };
  let reloads = 0;
  const o = instance(ChannelsView, { selectedId: 1 }); o.load = async () => { reloads++; };
  await o.fetchModels();
  assert.equal(o.diff.channel_id, 1);
  await o.applySync();
  assert.equal(calls.at(-1)[1], '/api/channels/1/models/sync');
  assert.deepEqual(plain(calls.at(-1)[2].added), ['a-chat']);
  assert.equal(reloads, 1);
  o.dispose();
});

await test('late model list cannot replace the selected channel models', async () => {
  const waiting = deferred();
  get = path => path.includes('/1/') ? waiting.promise : Promise.resolve({ models: [{ id: 22, model_id: 'b-chat', enabled: 1 }] });
  const o = instance(ChannelsView, { selectedId: 1, channels: [{ id: 2, models_count: 0, models_enabled: 0 }] });
  const old = o.loadModels(1);
  o.selectedId = 2; await o.loadModels(2);
  waiting.resolve({ models: [{ id: 11, model_id: 'a-chat' }] }); await old;
  assert.equal(o.models[0].id, 22);
  assert.equal(o.channels[0].models_enabled, 1);
  o.dispose();
});

await test('late key verification cannot create a diff for another channel', async () => {
  const waiting = deferred(); post = () => waiting.promise;
  const o = instance(ChannelsView, { selectedId: 1 }); o.load = async () => {};
  const verifying = o.verifyKey(7, 'models'); await o.select(2);
  waiting.resolve({ ok: true, models: ['a-chat'] }); await verifying;
  assert.equal(o.diff, null);
  o.dispose();
});

await test('chat test skips embeddings/images and permits an explicit enabled chat model', async () => {
  const o = instance(ChannelsView, { models: [
    { model_id: 'BAAI/bge-m3', mtype: 'embedding', enabled: 1 },
    { model_id: 'dall-e-3', mtype: 'image', enabled: 1 },
    { model_id: 'gpt-4o', mtype: 'chat', enabled: 1 },
    { model_id: 'qwen-vl', mtype: 'vision', enabled: 1 },
  ] });
  let chosen; o.verifyKey = async (...args) => { chosen = args; };
  await o.chatTest(7); assert.equal(chosen[2], 'gpt-4o');
  promptAnswer = 'qwen-vl'; await o.chatTest(7); assert.equal(chosen[2], 'qwen-vl');
  promptAnswer = null; chosen = null; await o.chatTest(7); assert.equal(chosen, null);
  o.dispose();
});

await test('model paste accepts supported data and never turns empty JSON into model IDs', () => {
  for (const input of ['[]', '{"data":[]}', '{}', 'null', '["  "]']) assert.deepEqual(plain(parseModelText(input)), []);
  assert.deepEqual(plain(parseModelText('[" a ", "a", "", " b "]')), ['a', 'b']);
  assert.deepEqual(plain(parseModelText('{"data":[{"id":" gpt-4o "}]}')), ['gpt-4o']);
  assert.deepEqual(plain(parseModelText('a\nb\na\n')), ['a', 'b']);
});

await test('quick add clears old validation and ignores responses for changed inputs', async () => {
  const waiting = deferred(); post = () => waiting.promise;
  const o = instance(QuickAddView, { form: { name: 'A', base_url: 'https://a.invalid', key: 'a', type: 'gateway' } });
  const verifying = o.verify(); o.form.key = 'b';
  waiting.resolve({ ok: true, models: ['a-chat'] }); await verifying;
  assert.equal(o.verifyResult, null);
  post = async () => ({ ok: true, models: ['b-chat'] }); await o.verify();
  assert.equal(o.verifyResult.ok, true);
  o.form.type = 'openai'; assert.equal(o.verifyResult, null);
  o.dispose();
});

await test('deleting the selected template selects a remaining template', async () => {
  get = async path => path === '/api/channels' ? { channels: [{ id: 1, keys: [{ id: 7 }] }] } : { templates: [{ id: 1 }], placeholders: [] };
  const o = instance(ExportView, { selChannel: 1, selKey: 7, selTemplate: 99, result: 'old config' });
  await o.removeTpl({ id: 99, name: 'custom' });
  assert.equal(o.selTemplate, 1); assert.equal(o.result, '');
  o.dispose();
});

await test('export ignores responses for changed keys and keeps current filename with current data', async () => {
  const waiting = deferred(); post = () => waiting.promise;
  const o = instance(ExportView, { selChannel: 1, selKey: 7, selTemplate: 1,
    channels: [{ id: 1, keys: [{ id: 7, name: 'A' }, { id: 8, name: 'B' }] }], templates: [{ id: 1, client_type: 'generic' }] });
  const rendering = o.render(); o.selKey = 8;
  waiting.resolve({ rendered: 'secret-a', is_json: true }); await rendering;
  assert.equal(o.result, '');
  post = async () => ({ rendered: '{"key":"b"}', is_json: true }); await o.render();
  assert.equal(o.resultName, 'generic-B.json');
  assert.equal(o.result, '{"key":"b"}');
  o.dispose();
});

await test('plaintext overwrite reports overwrite success without undefined merge counts', async () => {
  post = async () => ({ ok: true, mode: 'overwrite', relogin: false });
  const o = instance(SettingsView, { importMode: 'overwrite', confirmOverwrite: true }); o.load = async () => {};
  await o.doImport();
  assert.deepEqual(notices, ['覆盖导入完成']);
  assert.equal(o.confirmOverwrite, false); assert.equal(o.importBusy, false);
  o.dispose();
});

await test('backup file selection cannot reuse an old confirmation or a late file parse', async () => {
  const waiting = deferred();
  const o = instance(SettingsView, { confirmOverwrite: true, importPw: 'old-password' });
  const picking = o.pickFile({ target: { files: [{ name: 'a.json', text: () => waiting.promise }] } });
  assert.equal(o.confirmOverwrite, false); assert.equal(o.importPw, '');
  await o.pickFile({ target: { files: [{ name: 'b.json', text: async () => '{"format":"keyfolio-backup","data":{"id":"b"}}' }] } });
  waiting.resolve('{"format":"keyfolio-backup","data":{"id":"a"}}'); await picking;
  assert.equal(o.importFile.name, 'b.json'); assert.equal(o.importData.data.id, 'b');
  o.dispose();
});

await test('expired unlock returns to login, while a wrong password keeps a valid session on the lock screen', async () => {
  let authenticated = false;
  const { api: actualApi } = await load('js/api.js', ['api'], { fetch: async path => path === '/api/auth/status'
    ? new Response(JSON.stringify({ authenticated }), { status: 200 })
    : new Response(JSON.stringify({ detail: 'authentication failed' }), { status: 401 }) });
  await assert.rejects(actualApi.post('/api/auth/unlock', { password: 'correct' }));
  assert.deepEqual(events, ['kf:unauthorized']);
  events.length = 0; authenticated = true;
  await assert.rejects(actualApi.post('/api/auth/unlock', { password: 'wrong' }));
  assert.deepEqual(events, []);
});

await test('expiry is marked expired immediately after the deadline, including the first day', async () => {
  class FixedDate extends Date { static now() { return new Date('2026-11-15T12:00:00Z').getTime(); } }
  const { expiryInfo } = await load('js/api.js', ['expiryInfo'], { Date: FixedDate });
  assert.equal(expiryInfo('2026-11-15T11:59:59Z').cls, 'fail');
  assert.equal(expiryInfo('2026-11-15T12:00:01Z').cls, 'warn');
});

await test('closing a trend discards a pending response and cannot reopen the modal', async () => {
  const waiting = deferred(); get = () => waiting.promise;
  const o = instance(DashboardView, { trendKeyId: 7 });
  const loading = o.loadTrend(); o.closeTrend();
  waiting.resolve({ ok: true, key: { id: 7 }, records: [] }); await loading;
  assert.equal(o.trend, null); assert.equal(o.trendKeyId, null);
  o.dispose();
});

await test('the latest trend range wins even if an older request finishes later', async () => {
  const waiting = deferred();
  get = path => path.endsWith('days=90') ? waiting.promise : Promise.resolve({ ok: true, key: { id: 7 }, records: [], marker: 7 });
  const o = instance(DashboardView, { trendKeyId: 7 }); o.drawChart = () => {};
  const older = o.loadTrend(); o.trendDays = 7; await o.loadTrend();
  waiting.resolve({ ok: true, key: { id: 7 }, records: [], marker: 90 }); await older;
  assert.equal(o.trend.marker, 7); o.dispose();
});

await test('trend separates historical currencies and releases the chart for empty ranges and unmount', () => {
  canvas = {}; chartConfigs = []; destroyed = 0;
  const o = instance(DashboardView, { trend: { key: { name: 'A', currency: 'USD' }, records: [
    { balance: 100, currency: 'CNY', recorded_at: '2026-11-14' },
    { balance: 50, currency: 'USD', recorded_at: '2026-11-15' },
  ] } });
  o.drawChart();
  const config = chartConfigs[0];
  assert.deepEqual(plain(config.data.datasets.map(d => [d.label, d.data])), [['CNY', [100, null]], ['USD', [null, 50]]]);
  assert.equal(config.options.plugins.tooltip.callbacks.label({ parsed: { y: 100 }, dataset: config.data.datasets[0] }), '100.00 CNY');
  o.trend.records = []; canvas = null; o.drawChart(); assert.equal(destroyed, 1); assert.equal(o.chart, null);
  canvas = {}; o.trend.records = [{ balance: 50, currency: 'USD' }]; o.drawChart(); o.dispose();
  assert.equal(destroyed, 2); assert.equal(o.chart, null);
});
