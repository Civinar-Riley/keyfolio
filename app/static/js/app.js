/** 根组件：路由、导航、锁屏、Toast。 */
import { createApp, nextTick } from "/vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { bus } from "./bus.js";
import { SetupView, LoginView } from "./views/auth.js";
import { ChannelsView } from "./views/channels.js";
import { DashboardView } from "./views/dashboard.js";
import { QuickAddView } from "./views/quickadd.js";
import { ExportView } from "./views/export.js";
import { SettingsView } from "./views/settings.js";

const NAV = [
  { id: "dashboard", label: "看板", icon: "📊", path: "/dashboard", comp: DashboardView },
  { id: "channels", label: "渠道", icon: "🗂", path: "/channels", comp: ChannelsView },
  { id: "quickadd", label: "抓取", icon: "⚡", path: "/quickadd", comp: QuickAddView },
  { id: "export", label: "导出", icon: "📤", path: "/export", comp: ExportView },
  { id: "settings", label: "设置", icon: "⚙", path: "/settings", comp: SettingsView },
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
      <header class="topbar">
        <a class="brand" href="#/dashboard">⬡ Keyfolio</a>
        <nav class="nav">
          <a v-for="n in nav" :key="n.id" :href="'#' + n.path" :class="{active: route===n.path}">{{ n.icon }} {{ n.label }}</a>
        </nav>
        <span class="spacer"></span>
        <button class="btn sm" @click="lock">🔒 锁屏</button>
        <button class="btn sm danger m-hide" @click="logout">登出</button>
      </header>

      <nav class="bottomnav">
        <a v-for="n in nav" :key="n.id" :href="'#' + n.path" :class="{active: route===n.path}">
          <span class="ico">{{ n.icon }}</span>{{ n.label }}
        </a>
      </nav>

      <main class="page">
        <component :is="viewComp" :key="route" @lock="lock" @logout="logout"></component>
      </main>
    </template>

    <!-- 锁屏遮罩 -->
    <div class="lock-mask" v-if="locked">
      <div style="font-size:40px">🔒</div>
      <div>已锁定，输入主密码解锁</div>
      <form style="width:min(320px, 90vw)" @submit.prevent="unlock">
        <label class="field"><input type="password" v-model="unlockPw" autofocus style="text-align:center"></label>
        <div v-if="unlockErr" class="toast err" style="margin-bottom:8px">{{ unlockErr }}</div>
        <button class="btn primary" style="width:100%" :disabled="!unlockPw">解锁</button>
      </form>
    </div>

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
      this.toast("会话失效，请重新登录", "err");
    });
    this.readRoute();
    try {
      const s = await api.get("/api/auth/status");
      this.configured = s.configured;
    } catch { this.configured = true; }
  },
  methods: {
    readRoute() {
      const h = location.hash.replace(/^#/, "") || "/dashboard";
      this.route = NAV.some(n => n.path === h) ? h : "/dashboard";
    },
    onAuthDone() {
      this.authed = true;
      this.locked = false;
      this.readRoute();
      // 强制重挂载当前视图以刷新数据
      const key = this.route;
      this.route = "";
      nextTick(() => { this.route = key; });
    },
    lock() { this.locked = true; this.unlockPw = ""; this.unlockErr = ""; },
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

// 全局混入：所有组件可用 this.$toast / this.$goto
app_mixin(App);

function app_mixin(App) {
  const app = createApp(App);
  app.mixin({
    methods: {
      $toast(text, kind) { bus.emit("toast", text, kind); },
      $goto(path) { bus.emit("goto", path); },
    },
  });
  app.mount("#app");
}

// Service Worker 注册（localhost / HTTPS 下生效）
const secure = location.protocol === "https:";
const local = location.hostname === "localhost" || location.hostname === "127.0.0.1";
if ("serviceWorker" in navigator && (secure || local)) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
