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
const metadata = {
  channel_types: [{ id: 'gateway', label: '网关' }, { id: 'openai', label: 'OpenAI' }],
  providers: [], model_types: ['chat', 'embedding'],
};
function channel(id, extra = {}) {
  return { id, name: `Channel ${id}`, type: 'gateway', base_url: `https://${id}.invalid`,
    grp: '', keys: [], models_count: 0, models_enabled: 0, ...extra };
}
function backupFile(name, data = {}, encrypted = false) {
  return { name, size: 100, text: async () => JSON.stringify({ format: 'keyfolio-backup', encrypted, data }) };
}

await test('dashboard loads totals, channels and type filters in one request', async () => {
  const response = {
    summary: { balance_by_currency: { CNY: 20 }, shared_balance_accounts: 1 },
    channels: [channel(1, { keys: [
      { id: 7, name: 'A', balance: 20, balance_account: 'main' },
      { id: 8, name: 'B', balance: 20, balance_account: 'main' },
    ] })],
    channel_types: metadata.channel_types,
  };
  get = async path => { assert.equal(path, '/api/dashboard'); return response; };
  const o = instance(DashboardView);
  await DashboardView.created.call(o);
  assert.deepEqual(calls, [['get', '/api/dashboard']]);
  assert.deepEqual(plain(o.channelTypes), metadata.channel_types);
  assert.deepEqual(plain(o.balanceEntries), [{ cur: 'CNY', value: '20.00' }]);
  assert.equal(o.summary.shared_balance_accounts, 1);
  assert.equal(o.rows.length, 2);
  assert.equal(o.rows[0].key.balance_account, 'main');
  o.fType = 'openai'; assert.equal(o.rows.length, 0);
  assert.match(DashboardView.template, /v-if="summary.shared_balance_accounts > 0"[^>]*>共享账户按最新余额计一次/);
  assert.match(DashboardView.template, /v-if="r.key.balance_account">余额账户：{{ r.key.balance_account }}/);
  o.dispose();
});

await test('quick add loads channel types from metadata without reading channels', async () => {
  get = async path => { assert.equal(path, '/api/metadata'); return metadata; };
  const o = instance(QuickAddView);
  await QuickAddView.created.call(o);
  assert.deepEqual(calls, [['get', '/api/metadata']]);
  assert.deepEqual(plain(o.channelTypes), metadata.channel_types);
  o.dispose();
});

await test('channel initialization loads the list once and switching only loads the target models', async () => {
  const channels = [channel(1), channel(2)];
  get = async path => path === '/api/channels' ? { channels, ...metadata }
    : { models: [{ id: path.includes('/1/') ? 11 : 22, model_id: 'chat', enabled: 1 }] };
  const o = instance(ChannelsView);
  const select = o.select; let selecting;
  o.select = id => (selecting = select(id));
  await ChannelsView.created.call(o); await selecting;
  assert.deepEqual(calls, [['get', '/api/channels'], ['get', '/api/channels/1/models']]);
  assert.equal(o.detail, o.channels[0]);
  assert.equal(o.models[0].id, 11);
  o.diff = { channel_id: 1, added: ['old'] }; o.revealed = { 7: 'secret-a' }; o.modelQuery = 'old';
  await o.select(2);
  assert.deepEqual(calls.slice(2), [['get', '/api/channels/2/models']]);
  assert.equal(o.detail, o.channels[1]); assert.equal(o.detailOpen, true);
  assert.equal(o.models[0].id, 22);
  assert.equal(o.diff, null); assert.deepEqual(plain(o.revealed), {}); assert.equal(o.modelQuery, '');
  o.dispose();
});

await test('manual refresh updates channel details and models while keeping selection and filters', async () => {
  const channels = [channel(1), channel(2, { name: 'Updated elsewhere', keys: [{ id: 8, balance_account: 'main' }] })];
  get = async path => path === '/api/channels' ? { channels, ...metadata }
    : { models: [{ id: 22, model_id: 'b-chat', enabled: 1 }] };
  const o = instance(ChannelsView, { channels: [channel(1), channel(2)], selectedId: 2,
    detail: channel(2), detailOpen: true, filter: 'elsewhere', modelQuery: 'chat' });
  assert.match(ChannelsView.template, /<button[^>]*@click="load\(\)"[^>]*>\s*<k-icon name="refresh"><\/k-icon>刷新/);
  await o.load();
  assert.deepEqual(calls, [['get', '/api/channels'], ['get', '/api/channels/2/models']]);
  assert.equal(o.selectedId, 2); assert.equal(o.detail, o.channels[1]); assert.equal(o.detailOpen, true);
  assert.equal(o.detail.name, 'Updated elsewhere'); assert.equal(o.detail.keys[0].balance_account, 'main');
  assert.equal(o.filter, 'elsewhere'); assert.equal(o.modelQuery, 'chat');
  assert.equal(o.models[0].id, 22); assert.equal(o.detail.models_enabled, 1);
  o.dispose();
});

await test('refresh follows the current selection and older model responses cannot replace it', async () => {
  const refreshing = deferred(), olderModels = deferred();
  let modelRequests = 0;
  get = path => {
    if (path === '/api/channels') return refreshing.promise;
    assert.equal(path, '/api/channels/2/models');
    return ++modelRequests === 1 ? olderModels.promise
      : Promise.resolve({ models: [{ id: 23, model_id: 'new-b', enabled: 1 }] });
  };
  const o = instance(ChannelsView, { channels: [channel(1), channel(2)], selectedId: 1, detail: channel(1) });
  const refresh = o.load();
  const switching = o.select(2);
  refreshing.resolve({ channels: [channel(1), channel(2, { name: 'New B' })], ...metadata }); await refresh;
  olderModels.resolve({ models: [{ id: 22, model_id: 'old-b', enabled: 0 }] }); await switching;
  assert.equal(o.selectedId, 2); assert.equal(o.detail.name, 'New B'); assert.equal(o.models[0].id, 23);
  assert.equal(calls.filter(c => c[1] === '/api/channels').length, 1);
  o.dispose();
});

await test('older channel refresh cannot overwrite a newer refresh', async () => {
  const waiting = deferred(); let listRequests = 0;
  get = async path => path === '/api/channels'
    ? (++listRequests === 1 ? waiting.promise : { channels: [channel(1, { name: 'New' })], ...metadata })
    : { models: [{ id: 11, model_id: 'new-chat', enabled: 1 }] };
  const o = instance(ChannelsView, { selectedId: 1 });
  const older = o.load(); await o.load();
  waiting.resolve({ channels: [channel(1, { name: 'Old' })], ...metadata }); await older;
  assert.equal(o.detail.name, 'New'); assert.equal(o.models[0].model_id, 'new-chat');
  assert.equal(calls.filter(c => c[1].endsWith('/models')).length, 1);
  o.dispose();
});

await test('new keys default to independent balances and submit an optional account', async () => {
  let reloads = 0;
  const o = instance(ChannelsView, { selectedId: 1, detail: channel(1) });
  o.load = async () => { reloads++; };
  for (const account of ['', 'main']) {
    o.openKeyForm(null);
    assert.equal(o.keyForm.balance_account, '');
    o.keyForm.value = 'synthetic-key'; o.keyForm.balance_account = account;
    await o.saveKey();
    assert.equal(calls.at(-1)[0], 'post'); assert.equal(calls.at(-1)[1], '/api/channels/1/keys');
    assert.equal(calls.at(-1)[2].balance_account, account); assert.equal(o.keyForm, null);
  }
  assert.equal(reloads, 2);
  assert.match(ChannelsView.template, /<input v-model="keyForm.balance_account"/);
  assert.match(ChannelsView.template, /v-if="k.balance_account">余额账户：{{ k.balance_account }}/);
  o.dispose();
});

await test('editing a key keeps or clears its balance account without changing the secret', async () => {
  let reloads = 0;
  const o = instance(ChannelsView); o.load = async () => { reloads++; };
  const key = { id: 7, name: 'A', balance_account: 'main', enabled: 1 };
  for (const account of ['main', '']) {
    o.openKeyForm(key);
    assert.equal(o.keyForm.balance_account, 'main');
    o.keyForm.balance_account = account;
    await o.saveKey();
    assert.equal(calls.at(-1)[0], 'put'); assert.equal(calls.at(-1)[1], '/api/keys/7');
    assert.equal(calls.at(-1)[2].balance_account, account);
    assert.equal(Object.hasOwn(calls.at(-1)[2], 'value'), false);
  }
  o.openKeyForm({ id: 8, name: 'Legacy' }); assert.equal(o.keyForm.balance_account, '');
  assert.equal(reloads, 2);
  o.dispose();
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
  const waiting = deferred(); post = () => waiting.promise; get = async () => ({ models: [] });
  const o = instance(ChannelsView, { selectedId: 1, channels: [channel(1), channel(2)] });
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
  const o = instance(ChannelsView, { selectedId: 1, channels: [channel(1), channel(2)] });
  const old = o.select(1);
  await o.select(2);
  waiting.resolve({ models: [{ id: 11, model_id: 'a-chat' }] }); await old;
  assert.equal(o.models[0].id, 22);
  assert.equal(o.channels[1].models_enabled, 1);
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

await test('backup settings restoration is offered only for settings or encrypted files and starts unchecked', async () => {
  const o = instance(SettingsView);
  assert.equal(o.restoreSettings, false); assert.equal(o.canRestoreSettings, false);
  assert.match(SettingsView.template, /v-if="canRestoreSettings"/);
  assert.match(SettingsView.template, /type="checkbox" v-model="restoreSettings"/);
  for (const [file, available] of [
    [backupFile('old.json'), false],
    [backupFile('settings.json', { settings: { scheduler: { enabled: true } } }), true],
    [backupFile('encrypted.json', {}, true), true],
  ]) {
    o.restoreSettings = true;
    await o.pickFile({ target: { files: [file] } });
    assert.equal(o.canRestoreSettings, available); assert.equal(o.restoreSettings, false);
  }
  o.restoreSettings = true;
  await o.pickFile({ target: { files: [] } });
  assert.equal(o.restoreSettings, false); assert.equal(o.canRestoreSettings, false); assert.equal(o.importFile, null);
  o.dispose();
});

await test('merge restoration requires opt-in, refreshes the scheduler and clears the completed import', async () => {
  const scheduler = { enabled: true, balance_interval_hours: 3, model_interval_hours: 6 };
  get = async path => { assert.equal(path, '/api/settings'); return { scheduler }; };
  post = async (_path, body) => ({ mode: 'merge', channels: 1, keys: 2, models: 3, settings_restored: body.restore_settings });
  for (const restore of [false, true]) {
    const o = instance(SettingsView);
    await o.pickFile({ target: { files: [backupFile('settings.json', { settings: { scheduler } })] } });
    if (restore) o.restoreSettings = true;
    await o.doImport();
    const request = calls.filter(c => c[0] === 'post').at(-1);
    assert.equal(request[1], '/api/backup/import'); assert.equal(request[2].restore_settings, restore);
    assert.deepEqual(plain(o.sched), scheduler);
    assert.equal(o.restoreSettings, false); assert.equal(o.importData, null); assert.equal(o.importFile, null);
    assert.equal(o.importBusy, false);
    assert.equal(notices.at(-1).includes('定时任务设置已恢复'), restore);
    o.dispose();
  }
  assert.deepEqual(calls.map(c => c[0]), ['post', 'get', 'post', 'get']);
});

await test('pending import is sent once and cannot reset a newly selected file or its options', async () => {
  const waiting = deferred(); post = () => waiting.promise;
  get = async () => ({ scheduler: { enabled: false } });
  const o = instance(SettingsView);
  await o.pickFile({ target: { files: [backupFile('a.json', { settings: {} })] } });
  o.restoreSettings = true;
  const importing = o.doImport(); await o.doImport();
  assert.equal(calls.length, 1); assert.equal(calls[0][2].restore_settings, true); assert.equal(o.importBusy, true);
  await o.pickFile({ target: { files: [backupFile('b.json', {}, true)] } });
  assert.equal(o.restoreSettings, false);
  o.restoreSettings = true; o.importPw = 'new-password'; o.confirmOverwrite = true;
  waiting.resolve({ mode: 'merge', channels: 0, keys: 0, models: 0, settings_restored: true }); await importing;
  assert.equal(o.importFile.name, 'b.json'); assert.equal(o.restoreSettings, true);
  assert.equal(o.importPw, 'new-password'); assert.equal(o.confirmOverwrite, true); assert.equal(o.importBusy, false);
  o.dispose();
});

await test('encrypted overwrite reports restored settings and requests login without a settings fetch', async () => {
  post = async () => ({ mode: 'overwrite', relogin: true, settings_restored: true });
  const o = instance(SettingsView, { importMode: 'overwrite' });
  await o.pickFile({ target: { files: [backupFile('encrypted.json', {}, true)] } });
  o.restoreSettings = true; o.confirmOverwrite = true; o.importPw = 'synthetic-password';
  await o.doImport();
  assert.equal(calls.length, 1); assert.equal(calls[0][2].restore_settings, true);
  assert.deepEqual(events, ['kf:unauthorized']); assert.match(notices[0], /定时任务设置已恢复.*需要重新登录/);
  assert.equal(o.restoreSettings, false); assert.equal(o.importBusy, false); assert.equal(o.importFile, null);
  o.dispose();
});

await test('plaintext overwrite reports overwrite success without undefined merge counts', async () => {
  post = async () => ({ ok: true, mode: 'overwrite', relogin: false });
  const o = instance(SettingsView, { importMode: 'overwrite', confirmOverwrite: true });
  let reloads = 0; o.load = async () => { reloads++; };
  await o.doImport();
  assert.deepEqual(notices, ['覆盖导入完成']);
  assert.equal(calls[0][2].restore_settings, false); assert.equal(reloads, 1);
  assert.equal(o.confirmOverwrite, false); assert.equal(o.importBusy, false);
  o.dispose();
});

await test('backup file selection cannot reuse old confirmations or a late file parse', async () => {
  const waiting = deferred();
  const o = instance(SettingsView, { confirmOverwrite: true, restoreSettings: true, importPw: 'old-password' });
  const picking = o.pickFile({ target: { files: [{ name: 'a.json', text: () => waiting.promise }] } });
  assert.equal(o.confirmOverwrite, false); assert.equal(o.importPw, ''); assert.equal(o.restoreSettings, false);
  await o.pickFile({ target: { files: [backupFile('b.json', { id: 'b', settings: {} })] } });
  o.restoreSettings = true;
  waiting.resolve('{"format":"keyfolio-backup","data":{"id":"a"}}'); await picking;
  assert.equal(o.importFile.name, 'b.json'); assert.equal(o.importData.data.id, 'b'); assert.equal(o.restoreSettings, true);
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
