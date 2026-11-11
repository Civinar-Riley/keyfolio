/** 渠道与 Key 管理：列表 + 详情 + 模型同步 + 余额操作。 */
import { api, copyText, expiryInfo, fmtBalance, fmtTime } from "../api.js";

const emptyChannel = { name: "", type: "gateway", base_url: "", console_url: "", grp: "", notes: "" };

export const ChannelsView = {
  template: `
  <div>
    <div class="split">
      <!-- 左列：渠道索引 -->
      <aside class="index-col" v-if="!isMobile || !detailOpen">
        <div class="index-tools">
          <button class="btn primary block" @click="openChannelForm(null)">
            <k-icon name="plus"></k-icon>新渠道
          </button>
          <div class="search-box">
            <k-icon name="search"></k-icon>
            <input v-model="filter" placeholder="搜索名称 / URL / 分组" aria-label="搜索渠道">
          </div>
        </div>
        <div class="chan-list">
          <button type="button" class="chan-item" v-for="c in filtered" :key="c.id"
                  :class="{active: c.id===selectedId}" @click="select(c.id)">
            <span class="chan-top">
              <span class="chan-name">{{ c.name }}</span>
              <span class="badge acc">{{ typeLabel(c.type) }}</span>
              <span class="badge" v-if="c.grp">{{ c.grp }}</span>
            </span>
            <span class="chan-url">{{ c.base_url }}</span>
            <span class="chan-meta">
              <span>{{ c.keys.length }} Key</span>
              <span class="sep">/</span>
              <span>{{ c.models_enabled || 0 }}/{{ c.models_count }} 模型</span>
              <span class="badge dot" :class="c.enabled ? 'ok' : 'warn'">{{ c.enabled ? "启用" : "停用" }}</span>
            </span>
          </button>
          <div class="chan-empty" v-if="!filtered.length">
            还没有渠道，点上方「新渠道」开始
          </div>
        </div>
      </aside>

      <!-- 右列：渠道详情 -->
      <section v-if="detail">
        <header class="detail-head">
          <div class="detail-title">
            <h2>{{ detail.name }}</h2>
            <div class="detail-badges">
              <span class="badge acc">{{ typeLabel(detail.type) }}</span>
              <span class="badge" v-if="detail.grp">{{ detail.grp }}</span>
              <span class="badge dot" :class="detail.enabled ? 'ok' : 'warn'">{{ detail.enabled ? "启用" : "停用" }}</span>
            </div>
            <div class="mono detail-url">{{ detail.base_url }}</div>
            <div class="detail-notes" v-if="detail.notes">{{ detail.notes }}</div>
          </div>
          <div class="detail-actions">
            <button class="btn sm" v-if="isMobile" @click="detailOpen=false">
              <k-icon name="arrow-left"></k-icon>返回
            </button>
            <button class="btn sm" @click="openChannelForm(detail)">
              <k-icon name="edit"></k-icon>编辑
            </button>
            <a class="btn sm" v-if="detail.console_url" :href="detail.console_url" target="_blank" rel="noopener">
              <k-icon name="external"></k-icon>控制台
            </a>
            <button class="btn sm danger" @click="removeChannel(detail)">
              <k-icon name="trash"></k-icon>删除
            </button>
          </div>
        </header>

        <section class="sheet">
          <header class="sheet-head">
            <div>
              <h2>Keys <span class="count">{{ detail.keys.length }}</span></h2>
              <p>Key 值加密保存在本机</p>
            </div>
            <button class="btn sm primary" @click="openKeyForm(null)">
              <k-icon name="plus"></k-icon>添加 Key
            </button>
          </header>
          <div class="sheet-body" v-if="detail.keys.length">
            <div class="key-item" v-for="k in detail.keys" :key="k.id">
              <div class="key-line">
                <div class="key-info">
                  <div class="key-name">
                    {{ k.name }}
                    <span class="badge" v-if="!k.enabled">停用</span>
                    <span class="badge" :class="expiryOf(k).cls" v-if="expiryOf(k)">{{ expiryOf(k).text }}</span>
                    <span class="badge dot" :class="k.last_check==='ok' ? 'ok' : (k.last_check==='fail' ? 'fail' : '')"
                          v-if="k.last_check" :title="k.last_check_msg">
                      {{ k.last_check==='ok' ? "可用" : "异常" }}
                    </span>
                  </div>
                  <div class="key-secret mono">
                    {{ revealed[k.id] || k.value_masked }}
                    <a href="#" @click.prevent="toggleReveal(k)">{{ revealed[k.id] ? "隐藏" : "显示" }}</a>
                  </div>
                  <div class="key-msg" v-if="k.last_check_msg">{{ k.last_check_msg }}</div>
                </div>
                <div class="key-amount">
                  <div class="amt">{{ fmtBalance(k) }}</div>
                  <div class="hint">{{ fmtTime(k.balance_updated_at) }}</div>
                </div>
              </div>
              <div class="key-actions">
                <button class="btn sm ok" @click="copyConfig(k.id)"><k-icon name="copy"></k-icon>复制配置</button>
                <button class="btn sm" @click="verifyKey(k.id, 'models')"><k-icon name="refresh"></k-icon>测 Key</button>
                <button class="btn sm" @click="chatTest(k.id)">测对话</button>
                <button class="btn sm" @click="checkBalance(k.id)">查余额</button>
                <button class="btn sm" @click="openBalanceManual(k)">填余额</button>
                <button class="btn sm" @click="openKeyForm(k)">编辑</button>
                <button class="btn sm danger" @click="removeKey(k)" aria-label="删除 Key"><k-icon name="trash"></k-icon></button>
              </div>
            </div>
          </div>
          <div class="empty" v-else style="padding:36px 20px">
            <p style="margin:0">还没有 Key，点「添加 Key」录入。</p>
          </div>
          <footer class="sheet-foot" v-if="detail.keys.length">
            <div class="key-tools">
              <button class="btn sm" @click="verifyAll()">全部测 Key</button>
              <button class="btn sm" @click="checkAllBalance()">全部查余额</button>
            </div>
          </footer>
        </section>

        <section class="sheet">
          <header class="sheet-head">
            <div>
              <h2>模型 <span class="count">{{ enabledModelCount }} / {{ models.length }}</span></h2>
              <p>启用的模型会出现在导出配置里</p>
            </div>
            <div class="btn-row">
              <button class="btn sm primary" @click="fetchModels()"><k-icon name="refresh"></k-icon>拉取模型</button>
              <button class="btn sm" @click="pasteOpen=true">粘贴 JSON</button>
              <button class="btn sm" @click="modelFormOpen=true">手动添加</button>
            </div>
          </header>
          <div class="sheet-body">
            <div class="search-box" v-if="models.length" style="max-width:280px; margin-bottom:12px">
              <k-icon name="search"></k-icon>
              <input v-model="modelQuery" placeholder="筛选模型 ID" aria-label="筛选模型">
            </div>
            <table class="list" v-if="filteredModels.length">
              <thead><tr><th>模型 ID</th><th>类型</th><th>状态</th><th></th></tr></thead>
              <tbody>
                <tr v-for="m in filteredModels" :key="m.id">
                  <td class="mono">{{ m.model_id }}</td>
                  <td>
                    <select :value="m.mtype" @change="updateModel(m, {mtype: $event.target.value})">
                      <option v-for="t in modelTypes" :key="t" :value="t">{{ t }}</option>
                    </select>
                  </td>
                  <td><span class="badge dot" :class="m.enabled ? 'ok' : 'warn'">{{ m.enabled ? "启用" : "停用" }}</span></td>
                  <td>
                    <div class="btn-row" style="justify-content:flex-end">
                      <button class="btn sm" @click="updateModel(m, {enabled: !m.enabled})">{{ m.enabled ? "停用" : "启用" }}</button>
                      <button class="btn sm danger" @click="deleteModel(m)">删</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="empty" v-else-if="models.length" style="padding:26px 10px">
              <p style="margin:0">没有匹配的模型</p>
            </div>
            <div class="empty" v-else style="padding:32px 10px">
              <p style="margin:0 0 4px">还没有模型</p>
              <p style="margin:0; font-size:11.5px">用「拉取模型」从平台同步，或手动添加。</p>
            </div>
          </div>
        </section>
      </section>

      <section class="detail-empty" v-else-if="!isMobile">
        <k-icon name="channels"></k-icon>
        <p>从左侧选择一个渠道</p>
      </section>
    </div>

    <!-- 渠道表单 -->
    <div class="modal-mask" v-if="chanForm" @click.self="chanForm=null">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ chanForm.id ? "编辑渠道" : "新渠道" }}</h3>
          <button class="icon-btn" @click="chanForm=null" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <label class="field" v-if="providers.length">预设（可选）
          <select v-model="preset" @change="applyPreset">
            <option value="">自定义</option>
            <option v-for="p in providers" :key="p.type + '|' + p.base_url" :value="p.type + '|' + p.base_url">{{ p.name }}</option>
          </select>
        </label>
        <div class="form-grid">
          <label class="field">名称 <input v-model="chanForm.name" placeholder="如 DeepSeek 官方"></label>
          <label class="field">类型
            <select v-model="chanForm.type">
              <option v-for="t in channelTypes" :key="t.id" :value="t.id">{{ t.label }}</option>
            </select>
          </label>
          <label class="field span-2">Base URL <input v-model="chanForm.base_url" placeholder="https://api.example.com"></label>
          <label class="field">控制台地址 <input v-model="chanForm.console_url" placeholder="可选，快捷打开"></label>
          <label class="field">分组 <input v-model="chanForm.grp" placeholder="可选"></label>
          <label class="field span-2">备注 <textarea v-model="chanForm.notes"></textarea></label>
        </div>
        <label class="field" style="display:flex; align-items:center; gap:8px">
          <input type="checkbox" v-model="chanForm.enabled" style="width:auto; margin:0"> 启用
        </label>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="saveChannel">保存</button>
          <button class="btn" @click="chanForm=null">取消</button>
        </div>
      </div>
    </div>

    <!-- Key 表单 -->
    <div class="modal-mask" v-if="keyForm" @click.self="keyForm=null">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ keyForm.id ? "编辑 Key" : "添加 Key" }}</h3>
          <button class="icon-btn" @click="keyForm=null" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <div class="form-grid">
          <label class="field span-2">名称 <input v-model="keyForm.name" placeholder="如 主 Key"></label>
          <label class="field span-2">Key 值
            <textarea v-model="keyForm.value" :placeholder="keyForm.id ? '留空则不修改' : 'sk-...'" style="min-height:70px"></textarea>
          </label>
          <label class="field">到期日（可选） <input v-model="keyForm.expires_at" placeholder="如 2026-12-31"></label>
          <label class="field">备注 <input v-model="keyForm.notes"></label>
        </div>
        <label class="field" style="display:flex; align-items:center; gap:8px">
          <input type="checkbox" v-model="keyForm.enabled" style="width:auto; margin:0"> 启用
        </label>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="saveKey">保存</button>
          <button class="btn" @click="keyForm=null">取消</button>
        </div>
      </div>
    </div>

    <!-- 手动余额 -->
    <div class="modal-mask" v-if="balForm" @click.self="balForm=null">
      <div class="modal">
        <div class="modal-head">
          <h3>手动填写余额 · {{ balKeyName }}</h3>
          <button class="icon-btn" @click="balForm=null" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <div class="form-grid">
          <label class="field">余额 <input type="number" step="any" v-model="balForm.balance"></label>
          <label class="field">币种 <input v-model="balForm.currency" placeholder="CNY / USD"></label>
          <label class="field span-2">到期日 <input v-model="balForm.expires_at" placeholder="可选，如 2026-12-31"></label>
        </div>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="saveBalance">保存</button>
          <button class="btn" @click="balForm=null">取消</button>
        </div>
      </div>
    </div>

    <!-- 粘贴 JSON -->
    <div class="modal-mask" v-if="pasteOpen" @click.self="pasteOpen=false">
      <div class="modal">
        <div class="modal-head">
          <h3>粘贴模型列表</h3>
          <button class="icon-btn" @click="pasteOpen=false" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <p class="hint" style="margin-bottom:12px">支持字符串数组、OpenAI 返回体（data[].id）、每行一个。</p>
        <label class="field"><textarea v-model="pasteText" style="min-height:140px"></textarea></label>
        <div v-if="pasteIds.length" class="hint" style="margin-bottom:8px">解析出 {{ pasteIds.length }} 个模型 ID</div>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" :disabled="!pasteIds.length" @click="addParsed">全部添加</button>
          <button class="btn" @click="pasteOpen=false">取消</button>
        </div>
      </div>
    </div>

    <!-- 手动添加模型 -->
    <div class="modal-mask" v-if="modelFormOpen" @click.self="modelFormOpen=false">
      <div class="modal">
        <div class="modal-head">
          <h3>手动添加模型</h3>
          <button class="icon-btn" @click="modelFormOpen=false" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <label class="field">模型 ID <input v-model="newModelId" placeholder="如 gpt-4o-mini"></label>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" :disabled="!newModelId" @click="addManualModel">添加</button>
          <button class="btn" @click="modelFormOpen=false">取消</button>
        </div>
      </div>
    </div>

    <!-- 同步 diff 确认 -->
    <div class="modal-mask" v-if="diff" @click.self="diff=null">
      <div class="modal">
        <div class="modal-head">
          <h3>同步模型 · 远端 {{ diff.remote_count }} 个</h3>
          <button class="icon-btn" @click="diff=null" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <template v-if="diff.added.length">
          <h3 class="diff-add">新增（{{ diff.added.length }}）</h3>
          <ul class="diff-list">
            <li v-for="m in diff.added" :key="'a'+m">
              <input type="checkbox" v-model="diffChecked" :value="m" style="width:auto"> {{ m }}
            </li>
          </ul>
        </template>
        <template v-if="diff.revived && diff.revived.length">
          <h3 class="diff-add">重新出现（{{ diff.revived.length }}）</h3>
          <ul class="diff-list">
            <li v-for="m in diff.revived" :key="'r'+m">
              <input type="checkbox" v-model="revivedChecked" :value="m" style="width:auto"> {{ m }}
            </li>
          </ul>
        </template>
        <template v-if="diff.removed.length">
          <h3 class="diff-del">远端已消失（{{ diff.removed.length }}）</h3>
          <label class="field">处理方式
            <select v-model="removedAction">
              <option value="disable">标记停用（保留记录）</option>
              <option value="delete">直接删除</option>
            </select>
          </label>
        </template>
        <p class="hint" v-if="!diff.added.length && !diff.removed.length && !(diff.revived && diff.revived.length)">没有差异，本地已是最新。</p>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" :disabled="!diff.added.length && !diff.removed.length && !revivedChecked.length"
                  @click="applySync">应用同步</button>
          <button class="btn" @click="diff=null">取消</button>
        </div>
      </div>
    </div>
  </div>`,
  data: () => ({
    channels: [], channelTypes: [], providers: [], modelTypes: [],
    filter: "", selectedId: null, detail: null, models: [],
    revealed: {},
    isMobile: window.matchMedia("(max-width: 767px)").matches,
    detailOpen: false,
    chanForm: null, preset: "", keyForm: null,
    balForm: null, balKeyName: "",
    pasteOpen: false, pasteText: "", pasteIds: [],
    modelFormOpen: false, newModelId: "", modelQuery: "",
    diff: null, diffChecked: [], revivedChecked: [], removedAction: "disable",
  }),
  computed: {
    filtered() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.channels;
      return this.channels.filter(c =>
        [c.name, c.base_url, c.grp, c.notes].some(s => (s || "").toLowerCase().includes(q)));
    },
    filteredModels() {
      const q = this.modelQuery.trim().toLowerCase();
      if (!q) return this.models;
      return this.models.filter(m => (m.model_id || "").toLowerCase().includes(q));
    },
    enabledModelCount() { return this.models.filter(m => m.enabled).length; },
    enabledModels() { return this.models.filter(m => m.enabled).map(m => m.model_id); },
  },
  async created() {
    window.matchMedia("(max-width: 767px)").addEventListener("change", e => { this.isMobile = e.matches; });
    await this.load();
    if (!this.isMobile && this.channels.length && !this.selectedId) this.select(this.channels[0].id);
  },
  methods: {
    fmtBalance, fmtTime,
    typeLabel(id) {
      const t = this.channelTypes.find(t => t.id === id);
      return t ? t.label.split("（")[0] : id;
    },
    expiryOf(k) { return expiryInfo(k.expires_at); },
    async load() {
      const r = await api.get("/api/channels");
      this.channels = r.channels;
      this.channelTypes = r.channel_types;
      this.providers = r.providers || [];
      this.modelTypes = r.model_types;
      if (this.selectedId) {
        this.detail = this.channels.find(c => c.id === this.selectedId) || null;
        if (this.detail) await this.loadModels(this.selectedId);
      }
    },
    async select(id) {
      this.selectedId = id;
      this.detailOpen = true;
      this.revealed = {};
      this.modelQuery = "";
      await this.load();
    },
    async loadModels(cid) {
      const r = await api.get(`/api/channels/${cid}/models`);
      this.models = r.models;
    },
    openChannelForm(c) {
      this.preset = "";
      this.chanForm = c ? { ...c, enabled: !!c.enabled } : { ...emptyChannel, enabled: true };
    },
    applyPreset() {
      if (!this.chanForm || !this.preset) return;
      const p = this.providers.find(x => `${x.type}|${x.base_url}` === this.preset);
      if (!p) return;
      this.chanForm.type = p.type;
      this.chanForm.base_url = p.base_url;
      this.chanForm.console_url = p.console_url;
      if (!this.chanForm.id || !this.chanForm.name) this.chanForm.name = p.name;
    },
    async saveChannel() {
      const f = this.chanForm;
      try {
        if (f.id) {
          await api.put(`/api/channels/${f.id}`, f);
        } else {
          const r = await api.post("/api/channels", f);
          this.selectedId = r.id;
          this.detailOpen = true;
        }
        this.chanForm = null;
        await this.load();
        this.$toast("已保存", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async removeChannel(c) {
      if (!confirm(`删除渠道「${c.name}」及其所有 Key、模型、余额历史？`)) return;
      await api.del(`/api/channels/${c.id}`);
      this.selectedId = null; this.detail = null; this.detailOpen = false;
      await this.load();
      this.$toast("已删除", "ok");
    },
    openKeyForm(k) {
      this.keyForm = k
        ? { id: k.id, name: k.name, value: "", notes: k.notes, expires_at: k.expires_at || "", enabled: !!k.enabled }
        : { name: "Key " + (this.detail.keys.length + 1), value: "", notes: "", expires_at: "", enabled: true };
    },
    async saveKey() {
      const f = this.keyForm;
      try {
        if (f.id) {
          await api.put(`/api/keys/${f.id}`, {
            name: f.name, notes: f.notes, expires_at: f.expires_at, enabled: f.enabled,
            ...(f.value ? { value: f.value } : {}),
          });
        } else {
          await api.post(`/api/channels/${this.selectedId}/keys`, f);
        }
        this.keyForm = null;
        await this.load();
        this.$toast("Key 已保存", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async removeKey(k) {
      if (!confirm(`删除 Key「${k.name}」及其余额历史？`)) return;
      await api.del(`/api/keys/${k.id}`);
      await this.load();
      this.$toast("已删除", "ok");
    },
    async toggleReveal(k) {
      if (this.revealed[k.id]) { delete this.revealed[k.id]; this.revealed = { ...this.revealed }; return; }
      try {
        const r = await api.post(`/api/keys/${k.id}/reveal`);
        this.revealed = { ...this.revealed, [k.id]: r.value };
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async copyConfig(k) {
      try {
        const r = await api.post(`/api/keys/${k.id}/reveal`);
        const models = this.enabledModels.join(", ");
        const text = [
          `# ${this.detail.name} · ${k.name}`,
          `Base URL: ${this.detail.base_url}`,
          `API Key: ${r.value}`,
          models ? `Models: ${models}` : "",
        ].filter(Boolean).join("\n");
        await copyText(text);
        this.$toast("配置已复制到剪贴板", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async verifyKey(keyId, mode, model) {
      try {
        const r = await api.post(`/api/keys/${keyId}/verify`, { mode, model: model || "" });
        if (r.ok) {
          this.$toast(mode === "chat" ? r.message : `Key 可用，远端 ${r.models.length} 个模型`, "ok");
          if (mode === "models") {
            const remote = r.models;
            const localAll = new Set(this.models.map(m => m.model_id));
            this.diff = {
              remote_count: remote.length,
              added: remote.filter(id => !localAll.has(id)),
              removed: this.models.filter(m => m.enabled && !remote.includes(m.model_id)).map(m => m.model_id),
              revived: this.models
                .filter(m => m.auto_disabled && !m.enabled && remote.includes(m.model_id))
                .map(m => m.model_id),
            };
            this.diffChecked = [...this.diff.added];
            this.revivedChecked = [...this.diff.revived];
            this.removedAction = "disable";
          }
        } else {
          this.$toast(r.error, "err");
        }
        await this.load();
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async verifyAll() {
      const keys = this.detail.keys.filter(k => k.enabled);
      if (!keys.length) { this.$toast("没有启用的 Key", "err"); return; }
      const failures = [];
      for (const k of keys) {
        try {
          const r = await api.post(`/api/keys/${k.id}/verify`, { mode: "models", model: "" });
          if (!r.ok) failures.push(`${k.name}：${r.error}`);
        } catch (e) { failures.push(`${k.name}：${e.message}`); }
      }
      await this.load();
      if (failures.length) {
        this.$toast(`测 Key 完成：${keys.length - failures.length} 个可用，${failures.length} 个异常（${failures[0]}）`, "err");
      } else {
        this.$toast(`测 Key 完成：${keys.length} 个全部可用`, "ok");
      }
    },
    async chatTest(keyId) {
      const model = this.enabledModels[0];
      if (!model) { this.$toast("请先添加并启用一个模型", "err"); return; }
      await this.verifyKey(keyId, "chat", model);
    },
    async checkBalance(keyId) {
      try {
        const r = await api.post(`/api/keys/${keyId}/balance-check`);
        this.$toast(r.ok ? `余额 ${r.balance} ${r.currency}` : r.error, r.ok ? "ok" : "err");
        await this.load();
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async checkAllBalance() {
      const keys = this.detail.keys.filter(k => k.enabled);
      if (!keys.length) { this.$toast("没有启用的 Key", "err"); return; }
      const failures = [];
      for (const k of keys) {
        try {
          const r = await api.post(`/api/keys/${k.id}/balance-check`);
          if (!r.ok) failures.push(`${k.name}：${r.error}`);
        } catch (e) { failures.push(`${k.name}：${e.message}`); }
      }
      await this.load();
      if (failures.length) {
        this.$toast(`查余额完成：${keys.length - failures.length} 个成功，${failures.length} 个失败（${failures[0]}）`, "err");
      } else {
        this.$toast(`查余额完成：${keys.length} 个全部成功`, "ok");
      }
    },
    openBalanceManual(k) {
      this.balKeyName = k.name;
      this.balForm = {
        key_id: k.id,
        balance: k.balance ?? "",
        currency: k.currency || "CNY",
        expires_at: k.expires_at || "",
      };
    },
    async saveBalance() {
      try {
        await api.post(`/api/keys/${this.balForm.key_id}/balance-manual`, {
          balance: parseFloat(this.balForm.balance),
          currency: this.balForm.currency,
          expires_at: this.balForm.expires_at,
        });
        this.balForm = null;
        await this.load();
        this.$toast("余额已记录", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async fetchModels() {
      try {
        const r = await api.post(`/api/channels/${this.selectedId}/models/diff`, {});
        if (!r.ok) { this.$toast(r.error, "err"); return; }
        this.diff = r;
        this.diffChecked = [...r.added];
        this.revivedChecked = [...(r.revived || [])];
        this.removedAction = "disable";
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async applySync() {
      try {
        const r = await api.post(`/api/channels/${this.selectedId}/models/sync`, {
          added: this.diffChecked,
          removed: this.diff.removed,
          revived: this.revivedChecked,
          removed_action: this.removedAction,
        });
        this.diff = null;
        await Promise.all([this.load(), this.loadModels(this.selectedId)]);
        this.$toast(`同步完成：新增 ${r.added}，恢复 ${r.revived || 0}，移除 ${r.removed}`, "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async addManualModel() {
      try {
        await api.post(`/api/channels/${this.selectedId}/models`, { model_id: this.newModelId.trim() });
        this.newModelId = ""; this.modelFormOpen = false;
        await this.loadModels(this.selectedId);
        this.$toast("已添加", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async addParsed() {
      try {
        const r = await api.post(`/api/channels/${this.selectedId}/models/batch`, { ids: this.pasteIds });
        this.pasteOpen = false; this.pasteText = ""; this.pasteIds = [];
        await this.loadModels(this.selectedId);
        this.$toast(`已添加 ${r.added} 个`, "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async updateModel(m, patch) {
      try {
        await api.put(`/api/models/${m.id}`, patch);
        await this.loadModels(this.selectedId);
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async deleteModel(m) {
      if (!confirm(`删除模型 ${m.model_id}？`)) return;
      await api.del(`/api/models/${m.id}`);
      await this.loadModels(this.selectedId);
    },
  },
  watch: {
    pasteText(text) { this.pasteIds = parseModelText(text); },
  },
};

function parseModelText(text) {
  text = text.trim();
  const ids = [];
  let data = null;
  try { data = JSON.parse(text); } catch {}
  if (Array.isArray(data)) {
    for (const item of data) {
      if (typeof item === "string") ids.push(item);
      else if (item && item.id) ids.push(String(item.id));
    }
  } else if (data && typeof data === "object") {
    const items = data.data || data.models || data.ids;
    if (Array.isArray(items)) {
      for (const item of items) {
        if (typeof item === "string") ids.push(item);
        else if (item) { const n = item.id || item.name || item.model; if (n) ids.push(String(n)); }
      }
    }
  }
  if (!ids.length && text) {
    ids.push(...text.split(/\r?\n/).map(s => s.trim()).filter(Boolean));
  }
  return [...new Set(ids)];
}
