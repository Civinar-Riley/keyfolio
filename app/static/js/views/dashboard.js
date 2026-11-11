/** 统一看板：汇总统计 + 筛选排序 + 余额趋势图（Chart.js）。 */
import { api, expiryInfo, fmtBalance, fmtTime } from "../api.js";

export const DashboardView = {
  template: `
  <div>
    <div class="stat-grid">
      <div class="stat"><div class="v">{{ summary.channels_total ?? "—" }}</div><div class="l">渠道数</div></div>
      <div class="stat"><div class="v">{{ summary.keys_active ?? "—" }}<span class="hint" style="font-size:12px"> / {{ summary.keys_total }}</span></div><div class="l">启用 Key</div></div>
      <div class="stat"><div class="v dim">{{ balanceText }}</div><div class="l">总余额（按币种）</div></div>
      <div class="stat"><div class="v dim" style="font-size:13px">{{ fmtTime(summary.latest_update) }}</div><div class="l">最近余额更新</div></div>
    </div>

    <div class="card">
      <div class="inline-form" style="margin-bottom:4px">
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
      <table class="list" v-if="rows.length">
        <thead><tr><th>渠道 / Key</th><th>余额</th><th>状态</th><th class="m-hide">更新时间</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.key.id" style="cursor:pointer" @click="openTrend(r.key)">
            <td>
              <b>{{ r.channel.name }}</b> <span class="badge">{{ r.key.name }}</span>
              <div class="hint">{{ r.channel.grp || "" }}</div>
            </td>
            <td class="mono"><b>{{ fmtBalance(r.key) }}</b>
              <div class="hint" v-if="expiryOf(r.key)">
                <span class="badge" :class="expiryOf(r.key).cls">{{ expiryOf(r.key).text }}</span>
              </div>
            </td>
            <td>
              <span class="badge" :class="badgeClass(r.key)">{{ badgeText(r.key) }}</span>
            </td>
            <td class="hint m-hide">{{ fmtTime(r.key.balance_updated_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="hint" v-else style="padding:24px; text-align:center">还没有数据，先到「渠道」页添加</div>
    </div>

    <div class="modal-mask" v-if="trend" @click.self="closeTrend">
      <div class="modal">
        <h3>{{ trend.key.name }} · 余额趋势 <span class="badge">{{ trend.key.currency }}</span></h3>
        <p class="hint">当前 {{ trend.key.balance }} {{ trend.key.currency }} · 共 {{ trend.records.length }} 条记录</p>
        <label class="field" style="max-width:180px">范围
          <select v-model.number="trendDays" @change="loadTrend">
            <option :value="7">最近 7 天</option>
            <option :value="30">最近 30 天</option>
            <option :value="90">最近 90 天</option>
            <option :value="365">最近一年</option>
          </select>
        </label>
        <canvas id="trend-chart" height="220"></canvas>
        <div class="hint" v-if="!trend.records.length" style="text-align:center; padding:10px">该 Key 还没有余额记录</div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn" style="flex:1" @click="closeTrend">关闭</button>
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
    balanceText() {
      const b = this.summary.balance_by_currency || {};
      const parts = Object.entries(b).map(([cur, v]) => `${v} ${cur}`);
      return parts.length ? parts.join(" + ") : "—";
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
    fmtBalance, fmtTime,
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
            data, tension: 0.3, fill: true,
            borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.12)",
            pointRadius: 3,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { labels: { color: "#8ea0bf" } } },
          scales: {
            x: { ticks: { color: "#8ea0bf", maxTicksLimit: 8, font: { size: 10 } } },
            y: { ticks: { color: "#8ea0bf" } },
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
