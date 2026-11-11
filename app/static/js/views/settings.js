/** 设置：改密码 / TOTP / 定时任务 / 备份导入导出 / 锁屏登出。 */
import { api, copyText } from "../api.js";

export const SettingsView = {
  emits: ["lock", "logout"],
  template: `
  <div style="max-width:760px; margin:0 auto">
    <div class="card">
      <h3>安全</h3>
      <div class="btn-row">
        <button class="btn" @click="$emit('lock')">🔒 锁屏</button>
        <button class="btn danger" @click="logout">登出</button>
      </div>
    </div>

    <div class="card">
      <h3>修改主密码</h3>
      <label class="field">原密码 <input type="password" v-model="pw.old"></label>
      <label class="field">新密码（至少 8 位） <input type="password" v-model="pw.new1"></label>
      <label class="field">确认新密码 <input type="password" v-model="pw.new2"></label>
      <button class="btn primary" :disabled="busy || !pw.old || pw.new1.length < 8 || pw.new1 !== pw.new2" @click="changePassword">修改</button>
      <p class="hint" style="margin-top:8px">改密码只重新包裹加密密钥，Key 数据无需重新加密。恢复码不变；其他设备上的会话会退出。</p>
    </div>

    <div class="card">
      <h3>两步验证（TOTP）</h3>
      <template v-if="!s.totp_enabled">
        <p class="hint">用验证器 App（Google Authenticator / 1Password 等）扫码绑定。</p>
        <button class="btn primary" :disabled="busy" @click="totpStart">开始绑定</button>
        <div v-if="totpSetup" style="margin-top:12px">
          <div class="qr-box" v-html="totpSetup.qr_svg"></div>
          <p class="hint" style="text-align:center; word-break:break-all">密钥：{{ totpSetup.secret }}</p>
          <label class="field">输入 6 位验证码确认 <input v-model="totpCode" inputmode="numeric" maxlength="8"></label>
          <button class="btn primary" :disabled="totpCode.length < 6" @click="totpConfirm">确认开启</button>
        </div>
      </template>
      <template v-else>
        <p><span class="badge ok">已开启</span> 登录时需输入验证码，备用码可代替。</p>
        <div class="btn-row">
          <button class="btn" @click="op = op === 'regen' ? '' : 'regen'">重新生成备用码</button>
          <button class="btn danger" @click="op = op === 'off' ? '' : 'off'">关闭 TOTP</button>
        </div>
        <div v-if="op" style="margin-top:10px">
          <label class="field">输入主密码确认
            <input type="password" v-model="opPw" @keyup.enter="op === 'regen' ? regenCodes() : doTotpOff()">
          </label>
          <button class="btn" :class="op === 'off' ? 'danger' : 'primary'" :disabled="!opPw" @click="op === 'regen' ? regenCodes() : doTotpOff()">
            {{ op === 'regen' ? "生成新备用码" : "确认关闭" }}
          </button>
        </div>
      </template>
      <div v-if="backupCodes.length">
        <h3 style="margin-top:12px">备用码（只显示这一次）</h3>
        <div class="codes-grid"><code v-for="c in backupCodes" :key="c">{{ c }}</code></div>
        <button class="btn sm" @click="copyCodes">复制全部备用码</button>
      </div>
    </div>

    <div class="card">
      <h3>定时任务</h3>
      <label class="field" style="display:flex; align-items:center; gap:8px">
        <input type="checkbox" v-model="sched.enabled" style="width:auto; margin:0"> 启用（服务在线时自动执行）
      </label>
      <label class="field">自动查余额间隔（小时，0 = 关闭） <input type="number" min="0" step="0.5" v-model="sched.balance_interval_hours"></label>
      <label class="field">自动同步模型间隔（小时，0 = 关闭） <input type="number" min="0" step="0.5" v-model="sched.model_interval_hours"></label>
      <button class="btn primary" @click="saveSched">保存</button>
      <p class="hint" style="margin-top:8px">定时同步只自动新增模型，不会删除/停用已有模型。上次执行：余额 {{ ts(s.last_balance_run) }} · 模型 {{ ts(s.last_models_run) }}</p>
    </div>

    <div class="card">
      <h3>备份与恢复</h3>
      <p class="hint">全量导出渠道、Key、模型、余额历史、模板与登录凭证。</p>
      <div class="btn-row">
        <button class="btn primary" @click="exportBackup">导出备份（明文）</button>
        <button class="btn" @click="encOpen = !encOpen">加密导出…</button>
      </div>
      <div v-if="encOpen" class="inline-form" style="margin-top:10px">
        <label class="field">备份加密密码 <input type="password" v-model="encPw" placeholder="至少 8 位"></label>
        <button class="btn primary" :disabled="encPw.length < 8" @click="exportEncrypted">导出加密备份</button>
      </div>

      <div style="margin-top:16px; border-top:1px solid var(--border); padding-top:14px">
        <label class="field">导入备份文件 <input type="file" accept=".json" @change="pickFile"></label>
        <template v-if="importFile">
          <p class="hint">文件：{{ importFile.name }}（{{ importFile.size }} bytes，{{ importData?.encrypted ? "加密备份" : "明文备份" }}）</p>
          <label class="field">导入方式
            <select v-model="importMode">
              <option value="merge">合并（按 URL + Key 名去重，保留现有数据）</option>
              <option value="overwrite">覆盖（清空后恢复为备份内容，含登录凭证）</option>
            </select>
          </label>
          <label class="field" v-if="importData?.encrypted">备份密码 <input type="password" v-model="importPw"></label>
          <button class="btn danger" :disabled="importMode==='overwrite' && !confirmOverwrite" @click="doImport">
            {{ importMode === "overwrite" ? "确认覆盖导入" : "开始合并导入" }}
          </button>
          <label class="field" v-if="importMode==='overwrite'" style="display:flex; align-items:center; gap:8px; margin-top:8px">
            <input type="checkbox" v-model="confirmOverwrite" style="width:auto; margin:0">
            我知道覆盖导入会清空当前全部数据
          </label>
        </template>
      </div>
    </div>

    <div class="card">
      <h3>关于</h3>
      <p class="hint">
        Keyfolio · 本地优先的 API Key 资产管理器<br>
        数据库与日志位于 data/ 目录，迁移时整目录复制即可。
      </p>
    </div>
  </div>`,
  data: () => ({
    s: {}, pw: { old: "", new1: "", new2: "" },
    totpSetup: null, totpCode: "", backupCodes: [],
    op: "", opPw: "",
    sched: { enabled: false, balance_interval_hours: 12, model_interval_hours: 24 },
    encOpen: false, encPw: "",
    importFile: null, importData: null, importMode: "merge", importPw: "", confirmOverwrite: false,
    busy: false,
  }),
  async created() { await this.load(); },
  methods: {
    ts(v) { return v ? new Date(v * 1000).toLocaleString() : "从未"; },
    async load() {
      this.s = await api.get("/api/settings");
      this.sched = { ...this.s.scheduler };
    },
    async changePassword() {
      this.busy = true;
      try {
        await api.post("/api/auth/change-password", { old_password: this.pw.old, new_password: this.pw.new1 });
        this.pw = { old: "", new1: "", new2: "" };
        this.$toast("主密码已修改", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
      this.busy = false;
    },
    async totpStart() {
      try { this.totpSetup = await api.post("/api/auth/totp/setup"); }
      catch (e) { this.$toast(e.message, "err"); }
    },
    async totpConfirm() {
      try {
        const r = await api.post("/api/auth/totp/enable", { code: this.totpCode });
        this.backupCodes = r.backup_codes;
        this.totpSetup = null;
        await this.load();
        this.$toast("TOTP 已开启", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async regenCodes() {
      try {
        const r = await api.post("/api/auth/totp/backup-codes", { password: this.opPw });
        this.backupCodes = r.backup_codes;
        this.opPw = ""; this.op = "";
        this.$toast("新备用码已生成", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async doTotpOff() {
      try {
        await api.post("/api/auth/totp/disable", { password: this.opPw });
        this.opPw = ""; this.op = "";
        await this.load();
        this.$toast("TOTP 已关闭", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async saveSched() {
      try {
        await api.put("/api/settings/scheduler", {
          enabled: !!this.sched.enabled,
          balance_interval_hours: parseFloat(this.sched.balance_interval_hours) || 0,
          model_interval_hours: parseFloat(this.sched.model_interval_hours) || 0,
        });
        this.$toast("定时任务已保存", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async exportEncrypted() {
      await this._export(this.encPw);
    },
    async exportBackup() {
      await this._export("");
    },
    async _export(password) {
      try {
        const r = await api.post("/api/backup/export", { password });
        const stamp = new Date().toISOString().slice(0, 10);
        const name = password
          ? `keyfolio-backup-encrypted-${stamp}.json`
          : `keyfolio-backup-${stamp}.json`;
        const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.click();
        URL.revokeObjectURL(a.href);
        if (!password) this.$toast("已导出明文备份，内含 Key 明文，注意保管", "ok");
        else this.$toast("已导出加密备份", "ok");
        this.encOpen = false; this.encPw = "";
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async copyCodes() {
      try {
        await copyText(this.backupCodes.join("\n"));
        this.$toast("备用码已复制", "ok");
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async pickFile(ev) {
      const file = ev.target.files[0];
      if (!file) { this.importFile = null; return; }
      try {
        this.importData = JSON.parse(await file.text());
        if (this.importData.format !== "keyfolio-backup") {
          this.$toast("不是 Keyfolio 备份文件", "err");
          this.importFile = null; return;
        }
        this.importFile = file;
      } catch {
        this.$toast("文件解析失败", "err");
        this.importFile = null;
      }
    },
    async doImport() {
      try {
        const r = await api.post("/api/backup/import", {
          backup: this.importData, mode: this.importMode, password: this.importPw,
        });
        if (r.relogin) {
          this.$toast("覆盖导入完成，需要重新登录", "ok");
          window.dispatchEvent(new CustomEvent("kf:unauthorized"));
        } else {
          this.$toast(`合并完成：渠道 +${r.channels}，Key +${r.keys}，模型 +${r.models}`, "ok");
        }
        this.importFile = null; this.importData = null;
      } catch (e) { this.$toast(e.message, "err"); }
    },
    async logout() {
      try { await api.post("/api/auth/logout"); } catch {}
      this.$emit("logout");
    },
  },
};
