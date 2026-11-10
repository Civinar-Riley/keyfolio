/** 渠道与 Key 管理：列表 + 详情 + 模型同步 + 余额操作。 */
import { api, fmtBalance, fmtTime } from "../api.js";

const emptyChannel = { name: "", type: "gateway", base_url: "", console_url: "", grp: "", notes: "" };

export const ChannelsView = {
  template: `
  <div>
    <div class="split">
      <!-- 左列：渠道列表 -->
      <div class="list-col" v-if="!isMobile || !detailOpen">
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="openChannelForm(null)">＋ 新渠道</button>
        </div>
        <label class="field" style="margin:0">
          <input v-model="filter" placeholder="搜索名称 / URL / 分组">
        </label>
        <div v-for="c in filtered" :key="c.id" class="chan-item" :class="{active: c.id===selectedId}" @click="select(c.id)">
          <div class="name">
            {{ c.name }}
            <span class="badge acc">{{ typeLabel(c.type) }}</span>
            <span class="badge" v-if="c.grp">{{ c.grp }}</span>
            <span class="badge" :class="c.enabled ? 'ok' : 'warn'">{{ c.enabled ? "启用" : "停用" }}</span>
          </div>
          <div class="meta">{{ c.base_url }}</div>
          <div class="meta">{{ c.keys.length }} 个 Key · {{ c.models_count }} 个模型</div>
        </div>
        <div class="hint" v-if="!filtered.length" style="text-align:center; padding:30px 0">
          还没有渠道，点上面"＋ 新渠道"开始
        </div>
      </div>

      <!-- 右列：详情 -->
      <div v-if="detail">
        <div class="btn-row" style="margin-bottom:10px">
          <button class="btn sm" v-if="isMobile" @click="detailOpen=false">← 返回列表</button>
          <button class="btn sm" @click="openChannelForm(detail)">编辑</button>
          <a class="btn sm" v-if="detail.console_url" :href="detail.console_url" target="_blank" rel="noopener">控制台 ↗</a>
          <button class="btn sm danger" @click="removeChannel(detail)">删除渠道</button>
        </div>
        <div class="card">
          <h3>{{ detail.name }}
            <span class="badge acc">{{ typeLabel(detail.type) }}</span>
            <span class="badge" :class="detail.enabled ? 'ok' : 'warn'">{{ detail.enabled ? "启用" : "停用" }}</span>
          </h3>
          <div class="mono" style="word-break:break-all">{{ detail.base_url }}</div>
          <div class="hint" v-if="detail.notes">{{ detail.notes }}</div>
        </div>

        <div class="card">
          <h3>Keys（{{ detail.keys.length }}）
            <button class="btn sm primary" style="float:right" @click="openKeyForm(null)">＋ 添加 Key</button>
          </h3>
          <div class="key-row" v-for="k in detail.keys" :key="k.id">
            <div class="grow">
              <div class="key-name">{{ k.name }}
                <span class="badge" v-if="!k.enabled">停用</span>
                <span class="badge" :class="k.last_check==='ok' ? 'ok' : (k.last_check==='fail' ? 'fail' : '')"
                      v-if="k.last_check" :title="k.last_check_msg">
                  {{ k.last_check==='ok' ? "✓ 可用" : "✗ 异常" }}
                </span>
              </div>
              <div class="mono" style="color:var(--muted)">
                {{ revealed[k.id] || k.value_masked }}
                <a href="#" style="margin-left:6px" @click.prevent="toggleReveal(k)">{{ revealed[k.id] ? "隐藏" : "显示" }}</a>
              </div>
              <div class="hint" v-if="k.last_check_msg">{{ k.last_check_msg }}</div>
            </div>
            <div class="key-balance">
              <div class="amt">{{ fmtBalance(k) }}</div>
              <div class="hint">{{ fmtTime(k.balance_updated_at) }}</div>
            </div>
          </div>
          <div class="btn-row" style="margin-top:10px" v-if="detail.keys.length">
            <button class="btn sm" @click="verifyAll()">全部测 Key</button>
            <button class="btn sm" @click="checkAllBalance()">全部查余额</button>
          </div>
          <div class="key-row" v-for="k in detail.keys" :key="'ops'+k.id" style="padding-top:4px">
            <div class="btn-row">
              <button class="btn sm ok" @click="copyConfig(k.id)">复制配置</button>
              <button class="btn sm" @click="verifyKey(k.id, 'models')">测 Key</button>
              <button class="btn sm" @click="chatTest(k.id)">测对话</button>
              <button class="btn sm" @click="checkBalance(k.id)">查余额</button>
              <button class="btn sm" @click="openBalanceManual(k)">填余额</button>
              <button class="btn sm" @click="openKeyForm(k)">编辑</button>
              <button class="btn sm danger" @click="removeKey(k)">删</button>
            </div>
          </div>
        </div>

        <div class="card">
          <h3>模型（{{ models.length }}）
            <span class="btn-row" style="float:right">
              <button class="btn sm primary" @click="fetchModels()">拉取模型</button>
              <button class="btn sm" @click="pasteOpen=true">粘贴 JSON</button>
              <button class="btn sm" @click="modelFormOpen=true">手动添加</button>
            </span>
          </h3>
          <table class="list" v-if="models.length">
            <thead><tr><th>模型 ID</th><th>类型</th><th>状态</th><th></th></tr></thead>
            <tbody>
              <tr v-for="m in models" :key="m.id">
                <td class="mono">{{ m.model_id }}</td>
                <td>
                  <select :value="m.mtype" @change="updateModel(m, {mtype: $event.target.value})">
                    <option v-for="t in modelTypes" :key="t" :value="t">{{ t }}</option>
                  </select>
                </td>
                <td><span class="badge" :class="m.enabled ? 'ok' : 'warn'">{{ m.enabled ? "启用" : "停用" }}</span></td>
                <td>
                  <button class="btn sm" @click="updateModel(m, {enabled: !m.enabled})">{{ m.enabled ? "停用" : "启用" }}</button>
                  <button class="btn sm danger" @click="deleteModel(m)">删</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div class="hint" v-else>还没有模型。用"拉取模型"从平台同步，或手动添加。</div>
        </div>
      </div>
      <div class="hint" v-else-if="!isMobile" style="padding:40px; text-align:center;">
        ← 从左侧选择一个渠道
      </div>
    </div>

    <!-- 渠道表单 -->
    <div class="modal-mask" v-if="chanForm" @click.self="chanForm=null">
      <div class="modal">
        <h3>{{ chanForm.id ? "编辑渠道" : "新渠道" }}</h3>
        <label class="field">名称 <input v-model="chanForm.name" placeholder="如 DeepSeek 官方"></label>
        <label class="field">类型
          <select v-model="chanForm.type">
            <option v-for="t in channelTypes" :key="t.id" :value="t.id">{{ t.label }}</option>
          </select>
        </label>
        <label class="field">Base URL <input v-model="chanForm.base_url" placeholder="https://api.example.com"></label>
        <label class="field">控制台地址 <input v-model="chanForm.console_url" placeholder="可选，快捷打开"></label>
        <label class="field">分组 <input v-model="chanForm.grp" placeholder="可选"></label>
        <label class="field">备注 <textarea v-model="chanForm.notes"></textarea></label>
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
        <h3>{{ keyForm.id ? "编辑 Key" : "添加 Key" }}</h3>
        <label class="field">名称 <input v-model="keyForm.name" placeholder="如 主 Key"></label>
        <label class="field">Key 值 <textarea v-model="keyForm.value" :placeholder="keyForm.id ? '留空则不修改' : 'sk-...'" style="min-height:70px"></textarea></label>
        <label class="field">备注 <input v-model="keyForm.notes"></label>
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
        <h3>手动填写余额（{{ balKeyName }}）</h3>
        <label class="field">余额 <input type="number" step="any" v-model="balForm.balance"></label>
        <label class="field">币种 <input v-model="balForm.currency" placeholder="CNY / USD"></label>
        <label class="field">到期日 <input v-model="balForm.expires_at" placeholder="可选，如 2026-12-31"></label>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="saveBalance">保存</button>
          <button class="btn" @click="balForm=null">取消</button>
        </div>
      </div>
    </div>

    <!-- 粘贴 JSON -->
    <div class="modal-mask" v-if="pasteOpen" @click.self="pasteOpen=false">
      <div class="modal">
        <h3>粘贴模型列表</h3>
        <p class="hint">支持字符串数组、OpenAI 返回体（data[].id）、每行一个</p>
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
        <h3>手动添加模型</h3>
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
        <h3>模型同步确认（远端 {{ diff.remote_count }} 个）</h3>
        <template v-if="diff.added.length">
          <h3 class="diff-add">新增（{{ diff.added.length }}）</h3>
          <ul class="diff-list">
            <li v-for="m in diff.added" :key="'a'+m">
              <input type="checkbox" v-model="diffChecked" :value="m" style="width:auto"> {{ m }}
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
        <p class="hint" v-if="!diff.added.length && !diff.removed.length">没有差异，本地已是最新。</p>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" :disabled="!diff.added.length && !diff.removed.length"
                  @click="applySync">应用同步</button>
          <button class="btn" @click="diff=null">取消</button>
        </div>
      </div>
    </div>
  </div>`,
  data: () => ({
    channels: [], channelTypes: [], modelTypes: [],
    filter: "", selectedId: null, detail: null, models: [],
    revealed: {},
    isMobile: window.matchMedia("(max-width: 767px)").matches,
    detailOpen: false,
    chanForm: null, keyForm: null,
    balForm: null, balKeyName: "",
    pasteOpen: false, pasteText: "", pasteIds: [],
    modelFormOpen: false, newModelId: "",
    diff: null, diffChecked: [], removedAction: "disable",
  }),
  computed: {
    filtered() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.channels;
      return this.channels.filter(c =>
        [c.name, c.base_url, c.grp, c.notes].some(s => (s || "").toLowerCase().includes(q)));
    },
    enabledModels() { return this.models.filter(m => m.enabled).map(m => m.model_id); },
  },
  async created() {
    window.matchMedia("(max-width: 767px)").addEventListener("change", e => { this.isMobile = e.matches; });
    await this.load();
    if (this.channels.length && !this.selectedId) this.select(this.channels[0].id);
  },
  methods: {
    fmtBalance, fmtTime,
    typeLabel(id) {
      const t = this.channelTypes.find(t => t.id === id);
      return t ? t.label.split("（")[0] : id;
    },
    async load() {
      const r = await api.get("/api/channels");
      this.channels = r.channels;
      this.channelTypes = r.channel_types;
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
      await this.load();
    },
    async loadModels(cid) {
      const r = await api.get(`/api/channels/${cid}/models`);
      this.models = r.models;
    },
    openChannelForm(c) {
      this.chanForm = c ? { ...c, enabled: !!c.enabled } : { ...emptyChannel, enabled: true };
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
        ? { id: k.id, name: k.name, value: "", notes: k.notes, enabled: !!k.enabled }
        : { name: "Key " + (this.detail.keys.length + 1), value: "", notes: "", enabled: true };
    },
    async saveKey() {
      const f = this.keyForm;
      try {
        if (f.id) {
          await api.put(`/api/keys/${f.id}`, {
            name: f.name, notes: f.notes, enabled: f.enabled,
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
        await navigator.clipboard.writeText(text);
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
            const local = new Set(this.models.filter(m => m.enabled).map(m => m.model_id));
            this.diff = {
              remote_count: remote.length,
              added: remote.filter(id => !local.has(id)),
              removed: this.models.filter(m => m.enabled && !remote.includes(m.model_id)).map(m => m.model_id),
            };
            this.diffChecked = [...this.diff.added];
            this.removedAction = "disable";
          }
        } else {
          this.$toast(r.error, "err");
        }
        await this.load();
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async verifyAll() {
      for (const k of this.detail.keys.filter(k => k.enabled)) {
        await this.verifyKey(k.id, "models");
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
      for (const k of this.detail.keys.filter(k => k.enabled)) {
        await this.checkBalance(k.id);
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
        this.removedAction = "disable";
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async applySync() {
      try {
        const r = await api.post(`/api/channels/${this.selectedId}/models/sync`, {
          added: this.diffChecked,
          removed: this.diff.removed,
          removed_action: this.removedAction,
        });
        this.diff = null;
        await Promise.all([this.load(), this.loadModels(this.selectedId)]);
        this.$toast(`同步完成：新增 ${r.added}，移除 ${r.removed}`, "ok");
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
