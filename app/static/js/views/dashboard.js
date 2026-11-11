/** 统一看板：汇总统计 + 筛选排序 + 余额趋势图（Chart.js）。 */
import { api, expiryInfo, fmtTime } from "../api.js";

export const DashboardView = {
  template: `
  <div>
    <section class="folio">
      <div class="folio-main">
        <div class="folio-label">总余额（按币种）</div>
        <div class="folio-amounts" v-if="balanceEntries.length">
          <div class="amount" v-for="b in balanceEntries" :key="b.cur">
            <span class="cur">{{ b.cur }}</span><span class="val">{{ b.value }}</span>
          </div>
        </div>
        <div class="folio-amounts" v-else><span class="none">—</span></div>
      </div>
      <dl class="folio-meta">
        <div>
          <dt>渠道</dt>
          <dd>{{ summary.channels_total ?? "—" }}</dd>
        </div>
        <div>
          <dt>启用 Key</dt>
          <dd>{{ summary.keys_active ?? "—" }}<small> / {{ summary.keys_total ?? "—" }}</small></dd>
        </div>
        <div>
          <dt>最近余额更新</dt>
          <dd class="dd-time">{{ fmtTime(summary.latest_update) }}</dd>
        </div>
      </dl>
    </section>

    <section class="sheet">
      <header class="sheet-head">
        <div>
          <h2>Key 明细</h2>
          <p>{{ rows.length ? rows.length + " 个 Key" : "按渠道汇总" }}</p>
        </div>
        <div class="filters">
          <label class="field">分组
            <select v-model="fGroup"><option value="">全部分组</option><option v-for="g in groups" :key="g">{{ g }}</option></select>
          </label>
          <label class="field">类型
            <select v-model="fType"><option value="">全部类型</option><option v-for="t in channelTypes" :key="t.id" :value="t.id">{{ t.label }}</option></select>
          </label>
          <label class="field">排序
            <select v-model="sortBy">
              <option value="balance_desc">余额从高到低</option>
              <option value="balance_asc">余额从低到高</option>
              <option value="updated">按更新时间</option>
              <option value="channel">按渠道</option>
            </select>
          </label>
        </div>
      </header>

      <table class="ledger" v-if="rows.length">
        <thead>
          <tr><th>渠道 / Key</th><th class="num">余额</th><th>状态</th><th class="m-hide">更新时间</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.key.id" tabindex="0" @click="openTrend(r.key)"
              @keydown.enter="openTrend(r.key)" @keydown.space.prevent="openTrend(r.key)">
            <td>
              <div class="row-name">{{ r.channel.name }}</div>
              <div class="row-sub"><span class="tag">{{ r.key.name }}</span>{{ r.channel.grp || "未分组" }}</div>
            </td>
            <td class="num">
              <div class="row-balance">{{ fmtAmount(r.key.balance) }}<small v-if="r.key.currency">{{ r.key.currency }}</small></div>
              <div class="row-sub" v-if="expiryOf(r.key)">
                <span class="badge" :class="expiryOf(r.key).cls">{{ expiryOf(r.key).text }}</span>
              </div>
            </td>
            <td><span class="badge dot" :class="badgeClass(r.key)">{{ badgeText(r.key) }}</span></td>
            <td class="row-sub m-hide">{{ fmtTime(r.key.balance_updated_at) }}</td>
            <td class="row-arrow"><k-icon name="chart"></k-icon></td>
          </tr>
        </tbody>
      </table>

      <div class="empty" v-else>
        <k-icon name="key"></k-icon>
        <h3>还没有 Key</h3>
        <p>先在渠道里添加第一个 API Key，余额会汇总到这里。</p>
        <a class="btn primary" href="#/channels">去添加</a>
      </div>
    </section>

    <div class="modal-mask" v-if="trend" @click.self="closeTrend">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ trend.key.name }} · 余额趋势</h3>
          <button class="icon-btn" @click="closeTrend" aria-label="关闭"><k-icon name="x"></k-icon></button>
        </div>
        <div class="trend-bar">
          <p class="hint">当前 {{ fmtAmount(trend.key.balance) }} {{ trend.key.currency }} · 共 {{ trend.records.length }} 条记录</p>
          <select class="trend-range" v-model.number="trendDays" @change="loadTrend" aria-label="时间范围">
            <option :value="7">最近 7 天</option>
            <option :value="30">最近 30 天</option>
            <option :value="90">最近 90 天</option>
            <option :value="365">最近一年</option>
          </select>
        </div>
        <div class="chart-wrap" v-if="trend.records.length"><canvas id="trend-chart"></canvas></div>
        <div class="empty" v-else style="padding:28px 10px">
          <p style="margin:0">该 Key 还没有余额记录</p>
        </div>
      </div>
    </div>
  </div>`,
  data: () => ({
    summary: {}, channels: [], channelTypes: [],
    fGroup: "", fType: "", sortBy: "balance_desc",
    trend: null, trendKeyId: null, trendDays: 90, chart: null,
  }),
  computed: {
    groups() {
      return [...new Set(this.channels.map(c => c.grp).filter(Boolean))];
    },
    balanceEntries() {
      const b = this.summary.balance_by_currency || {};
      return Object.entries(b).map(([cur, v]) => ({ cur, value: this.fmtAmount(v) }));
    },
    rows() {
      let out = [];
      for (const c of this.channels) {
        if (this.fGroup && c.grp !== this.fGroup) continue;
        if (this.fType && c.type !== this.fType) continue;
        for (const k of c.keys) out.push({ channel: c, key: k });
      }
      const bal = k => (k.balance === null || k.balance === undefined ? -Infinity : k.balance);
      if (this.sortBy === "balance_desc") out.sort((a, b) => bal(b.key) - bal(a.key));
      else if (this.sortBy === "balance_asc") out.sort((a, b) => bal(a.key) - bal(b.key));
      else if (this.sortBy === "updated") out.sort((a, b) => (b.key.balance_updated_at || "").localeCompare(a.key.balance_updated_at || ""));
      else out.sort((a, b) => a.channel.name.localeCompare(b.channel.name));
      return out;
    },
  },
  async created() { await this.load(); },
  methods: {
    fmtTime,
    fmtAmount(v) {
      if (v === null || v === undefined || v === "") return "—";
      const n = Number(v);
      if (Number.isNaN(n)) return String(v);
      return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    expiryOf(k) { return expiryInfo(k.expires_at); },
    badgeClass(k) {
      if (!k.enabled) return "warn";
      if (k.last_check === "ok") return "ok";
      if (k.last_check === "fail") return "fail";
      return "";
    },
    badgeText(k) {
      if (!k.enabled) return "停用";
      if (k.last_check === "ok") return "可用";
      if (k.last_check === "fail") return "异常";
      return "未验证";
    },
    async load() {
      const r = await api.get("/api/dashboard");
      this.summary = r.summary;
      this.channels = r.channels;
      const t = await api.get("/api/channels");
      this.channelTypes = t.channel_types;
    },
    async openTrend(k) {
      this.trendKeyId = k.id;
      await this.loadTrend();
    },
    async loadTrend() {
      if (!this.trendKeyId) return;
      const r = await api.get(`/api/dashboard/trend?key_id=${this.trendKeyId}&days=${this.trendDays}`);
      if (!r.ok) { this.$toast(r.error, "err"); return; }
      this.trend = r;
      this.$nextTick(() => this.drawChart());
    },
    drawChart() {
      const el = document.getElementById("trend-chart");
      if (!el || !window.Chart || !this.trend.records.length) return;
      const labels = this.trend.records.map(r => fmtTime(r.recorded_at));
      const data = this.trend.records.map(r => r.balance);
      if (this.chart) this.chart.destroy();
      this.chart = new window.Chart(el, {
        type: "line",
        data: {
          labels,
          datasets: [{
            label: `${this.trend.key.name} 余额（${this.trend.key.currency}）`,
            data, tension: 0.32, fill: true,
            borderColor: "#c7a15b", backgroundColor: "rgba(199,161,91,.10)",
            pointRadius: 2.5, pointHoverRadius: 4, pointBackgroundColor: "#0b110d",
            pointBorderColor: "#c7a15b", borderWidth: 2,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "#111a14", borderColor: "#28352b", borderWidth: 1,
              titleColor: "#eae4d5", bodyColor: "#9ba79c", padding: 10, displayColors: false,
              callbacks: { label: (c) => `${this.fmtAmount(c.parsed.y)} ${this.trend.key.currency}` },
            },
          },
          scales: {
            x: {
              grid: { color: "rgba(234,228,213,.05)" }, border: { color: "#1d2921" },
              ticks: { color: "#7c8a7f", maxTicksLimit: 7, font: { size: 10 } },
            },
            y: {
              grid: { color: "rgba(234,228,213,.05)" }, border: { display: false },
              ticks: { color: "#7c8a7f", font: { size: 10 }, callback: (v) => this.fmtAmount(v) },
            },
          },
        },
      });
    },
    closeTrend() {
      if (this.chart) { this.chart.destroy(); this.chart = null; }
      this.trend = null;
      this.trendKeyId = null;
    },
  },
};
