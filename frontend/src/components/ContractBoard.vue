<template>
  <div class="board" v-if="detail">
    <div class="board-summary" :class="sale ? 'sale' : 'purchase'">
      <div class="sum-line">
        <span><em>合同编号</em> {{ detail.contract_code }}</span>
        <span><em>合同名称</em> <b>{{ detail.name }}</b></span>
        <span><em>合同类型</em> <i :class="['tag', 'tag-orange']">{{ detail.type_name || "—" }}</i></span>
        <span><em>合同状态</em> <i :class="['tag', statusClass(detail.status)]">{{ detail.status }}</i></span>
        <span><em>{{ sale ? "发货情况" : "到货情况" }}</em> <i :class="['tag', moveClass(detail.move_state)]">{{ detail.move_state || "—" }}</i></span>
      </div>
      <div class="sum-line">
        <span><em>合同金额</em> {{ money(detail.amount) }}</span>
        <span><em>{{ sale ? "合同预收" : "合同预付" }}</em> {{ money(detail.prepaid) }}</span>
        <span><em>{{ sale ? "累计收款金额" : "累计付款金额" }}</em> {{ money(detail.settled || detail.paid_now) }}</span>
        <span><em>{{ sale ? "未收款" : "未付款" }}</em> <b :class="{ danger: positive(detail.unpaid) }">{{ money(detail.unpaid) }}</b></span>
        <span><em>{{ sale ? "未开票" : "未收票" }}</em> <b :class="{ danger: positive(detail.uninvoiced) }">{{ money(detail.uninvoiced) }}</b></span>
      </div>
    </div>

    <div class="board-tabs">
      <button v-for="item in tabs" :key="item.key" type="button" :class="{ on: tab === item.key }" @click="tab = item.key">{{ item.label }}</button>
    </div>

    <div v-if="tab === 'info'" class="info-grid">
      <div class="cell"><em>合同编号</em><span>{{ detail.contract_code }}</span></div>
      <div class="cell"><em>合同类型</em><span><i class="tag tag-orange">{{ detail.type_name || "—" }}</i></span></div>
      <div class="cell"><em>合同名称</em><span>{{ detail.name }}</span></div>
      <div class="cell"><em>合同状态</em><span><i :class="['tag', statusClass(detail.status)]">{{ detail.status }}</i> <i class="tag tag-gray">{{ detail.archived_label || "未归档" }}</i></span></div>
      <div class="cell"><em>计价方式</em><span><i :class="['tag', detail.pricing === 'actual' ? 'tag-purple' : 'tag-blue-soft']">{{ detail.pricing_label }}</i></span></div>
      <div class="cell"></div>
      <div class="cell"><em>合同金额</em><span>{{ money(detail.amount) }}</span></div>
      <div class="cell"><em>增值税税率</em><span>{{ detail.tax_text || (detail.tax_rate + "%") }}</span></div>
      <div class="cell"><em>{{ sale ? "合同已收款" : "合同已付款" }}</em><span>{{ money(detail.settled) }}</span></div>
      <div class="cell"><em>{{ sale ? "合同未收款" : "合同未付款" }}</em><span :class="{ danger: positive(detail.unpaid) }">{{ money(detail.unpaid) }}</span></div>
      <div class="cell wide"><em>{{ sale ? "累计收款金额" : "累计付款金额" }}</em><span>{{ money(sale ? (detail.settled || detail.paid_now) : (detail.settled || detail.paid_now)) }}</span></div>
      <div class="cell"><em>{{ sale ? "已收款" : "已付款" }}</em><span>{{ money(detail.paid_now || detail.settled) }}</span></div>
      <div class="cell"><em>{{ sale ? "已开票" : "已收票" }}</em><span>{{ money(detail.invoiced) }}</span></div>
      <div class="cell"><em>{{ sale ? "未收款" : "未付款" }}</em><span :class="{ danger: positive(detail.unpaid) }">{{ money(detail.unpaid) }}</span></div>
      <div class="cell"><em>{{ sale ? "未开票" : "未收票" }}</em><span :class="{ danger: positive(detail.uninvoiced) }">{{ money(detail.uninvoiced) }}</span></div>
      <div class="cell"><em>{{ sale ? "收款未开票" : "付款未收票" }}</em><span>{{ money(detail.paid_not_invoiced) }}</span></div>
      <div class="cell"><em>{{ sale ? "开票未收款" : "收票未付款" }}</em><span>{{ money(detail.invoiced_not_paid) }}</span></div>
      <div class="cell"><em>{{ sale ? "收款进度" : "付款进度" }}</em><span class="pct" :style="{ '--p': payBar }"><i /><em>{{ sale ? (detail.pay_percent || "0%") : (detail.stage_text || "0/0") }}</em></span></div>
      <div class="cell"><em>{{ sale ? "开票进度" : "收票进度" }}</em><span class="pct" :style="{ '--p': detail.invoice_percent || '0%' }"><i /><em>{{ detail.invoice_percent || "0%" }}</em></span></div>
      <div class="cell"><em>{{ sale ? "客户编码" : "供应商编码" }}</em><span class="cell-link">{{ detail.party_code || "—" }}</span></div>
      <div class="cell"><em>{{ sale ? "客户名称" : "供应商名称" }}</em><span>{{ detail.party_name || "—" }}</span></div>
      <div class="cell"><em>签订日期</em><span>{{ detail.sign_date || "—" }}</span></div>
      <div class="cell wide"><em>关联项目</em><span class="cell-link">{{ detail.project_name || "—" }}</span></div>
      <div class="cell wide"><em>{{ sale ? "关联采购" : "关联销售" }}</em><span>{{ linkedText }}</span></div>
      <div class="cell wide"><em>业务员</em><span>{{ detail.owner_name || "—" }}</span></div>
      <div class="cell wide"><em>合同内容概述</em><span>{{ detail.content || "—" }}</span></div>
      <div class="cell wide"><em>合同条款</em><span>{{ detail.terms || "—" }}</span></div>
      <div class="cell"><em>创建人</em><span>{{ detail.created_by_name || "—" }}</span></div>
      <div class="cell"><em>更新人</em><span>{{ detail.updated_by_name || "—" }}</span></div>
      <div class="cell"><em>创建时间</em><span>{{ detail.created_at || "—" }}</span></div>
      <div class="cell"><em>更新时间</em><span>{{ detail.updated_at || "—" }}</span></div>
      <div class="cell wide"><em>备注</em><span>{{ detail.remark || "—" }}</span></div>
      <div class="cell wide"><em>附件</em><span>无附件</span></div>
    </div>

    <div v-else-if="tab === 'goods'">
      <div class="board-tool"><span>条目个数：{{ detail.items?.length || 0 }}　金额合计：{{ money(detail.amount) }}</span></div>
      <div class="line-box line-scroll" v-if="detail.items?.length">
      <table class="board-table">
        <thead><tr><th>商品编码</th><th>商品名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>{{ sale ? "已开票" : "已收票" }}</th><th>{{ sale ? "未开票" : "未收票" }}</th><th>单价</th><th>含税单价</th><th>含税金额</th></tr></thead>
        <tbody>
          <tr v-for="row in detail.items" :key="row.material_code">
            <td class="cell-link">{{ row.material_code }}</td>
            <td>{{ row.name_cn }}</td>
            <td>{{ row.spec || "—" }}</td>
            <td>{{ row.unit || "—" }}</td>
            <td>{{ row.qty }}</td>
            <td>{{ row.invoiced_qty || "0" }}</td>
            <td>{{ row.uninvoiced_qty || "0" }}</td>
            <td class="money">{{ exPrice(row) }}</td>
            <td class="money">{{ money(row.price) }}</td>
            <td class="money">{{ money(row.amount) }}</td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-else class="empty-box">暂无数据</div>
    </div>

    <div v-else-if="tab === 'pay'">
      <div class="board-tool">
        <el-button type="primary" @click="$emit('go', sale ? 'receipt' : 'payment')">+ 新增{{ sale ? "收款" : "付款" }}记录</el-button>
        <span>计划合计：{{ money(detail.amount) }}　已{{ sale ? "收款" : "付款" }}：{{ money(detail.settled) }}　未{{ sale ? "收款" : "付款" }}：<b :class="{ danger: positive(detail.unpaid) }">{{ money(detail.unpaid) }}</b></span>
      </div>
      <div v-if="detail.stages?.length">
        <section v-for="(row, index) in detail.stages" :key="row.id || index" class="pay-stage">
          <div class="pay-stage-head">
            <div class="pay-stage-title">
              <b>{{ row.name }}</b>
              <span class="cell-link">{{ planCode(index) }}</span>
              <span class="cell-link">{{ dueCode(index) }}</span>
              <i :class="['tag', positive(row.remain) ? 'tag-gray' : 'tag-green']">{{ positive(row.remain) ? (sale ? "未收款" : "未付款") : (sale ? "已收款" : "已付款") }}</i>
            </div>
            <div class="pay-meta">
              <span><em>{{ sale ? "收款比例" : "付款比例" }}</em>{{ row.ratio }}%</span>
              <span><em>计划金额</em>{{ money(row.plan_amount) }}</span>
              <span><em>计划日期</em>{{ row.plan_date || "—" }}</span>
              <span><em>已{{ sale ? "收款" : "付款" }}</em>{{ money(row.settled_amount) }}</span>
              <span><em>未{{ sale ? "收款" : "付款" }}</em><b :class="{ danger: positive(row.remain) }">{{ money(row.remain) }}</b></span>
              <span class="pct" :style="{ '--p': stagePct(row) }"><i /><em>{{ stagePct(row) }}</em></span>
            </div>
          </div>
          <table class="board-table" v-if="stageBills(row).length">
            <thead><tr><th>单据日期</th><th>单据编号</th><th>{{ sale ? "收款金额" : "付款金额" }}</th><th>本次核销</th><th>账户</th></tr></thead>
            <tbody>
              <tr v-for="bill in stageBills(row)" :key="bill.id">
                <td>{{ bill.bill_date }}</td>
                <td class="cell-link">{{ bill.bill_code }}</td>
                <td class="money">{{ money(bill.amount) }}</td>
                <td class="money">{{ money(bill.amount) }}</td>
                <td>{{ bill.account_name || "—" }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="pay-empty">本阶段暂无{{ sale ? "收款" : "付款" }}记录</div>
        </section>
        <section v-if="orphanBills.length" class="pay-stage">
          <div class="pay-stage-head"><div class="pay-stage-title"><b>未对应阶段的{{ sale ? "收款" : "付款" }}</b></div></div>
          <table class="board-table">
            <thead><tr><th>单据日期</th><th>单据编号</th><th>{{ sale ? "收款金额" : "付款金额" }}</th><th>阶段</th><th>账户</th></tr></thead>
            <tbody>
              <tr v-for="bill in orphanBills" :key="bill.id">
                <td>{{ bill.bill_date }}</td>
                <td class="cell-link">{{ bill.bill_code }}</td>
                <td class="money">{{ money(bill.amount) }}</td>
                <td>{{ bill.stage_name || "—" }}</td>
                <td>{{ bill.account_name || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
      <div v-else class="empty-box">暂无数据</div>
    </div>

    <div v-else-if="tab === 'invoice'">
      <div class="board-tool">
        <el-button type="primary" @click="$emit('go', sale ? 'output' : 'input')">+ 新增{{ sale ? "销项" : "进项" }}发票</el-button>
        <span>发票金额（含税）合计：{{ money(invoiceSum) }}</span>
      </div>
      <table class="board-table" v-if="invoices.length">
        <thead><tr><th>单据日期</th><th>单据编号</th><th>发票号码</th><th>发票类型</th><th>{{ sale ? "客户编码" : "供应商编码" }}</th><th>{{ sale ? "客户名称" : "供应商名称" }}</th><th>不含税金额</th><th>税额</th><th>价税合计</th></tr></thead>
        <tbody>
          <tr v-for="row in invoices" :key="row.id">
            <td>{{ row.bill_date }}</td>
            <td>{{ row.bill_code || "—" }}</td>
            <td class="cell-link">{{ row.invoice_no }}</td>
            <td>{{ row.invoice_type }}</td>
            <td class="cell-link">{{ row.party_code || detail.party_code }}</td>
            <td>{{ row.party_name }}</td>
            <td class="money">{{ money(row.amount_ex_tax) }}</td>
            <td class="money">{{ money(row.tax) }}</td>
            <td class="money">{{ money(row.total) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-box">暂无数据</div>
    </div>

    <div v-else-if="tab === 'purchase'">
      <table class="board-table" v-if="linked.length">
        <thead><tr><th>合同编号</th><th>合同名称</th><th>供应商</th><th>合同金额</th><th>已付款</th><th>未付款</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in linked" :key="row.id">
            <td class="cell-link">{{ row.contract_code }}</td>
            <td>{{ row.name }}</td>
            <td>{{ row.party_name }}</td>
            <td class="money">{{ money(row.amount) }}</td>
            <td class="money">{{ money(row.settled) }}</td>
            <td class="money danger">{{ money(row.unpaid) }}</td>
            <td><i :class="['tag', statusClass(row.status)]">{{ row.status }}</i></td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-box">暂无数据</div>
    </div>

    <div v-else-if="tab === 'expense'">
      <table class="board-table" v-if="expenses.length">
        <thead><tr><th>单据日期</th><th>单据编号</th><th>客商</th><th>金额</th><th>账户</th><th>备注</th></tr></thead>
        <tbody>
          <tr v-for="row in expenses" :key="row.id">
            <td>{{ row.bill_date }}</td>
            <td>{{ row.bill_code }}</td>
            <td>{{ row.party_name || "—" }}</td>
            <td class="money">{{ money(row.amount) }}</td>
            <td>{{ row.account_name || "—" }}</td>
            <td>{{ row.remark || "—" }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-box">暂无数据</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { money } from "../api";

const props = defineProps({
  detail: Object,
  direction: String,
  invoices: { type: Array, default: () => [] },
  settles: { type: Array, default: () => [] },
  expenses: { type: Array, default: () => [] },
  linked: { type: Array, default: () => [] },
});
defineEmits(["go"]);
const tab = ref("info");
const sale = computed(() => props.direction === "sale");
const payBar = computed(() => (sale.value ? props.detail?.pay_percent || "0%" : fractionFill(props.detail?.stage_text)));
function fractionFill(value) {
  const frac = String(value || "").match(/^(\d+)\/(\d+)$/);
  if (!frac) return "0%";
  const total = Number(frac[2]);
  return total ? `${Math.min(100, Math.round((Number(frac[1]) / total) * 100))}%` : "0%";
}
const tabs = computed(() => {
  const goods = `合同商品(${props.detail?.items?.length || 0})`;
  const invoice = `${sale.value ? "开票记录" : "收票记录"}(${props.invoices.length})`;
  const base = [
    { key: "info", label: "合同信息" },
    { key: "goods", label: goods },
  ];
  base.push({ key: "pay", label: `${sale.value ? "收款" : "付款"}(${props.detail?.stages?.length || 0})` });
  base.push({ key: "invoice", label: invoice });
  if (sale.value) {
    base.push({ key: "purchase", label: `采购合同(${props.linked.length})` });
    base.push({ key: "expense", label: `其他支出(${props.expenses.length})` });
  }
  return base;
});
const invoiceSum = computed(() => props.invoices.reduce((sum, row) => sum + Number(String(row.total || 0).replace(/,/g, "")), 0));
const linkedText = computed(() => (props.linked.length ? props.linked.map((row) => row.contract_code).join("、") : "—"));

function positive(value) {
  return Number(String(value || 0).replace(/,/g, "")) > 0;
}
function statusClass(text) {
  if (text === "已签订") return "tag-blue";
  if (text === "已终止") return "tag-red";
  return "tag-gray";
}
function moveClass(text) {
  if (text === "已到货" || text === "已发货") return "tag-green";
  if (text === "部分到货" || text === "部分发货") return "tag-orange";
  return "tag-gray";
}
function exPrice(row) {
  const rate = Number(props.detail?.tax_rate || 0) / 100;
  const price = Number(String(row.price || 0).replace(/,/g, ""));
  return money(rate ? price / (1 + rate) : price);
}
function planCode(index) {
  return `${sale.value ? "SKJH" : "FKJH"}-${props.detail.contract_code}-${String(index + 1).padStart(2, "0")}`;
}
function dueCode(index) {
  return `${sale.value ? "YS" : "YF"}-${props.detail.contract_code}-${String(index + 1).padStart(2, "0")}`;
}
function stagePct(row) {
  const plan = Number(String(row.plan_amount || 0).replace(/,/g, ""));
  const paid = Number(String(row.settled_amount || 0).replace(/,/g, ""));
  if (!plan) return "0%";
  return `${Math.min(100, Math.round((paid / plan) * 100))}%`;
}
function stageBills(stage) {
  return props.settles.filter((row) => (row.stage_id && row.stage_id === stage.id) || (!row.stage_id && row.stage_name && row.stage_name === stage.name));
}
const orphanBills = computed(() => {
  const used = new Set((props.detail?.stages || []).flatMap((stage) => stageBills(stage).map((row) => row.id)));
  return props.settles.filter((row) => !used.has(row.id));
});
</script>
