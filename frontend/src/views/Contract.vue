<template>
  <ListShell ref="shell" :title="title" :storage-key="'contract-board-'+direction" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :sums="sums" :summary="summary" export-module="contract" :export-query="exportQuery" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}" @select="syncPick" @cell="onCell">
    <template #filters="{ expanded }">
      <el-input v-model="query.keyword" placeholder="关键字" style="width:160px" />
      <el-select v-model="query.party_id" clearable filterable :placeholder="partyLabel" style="width:160px">
        <el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="query.project_id" clearable filterable placeholder="项目" style="width:140px">
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="query.pay_status" clearable :placeholder="sale ? '收款状态' : '付款状态'" style="width:120px">
        <el-option v-for="s in payOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <template v-if="expanded">
        <el-select v-model="query.year" clearable placeholder="项目年度" style="width:120px">
          <el-option v-for="y in years" :key="y" :label="y" :value="y" />
        </el-select>
        <el-select v-model="query.move_state" clearable :placeholder="sale ? '发货情况' : '到货情况'" style="width:120px">
          <el-option v-for="s in moveOptions" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="query.invoice_state" clearable :placeholder="sale ? '开票状态' : '收票状态'" style="width:120px">
          <el-option v-for="s in invoiceOptions" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="query.type_name" clearable placeholder="合同类型" style="width:130px">
          <el-option v-for="t in types" :key="t.id" :label="t.name" :value="t.name" />
        </el-select>
        <el-select v-model="query.status" clearable placeholder="合同状态" style="width:120px">
          <el-option label="未签订" value="未签订" /><el-option label="已签订" value="已签订" /><el-option label="已终止" value="已终止" />
        </el-select>
        <el-select v-model="query.archived" clearable placeholder="归档状态" style="width:120px">
          <el-option label="未归档" value="未归档" /><el-option label="已归档" value="已归档" />
        </el-select>
        <el-date-picker v-model="query.sign_from" value-format="YYYY-MM-DD" placeholder="签订开始" style="width:140px" />
        <el-date-picker v-model="query.sign_to" value-format="YYYY-MM-DD" placeholder="签订结束" style="width:140px" />
      </template>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增{{ title }}</el-button>
      <el-button @click="showImport = true">导入</el-button>
      <el-button @click="batchRemove">批量删除</el-button>
      <el-button v-if="direction==='purchase'" @click="exportWord">生成合同</el-button>
      <GenerateForm v-else :shell="shell" :rows="rows" doc-code="sale_contract" doc-name="销售合同" party-word="客户" :fallback-name="(row) => `${row.contract_code || '销售合同'}.docx`" />
      <el-dropdown trigger="click" @visible-change="(open) => open && syncPick()">
        <el-button>更多</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="shell?.exportFile()">批量导出</el-dropdown-item>
            <el-dropdown-item @click="openLink">关联项目</el-dropdown-item>
            <el-dropdown-item v-if="direction==='purchase'" @click="genSettle">生成付款单</el-dropdown-item>
            <el-dropdown-item v-if="direction==='purchase' && signedPicked.length===1" @click="genInvoice">生成进项发票</el-dropdown-item>
            <el-dropdown-item v-if="direction==='sale'" @click="genSettle">生成收款单</el-dropdown-item>
            <el-dropdown-item v-if="direction==='purchase' && signedPicked.length" @click="genSale">生成销售合同</el-dropdown-item>
            <el-dropdown-item v-if="direction==='purchase' && signedPicked.length===1" @click="genWms">生成到货单</el-dropdown-item>
            <el-dropdown-item v-if="direction==='sale' && signedPicked.length===1" @click="genWms">生成发货单</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="row.status === '未签订' ? open(row, false) : openBoard(row)">{{ row.status === "未签订" ? "编辑" : "查看" }}</span>
      <el-dropdown trigger="click">
        <span class="ops more-dots">···</span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="openBoard(row)">详情</el-dropdown-item>
            <el-dropdown-item @click="open(row, false)">编辑</el-dropdown-item>
            <el-dropdown-item v-if="direction==='purchase'" @click="copyContract(row)">复制</el-dropdown-item>
            <el-dropdown-item @click="showOrder(row)">订单</el-dropdown-item>
            <el-dropdown-item @click="supplement(row)">补充</el-dropdown-item>
            <el-dropdown-item @click="ElMessage.info('无附件')">下载附件</el-dropdown-item>
            <el-dropdown-item @click="confirmRemove(row)">删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
  </ListShell>

  <el-dialog v-model="visible" class="contract-dialog" :title="(form.id ? '编辑' : '新增') + title" width="1040px" top="6vh" append-to-body :close-on-click-modal="false">
    <el-tabs v-model="tab">
      <el-tab-pane label="基本信息" name="base">
        <el-form class="contract-form" label-width="92px" :disabled="readonly">
          <el-row :gutter="16">
            <el-col :span="12"><el-form-item label="合同编号"><el-input v-model="form.contract_code" placeholder="留空自动生成" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="合同名称"><el-input v-model="form.name" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="合同类型">
                <el-select v-model="form.type_name" clearable><el-option v-for="t in types" :key="t.id" :label="t.name" :value="t.name" /></el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item :label="partyLabel">
                <el-select v-model="form.party_id" filterable @change="onParty">
                  <el-option v-for="p in parties" :key="p.id" :label="p.code + ' ' + p.name" :value="p.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <div v-if="selectedParty" class="party-card">
            <strong>{{ direction === "purchase" ? "供应商信息" : "客户信息" }}</strong>
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="纳税人识别号">{{ selectedParty.tax_no || "—" }}</el-descriptions-item>
              <el-descriptions-item label="开票名称">{{ selectedParty.invoice_title || "—" }}</el-descriptions-item>
              <el-descriptions-item label="开户银行">{{ selectedParty.bank_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="账户名称">{{ selectedParty.account_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="银行账号">{{ selectedParty.bank_account || "—" }}</el-descriptions-item>
              <el-descriptions-item label="开户支行">{{ selectedParty.bank_branch || "—" }}</el-descriptions-item>
              <el-descriptions-item label="开票电话">{{ selectedParty.invoice_phone || "—" }}</el-descriptions-item>
              <el-descriptions-item label="法人代表">{{ selectedParty.legal_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="委托代理人">{{ selectedParty.agent_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="联系人">{{ selectedParty.contact_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="联系电话">{{ selectedParty.contact_phone || "—" }}</el-descriptions-item>
              <el-descriptions-item label="开票地址">{{ selectedParty.invoice_address || "—" }}</el-descriptions-item>
              <el-descriptions-item label="通讯地址" :span="2">{{ selectedParty.address || "—" }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="业务员">
                <el-select v-model="form.owner_id" filterable>
                  <el-option v-for="u in users" :key="u.employee_id" :label="u.employee_id + ' ' + u.name" :value="u.employee_id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="项目">
                <el-select v-model="form.project_id" clearable filterable><el-option v-for="p in projects" :key="p.id" :label="p.project_code + ' ' + p.name" :value="p.id" /></el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="合同状态">
                <el-select v-model="form.status"><el-option label="未签订" value="未签订" /><el-option label="已签订" value="已签订" /><el-option label="已终止" value="已终止" /></el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12"><el-form-item label="归档"><span class="static-value">未归档</span></el-form-item></el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="计价方式">
                <el-select v-model="form.pricing"><el-option label="固定总价" value="fixed" /><el-option label="按实结算" value="actual" /></el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12"><el-form-item label="税率"><el-input v-model="form.tax_rate" @change="rebuildStages" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12"><el-form-item label="签订日期"><el-date-picker v-model="form.sign_date" value-format="YYYY-MM-DD" placeholder="选择日期" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item></el-col>
          </el-row>
          <template v-if="direction==='purchase'">
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="标的名称"><el-input v-model="form.subject_name" placeholder="写入合同首段和汇总行，留空则用物料名称" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="收货地址"><el-input v-model="form.ship_address" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="收货人"><el-input v-model="form.receiver_name" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="运输方式"><el-input v-model="form.transport_mode" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="交货期限"><el-input v-model="form.delivery_term" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="运费承担"><el-input v-model="form.freight_bearer" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="附件说明"><el-input v-model="form.annex_note" placeholder="例如车型、车架号，留空则不写入附件" /></el-form-item>
          </template>
          <el-form-item label="内容概述"><el-input v-model="form.content" type="textarea" :rows="2" /></el-form-item>
          <el-form-item :label="direction==='purchase' ? '付款条款' : '条款'"><el-input v-model="form.terms" type="textarea" :rows="3" :placeholder="direction==='purchase' ? '写入合同第四节：付款方式、期限及发票' : ''" /></el-form-item>
          <el-form-item v-if="direction==='purchase'" label="验收标准"><el-input v-model="form.acceptance_text" type="textarea" :rows="2" /></el-form-item>
          <div v-if="form.supplements?.length" class="supplement-line">补充协议：{{ form.supplements.join("、") }}</div>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="物料明细" name="items">
        <div class="dialog-tools">
          <el-button v-if="!readonly && !form.generated_from" @click="form.items.push(blankItem())">加行</el-button>
          <el-button v-if="direction==='purchase' && !readonly" @click="openPlans">从采购计划选择</el-button>
          <el-button v-if="!readonly && !form.generated_from" @click="itemImportVisible=true">导入物料</el-button>
          <el-button v-if="!readonly && !form.generated_from" class="tools-clear" @click="clearItems">一键清空</el-button>
        </div>
        <div v-if="direction==='sale' && form.generated_from && !readonly" class="markup-bar">
          <span>加价比例</span>
          <el-input v-model="markup" @change="applyMarkup"><template #append>%</template></el-input>
        </div>
        <div class="line-box">
        <el-table :data="form.items" height="320" size="small" empty-text="暂无物料">
          <el-table-column label="物料编号" min-width="130"><template #default="{ row }"><el-input v-model="row.material_code" :disabled="readonly" /></template></el-table-column>
          <el-table-column label="中文名称" min-width="140"><template #default="{ row }"><el-input v-model="row.name_cn" :disabled="readonly" /></template></el-table-column>
          <el-table-column v-if="direction==='purchase'" label="英文名称" min-width="120"><template #default="{ row }"><el-input v-model="row.name_en" :disabled="readonly" /></template></el-table-column>
          <el-table-column v-if="direction==='purchase'" label="计划单号" min-width="120"><template #default="{ row }"><el-input v-model="row.plan_no" :disabled="readonly" /></template></el-table-column>
          <el-table-column v-if="direction==='purchase'" label="使用设备" min-width="110"><template #default="{ row }"><el-input v-model="row.category" :disabled="readonly" /></template></el-table-column>
          <el-table-column label="规格" min-width="120"><template #default="{ row }"><el-input v-model="row.spec" :disabled="readonly" /></template></el-table-column>
          <el-table-column label="单位" width="72"><template #default="{ row }"><el-input v-model="row.unit" :disabled="readonly" /></template></el-table-column>
          <el-table-column label="数量" width="100"><template #default="{ row }"><el-input v-model="row.qty" :disabled="readonly || !!form.generated_from" @change="rebuildStages" /></template></el-table-column>
          <el-table-column v-if="direction==='sale' && form.generated_from" label="采购单价" width="110"><template #default="{ row }"><span class="cell-text">{{ row.cost || "—" }}</span></template></el-table-column>
          <el-table-column label="含税单价" width="110"><template #default="{ row }"><el-input v-model="row.price" :disabled="readonly" @change="rebuildStages" /></template></el-table-column>
          <el-table-column label="含税总价" width="110"><template #default="{ row }"><span class="cell-text">{{ lineAmount(row) }}</span></template></el-table-column>
          <el-table-column v-if="!readonly" label="操作" width="64" fixed="right"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1);rebuildStages()">删除</el-button></template></el-table-column>
        </el-table>
        </div>
        <div class="dialog-sum">合同金额：{{ money(contractAmount) }}</div>
      </el-tab-pane>
      <el-tab-pane label="阶段付款" name="stages">
        <div class="dialog-tools">
          <el-button v-if="!readonly" @click="addStage">插入阶段</el-button>
        </div>
        <el-table :data="form.stages" size="small">
          <el-table-column :label="direction==='purchase' ? '到货阶段' : '发货阶段'" width="88" align="center">
            <template #default="{ $index }"><el-radio v-model="roundIndex" :value="$index" :disabled="readonly" /></template>
          </el-table-column>
          <el-table-column label="阶段名称" min-width="130"><template #default="{ row }"><el-select v-model="row.name" :disabled="readonly" filterable allow-create><el-option v-for="n in stageNames" :key="n" :label="n" :value="n" /></el-select></template></el-table-column>
          <el-table-column label="比例" width="88"><template #default="{ row }"><el-input v-model="row.ratio" :disabled="readonly" @change="rebuildStages" /></template></el-table-column>
          <el-table-column label="计划金额" width="120"><template #default="{ row, $index }"><el-input v-model="row.plan_amount" :disabled="readonly" @change="onStageAmount($index)" /></template></el-table-column>
          <el-table-column label="计划日期" width="150"><template #default="{ row }"><el-date-picker v-model="row.plan_date" value-format="YYYY-MM-DD" :disabled="readonly" /></template></el-table-column>
          <el-table-column label="已收/已付" width="100"><template #default="{ row }"><span class="cell-text">{{ row.settled_amount || "0.00" }}</span></template></el-table-column>
          <el-table-column label="超收/超付" width="96"><template #default="{ row }"><span class="cell-text">{{ row.over || "0.00" }}</span></template></el-table-column>
          <el-table-column label="备注" min-width="120"><template #default="{ row }"><el-input v-model="row.remark" :disabled="readonly" /></template></el-table-column>
          <el-table-column v-if="!readonly" label="操作" width="64" fixed="right"><template #default="{ $index }"><el-button link type="danger" @click="form.stages.splice($index,1);rebuildStages()">删除</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    <template #footer>
      <el-button @click="visible=false">关闭</el-button>
      <el-button v-if="!readonly" type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="templateVisible" title="选择合同模板" width="640px" append-to-body :close-on-click-modal="false" @close="cancelTemplate">
    <p style="margin:0 0 12px">供应商：{{ templateParty }}。请选择这份供应商要使用的合同模板。</p>
    <el-radio-group v-model="templatePick" style="display:flex;flex-direction:column;align-items:stretch;gap:10px">
      <el-radio v-for="item in templateChoices" :key="item.id" :value="item.id" style="height:auto;align-items:flex-start;white-space:normal">
        <div>{{ item.title || item.doc_name }}<span style="color:var(--muted)">　{{ item.party_name || "不限客商" }}</span></div>
        <div style="color:var(--muted);font-size:12px">{{ item.template_path }}</div>
      </el-radio>
    </el-radio-group>
    <template #footer>
      <el-button @click="templateVisible=false">取消</el-button>
      <el-button type="primary" @click="confirmTemplate">生成</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="linkVisible" title="关联项目" width="480px">
    <el-form label-width="80px">
      <el-form-item label="已选合同">{{ selectedRows.map((row) => row.contract_code).join("、") }}</el-form-item>
      <el-form-item label="项目">
        <el-select v-model="linkProjectId" filterable placeholder="请选择项目" style="width:100%">
          <el-option v-for="p in projects" :key="p.id" :label="p.project_code + ' ' + p.name" :value="p.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="linkVisible=false">取消</el-button>
      <el-button type="primary" @click="saveLink">确定</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="planVisible" title="从采购计划选择" width="860px" append-to-body :close-on-click-modal="false">
    <div class="plan-picker">
      <div class="plan-filter">
        <el-input v-model="planQuery.keyword" clearable placeholder="物料编号 / 名称 / 规格" style="width:220px" />
        <el-input v-model="planQuery.plan_no" clearable placeholder="计划单号" style="width:160px" />
      </div>
      <div class="plan-box">
        <el-table :data="filteredPlans" height="360" empty-text="没有待选物料" @selection-change="(v)=>picked=v">
          <el-table-column type="selection" width="42" />
          <el-table-column prop="plan_no" label="计划单号" min-width="120" />
          <el-table-column prop="material_code" label="物料编号" min-width="120" />
          <el-table-column prop="category" label="使用设备" min-width="110" />
          <el-table-column prop="name_cn" label="中文名称" min-width="140" />
          <el-table-column prop="spec" label="规格" min-width="120" />
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column prop="remain_qty" label="待采购数量" width="110" />
        </el-table>
      </div>
    </div>
    <template #footer>
      <el-button @click="planVisible=false">取消</el-button>
      <el-button type="primary" @click="takePlans">确定</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="itemImportVisible" title="导入物料" width="520px" append-to-body :close-on-click-modal="false">
    <p class="import-note">{{ direction === "purchase" ? "按物料编号匹配采购计划；编号对不上时，再用规格型号匹配。计划内物料随合同保存核销待采购数量，超出计划则本次整份不导入。" : "按模板导入物料明细。相同物料编号不能重复。" }}</p>
    <div class="dialog-tools">
      <el-button @click="downloadItemTemplate">下载模板</el-button>
      <el-button type="primary" @click="itemFile?.click()">选择文件</el-button>
    </div>
    <input ref="itemFile" type="file" accept=".xlsx,.xls" hidden @change="onItemFile" />
  </el-dialog>
  <ImportWizard v-model="showImport" module="contract" :direction="direction" @done="load" />
  <el-dialog v-model="orderVisible" title="订单详情" width="760px">
    <div v-if="orderHead">{{ orderHead.order_code }}　{{ orderHead.status_label }}</div>
    <div class="line-box" style="margin-top:8px">
    <el-table :data="orderHead?.items || []" height="320" size="small" empty-text="暂无物料">
      <el-table-column prop="material_code" label="物料编号" />
      <el-table-column prop="name_cn" label="中文名称" />
      <el-table-column prop="spec" label="规格" />
      <el-table-column prop="unit" label="单位" width="70" />
      <el-table-column prop="qty" label="数量" />
      <el-table-column prop="price" label="含税单价" />
      <el-table-column prop="moved_text" label="到货 / 发货" />
    </el-table>
    </div>
    <template #footer><el-button @click="orderVisible=false">关闭</el-button></template>
  </el-dialog>
  <el-dialog v-model="boardVisible" width="1120px" top="3vh" destroy-on-close>
    <template #header>
      <div>合同详情 - <span class="name-pill">{{ board?.name }}</span></div>
    </template>
    <ContractBoard :detail="board" :direction="direction" :invoices="boardInvoices" :settles="boardSettles" :expenses="boardExpenses" :linked="boardLinked" @go="goBoard" />
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import http, { money } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";
import ContractBoard from "../components/ContractBoard.vue";
import GenerateForm from "../components/GenerateForm.vue";

const props = defineProps({ direction: String });
const route = useRoute();
const router = useRouter();
const title = computed(() => (props.direction === "sale" ? "销售合同" : "采购合同"));
const sale = computed(() => props.direction === "sale");
const partyLabel = computed(() => (sale.value ? "客户" : "供应商"));
const payOptions = computed(() => (sale.value ? ["未收", "部分收款", "已收清"] : ["未付", "部分付款", "已付清"]));
const invoiceOptions = computed(() => (sale.value ? ["未开票", "部分开票", "已开票"] : ["未收票", "部分收票", "已收票"]));
const moveOptions = computed(() => (sale.value ? ["未发货", "部分发货", "已发货"] : ["未到货", "部分到货", "已到货"]));
const years = computed(() => [...new Set(projects.value.map((p) => p.year).filter(Boolean))]);
const selectedParty = computed(() => parties.value.find((p) => p.id === form.party_id) || null);
const stageNames = computed(() => props.direction === "sale" ? ["预收款", "进度款", "验收款", "尾款", "质保金"] : ["预付款", "进度款", "到货款", "验收款", "尾款", "质保金"]);
const columns = computed(() => {
  const paid = sale.value ? "收款" : "付款";
  const bill = sale.value ? "开票" : "收票";
  const party = sale.value ? "客户" : "供应商";
  return [
    { key: "contract_code", label: "合同编号", fixed: "left", width: 150, kind: "link" },
    { key: "name", label: "合同名称", width: 180, kind: "link" },
    { key: "parent_code", label: "原合同", width: 140 },
    { key: "type_name", label: "合同类型", tag: true, tone: "tag-orange" },
    { key: "direction_label", label: "方向", tag: true },
    { key: "party_code", label: party + "编码", kind: "link", tone: "link-orange" },
    { key: "party_name", label: party + "名称", width: 180 },
    { key: "project_code", label: "项目编号", kind: "link" },
    { key: "project_name", label: "项目名称" },
    { key: "project_year", label: "项目年度" },
    { key: "owner_name", label: "业务员" },
    { key: "status", label: "合同状态", tag: true },
    { key: "archived_label", label: "归档状态", tag: true },
    { key: "sign_date", label: "签订日期" },
    { key: "end_date", label: "结束日期" },
    { key: "pricing_label", label: "计价方式", tag: true },
    { key: "qty_total", label: "商品数量" },
    { key: "tax_text", label: "合同税率" },
    { key: "amount_ex_tax", label: "合同金额(不含税)", money: true, width: 150 },
    { key: "amount", label: "合同金额", money: true },
    { key: "prepaid", label: "合同预" + (sale.value ? "收" : "付"), money: true },
    { key: "stage_text", label: "阶段完成数", kind: "percent" },
    { key: "settled", label: "已" + paid, money: true },
    { key: "unpaid", label: "未" + paid, money: true, danger: true },
    { key: "pay_status", label: paid + "状态", tag: true },
    { key: "move_state", label: sale.value ? "发货情况" : "到货情况", tag: true, width: 100 },
    { key: "invoice_state", label: sale.value ? "开票状态" : "发票收到", tag: true },
    { key: "due_total", label: "累计应" + (sale.value ? "收" : "付") + "金额", money: true, width: 140, show: false },
    { key: "paid_now", label: "合同已" + paid, money: true, show: false },
    { key: "unpaid_now", label: "合同未" + paid, money: true, danger: true, show: false },
    { key: "invoiced", label: "已" + bill, money: true, show: false },
    { key: "uninvoiced", label: "未" + bill, money: true, danger: true, show: false },
    { key: "paid_not_invoiced", label: paid + "未" + bill, money: true, show: false },
    { key: "invoiced_not_paid", label: bill + "未" + paid, money: true, show: false },
    { key: "pay_percent", label: paid + "进度", kind: "percent", show: false },
    { key: "invoice_percent", label: bill + "进度", kind: "percent", show: false },
    { key: "created_by_name", label: "创建人", show: false },
    { key: "created_at", label: "创建时间", width: 160, show: false },
    { key: "updated_by_name", label: "更新人", show: false },
    { key: "updated_at", label: "更新时间", width: 160, show: false },
    { key: "attachment", label: "附件", show: false },
    { key: "remark", label: "备注", show: false, wrap: true },
  ];
});
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const sums = ref({});
const summary = computed(() => `合同金额合计：<span class="sum-link">${money(sums.value.amount)}</span>`);
const query = reactive({ party_id: null, keyword: "", status: "", project_id: null, year: "", pay_status: "", move_state: "", invoice_state: "", type_name: "", archived: "", sign_from: "", sign_to: "" });
const exportQuery = computed(() => {
  const params = { direction: props.direction };
  Object.entries(query).forEach(([key, value]) => { if (value) params[key] = value; });
  return params;
});
const parties = ref([]);
const projects = ref([]);
const users = ref([]);
const types = ref([]);
const plans = ref([]);
const picked = ref([]);
const shell = ref(null);
const selectedRows = ref([]);
const signedPicked = computed(() => selectedRows.value.filter((row) => row.status === "已签订"));
const boardVisible = ref(false);
const board = ref(null);
const boardInvoices = ref([]);
const boardSettles = ref([]);
const boardExpenses = ref([]);
const boardLinked = ref([]);
const orderVisible = ref(false);
const orderHead = ref(null);
const visible = ref(false);
const showImport = ref(false);
const planVisible = ref(false);
const itemImportVisible = ref(false);
const itemFile = ref(null);
const planQuery = reactive({ keyword: "", plan_no: "" });
const linkVisible = ref(false);
const linkProjectId = ref(null);
const readonly = ref(false);
const tab = ref("base");
const roundIndex = ref(0);
const form = reactive(blank());
const markup = ref("10");

function blank() {
  return { id: null, version: null, contract_code: "", name: "", type_name: "", party_id: null, owner_id: "", project_id: null, status: "已签订", pricing: "fixed", tax_rate: "13", sign_date: "", content: "", terms: "", remark: "", subject_name: "", ship_address: "", receiver_name: "", transport_mode: "", delivery_term: "", freight_bearer: "", annex_note: "", acceptance_text: "", items: [blankItem()], stages: [], nature: "main", parent_contract_id: null, generated_from: null, supplements: [] };
}
function blankItem() { return { material_code: "", name_cn: "", name_en: "", spec: "", unit: "", qty: "1", price: "0", plan_no: "", category: "", remark: "" }; }
const filteredPlans = computed(() => {
  const keyword = planQuery.keyword.trim().toLowerCase();
  const planNo = planQuery.plan_no.trim().toLowerCase();
  return plans.value.filter((row) => {
    const text = `${row.material_code || ""} ${row.name_cn || ""} ${row.name_en || ""} ${row.spec || ""}`.toLowerCase();
    if (keyword && !text.includes(keyword)) return false;
    if (planNo && !String(row.plan_no || "").toLowerCase().includes(planNo)) return false;
    return true;
  });
});
function round2(n) { const x = Number(n || 0); return Math.round((x + Number.EPSILON) * 100) / 100; }
function lineAmount(row) { return money(round2(Number(row.qty || 0) * Number(row.price || 0))); }
const contractAmount = computed(() => round2(form.items.reduce((s, row) => s + Number(row.qty || 0) * Number(row.price || 0), 0)));
function rebuildStages() {
  if (!form.stages.length) {
    const names = props.direction === "sale" ? ["预收款", "进度款", "验收款", "质保金"] : ["预付款", "进度款", "验收款", "质保金"];
    const ratios = [30, 40, 25, 5];
    form.stages = names.map((name, i) => ({ name, ratio: String(ratios[i]), plan_amount: "0", plan_date: "", remark: "", settled_amount: "0.00" }));
  }
  const weights = form.stages.map((s) => Number(s.ratio || 0));
  const base = weights.reduce((a, b) => a + b, 0) || form.stages.length;
  const total = contractAmount.value;
  let acc = 0;
  form.stages.forEach((stage, i) => {
    if (i === form.stages.length - 1) stage.plan_amount = (round2(total - acc)).toFixed(2);
    else {
      const w = Number(stage.ratio || 0) || (base === form.stages.length ? 1 : 0);
      const part = base ? round2(total * (Number(stage.ratio || 0) || (base === form.stages.length ? 1 : 0)) / (weights.reduce((a,b)=>a+b,0) || form.stages.length)) : 0;
      stage.plan_amount = part.toFixed(2);
      acc = round2(acc + part);
    }
  });
}
function onStageAmount(index) {
  if (index === form.stages.length - 1) return;
  const others = form.stages.reduce((s, row, i) => i === form.stages.length - 1 ? s : s + Number(row.plan_amount || 0), 0);
  form.stages[form.stages.length - 1].plan_amount = round2(contractAmount.value - others).toFixed(2);
}
function addStage() {
  form.stages.push({ name: "进度款", ratio: "0", plan_amount: "0", plan_date: "", remark: "" });
  rebuildStages();
}
async function load() {
  const params = { direction: props.direction, page: page.value, pageSize: pageSize.value };
  Object.entries(query).forEach(([key, value]) => { if (value) params[key] = value; });
  const res = await http.get("/api/contracts", { params });
  rows.value = (res.data.items || []).map((row) => (sale.value ? row : { ...row, pay_percent: row.stage_text || "0/0" }));
  total.value = res.data.total;
  sums.value = res.data.sums || {};
  syncPick();
}
function reset() {
  Object.assign(query, { party_id: null, keyword: "", status: "", project_id: null, year: "", pay_status: "", move_state: "", invoice_state: "", type_name: "", archived: "", sign_from: "", sign_to: "" });
  load();
}
async function open(row, view = false) {
  if (view && row) return openBoard(row);
  readonly.value = false;
  tab.value = "base";
  Object.assign(form, blank());
  if (row) {
    const res = await http.get(`/api/contracts/${row.id}`);
    Object.assign(form, res.data);
    roundIndex.value = form.stages.findIndex((s) => props.direction === "purchase" ? s.is_arrival : s.is_ship);
    if (roundIndex.value < 0) roundIndex.value = 0;
  } else rebuildStages();
  visible.value = true;
}
function markedPrice(cost, rate) {
  const cents = Math.round(Number(cost) * 100);
  const scaled = Math.round(cents * (100 + rate) / 100);
  return (scaled / 100).toFixed(2);
}
function applyMarkup() {
  const raw = String(markup.value ?? "").trim();
  const rate = Number(raw);
  if (raw === "" || Number.isNaN(rate)) {
    ElMessage.warning("加价比例不正确");
    return;
  }
  form.items.forEach((row) => {
    if (row.cost === undefined || row.cost === null || row.cost === "") return;
    row.price = markedPrice(row.cost, rate);
  });
  rebuildStages();
}
async function clearItems() {
  if (!form.items.length) return;
  try {
    await ElMessageBox.confirm("清空后物料明细需要重新填写。", "一键清空", {
      confirmButtonText: "确定",
      cancelButtonText: "取消",
      type: "warning",
      closeOnClickModal: false,
    });
  } catch {
    return;
  }
  form.items = [];
  rebuildStages();
}
function onParty() {
  const party = parties.value.find((p) => p.id === form.party_id);
  if (party && !form.id) form.tax_rate = String(party.default_tax_rate || 13);
}
async function copyContract(row) {
  const src = (await http.get(`/api/contracts/${row.id}`)).data;
  readonly.value = false;
  tab.value = "base";
  Object.assign(form, blank(), {
    name: src.name,
    type_name: src.type_name || "",
    party_id: src.party_id,
    owner_id: src.owner_id || "",
    project_id: src.project_id,
    status: src.status === "已终止" ? "已签订" : (src.status || "已签订"),
    pricing: src.pricing || "fixed",
    tax_rate: String(src.tax_rate || "13").replace("%", ""),
    sign_date: src.sign_date || "",
    content: src.content || "",
    terms: src.terms || "",
    remark: src.remark || "",
    subject_name: src.subject_name || "",
    ship_address: src.ship_address || "",
    receiver_name: src.receiver_name || "",
    transport_mode: src.transport_mode || "",
    delivery_term: src.delivery_term || "",
    freight_bearer: src.freight_bearer || "",
    annex_note: src.annex_note || "",
    acceptance_text: src.acceptance_text || "",
    items: (src.items || []).map((item) => ({
      material_code: item.material_code,
      name_cn: item.name_cn || "",
      name_en: item.name_en || "",
      spec: item.spec || "",
      unit: item.unit || "",
      qty: item.qty,
      price: item.price,
      plan_no: item.plan_no || "",
      category: item.category || "",
      plan_row: item.plan_row,
      remark: item.remark || "",
    })),
    stages: (src.stages || []).map((stage) => ({
      name: stage.name,
      ratio: stage.ratio,
      plan_amount: stage.plan_amount,
      plan_date: stage.plan_date || "",
      remark: stage.remark || "",
      settled_amount: "0.00",
      over: "0.00",
    })),
  });
  if (!form.items.length) form.items = [blankItem()];
  const arrival = (src.stages || []).findIndex((stage) => stage.is_arrival);
  roundIndex.value = arrival >= 0 ? arrival : 0;
  visible.value = true;
  ElMessage.success("已复制为新合同，确认后保存");
}
async function save() {
  const payload = { ...form, direction: props.direction, arrival_index: props.direction === "purchase" ? roundIndex.value : 0, ship_index: props.direction === "sale" ? roundIndex.value : 0 };
  delete payload.start_date;
  delete payload.end_date;
  delete payload.party_legal_name;
  delete payload.party_agent;
  if (form.id) await http.put(`/api/contracts/${form.id}`, payload);
  else await http.post("/api/contracts", payload);
  visible.value = false;
  load();
}
async function remove(row) { await http.delete(`/api/contracts/${row.id}`, { params: { version: row.version } }); load(); }
async function confirmRemove(row) {
  await ElMessageBox.confirm("确定删除该合同？", "删除", { type: "warning" });
  await remove(row);
}
async function batchRemove() {
  syncPick();
  if (!selectedRows.value.length) return ElMessage.warning("请先勾选合同");
  await ElMessageBox.confirm(`确定删除选中的 ${selectedRows.value.length} 条${title.value}？`, "批量删除", { type: "warning" });
  await http.post("/api/contracts/batch-delete", { items: selectedRows.value.map((row) => ({ id: row.id, version: row.version })) });
  ElMessage.success("已删除");
  load();
}
function onCell({ key, row }) {
  if (key === "contract_code" || key === "name") openBoard(row);
}
async function openBoard(row) {
  const detail = (await http.get(`/api/contracts/${row.id}`)).data;
  const invoiceDir = sale.value ? "output" : "input";
  const settleDir = sale.value ? "receipt" : "payment";
  boardInvoices.value = (await http.get("/api/invoices", { params: { direction: invoiceDir, contract_id: row.id, pageSize: 200 } })).data.items || [];
  boardSettles.value = (await http.get("/api/settle-bills", { params: { direction: settleDir, contract_id: row.id, pageSize: 200 } })).data.items || [];
  const others = (await http.get("/api/other-bills", { params: { direction: "expense", pageSize: 200 } })).data.items || [];
  boardExpenses.value = others.filter((item) => item.contract_code === detail.contract_code);
  if (detail.project_id) {
    const otherDir = sale.value ? "purchase" : "sale";
    boardLinked.value = (await http.get("/api/contracts", { params: { direction: otherDir, project_id: detail.project_id, pageSize: 200 } })).data.items || [];
  } else boardLinked.value = [];
  board.value = detail;
  boardVisible.value = true;
}
function goBoard(kind) {
  const map = { input: "/invoice/input", output: "/invoice/output", payment: "/settlement/payment", receipt: "/settlement/receipt" };
  if (map[kind]) router.push(map[kind]);
}
async function supplement(row) {
  const res = await http.post(`/api/contracts/${row.id}/supplement`);
  Object.assign(form, blank(), res.data, { items: [blankItem()] });
  readonly.value = false;
  rebuildStages();
  visible.value = true;
}
function syncPick() {
  const set = shell.value?.selected || new Set();
  selectedRows.value = rows.value.filter((row) => set.has(row.id));
}
async function showOrder(row) {
  if (!row.order_id) {
    ElMessage.warning("请先生成订单");
    return;
  }
  orderHead.value = (await http.get(`/api/orders/${row.order_id}`)).data;
  orderVisible.value = true;
}
function openLink() {
  syncPick();
  if (!selectedRows.value.length) return ElMessage.warning("请先勾选合同");
  linkProjectId.value = null;
  linkVisible.value = true;
}
async function saveLink() {
  if (!linkProjectId.value) return ElMessage.warning("请选择项目");
  await http.post("/api/contracts/link-project", {
    project_id: linkProjectId.value,
    items: selectedRows.value.map((row) => ({ id: row.id, version: row.version })),
  });
  ElMessage.success("已关联项目");
  linkVisible.value = false;
  load();
}
async function genSale() {
  syncPick();
  const ids = signedPicked.value.map((row) => row.id);
  if (!ids.length) return ElMessage.warning("请勾选已签订的采购合同");
  const res = await http.post("/api/purchase-contracts/generate-sale-contract", { ids });
  sessionStorage.setItem("sale-prefill", JSON.stringify(res.data));
  ElMessage.success("已生成未保存的销售合同，单价已按采购价加价");
  router.push("/contract/sale");
}
async function genInvoice() {
  syncPick();
  if (signedPicked.value.length !== 1) return ElMessage.warning("请只勾选一张已签订采购合同");
  const row = signedPicked.value[0];
  const res = await http.post(`/api/contracts/${row.id}/generate-input-invoice`);
  sessionStorage.setItem("invoice-prefill", JSON.stringify(res.data));
  router.push("/invoice/input");
}
async function genWms() {
  syncPick();
  if (signedPicked.value.length !== 1) return ElMessage.warning(props.direction === "purchase" ? "请只勾选一张已签订采购合同" : "请只勾选一张已签订销售合同");
  const row = signedPicked.value[0];
  const path = props.direction === "purchase" ? "generate-arrival" : "generate-shipment";
  const res = await http.post(`/api/contracts/${row.id}/${path}`);
  sessionStorage.setItem("wms-prefill", JSON.stringify(res.data));
  router.push(props.direction === "purchase" ? "/warehouse/inbound" : "/warehouse/outbound");
}
function downloadName(res, fallback) {
  const raw = res.headers?.["x-download-name"] || "";
  if (!raw) return fallback;
  try { return decodeURIComponent(raw); } catch { return fallback; }
}
const templateVisible = ref(false);
const templateChoices = ref([]);
const templatePick = ref(null);
const templateParty = ref("");
let templateResolve = null;
function chooseTemplate(row, items) {
  const ranked = [...items].sort((a, b) => {
    const rank = (item) => (item.party_id && item.party_id === row.party_id ? 0 : item.party_id ? 2 : 1);
    return rank(a) - rank(b);
  });
  templateParty.value = row.party_name || "";
  templateChoices.value = ranked;
  const matched = ranked.find((item) => item.party_id && item.party_id === row.party_id);
  templatePick.value = (matched || ranked[0]).id;
  templateVisible.value = true;
  return new Promise((resolve) => { templateResolve = resolve; });
}
function confirmTemplate() {
  const resolve = templateResolve;
  templateResolve = null;
  templateVisible.value = false;
  if (resolve) resolve(templatePick.value);
}
function cancelTemplate() {
  const resolve = templateResolve;
  templateResolve = null;
  if (resolve) resolve(null);
}
async function exportWord() {
  syncPick();
  if (selectedRows.value.length !== 1) return ElMessage.warning("请只勾选一张采购合同");
  const row = selectedRows.value[0];
  const listed = await http.get("/api/export-profiles", { params: { doc_code: "purchase_contract" } });
  const items = (listed.data.items || []).filter((item) => item.template_path);
  if (!items.length) return ElMessage.warning("请先在基础资料的导出模板里填写采购合同的模板绝对地址");
  let templateId = items[0].id;
  if (items.length > 1) {
    templateId = await chooseTemplate(row, items);
    if (!templateId) return;
  }
  const res = await http.get(`/api/contracts/${row.id}/word`, { params: { template_id: templateId }, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = downloadName(res, `${row.contract_code || "采购合同"}.docx`);
  link.click();
  URL.revokeObjectURL(url);
}
function genSettle() {
  syncPick();
  const sale = props.direction === "sale";
  if (!selectedRows.value.length) return ElMessage.warning(sale ? "请先勾选一张销售合同" : "请先勾选一张采购合同");
  if (selectedRows.value.length > 1) {
    ElMessageBox.alert("一次只能选择一个", "提示", { type: "warning", confirmButtonText: "确定", closeOnClickModal: false });
    return;
  }
  const row = selectedRows.value[0];
  if (row.status !== "已签订") return ElMessage.warning("未签订与已终止的合同不能新建后续单据");
  sessionStorage.setItem("pay-prefill", JSON.stringify({
    contract_id: row.id,
    party_id: row.party_id,
    direction: sale ? "receipt" : "payment",
  }));
  router.push(sale ? "/settlement/receipt" : "/settlement/payment");
}
async function openPlans() {
  const chosen = form.items.map((row) => row.material_code).filter(Boolean).join(",");
  plans.value = (await http.get("/api/purchase-plans/available", { params: { chosen } })).data || [];
  picked.value = [];
  planQuery.keyword = "";
  planQuery.plan_no = "";
  planVisible.value = true;
}
async function takePlans() {
  if (!picked.value.length) return ElMessage.warning("请先勾选物料");
  picked.value.forEach((p) => form.items.push({ ...blankItem(), material_code: p.material_code, name_cn: p.name_cn, name_en: p.name_en || "", spec: p.spec, unit: p.unit, qty: p.remain_qty, price: "0", plan_no: p.plan_no || "", category: p.category || "", plan_row: p.plan_row }));
  form.items = form.items.filter((row) => row.material_code);
  planVisible.value = false;
  rebuildStages();
}
async function downloadItemTemplate() {
  const res = await http.get("/api/contracts/item-template", { params: { direction: props.direction }, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = props.direction === "purchase" ? "采购合同物料导入模板.xlsx" : "销售合同物料导入模板.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}
async function onItemFile(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  body.append("direction", props.direction);
  body.append("contract_id", form.id || "");
  body.append("existing", form.items.map((row) => row.material_code).filter(Boolean).join(","));
  const res = await http.post("/api/contracts/parse-items", body);
  const rows = res.data.items || [];
  form.items = form.items.filter((row) => row.material_code);
  rows.forEach((row) => form.items.push({ ...blankItem(), ...row, price: row.price || "0" }));
  if (!form.items.length) form.items.push(blankItem());
  rebuildStages();
  itemImportVisible.value = false;
  const matched = res.data.matched || 0;
  ElMessage.success(props.direction === "purchase" ? `已导入 ${rows.length} 行，其中 ${matched} 行匹配采购计划，保存合同时核销` : `已导入 ${rows.length} 行`);
}
async function boot() {
  boardVisible.value = false;
  visible.value = false;
  parties.value = (await http.get("/api/parties", { params: { type: props.direction === "sale" ? "customer" : "supplier", status: "启用", pageSize: 200 } })).data.items;
  projects.value = (await http.get("/api/projects", { params: { pageSize: 200 } })).data.items;
  users.value = (await http.get("/api/users", { params: { status: "启用", pageSize: 200 } })).data.items;
  types.value = (await http.get("/api/contract-types", { params: { status: "启用", pageSize: 200 } })).data.items;
  if (props.direction === "purchase") plans.value = (await http.get("/api/purchase-plans/available")).data;
  const pre = sessionStorage.getItem("sale-prefill");
  if (props.direction === "sale" && pre) {
    sessionStorage.removeItem("sale-prefill");
    const data = JSON.parse(pre);
    markup.value = data.markup || "10";
    Object.assign(form, blank(), data);
    form.items = (form.items || []).map((row) => ({ ...blankItem(), ...row, cost: row.cost || "", price: row.price || "" }));
    applyMarkup();
    tab.value = "items";
    visible.value = true;
  }
  load();
  if (route.query.open) openBoard({ id: route.query.open });
}
watch(() => props.direction, boot);
onMounted(boot);
</script>
