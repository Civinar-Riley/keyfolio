/** 一键导出：模板管理 + 渲染复制/下载。 */
import { api } from "../api.js";

export const ExportView = {
  template: `
  <div class="split" style="grid-template-columns: 320px 1fr">
    <div>
      <div class="card">
        <h3>选择凭证</h3>
        <label class="field">渠道
          <select v-model="selChannel" @change="selKey = ''">
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
        <div class="btn-row">
          <button class="btn primary" style="flex:1" :disabled="!selKey || !selTemplate" @click="render">生成</button>
        </div>
        <p class="hint" style="margin-top:8px">生成结果包含 Key 明文，复制/下载后注意保管。</p>
      </div>
      <div class="card">
        <h3>占位符</h3>
        <code class="mono" v-for="p in placeholders" :key="p" style="display:block; margin:2px 0">{{ p }}</code>
      </div>
    </div>

    <div>
      <div class="card" v-if="result">
        <h3>生成结果</h3>
        <pre class="mono" style="white-space:pre-wrap; background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:12px; max-height:320px; overflow:auto">{{ result }}</pre>
        <div class="btn-row">
          <button class="btn ok" @click="copyOut">复制</button>
          <button class="btn" @click="download">下载文件</button>
        </div>
      </div>

      <div class="card">
        <h3>模板管理
          <button class="btn sm primary" style="float:right" @click="openForm(null)">＋ 新模板</button>
        </h3>
        <table class="list" v-if="templates.length">
          <thead><tr><th>名称</th><th class="m-hide">类型</th><th></th></tr></thead>
          <tbody>
            <tr v-for="t in templates" :key="t.id">
              <td>{{ t.name }} <span class="badge" v-if="t.builtin">内置</span></td>
              <td class="hint m-hide">{{ t.client_type || "—" }}</td>
              <td>
                <button class="btn sm" @click="openForm(t)">编辑</button>
                <button class="btn sm danger" v-if="!t.builtin" @click="removeTpl(t)">删</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="modal-mask" v-if="form" @click.self="form=null">
      <div class="modal">
        <h3>{{ form.id ? "编辑模板" : "新模板" }}</h3>
        <label class="field">名称 <input v-model="form.name"></label>
        <label class="field">客户端类型 <input v-model="form.client_type" placeholder="如 cherry-studio / chatbox"></label>
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
        await navigator.clipboard.writeText(this.result);
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
