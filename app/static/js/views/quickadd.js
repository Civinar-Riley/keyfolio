/** 快速抓取：粘贴 → 解析 → 验证 → 入库。 */
import { api } from "../api.js";

export const QuickAddView = {
  template: `
  <div class="intake">
    <section class="step">
      <div class="step-marker">01</div>
      <div>
        <div class="step-head">
          <h2>粘贴文本</h2>
          <p>把网页上复制的 Base URL / Key（或包含它们的任意文本）粘进来，自动解析。</p>
        </div>
        <label class="field" style="margin-bottom:0">
          <textarea class="paste" v-model="raw" aria-label="粘贴文本"
                    placeholder="https://api.example.com/v1  sk-xxxx..."></textarea>
        </label>
        <div class="paste-hints">
          <span>支持</span>
          <span class="chip">控制台 Key</span>
          <span class="chip">curl 命令</span>
          <span class="chip">.env</span>
          <span class="chip">JSON 配置</span>
        </div>
        <p class="hint" style="margin:12px 0 0">解析在本机完成；点「测一下」时才会请求你填写的 Base URL。</p>
      </div>
    </section>

    <section class="step" v-if="parsed">
      <div class="step-marker">02</div>
      <div>
        <div class="step-head">
          <h2>确认字段</h2>
          <p>解析结果可直接修改，保存前可以先测一下。</p>
        </div>
        <div class="form-grid">
          <label class="field">渠道名称 <input v-model="form.name" :placeholder="hostHint"></label>
          <label class="field">类型
            <select v-model="form.type">
              <option v-for="t in channelTypes" :key="t.id" :value="t.id">{{ t.label }}</option>
            </select>
          </label>
          <label class="field span-2">Base URL <input v-model="form.base_url"></label>
          <label class="field span-2">Key <textarea v-model="form.key" style="min-height:64px"></textarea></label>
        </div>

        <div class="candidates" v-if="urlCandidates.length > 1">
          <div>其他候选 URL</div>
          <a v-for="u in urlCandidates.slice(1)" :key="u" href="#" @click.prevent="form.base_url = u">{{ u }}</a>
        </div>
        <div class="candidates" v-if="keyCandidates.length > 1">
          <div>其他候选 Key</div>
          <code class="mono" v-for="k in keyCandidates.slice(1)" :key="k">{{ k }}</code>
        </div>

        <div class="btn-row">
          <button class="btn" :disabled="!form.base_url || !form.key" @click="verify">
            <k-icon name="refresh"></k-icon>测一下
          </button>
          <button class="btn primary" :disabled="!form.base_url || !form.key" @click="save">
            <k-icon name="check"></k-icon>保存入库
          </button>
        </div>
      </div>
    </section>

    <section class="step" v-if="verifyResult">
      <div class="step-marker">03</div>
      <div>
        <div class="step-head">
          <h2>验证结果</h2>
          <p>验证只读取模型列表，不消耗额度。</p>
        </div>
        <div class="result-banner" :class="verifyResult.ok ? 'ok' : 'fail'">
          <k-icon :name="verifyResult.ok ? 'check' : 'alert'"></k-icon>
          <div>
            <div v-if="verifyResult.ok">Key 可用，拉到 {{ verifyResult.models.length }} 个模型</div>
            <div v-else>{{ verifyResult.error }}</div>
          </div>
        </div>
        <div class="result-models" v-if="verifyResult.ok && verifyResult.models.length">
          <span class="chip" v-for="m in verifyResult.models.slice(0, 12)" :key="m">{{ m }}</span>
          <span class="chip" v-if="verifyResult.models.length > 12">+{{ verifyResult.models.length - 12 }}</span>
        </div>
      </div>
    </section>
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
