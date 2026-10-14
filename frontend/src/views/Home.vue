<template>
  <div class="dash" v-loading="loading">
    <h2 class="page-title">仪表盘</h2>

    <div class="stat-grid">
      <div v-for="item in countCards" :key="item.title" class="panel stat-card">
        <div class="stat-icon" :class="item.tone">
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="muted">{{ item.title }}</div>
          <div class="stat-num">{{ item.value }}<small>{{ item.unit }}</small></div>
          <div class="sub">{{ item.sub }}</div>
        </div>
      </div>
    </div>

    <div class="stat-grid">
      <div v-for="item in moneyCards" :key="item.title" class="panel money-card">
        <div class="money-head">
          <div class="stat-icon sm" :class="item.tone">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <div>
            <div class="muted">{{ item.title }}</div>
            <div class="money-num">¥{{ money(item.value) }}</div>
          </div>
        </div>
        <div class="money-foot">
          <span>{{ item.monthLabel }} {{ money(item.month) }}</span>
          <span>{{ item.rateLabel }}</span>
        </div>
        <div class="bar"><i :class="item.tone" :style="{ width: barWidth(item.rate) }"></i></div>
        <div class="rate" :class="item.tone">{{ item.rate }}%</div>
      </div>
    </div>

    <div class="panel remind">
      <div class="panel-head">
        <div class="head-left">
          <el-icon><Bell /></el-icon>
          <strong>最近提醒</strong>
          <el-select v-model="reminderKind" size="small" style="width:120px">
            <el-option v-for="opt in reminderOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </div>
        <el-badge :value="reminders.length" :hidden="!reminders.length" type="danger">
          <el-button link type="primary" @click="router.push('/reminder')">查看全部</el-button>
        </el-badge>
      </div>
      <div v-if="shownReminders.length" class="remind-list">
        <div v-for="(row, index) in shownReminders" :key="index" class="remind-row">
          <span class="arrow" :class="row.kind === 'sale' || row.kind === 'output' ? 'up' : 'down'">
            <el-icon><component :is="row.kind === 'sale' || row.kind === 'output' ? Top : Bottom" /></el-icon>
          </span>
          <span class="tag-soft">{{ row.label }}</span>
          <span class="grow name">{{ row.name }}</span>
          <span class="code">{{ row.code }}</span>
          <span class="party">{{ row.party_name }}</span>
          <span class="date">{{ row.due_date }}</span>
          <span class="days" :class="row.days < 0 ? 'over' : 'left'">{{ dayText(row.days) }}</span>
          <el-button link type="primary" @click="openReminder(row)">查看</el-button>
        </div>
      </div>
      <div v-else class="empty">暂无提醒</div>
    </div>

    <div class="split">
      <div class="panel">
        <div class="panel-head">
          <strong>合同金额趋势</strong>
        </div>
        <div class="chart-box" @mouseleave="tip = null">
          <svg :viewBox="`0 0 ${chart.w} ${chart.h}`" class="chart">
            <line v-for="tick in chart.ticks" :key="tick.y" :x1="chart.l" :x2="chart.w - 12" :y1="tick.y" :y2="tick.y" class="grid" />
            <text v-for="tick in chart.ticks" :key="'t'+tick.y" :x="chart.l - 8" :y="tick.y + 4" class="axis" text-anchor="end">{{ tick.label }}</text>
            <polyline :points="chart.sale" class="line sale" />
            <polyline :points="chart.purchase" class="line purchase" />
            <g v-for="(point, index) in chart.points" :key="index">
              <rect :x="point.hit" y="8" :width="chart.slot" :height="chart.h - 28" fill="transparent" @mouseenter="showTip($event, point)" />
              <circle :cx="point.x" :cy="point.ySale" r="3.5" class="dot sale" />
              <circle :cx="point.x" :cy="point.yPurchase" r="3.5" class="dot purchase" />
              <text v-if="point.show" :x="point.x" :y="chart.h - 8" class="axis" text-anchor="middle">{{ point.label }}</text>
            </g>
          </svg>
          <div v-if="tip" class="float-tip" :style="{ left: tip.left + 'px', top: tip.top + 'px' }">
            <div>{{ tip.label }}</div>
            <div><i class="legend-dot sale"></i>销售合同金额 ¥{{ money(tip.sale) }}</div>
            <div><i class="legend-dot purchase"></i>采购合同金额 ¥{{ money(tip.purchase) }}</div>
          </div>
        </div>
        <div class="legend">
          <span><i class="legend-dot sale"></i>销售合同金额</span>
          <span><i class="legend-dot purchase"></i>采购合同金额</span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><strong>合同状态分布</strong></div>
        <div class="donut-wrap" @mouseleave="donutTip = null">
          <svg viewBox="0 0 160 160" class="donut">
            <circle v-if="!donut.segs.length" cx="80" cy="80" r="54" class="ring-empty" />
            <circle
              v-for="seg in donut.segs"
              :key="seg.name"
              cx="80"
              cy="80"
              r="54"
              fill="none"
              :stroke="seg.color"
              stroke-width="18"
              :stroke-dasharray="seg.dash"
              :stroke-dashoffset="seg.offset"
              transform="rotate(-90 80 80)"
              @mouseenter="showDonut($event, seg)"
            />
            <text x="80" y="74" text-anchor="middle" class="donut-label">合同总数</text>
            <text x="80" y="100" text-anchor="middle" class="donut-num">{{ donut.total }}</text>
          </svg>
          <div v-if="donutTip" class="float-tip" :style="{ left: donutTip.left + 'px', top: donutTip.top + 'px' }">
            <div>{{ donutTip.name }} {{ donutTip.count }}</div>
            <div>{{ donutTip.pct }}%</div>
            <div>金额：{{ money(donutTip.amount) }}</div>
            <div>已收付：{{ money(donutTip.settled) }}</div>
          </div>
        </div>
        <div class="legend">
          <span v-for="seg in board.status" :key="seg.name" @mouseenter="pinDonut(seg)" @mouseleave="donutTip = null">
            <i class="legend-dot" :style="{ background: statusColor(seg.name) }"></i>{{ seg.name }}
          </span>
        </div>
      </div>
    </div>

    <div class="split bottom">
      <div class="panel">
        <div class="panel-head">
          <div class="head-left">
            <el-icon><Document /></el-icon>
            <strong>最近合同</strong>
          </div>
          <div class="tabs">
            <button :class="{ on: contractTab === 'sale' }" @click="contractTab = 'sale'">销售合同</button>
            <button :class="{ on: contractTab === 'purchase' }" @click="contractTab = 'purchase'">采购合同</button>
          </div>
        </div>
        <div v-if="contractRows.length" class="feed">
          <div v-for="row in contractRows" :key="row.id" class="feed-row">
            <div>
              <div class="feed-title">{{ row.name }} <b>¥{{ money(row.amount) }}</b></div>
              <div class="sub">{{ row.party_name }}　{{ row.date }}</div>
            </div>
            <div class="feed-ops">
              <el-tag :type="row.status === '已签订' ? 'success' : row.status === '未签订' ? 'warning' : 'info'" size="small">{{ row.status }}</el-tag>
              <el-button link type="primary" @click="openContract(row)">查看</el-button>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无合同</div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div class="head-left">
            <el-icon><Wallet /></el-icon>
            <strong>最近交易</strong>
          </div>
          <div class="tabs">
            <button :class="{ on: billTab === 'receipt' }" @click="billTab = 'receipt'">查看收款</button>
            <button :class="{ on: billTab === 'payment' }" @click="billTab = 'payment'">查看付款</button>
          </div>
        </div>
        <div v-if="billRows.length" class="feed">
          <div v-for="row in billRows" :key="row.id" class="feed-row">
            <div>
              <div class="feed-title">{{ billTab === "receipt" ? "收款" : "付款" }} · {{ money(row.amount) }}</div>
              <div class="sub">{{ row.party_name || "—" }}　{{ row.bill_date }}</div>
            </div>
            <div class="feed-ops">
              <el-tag type="success" size="small">已入账</el-tag>
              <el-button link type="primary" @click="openBill">查看</el-button>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无交易</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Bell, Bottom, CircleCheck, Document, Lock, OfficeBuilding, Ticket, Top, User, Wallet } from "@element-plus/icons-vue";
import http, { money } from "../api";

const router = useRouter();
const loading = ref(false);
const board = ref({ counts: {}, money: {}, reminders: [], trend: [], status: [], contracts: { sale: [], purchase: [] }, bills: { receipt: [], payment: [] } });
const reminderKind = ref("all");
const contractTab = ref("sale");
const billTab = ref("receipt");
const tip = ref(null);
const donutTip = ref(null);
const reminderOptions = [
  { label: "全部", value: "all" },
  { label: "销售合同", value: "sale" },
  { label: "采购合同", value: "purchase" },
  { label: "销项发票", value: "output" },
  { label: "进项发票", value: "input" },
];

const countCards = computed(() => {
  const counts = board.value.counts || {};
  return [
    { title: "合同总数", value: counts.contracts || 0, unit: "份", sub: `本月新增 ${counts.contracts_month || 0}份`, tone: "blue", icon: Document },
    { title: "已完成合同", value: counts.done || 0, unit: "份", sub: `完成率 ${counts.done_rate || "0.0"}%`, tone: "green", icon: CircleCheck },
    { title: "客户总数", value: counts.customers || 0, unit: "个", sub: `本月新增 ${counts.customers_month || 0}个`, tone: "purple", icon: User },
    { title: "供应商总数", value: counts.suppliers || 0, unit: "个", sub: `本月新增 ${counts.suppliers_month || 0}个`, tone: "cyan", icon: OfficeBuilding },
  ];
});
const moneyCards = computed(() => {
  const row = board.value.money || {};
  return [
    { title: "已收款", value: row.received, month: row.received_month, monthLabel: "本月收款", rate: row.received_rate || "0.0", rateLabel: "收款比例", tone: "green", icon: Wallet },
    { title: "已开票", value: row.invoiced_out, month: row.invoiced_out_month, monthLabel: "本月开票", rate: row.invoiced_out_rate || "0.0", rateLabel: "开票比例", tone: "pink", icon: Ticket },
    { title: "已付款", value: row.paid, month: row.paid_month, monthLabel: "本月付款", rate: row.paid_rate || "0.0", rateLabel: "付款比例", tone: "orange", icon: Wallet },
    { title: "已收票", value: row.invoiced_in, month: row.invoiced_in_month, monthLabel: "本月收票", rate: row.invoiced_in_rate || "0.0", rateLabel: "收票比例", tone: "blue", icon: Lock },
  ];
});
const reminders = computed(() => {
  const rows = board.value.reminders || [];
  if (!reminderKind.value || reminderKind.value === "all") return rows;
  return rows.filter((row) => row.kind === reminderKind.value);
});
const shownReminders = computed(() => reminders.value.slice(0, 6));
const contractRows = computed(() => board.value.contracts?.[contractTab.value] || []);
const billRows = computed(() => board.value.bills?.[billTab.value] || []);

function niceMax(value) {
  if (value <= 0) return 1000;
  const pow = 10 ** Math.floor(Math.log10(value));
  const step = value / pow;
  const nice = step <= 1 ? 1 : step <= 2 ? 2 : step <= 5 ? 5 : 10;
  return nice * pow;
}
function axisText(value) {
  return Math.round(value).toLocaleString("zh-CN");
}
const chart = computed(() => {
  const rows = board.value.trend || [];
  const w = 720;
  const h = 280;
  const l = 72;
  const top = 16;
  const bottom = 36;
  const max = niceMax(Math.max(0, ...rows.map((row) => Math.max(Number(row.sale) || 0, Number(row.purchase) || 0))));
  const innerW = w - l - 16;
  const innerH = h - top - bottom;
  const slot = rows.length ? innerW / rows.length : innerW;
  const x = (index) => (rows.length <= 1 ? l + innerW / 2 : l + (index / (rows.length - 1)) * innerW);
  const y = (value) => top + (1 - (Number(value) || 0) / max) * innerH;
  const points = rows.map((row, index) => ({
    x: x(index),
    hit: x(index) - slot / 2,
    ySale: y(row.sale),
    yPurchase: y(row.purchase),
    label: row.label,
    show: index % 3 === 0,
    sale: row.sale,
    purchase: row.purchase,
  }));
  return {
    w, h, l, slot,
    ticks: [0, 0.25, 0.5, 0.75, 1].map((part) => ({ y: top + (1 - part) * innerH, label: axisText(max * part) })),
    sale: points.map((point) => `${point.x},${point.ySale}`).join(" "),
    purchase: points.map((point) => `${point.x},${point.yPurchase}`).join(" "),
    points,
  };
});
const donut = computed(() => {
  const rows = board.value.status || [];
  const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
  const length = 2 * Math.PI * 54;
  let cursor = 0;
  const segs = rows.filter((row) => Number(row.count) > 0).map((row) => {
    const span = total ? (Number(row.count) / total) * length : 0;
    const seg = {
      ...row,
      color: statusColor(row.name),
      dash: `${span} ${length - span}`,
      offset: -cursor,
      pct: total ? ((Number(row.count) / total) * 100).toFixed(1) : "0.0",
    };
    cursor += span;
    return seg;
  });
  return { total, segs };
});

function statusColor(name) {
  if (name === "已签订") return "#3b82f6";
  if (name === "未签订") return "#22c55e";
  return "#94a3b8";
}
function barWidth(rate) {
  const value = Number(rate) || 0;
  return `${Math.max(0, Math.min(100, value))}%`;
}
function dayText(days) {
  if (days < 0) return `过期 ${-days}天`;
  if (days === 0) return "今日到期";
  return `剩余 ${days}天`;
}
function showTip(event, point) {
  const box = event.currentTarget.closest(".chart-box").getBoundingClientRect();
  tip.value = { ...point, left: Math.min(event.clientX - box.left + 12, box.width - 180), top: Math.max(8, event.clientY - box.top - 72) };
}
function showDonut(event, seg) {
  const box = event.currentTarget.closest(".donut-wrap").getBoundingClientRect();
  donutTip.value = { ...seg, left: event.clientX - box.left + 8, top: event.clientY - box.top - 8 };
}
function pinDonut(seg) {
  const found = donut.value.segs.find((row) => row.name === seg.name) || { ...seg, pct: "0.0" };
  donutTip.value = { ...found, left: 180, top: 24 };
}
function openReminder(row) {
  if (row.target === "contract") {
    router.push({ path: row.kind === "sale" ? "/contract/sale" : "/contract/purchase", query: { open: row.id } });
    return;
  }
  router.push({ path: row.kind === "output" ? "/invoice/output" : "/invoice/input", query: { open: row.id } });
}
function openContract(row) {
  router.push({ path: contractTab.value === "sale" ? "/contract/sale" : "/contract/purchase", query: { open: row.id } });
}
function openBill() {
  router.push(billTab.value === "receipt" ? "/settlement/receipt" : "/settlement/payment");
}
async function load() {
  loading.value = true;
  try {
    const res = await http.get("/api/stats/home");
    if (res.data.board) board.value = res.data.board;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.panel { background: var(--card); border-radius: 8px; box-shadow: var(--shadow); padding: 14px 16px; }
.stat-card, .money-head, .head-left, .feed-ops, .legend, .tabs { display: flex; align-items: center; }
.stat-card { gap: 14px; min-height: 96px; }
.stat-icon { width: 42px; height: 42px; border-radius: 10px; display: grid; place-items: center; font-size: 20px; flex: none; }
.stat-icon.sm { width: 36px; height: 36px; font-size: 18px; }
.stat-icon.blue, .rate.blue { color: #1677ff; } .stat-icon.blue { background: #e8f3ff; }
.stat-icon.green, .rate.green { color: #16a34a; } .stat-icon.green { background: #e8f8ef; }
.stat-icon.purple { color: #7c3aed; background: #f3e8ff; }
.stat-icon.cyan { color: #0891b2; background: #e0f7fb; }
.stat-icon.pink, .rate.pink { color: #db2777; } .stat-icon.pink { background: #fce7f3; }
.stat-icon.orange, .rate.orange { color: #ea580c; } .stat-icon.orange { background: #fff1e6; }
.stat-body { min-width: 0; }
.muted, .sub, .code, .party, .date { color: var(--muted); font-size: 12px; }
.stat-num { font-size: 26px; font-weight: 700; line-height: 1.2; margin: 2px 0; }
.stat-num small { font-size: 14px; font-weight: 500; margin-left: 2px; }
.money-card { position: relative; padding-bottom: 28px; }
.money-head { gap: 10px; }
.money-num { font-size: 22px; font-weight: 700; line-height: 1.3; }
.money-foot { display: flex; justify-content: space-between; gap: 8px; margin-top: 12px; color: var(--muted); font-size: 12px; }
.bar { height: 4px; border-radius: 99px; background: #f0f0f0; margin-top: 8px; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 99px; }
.bar i.green { background: #22c55e; }
.bar i.pink { background: #ec4899; }
.bar i.orange { background: #f59e0b; }
.bar i.blue { background: #3b82f6; }
.rate { position: absolute; right: 16px; bottom: 8px; font-size: 12px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.head-left { gap: 8px; }
.remind-list { display: flex; flex-direction: column; }
.remind-row { display: grid; grid-template-columns: 28px 108px minmax(120px, 1.4fr) minmax(100px, 1fr) minmax(100px, 1fr) 96px 72px 52px; gap: 8px; align-items: center; min-height: 42px; border-top: 1px solid var(--border); font-size: 13px; }
.arrow { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; }
.arrow.up { background: #fff1e6; color: #ea580c; }
.arrow.down { background: #fce7f3; color: #db2777; }
.tag-soft { color: #4e5969; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.days { font-size: 12px; }
.days.over { color: #f53f3f; }
.days.left { color: #d46b08; }
.empty { color: var(--muted); padding: 28px 0; text-align: center; }
.split { display: grid; grid-template-columns: 1.45fr 0.85fr; gap: 12px; }
.split.bottom { grid-template-columns: 1fr 1fr; }
.chart-box, .donut-wrap { position: relative; }
.chart { width: 100%; height: 280px; display: block; }
.grid { stroke: var(--border); stroke-width: 1; }
.axis { fill: var(--muted); font-size: 11px; }
.line { fill: none; stroke-width: 2; }
.line.sale, .dot.sale { stroke: #3b82f6; }
.line.purchase, .dot.purchase { stroke: #f59e0b; }
.dot { fill: #fff; stroke-width: 2; }
.legend { justify-content: center; gap: 18px; color: var(--muted); font-size: 12px; margin-top: 4px; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.legend-dot.sale { background: #3b82f6; }
.legend-dot.purchase { background: #f59e0b; }
.donut { width: 220px; height: 220px; display: block; margin: 8px auto; }
.donut-label { fill: var(--muted); font-size: 12px; }
.donut-num { fill: var(--text); font-size: 28px; font-weight: 700; }
.ring-empty { fill: none; stroke: var(--border); stroke-width: 18; }
.float-tip { position: absolute; z-index: 2; min-width: 160px; padding: 8px 10px; border-radius: 6px; background: var(--card); border: 1px solid var(--border); box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12); font-size: 12px; line-height: 1.7; pointer-events: none; }
.tabs { gap: 4px; }
.tabs button { border: none; background: transparent; color: var(--muted); cursor: pointer; padding: 4px 8px; border-radius: 4px; }
.tabs button.on { color: var(--primary); background: #e8f3ff; }
.feed { display: flex; flex-direction: column; }
.feed-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; min-height: 58px; border-top: 1px solid var(--border); }
.feed-title { font-size: 14px; }
.feed-title b { color: var(--primary); font-weight: 600; margin-left: 8px; }
.feed-ops { gap: 8px; flex: none; }
@media (max-width: 1100px) {
  .stat-grid, .split, .split.bottom { grid-template-columns: 1fr 1fr; }
  .remind-row { grid-template-columns: 28px 96px 1fr 72px 52px; }
  .code, .party { display: none; }
}
</style>
