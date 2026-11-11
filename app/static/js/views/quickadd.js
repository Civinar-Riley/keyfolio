/** 快速抓取：粘贴 → 解析 → 验证 → 入库。 */
import { api } from "../api.js";

export const QuickAddView = {
  template: `
  <div style="max-width:680px; margin:0 auto">
    <div class="card">
      <h3>① 粘贴</h3>
      <p class="hint">把网页上复制的 Base URL / Key（或包含它们的任意文本）粘进来，自动解析。</p>
      <label class="field"><textarea v-model="raw" placeholder="https://api.example.com/v1  sk-xxxx..." style="min-height:110px"></textarea></label>
    </div>

    <div class="card" v-if="parsed">
      <h3>② 确认字段</h3>
      <label class="field">渠道名称 <input v-model="form.name" :placeholder="hostHint"></label>
      <label class="field">类型
        <select v-model="form.type">
          <option v-for="t in channelTypes" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
      </label>
      <label class="field">Base URL <input v-model="form.base_url"></label>
      <label class="field">Key <textarea v-model="form.key" style="min-height:64px"></textarea></label>
      <div v-if="urlCandidates.length > 1" class="hint" style="margin-bottom:6px">
        其他候选 URL：
        <a v-for="u in urlCandidates.slice(1)" :key="u" href="#" style="display:block; word-break:break-all" @click.prevent="form.base_url = u">{{ u }}</a>
      </div>
      <div v-if="keyCandidates.length > 1" class="hint" style="margin-bottom:6px">
        其他候选 Key：<code v-for="k in keyCandidates.slice(1)" :key="k" class="mono" style="display:block; word-break:break-all">{{ k }}</code>
      </div>
      <div class="btn-row">
        <button class="btn primary" style="flex:1" :disabled="!form.base_url || !form.key" @click="verify">测一下</button>
        <button class="btn ok" style="flex:1" :disabled="!form.base_url || !form.key" @click="save">保存入库</button>
      </div>
    </div>

    <div class="card" v-if="verifyResult">
      <h3>③ 验证结果</h3>
      <div v-if="verifyResult.ok" class="badge ok" style="font-size:13px">✓ Key 可用，拉到 {{ verifyResult.models.length }} 个模型</div>
      <div v-else class="badge fail" style="font-size:13px">✗ {{ verifyResult.error }}</div>
      <div v-if="verifyResult.ok && verifyResult.models.length" class="hint" style="margin-top:8px; word-break:break-all">
        {{ verifyResult.models.slice(0, 12).join(" · ") }}{{ verifyResult.models.length > 12 ? " …" : "" }}
      </div>
    </div>
  </div>`,
  data: () => ({
    raw: "", parsed: null,
    form: { name: "", type: "gateway", base_url: "", key: "" },
    channelTypes: [],
    verifyResult: null,
    parseTimer: null,
  }),
  computed: {
    hostHint() {
      try { return new URL(this.form.base_url).hostname; } catch { return ""; }
    },
    urlCandidates() { return this.parsed ? this.parsed.url_candidates : []; },
    keyCandidates() { return this.parsed ? this.parsed.key_candidates : []; },
  },
  async created() {
    const r = await api.get("/api/channels");
    this.channelTypes = r.channel_types;
  },
  watch: {
    raw(text) {
      clearTimeout(this.parseTimer);
      if (!text.trim()) { this.parsed = null; return; }
      this.parseTimer = setTimeout(() => this.doParse(text), 400);
    },
  },
  methods: {
    async doParse(text) {
      try {
        const r = await api.post("/api/quickadd/parse", { text });
        if (text !== this.raw) return; // 已被更新的输入取代
        this.parsed = r;
        this.form.base_url = r.base_url;
        this.form.key = r.key;
        this.form.type = r.guessed_type;
        this.form.name = this.hostHint;
        this.verifyResult = null;
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async verify() {
      this.verifyResult = null;
      try {
        this.verifyResult = await api.post("/api/quickadd/verify", {
          base_url: this.form.base_url, key: this.form.key, type: this.form.type,
        });
      } catch (e) { this.verifyResult = { ok: false, error: e.message }; }
    },
    async save() {
      try {
        const r = await api.post("/api/quickadd/save", {
          name: this.form.name, base_url: this.form.base_url, key: this.form.key, type: this.form.type,
        });
        this.$toast(r.created ? `已入库：${r.type} 类型渠道` : `已追加到现有渠道（${r.type}）`, "ok");
        this.raw = ""; this.parsed = null; this.verifyResult = null;
        this.$goto("/channels");
      } catch (e) { this.$toast(e.message, "err"); }
    },
  },
};
