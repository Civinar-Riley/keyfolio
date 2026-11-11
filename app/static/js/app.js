/** 根组件：路由、导航、锁屏、Toast。 */
import { createApp, nextTick } from "/vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { bus } from "./bus.js";
import { KIcon } from "./icons.js";
import { SetupView, LoginView } from "./views/auth.js";
import { ChannelsView } from "./views/channels.js";
import { DashboardView } from "./views/dashboard.js";
import { QuickAddView } from "./views/quickadd.js";
import { ExportView } from "./views/export.js";
import { SettingsView } from "./views/settings.js";

const NAV = [
  { id: "dashboard", label: "看板", icon: "dashboard", path: "/dashboard", title: "看板", sub: "所有渠道的 Key、余额与到期状态", comp: DashboardView },
  { id: "channels", label: "渠道", icon: "channels", path: "/channels", title: "渠道与 Key", sub: "维护渠道、Key 与模型清单", comp: ChannelsView },
  { id: "quickadd", label: "抓取", icon: "quickadd", path: "/quickadd", title: "快速抓取", sub: "从任意文本中提取凭证并入库", comp: QuickAddView },
  { id: "export", label: "导出", icon: "export", path: "/export", title: "导出配置", sub: "按模板生成客户端可用的配置", comp: ExportView },
  { id: "settings", label: "设置", icon: "settings", path: "/settings", title: "设置", sub: "安全、定时任务与备份", comp: SettingsView },
];

const App = {
  template: `
  <div>
    <!-- 未初始化：向导 -->
    <setup-view v-if="!configured" @done="onAuthDone"></setup-view>

    <!-- 未登录 -->
    <login-view v-else-if="!authed" @logged-in="onAuthDone"></login-view>

    <!-- 主界面 -->
    <template v-else>
      <div class="shell" v-if="!locked">
        <aside class="rail">
          <a class="rail-brand" href="#/dashboard" aria-label="Keyfolio 看板">
            <k-icon name="seal" class="brand-seal"></k-icon>
            <span class="brand-text">
              <span class="brand-word">Keyfolio</span>
              <span class="brand-sub">API 资产账本</span>
            </span>
          </a>

          <nav class="rail-nav" aria-label="主导航">
            <a v-for="n in nav" :key="n.id" :href="'#' + n.path" :class="{active: route===n.path}">
              <k-icon :name="n.icon"></k-icon>
              <span>{{ n.label }}</span>
            </a>
          </nav>

          <div class="rail-foot">
            <div class="vault-line"><span class="vault-dot"></span>本地加密存储</div>
            <button class="btn sm rail-btn" @click="lock">
              <k-icon name="lock"></k-icon><span>锁屏</span>
            </button>
            <button class="rail-logout" @click="logout">登出</button>
          </div>
        </aside>

        <div class="main">
          <header class="topbar">
            <a class="topbar-brand" href="#/dashboard">
              <k-icon name="seal" class="topbar-seal"></k-icon><span>Keyfolio</span>
            </a>
            <button class="icon-btn" @click="lock" aria-label="锁屏">
              <k-icon name="lock"></k-icon>
            </button>
          </header>

          <main class="page">
            <header class="page-head">
              <div class="page-head-text">
                <h1>{{ pageTitle }}</h1>
                <p>{{ pageSub }}</p>
              </div>
              <div class="page-mark"><k-icon name="shield"></k-icon><span>本地加密</span></div>
            </header>
            <component :is="viewComp" :key="route" @lock="lock" @logout="logout"></component>
          </main>
        </div>

        <nav class="bottomnav" aria-label="主导航">
          <a v-for="n in nav" :key="n.id" :href="'#' + n.path" :class="{active: route===n.path}">
            <k-icon :name="n.icon"></k-icon>
            <span>{{ n.label }}</span>
          </a>
        </nav>
      </div>

      <!-- 锁屏：服务端同时拒绝数据接口，刷新页面仍保持锁定 -->
      <div class="lock-mask" v-if="locked" role="dialog" aria-modal="true" aria-label="已锁定">
        <k-icon name="seal" class="lock-seal"></k-icon>
        <div class="lock-title">已锁定</div>
        <p class="lock-sub">输入主密码继续</p>
        <form class="lock-form" @submit.prevent="unlock">
          <input type="password" v-model="unlockPw" placeholder="主密码" aria-label="主密码" autofocus>
          <div v-if="unlockErr" class="form-error">{{ unlockErr }}</div>
          <button class="btn primary block" :disabled="!unlockPw">解锁</button>
        </form>
      </div>
    </template>

    <div class="toasts">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
    </div>
  </div>`,
  components: {
    "setup-view": SetupView,
    "login-view": LoginView,
    "dashboard-view": DashboardView,
    "channels-view": ChannelsView,
    "quickadd-view": QuickAddView,
    "export-view": ExportView,
    "settings-view": SettingsView,
  },
  data: () => ({
    nav: NAV,
    route: "/dashboard",
    configured: true,
    authed: false,
    locked: false,
    unlockPw: "", unlockErr: "",
    toasts: [], toastSeq: 0,
  }),
  computed: {
    current() {
      return NAV.find(n => n.path === this.route) || NAV[0];
    },
    pageTitle() { return this.current.title; },
    pageSub() { return this.current.sub; },
    viewComp() {
      const n = NAV.find(n => n.path === this.route) || NAV[0];
      return n.id + "-view";
    },
  },
  async created() {
    bus.on("toast", (text, kind) => this.toast(text, kind));
    bus.on("goto", (path) => { location.hash = "#" + path; });
    window.addEventListener("hashchange", () => this.readRoute());
    window.addEventListener("kf:unauthorized", () => {
      this.authed = false;
      this.locked = false;
      this.toast("会话失效，请重新登录", "err");
    });
    window.addEventListener("kf:locked", () => {
      this.locked = true;
      this.unlockPw = "";
      this.unlockErr = "";
    });
    this.readRoute();
    try {
      const s = await api.get("/api/auth/status");
      this.configured = s.configured;
      if (s.configured) {
        // 刷新页面时沿用服务端会话，不再强制重新登录
        this.authed = !!s.authenticated;
        this.locked = !!s.screen_locked;
      }
    } catch { this.configured = true; }
  },
  methods: {
    readRoute() {
      const h = location.hash.replace(/^#/, "") || "/dashboard";
      this.route = NAV.some(n => n.path === h) ? h : "/dashboard";
    },
    onAuthDone() {
      this.configured = true;
      this.authed = true;
      this.locked = false;
      this.readRoute();
      // 强制重挂载当前视图以刷新数据
      const key = this.route;
      this.route = "";
      nextTick(() => { this.route = key; });
    },
    async lock() {
      try {
        await api.post("/api/auth/lock");
        this.locked = true;
        this.unlockPw = "";
        this.unlockErr = "";
      } catch (e) { this.toast(e.message, "err"); }
    },
    async unlock() {
      this.unlockErr = "";
      try {
        await api.post("/api/auth/unlock", { password: this.unlockPw });
        this.locked = false;
        this.unlockPw = "";
      } catch (e) { this.unlockErr = e.message; }
    },
    async logout() {
      try { await api.post("/api/auth/logout"); } catch {}
      this.authed = false;
      this.locked = false;
    },
    toast(text, kind = "") {
      const id = ++this.toastSeq;
      this.toasts.push({ id, text, kind });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, kind === "err" ? 6000 : 3200);
    },
  },
};

const app = createApp(App);
app.component("k-icon", KIcon);
app.mixin({
  methods: {
    $toast(text, kind) { bus.emit("toast", text, kind); },
    $goto(path) { bus.emit("goto", path); },
  },
});
app.mount("#app");

// Service Worker 注册（localhost / HTTPS 下生效）
const secure = location.protocol === "https:";
const local = location.hostname === "localhost" || location.hostname === "127.0.0.1";
if ("serviceWorker" in navigator && (secure || local)) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
