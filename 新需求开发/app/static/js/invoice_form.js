(function () {
  const form = document.getElementById("invoice-form");
  if (!form) return;
  const editing = form.dataset.editing === "1";
  const biz = document.getElementById("business_type");
  const transport = document.getElementById("transport_type");
  const rule = document.getElementById("number_rule");
  const year = document.getElementById("number_year");
  const batch = document.getElementById("batch_id");
  const preview = document.getElementById("preview-box");
  const usd = document.getElementById("amount_usd");
  const cny = document.getElementById("amount_cny");
  const rate = document.getElementById("exchange_rate");
  const month = document.getElementById("exchange_month");
  const currency = document.getElementById("currency");
  const hint = document.getElementById("rate-hint");
  const joinBox = document.getElementById("join-box");
  let ruleDirty = false;
  let calcLock = false;

  function mode() {
    const picked = form.querySelector("input[name=mode]:checked");
    return picked ? picked.value : "normal";
  }

  function syncRule() {
    if (editing || ruleDirty || mode() === "join_batch") return;
    if (biz.value === "锰矿") rule.value = "锰矿";
    else if (transport.value === "空运") rule.value = "铝矿空运";
    else rule.value = "铝矿海运";
  }

  function lockJoinFields(locked) {
    [biz, transport, rule, year].forEach(function (el) {
      if (!el || editing) return;
      el.disabled = locked;
    });
  }

  function applyBatch() {
    if (!batch || !batch.selectedOptions.length) return;
    const option = batch.selectedOptions[0];
    if (!option.value) return;
    biz.value = option.dataset.biz || biz.value;
    transport.value = option.dataset.transport || transport.value;
    rule.value = option.dataset.rule || rule.value;
    year.value = option.dataset.year || year.value;
  }

  function toggleMode() {
    const joining = mode() === "join_batch";
    if (joinBox) joinBox.hidden = !joining;
    lockJoinFields(joining);
    if (joining) applyBatch();
    refreshPreview();
  }

  async function refreshPreview() {
    if (editing || !preview) return;
    try {
      let url;
      if (mode() === "join_batch") {
        if (!batch || !batch.value) {
          preview.textContent = "请选择近 3 个月内的批次，保存后自动生成最小空闲小批号。";
          return;
        }
        url = "/invoices/api/preview-sub?batch_id=" + encodeURIComponent(batch.value);
      } else {
        url = "/invoices/api/preview?number_rule=" + encodeURIComponent(rule.value) + "&year=" + encodeURIComponent(year.value);
      }
      const data = await (await fetch(url)).json();
      if (!data.ok) {
        preview.textContent = data.message || "暂时无法预计编号";
        return;
      }
      const prefix = mode() === "new_batch" ? "预计批次前缀：" : "预计编号：";
      preview.textContent = (data.reused ? prefix + data.number + "，将复用空闲编号" : prefix + data.number) + "（以保存结果为准）";
    } catch (err) {
      preview.textContent = "预计编号获取失败";
    }
  }

  function calc(from) {
    if (calcLock) return;
    const rateValue = Number(rate.value);
    if (!rateValue) return;
    calcLock = true;
    if (from === "usd" && usd.value !== "") cny.value = (Number(usd.value) * rateValue).toFixed(2);
    if (from === "cny" && cny.value !== "") usd.value = (Number(cny.value) / rateValue).toFixed(2);
    calcLock = false;
  }

  async function loadRate() {
    if (!month.value) return;
    try {
      const data = await (await fetch("/invoices/api/rate?month=" + encodeURIComponent(month.value))).json();
      if (!data.ok) return;
      if (data.found) {
        rate.value = Number(data.rate).toFixed(6);
        hint.textContent = "当月汇率 " + rate.value + "（" + data.month + "，USD/CNY）。输入一边金额会按汇率计算另一边，两边都会保存。";
        calc(currency.value === "CNY" ? "cny" : "usd");
      } else {
        hint.textContent = data.month + " 尚未维护汇率，请手工填写，或先到汇率维护录入。";
      }
    } catch (err) {
      hint.textContent = "汇率读取失败，可手工填写。";
    }
  }

  if (!editing) {
    form.querySelectorAll("input[name=mode]").forEach(function (item) {
      item.addEventListener("change", function () {
        ruleDirty = false;
        toggleMode();
      });
    });
    biz.addEventListener("change", function () { ruleDirty = false; syncRule(); refreshPreview(); });
    transport.addEventListener("change", function () { ruleDirty = false; syncRule(); refreshPreview(); });
    rule.addEventListener("change", function () { ruleDirty = true; refreshPreview(); });
    year.addEventListener("change", refreshPreview);
    if (batch) batch.addEventListener("change", function () { applyBatch(); refreshPreview(); });
    toggleMode();
  }

  usd.addEventListener("input", function () { calc("usd"); });
  cny.addEventListener("input", function () { calc("cny"); });
  rate.addEventListener("input", function () { calc(currency.value === "CNY" ? "cny" : "usd"); });
  currency.addEventListener("change", function () { calc(currency.value === "CNY" ? "cny" : "usd"); });
  month.addEventListener("change", loadRate);

  const openBtn = document.getElementById("open-contract");
  const closeBtn = document.getElementById("close-contract");
  const clearBtn = document.getElementById("clear-contract");
  const contractMask = document.getElementById("contract-mask");
  const results = document.getElementById("contract-results");

  function selectContract(item) {
    document.getElementById("contract_id").value = item.id;
    document.getElementById("contract_label").textContent = "已选 " + item.contract_no + " / " + item.product_name + "（" + item.business_type + "）";
    document.getElementById("party_info").textContent = "乙方：" + item.party_b + "　甲方：" + item.party_a;
    if (!editing) {
      biz.value = item.business_type;
      const content = document.getElementById("content");
      if (!content.value) content.value = item.product_name;
      ruleDirty = false;
      syncRule();
      refreshPreview();
    }
    contractMask.hidden = true;
  }

  async function searchContracts() {
    const params = new URLSearchParams({
      keyword: document.getElementById("q-keyword").value,
      contract_no: document.getElementById("q-no").value,
      product_name: document.getElementById("q-name").value,
      party_b: document.getElementById("q-b").value,
      party_a: document.getElementById("q-a").value,
      business_type: document.getElementById("q-biz").value,
      sign_from: document.getElementById("q-from").value,
      sign_to: document.getElementById("q-to").value
    });
    const data = await (await fetch("/invoices/api/contracts?" + params.toString())).json();
    results.innerHTML = "";
    if (!data.ok || !data.items.length) {
      results.innerHTML = '<tr><td class="empty" colspan="7">没有匹配的合同</td></tr>';
      return;
    }
    data.items.forEach(function (item) {
      const tr = document.createElement("tr");
      [item.contract_no, item.business_type, item.product_name, item.party_b, item.party_a, item.sign_date].forEach(function (text) {
        const td = document.createElement("td");
        td.textContent = text || "";
        tr.appendChild(td);
      });
      const op = document.createElement("td");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "link";
      button.textContent = "选择";
      button.addEventListener("click", function () { selectContract(item); });
      op.appendChild(button);
      tr.appendChild(op);
      results.appendChild(tr);
    });
  }

  if (openBtn) openBtn.addEventListener("click", function () { contractMask.hidden = false; searchContracts(); });
  if (closeBtn) closeBtn.addEventListener("click", function () { contractMask.hidden = true; });
  if (contractMask) contractMask.addEventListener("click", function (event) { if (event.target === contractMask) contractMask.hidden = true; });
  const searchBtn = document.getElementById("q-search");
  if (searchBtn) searchBtn.addEventListener("click", searchContracts);
  if (clearBtn) clearBtn.addEventListener("click", function () {
    document.getElementById("contract_id").value = "";
    document.getElementById("contract_label").textContent = "未关联合同，可直接登记。";
    document.getElementById("party_info").textContent = "";
  });
})();
