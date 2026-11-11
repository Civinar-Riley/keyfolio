/** 一键导出：模板管理 + 渲染复制/下载。 */
import { api, copyText } from "../api.js";

export const ExportView = {
  template: `
  <div class="split export-split">
    <div>
      <section class="sheet">
        <header class="sheet-head">
          <div><h2>选择凭证</h2><p>生成结果包含 Key 明文</p></div>
        </header>
        <div class="sheet-body">
          <label class="field">渠道
            <select v-model="selChannel" @change="onChannelChange">
              <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="field">Key
            <select v-model="selKey">
              <option v-for="k in selChannelKeys" :key="k.id" :value="k.id">{{ k.name }}（{{ k.value_masked }}）</option>
            </select>
          </label>
          <label class="field">模板
            <select v-model="selTemplate">
              <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}{{ t.builtin ? "（内置）" : "" }}</option>
            </select>
          </label>
          <button class="btn primary block" :disabled="!selKey || !selTemplate" @click="render">
            <k-icon name="export"></k-icon>生成配置
          </button>
          <p class="hint" style="margin:12px 0 0">复制或下载后注意保管，不要发到公开渠道。</p>
        </div>
      </section>

      <section class="sheet">
        <header class="sheet-head">
          <div><h2>占位符</h2><p>写在模板里会被替换</p></div>
        </header>
        <div class="sheet-body">
          <div class="placeholder-list">
            <code class="chip" v-for="p in placeholders" :key="p">{{ p }}</code>
          </div>
        </div>
      </section>
    </div>

    <div>
      <section class="sheet" v-if="result">
        <header class="sheet-head">
          <div><h2>生成结果</h2><p>{{ resultName }}</p></div>
          <div class="btn-row">
            <button class="btn sm ok" @click="copyOut"><k-icon name="copy"></k-icon>复制</button>
            <button class="btn sm" @click="download"><k-icon name="download"></k-icon>下载</button>
          </div>
        </header>
        <div class="sheet-body">
          <pre class="output">{{ result }}</pre>
        </div>
      </section>

      <section class="sheet">
        <header class="sheet-head">
          <div><h2>模板管理</h2><p>内置模板可直接编辑，不能删除</p></div>
          <button class="btn sm primary" @click="openForm(null)"><k-icon name="plus"></k-icon>新模板</button>
        </header>
        <table class="list" v-if="templates.length">
          <thead><tr><th>名称</th><th class="m-hide">客户端</th><th></th></tr></thead>
          <tbody>
            <tr v-for="t in templates" :key="t.id">
              <td>{{ t.name }} <span class="badge" v-if="t.builtin">内置</span></td>
              <td class="hint m-hide">{{ t.client_type || "—" }}</td>
              <td>
                <div class="btn-row" style="justify-content:flex-end">
                  <button class="btn sm" @click="openForm(t)">编辑</button>
                  <button class="btn sm danger" v-if="!t.builtin" @click="removeTpl(t)">删</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="empty" v-else style="padding:30px 10px"><p style="margin:0">还没有模板</p></div>
      </section>
    </div>

    <div class="modal-mask" v-if="form" @click.self="form=null">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ form.id ? "编辑模板" : "新模板" }}</h3>
          <button class="icon-btn" @click="form=null" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <div class="form-grid">
          <label class="field">名称 <input v-model="form.name"></label>
          <label class="field">客户端类型 <input v-model="form.client_type" placeholder="如 cherry-studio / chatbox"></label>
        </div>
        <label class="field">模板内容
          <textarea v-model="form.json_template" style="min-height:180px"></textarea>
        </label>
        <div class="btn-row">
          <button class="btn primary" style="flex:1" @click="saveTpl">保存</button>
          <button class="btn" @click="form=null">取消</button>
        </div>
      </div>
    </div>
  </div>`,
  data: () => ({
    channels: [], templates: [], placeholders: [],
    selChannel: "", selKey: "", selTemplate: "",
    result: "", resultName: "config.json",
    form: null,
  }),
  computed: {
    selChannelKeys() {
      const c = this.channels.find(c => c.id === Number(this.selChannel));
      return c ? c.keys : [];
    },
  },
  async created() {
    await this.load();
  },
  methods: {
    async load() {
      const [ch, tp] = await Promise.all([api.get("/api/channels"), api.get("/api/templates")]);
      this.channels = ch.channels;
      this.templates = tp.templates;
      this.placeholders = tp.placeholders;
      if (!this.selChannel && this.channels.length) this.selChannel = this.channels[0].id;
      const keys = this.selChannelKeys;
      if (!this.selKey && keys.length) this.selKey = keys[0].id;
      if (!this.selTemplate && this.templates.length) this.selTemplate = this.templates[0].id;
    },
    onChannelChange() {
      const keys = this.selChannelKeys;
      this.selKey = keys.length ? keys[0].id : "";
    },
    async render() {
      try {
        const r = await api.post("/api/templates/render", {
          template_id: Number(this.selTemplate), key_id: Number(this.selKey),
        });
        this.result = r.rendered;
        const tpl = this.templates.find(t => t.id === Number(this.selTemplate));
        const key = this.selChannelKeys.find(k => k.id === Number(this.selKey));
        this.resultName = r.is_json
          ? `${(tpl?.client_type || "config")}-${key?.name || "key"}.json`
          : `${(tpl?.client_type || "config")}-${key?.name || "key"}.txt`;
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async copyOut() {
      try {
        await copyText(this.result);
        this.$toast("已复制（含 Key 明文，注意保管）", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    download() {
      const blob = new Blob([this.result], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = this.resultName;
      a.click();
      URL.revokeObjectURL(a.href);
    },
    openForm(t) {
      this.form = t
        ? { id: t.id, name: t.name, client_type: t.client_type, json_template: t.json_template }
        : { name: "", client_type: "", json_template: '{\n  "base_url": "{base_url}",\n  "api_key": "{key}"\n}' };
    },
    async saveTpl() {
      try {
        if (this.form.id) await api.put(`/api/templates/${this.form.id}`, this.form);
        else await api.post("/api/templates", this.form);
        this.form = null;
        await this.load();
        this.$toast("模板已保存", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async removeTpl(t) {
      if (!confirm(`删除模板「${t.name}」？`)) return;
      try {
        await api.del(`/api/templates/${t.id}`);
        await this.load();
      } catch (e) { this.$toast(e.message, "err"); }
    },
  },
};
