/** 初始化向导 + 登录 + 恢复码重置。 */
import { api, copyText } from "../api.js";

export const SetupView = {
  emits: ["done"],
  template: `
  <div class="auth-wrap">
    <div class="auth-shell">
      <k-icon name="seal" class="auth-seal"></k-icon>
      <div class="auth-brand">Keyfolio</div>
      <p class="auth-tag">本地 API 资产账本</p>

      <div class="auth-card">
        <template v-if="stage==='form'">
          <h3>设置主密码</h3>
          <p class="hint">主密码用于加密所有 Key，丢失无法找回。</p>
          <label class="field">主密码
            <input type="password" v-model="password" @keyup.enter="submit" placeholder="至少 8 位">
          </label>
          <label class="field">确认密码
            <input type="password" v-model="confirm" @keyup.enter="submit">
          </label>
          <div v-if="error" class="form-error">{{ error }}</div>
          <button class="btn primary block" :disabled="busy || password.length < 8" @click="submit">
            {{ busy ? "生成加密密钥中…" : "设置主密码" }}
          </button>
        </template>
        <template v-else>
          <h3>恢复码</h3>
          <p class="hint">用于忘记主密码时重置。只显示这一次，请立即保存。</p>
          <div class="recovery-box">{{ recovery }}</div>
          <button class="btn block" @click="copyRecovery"><k-icon name="copy"></k-icon>复制恢复码</button>
          <button class="btn primary block" style="margin-top:8px" @click="$emit('done')">我已保存，进入系统</button>
        </template>
      </div>

      <p class="auth-foot">数据只保存在这台机器 · Key 字段级加密</p>
    </div>
  </div>`,
  data: () => ({ password: "", confirm: "", recovery: "", stage: "form", busy: false, error: "" }),
  methods: {
    async copyRecovery() {
      try {
        await copyText(this.recovery);
        this.$toast("恢复码已复制", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async submit() {
      if (this.password !== this.confirm) { this.error = "两次输入不一致"; return; }
      this.busy = true; this.error = "";
      try {
        const r = await api.post("/api/auth/setup", { password: this.password });
        this.recovery = r.recovery_code;
        this.stage = "recovery";
      } catch (e) { this.error = e.message; }
      this.busy = false;
    },
  },
};

export const LoginView = {
  emits: ["logged-in"],
  template: `
  <div class="auth-wrap">
    <div class="auth-shell">
      <k-icon name="seal" class="auth-seal"></k-icon>
      <div class="auth-brand">Keyfolio</div>
      <p class="auth-tag">本地 API 资产账本</p>

      <div class="auth-card" v-if="!showRecovery && !newRecovery">
        <h3>解锁账本</h3>
        <p class="hint">输入主密码继续。</p>
        <label class="field">主密码
          <input type="password" v-model="password" @keyup.enter="submit" autofocus>
        </label>
        <label class="field" v-if="totpEnabled">两步验证码 / 备用码
          <input v-model="totp" @keyup.enter="submit" inputmode="numeric" autocomplete="one-time-code">
        </label>
        <div v-if="error" class="form-error">{{ error }}</div>
        <button class="btn primary block" :disabled="busy || !password" @click="submit">
          {{ busy ? "解锁中…" : "解锁" }}
        </button>
        <div style="text-align:center">
          <a href="#" class="auth-link" @click.prevent="showRecovery = true">忘记主密码？用恢复码重置</a>
        </div>
      </div>

      <div class="auth-card" v-else-if="showRecovery">
        <h3>用恢复码重置密码</h3>
        <p class="hint">重置后会用新密码重新包裹加密密钥。</p>
        <label class="field">恢复码
          <input v-model="recCode" placeholder="xxxx-xxxx-xxxx-xxxx">
        </label>
        <label class="field">新主密码
          <input type="password" v-model="recNew">
        </label>
        <div v-if="error" class="form-error">{{ error }}</div>
        <button class="btn primary block" :disabled="busy || !recCode || !recNew" @click="doRecovery">重置并登录</button>
        <div style="text-align:center">
          <a href="#" class="auth-link" @click.prevent="showRecovery = false">返回登录</a>
        </div>
      </div>

      <div class="auth-card" v-if="newRecovery">
        <h3>新恢复码</h3>
        <p class="hint">只显示这一次，请立即保存到安全的地方。</p>
        <div class="recovery-box">{{ newRecovery }}</div>
        <button class="btn block" @click="copyNewRecovery"><k-icon name="copy"></k-icon>复制新恢复码</button>
        <button class="btn ok block" style="margin-top:8px" @click="finishRecovery">我已保存</button>
      </div>

      <p class="auth-foot">数据只保存在这台机器 · Key 字段级加密</p>
    </div>
  </div>`,
  data: () => ({
    password: "", totp: "", totpEnabled: false,
    showRecovery: false, recCode: "", recNew: "", newRecovery: "",
    busy: false, error: "",
  }),
  async created() {
    try { this.totpEnabled = (await api.get("/api/auth/status")).totp_enabled; } catch {}
  },
  methods: {
    async submit() {
      this.busy = true; this.error = "";
      try {
        await api.post("/api/auth/login", { password: this.password, totp_code: this.totp });
        this.$emit("logged-in");
      } catch (e) { this.error = e.message; }
      this.busy = false;
    },
    async doRecovery() {
      this.busy = true; this.error = "";
      try {
        const r = await api.post("/api/auth/recovery-reset", {
          recovery_code: this.recCode.trim(), new_password: this.recNew,
        });
        this.newRecovery = r.recovery_code;
        this.showRecovery = false;
      } catch (e) { this.error = e.message; }
      this.busy = false;
    },
    finishRecovery() {
      this.newRecovery = "";
      this.recCode = ""; this.recNew = "";
      this.$emit("logged-in");
    },
    async copyNewRecovery() {
      try {
        await copyText(this.newRecovery);
        this.$toast("新恢复码已复制", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
  },
};
