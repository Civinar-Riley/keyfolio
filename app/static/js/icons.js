/** 线性图标集。所有图标随 currentColor 着色，尺寸由 font-size 控制。 */

const stroke = (body) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

export const ICONS = {
  dashboard: stroke('<path d="M12 6.5C10.2 5 7.8 4.3 5 4.3v14c2.8 0 5.2.7 7 2.2 1.8-1.5 4.2-2.2 7-2.2v-14c-2.8 0-5.2.7-7 2.2Z"/><path d="M12 6.5v14"/>'),
  channels: stroke('<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/>'),
  quickadd: stroke('<path d="M5 4h4v8a3 3 0 0 0 6 0V4h4v8a7 7 0 0 1-14 0V4Z"/><path d="M5 8h4M15 8h4"/>'),
  export: stroke('<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>'),
  settings: stroke('<path d="M4 7h4M12 7h8M4 17h8M16 17h4"/><circle cx="10" cy="7" r="2"/><circle cx="14" cy="17" r="2"/>'),
  lock: stroke('<rect x="4.5" y="10" width="15" height="10.5" rx="2"/><path d="M8 10V7.5a4 4 0 0 1 8 0V10"/><path d="M12 14v3"/>'),
  logout: stroke('<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="m9 16 4-4-4-4"/><path d="M13 12H3"/>'),
  plus: stroke('<path d="M12 5v14M5 12h14"/>'),
  search: stroke('<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>'),
  x: stroke('<path d="M6 6l12 12M18 6 6 18"/>'),
  check: stroke('<path d="m5 12.5 4.5 4.5L19 6.5"/>'),
  alert: stroke('<circle cx="12" cy="12" r="8.5"/><path d="M12 8v5"/><path d="M12 16.5h.01"/>'),
  external: stroke('<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>'),
  copy: stroke('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/>'),
  trash: stroke('<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M10 11v6M14 11v6"/>'),
  edit: stroke('<path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="m13.5 6.5 3 3"/>'),
  eye: stroke('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>'),
  "eye-off": stroke('<path d="M3 3l18 18"/><path d="M10.6 6.1A10.9 10.9 0 0 1 12 6c6 0 9.5 6 9.5 6a17 17 0 0 1-3.2 3.9"/><path d="M6.3 6.9A16.5 16.5 0 0 0 2.5 12S6 18 12 18a10.6 10.6 0 0 0 4.2-.9"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
  refresh: stroke('<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>'),
  clock: stroke('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 1.8"/>'),
  shield: stroke('<path d="M12 3 5 6v5.5c0 4.4 3 7.6 7 9.5 4-1.9 7-5.1 7-9.5V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>'),
  chart: stroke('<path d="M4 20V4"/><path d="M4 20h16"/><path d="m7 15 4-4 3 3 5-6"/>'),
  key: stroke('<circle cx="8" cy="8" r="4"/><path d="m11 11 9 9"/><path d="m16 16 2-2M19 19l2-2"/>'),
  "arrow-left": stroke('<path d="M20 12H4"/><path d="m10 6-6 6 6 6"/>'),
  "chevron-right": stroke('<path d="m9 5 7 7-7 7"/>'),
  "chevron-down": stroke('<path d="m5 9 7 7 7-7"/>'),
  download: stroke('<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>'),
  wallet: stroke('<path d="M4 7a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v1"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 13h3"/>'),
  seal: `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><mask id="kf-keyhole"><rect width="32" height="32" fill="#fff"/><circle cx="16" cy="14.1" r="3.8" fill="#000"/><path d="M14.05 16.5h3.9l1.35 7.1h-6.6z" fill="#000"/></mask></defs><circle cx="16" cy="16" r="13" fill="currentColor" mask="url(#kf-keyhole)"/></svg>`,
};

let sealSeq = 0;

export const KIcon = {
  props: { name: { type: String, required: true } },
  computed: {
    svg() {
      const markup = ICONS[this.name] || "";
      if (this.name !== "seal") return markup;
      // 同一页面可能有多个印章，给遮罩一个唯一 id
      const id = `kf-keyhole-${++sealSeq}`;
      return markup.split("kf-keyhole").join(id);
    },
  },
  template: `<span class="k-icon" v-html="svg"></span>`,
};
