<template>
  <section class="page audit-page" data-module="audit_lineage">
    <header class="page-head">
      <div>
        <h2>数据审计证据复核</h2>
        <p class="page-desc">
          按扫描批次、下游列和证据版本定位字段血缘关系，领取受变更影响的审计复核范围，
          证据替换后区分原证据、当前证据及其他未受影响项。
        </p>
      </div>
      <button class="btn" data-testid="refresh-all" type="button" @click="refreshAll">刷新</button>
    </header>

    <div class="tab-bar" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        :data-testid="`tab-${tab.key}`"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ================= Tab 1：关系查询与领取 ================= -->
    <div v-if="activeTab === 'relations'" class="tab-panel">
      <form class="filter-bar audit-filter" @submit.prevent="loadRelations">
        <label class="filter-item">
          <span>扫描批次</span>
          <input v-model="relationFilter.扫描批次" data-testid="filter-batch" placeholder="如 BATCH-20261120-A" />
        </label>
        <label class="filter-item">
          <span>下游列</span>
          <input v-model="relationFilter.下游列" data-testid="filter-column" placeholder="如 balance" />
        </label>
        <label class="filter-item">
          <span>证据版本</span>
          <input v-model="relationFilter.证据版本" data-testid="filter-version" placeholder="如 v1.0" />
        </label>
        <button class="btn primary" data-testid="query-relations" type="submit">查询下游关系</button>
        <button class="btn ghost" type="button" @click="resetRelationFilter">重置</button>
        <button class="btn" data-testid="claim-scope" type="button" @click="claimCurrentScope">
          领取复核范围
        </button>
      </form>

      <p v-if="claimMessage" class="inline-message" :class="claimOk ? 'ok' : 'error-text'">
        {{ claimMessage }}
      </p>

      <table class="data-table">
        <thead>
          <tr>
            <th>关系标识</th>
            <th>扫描批次</th>
            <th>上游列</th>
            <th>下游表.下游列</th>
            <th>当前采用证据</th>
            <th>原证据</th>
            <th>血缘路径</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in relations"
            :key="row.id"
            :data-testid="`relation-row-${row.id}`"
            :class="{ conflict: row.证据冲突, broken: row.status === '已断裂' }"
          >
            <td>{{ row.关系标识 }}</td>
            <td>{{ row.扫描批次 }}</td>
            <td>{{ row.上游表 }}.{{ row.上游列 }}</td>
            <td>{{ row.下游表 }}.{{ row.下游列 }}</td>
            <td>
              <strong>{{ row.当前证据标识 }}</strong>
              <span class="muted">（{{ row.证据版本 }}）</span>
              <span v-if="row.证据冲突" class="badge badge-warn" data-testid="conflict-flag">证据冲突</span>
            </td>
            <td>{{ row.原证据标识 || '—' }}</td>
            <td class="path-cell">
              <span v-for="(step, index) in row.血缘路径" :key="step" class="path-step">
                {{ step }}<template v-if="index < row.血缘路径.length - 1"> →</template>
              </span>
            </td>
            <td>
              <span class="badge" :class="row.status === '已断裂' ? 'badge-danger' : 'badge-ok'">
                {{ row.status }}
              </span>
            </td>
            <td class="row-actions">
              <button class="link" data-testid="view-detail" type="button" @click="openDetail(row.id)">
                关系详情
              </button>
              <button
                v-if="row.status === '已断裂'"
                class="link"
                type="button"
                @click="restore(row.id)"
              >
                断线恢复
              </button>
            </td>
          </tr>
          <tr v-if="!relations.length">
            <td colspan="9" class="empty-state">按当前条件未查到字段血缘关系</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ================= Tab 2：工单与审计清单 ================= -->
    <div v-if="activeTab === 'scopes'" class="tab-panel">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">复核工单</span>
          <strong class="stat-value">{{ scopes.length }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">原证据（签核后替换冻结）</span>
          <strong class="stat-value">{{ checklistGroups['原证据'] ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">当前证据（跟随替换）</span>
          <strong class="stat-value">{{ checklistGroups['当前证据'] ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">未受影响项</span>
          <strong class="stat-value">{{ checklistGroups['未受影响'] ?? 0 }}</strong>
        </article>
      </div>

      <h3>复核工单（受变更影响的审计复核范围）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>工单标识</th>
            <th>扫描批次</th>
            <th>下游列</th>
            <th>范围关系数</th>
            <th>领取人</th>
            <th>状态</th>
            <th>复核结论</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="scope in scopes" :key="scope.id" :data-testid="`scope-row-${scope.id}`">
            <td>{{ scope.工单标识 }}</td>
            <td>{{ scope.扫描批次 }}</td>
            <td>{{ scope.下游列 }}</td>
            <td>{{ scope.范围关系数 }}</td>
            <td>{{ scope.领取人 }}</td>
            <td>
              <span class="badge" :class="scope.工单状态 === '已签核' ? 'badge-ok' : 'badge-warn'">
                {{ scope.工单状态 }}
              </span>
            </td>
            <td>{{ scope.复核结论 || '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="toggleScopeItems(scope.id)">
                {{ expandedScope === scope.id ? '收起复核项' : '查看复核项' }}
              </button>
              <button
                v-if="scope.工单状态 === '待复核'"
                class="link"
                data-testid="open-signoff"
                type="button"
                @click="openSignOff(scope)"
              >
                提交复核
              </button>
            </td>
          </tr>
          <tr v-if="!scopes.length">
            <td colspan="8" class="empty-state">暂无复核工单，请先在关系查询页领取复核范围</td>
          </tr>
        </tbody>
      </table>

      <div v-if="expandedScope" class="scope-items">
        <h3>工单 {{ expandedScope }} 复核项（复核记录归入受变更影响范围）</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>关系标识</th>
              <th>原证据</th>
              <th>当前采用证据</th>
              <th>证据分类</th>
              <th>替换关系</th>
              <th>复核状态</th>
              <th>复核结论</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in expandedItems" :key="String(item.id)" :data-testid="`review-item-${item.id}`">
              <td>{{ item.关系标识 }}</td>
              <td>{{ item.原证据标识 }}（{{ item.原证据版本 }}）</td>
              <td>
                {{ item.当前证据标识 }}（{{ item.当前证据版本 }}）
                <span v-if="item.证据冲突" class="badge badge-warn">待确认</span>
                <span v-if="item.证据冻结" class="badge badge-danger">已冻结原证据</span>
              </td>
              <td>
                <span class="badge" :class="categoryClass(item.证据分类)">{{ item.证据分类 }}</span>
              </td>
              <td>{{ item.替换关系 || '—' }}</td>
              <td>{{ item.复核状态 }}</td>
              <td>{{ item.复核结论 || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>审计清单（原证据 / 当前证据 / 未受影响）</h3>
      <form class="filter-bar" @submit.prevent="loadChecklist">
        <label class="filter-item">
          <span>扫描批次</span>
          <input v-model="checklistFilter.扫描批次" placeholder="按扫描批次筛选" />
        </label>
        <label class="filter-item">
          <span>下游列</span>
          <input v-model="checklistFilter.下游列" placeholder="按下游列筛选" />
        </label>
        <button class="btn primary" data-testid="query-checklist" type="submit">刷新清单</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>关系标识</th>
            <th>所属工单</th>
            <th>下游表.下游列</th>
            <th>原证据</th>
            <th>当前采用证据</th>
            <th>证据分类</th>
            <th>复核状态</th>
            <th>复核结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in checklist" :key="String(row.id)" :data-testid="`checklist-row-${row.id}`">
            <td>{{ row.关系标识 }}</td>
            <td>{{ row.工单标识 || '未领取' }}</td>
            <td>{{ row.下游表 }}.{{ row.下游列 }}</td>
            <td>{{ row.原证据标识 }}（{{ row.原证据版本 }}）</td>
            <td>{{ row.当前证据标识 }}（{{ row.当前证据版本 }}）</td>
            <td>
              <span class="badge" :class="categoryClass(row.证据分类)">{{ row.证据分类 }}</span>
            </td>
            <td>{{ row.复核状态 }}</td>
            <td>{{ row.复核结论 || '—' }}</td>
          </tr>
          <tr v-if="!checklist.length">
            <td colspan="8" class="empty-state">暂无审计清单数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ================= Tab 3：证据登记与替换 ================= -->
    <div v-if="activeTab === 'evidence'" class="tab-panel">
      <div class="two-col">
        <form class="modal modeless" @submit.prevent="submitEvidence">
          <h3>登记证据版本</h3>
          <label v-for="field in evidenceFields" :key="field" class="create-field">
            <span>{{ field }}</span>
            <input v-model="evidenceForm[field]" :data-testid="`evidence-${field}`" required />
          </label>
          <button class="btn primary" data-testid="submit-evidence" type="submit">确认登记</button>
        </form>

        <form class="modal modeless" @submit.prevent="submitReplace">
          <h3>证据替换（来源证据更正）</h3>
          <label class="create-field">
            <span>原证据标识</span>
            <input v-model="replaceForm.原证据标识" data-testid="replace-old" required />
          </label>
          <label class="create-field">
            <span>新证据标识（须先登记）</span>
            <input v-model="replaceForm.新证据标识" data-testid="replace-new" required />
          </label>
          <button class="btn primary" data-testid="submit-replace" type="submit">执行替换</button>
          <p class="muted hint">
            替换只影响未签核复核项；已签核项冻结保留原证据，同页其他关系不会重新送审。
          </p>
        </form>
      </div>

      <h3>证据登记台账</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>证据标识</th>
            <th>扫描批次</th>
            <th>证据版本</th>
            <th>来源系统</th>
            <th>证据说明</th>
            <th>登记人</th>
            <th>登记时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in evidenceRows" :key="row.id" :data-testid="`evidence-row-${row.id}`">
            <td>{{ row.证据标识 }}</td>
            <td>{{ row.扫描批次 }}</td>
            <td>{{ row.证据版本 }}</td>
            <td>{{ row.来源系统 }}</td>
            <td>{{ row.证据说明 }}</td>
            <td>{{ row.登记人 }}</td>
            <td>{{ row.登记时间 }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ================= 关系详情抽屉 ================= -->
    <div v-if="detail" class="modal-backdrop" data-testid="relation-detail" @click.self="detail = null">
      <div class="modal detail-modal">
        <h3>关系详情 · {{ detail.relation.关系标识 }}</h3>
        <dl class="detail-grid">
          <dt>扫描批次</dt><dd>{{ detail.relation.扫描批次 }}</dd>
          <dt>血缘路径</dt><dd>{{ detail.relation.血缘路径.join(' → ') }}</dd>
          <dt>替换关系</dt><dd>{{ detail.relation.替换关系 || '—' }}</dd>
        </dl>

        <div class="evidence-cols">
          <article class="evidence-card" :class="{ dimmed: detail.原证据 }">
            <h4>原证据</h4>
            <template v-if="detail.原证据">
              <p><strong>{{ detail.原证据.证据标识 }}</strong>（{{ detail.原证据.证据版本 }}）</p>
              <p class="muted">{{ detail.原证据.证据说明 }}</p>
              <p class="muted">来源：{{ detail.原证据.来源系统 }}</p>
            </template>
            <p v-else class="muted">该关系尚未发生证据替换</p>
          </article>
          <article v-if="detail.当前证据" class="evidence-card current">
            <h4>当前采用证据</h4>
            <p><strong>{{ detail.当前证据.证据标识 }}</strong>（{{ detail.当前证据.证据版本 }}）</p>
            <p class="muted">{{ detail.当前证据.证据说明 }}</p>
            <p class="muted">来源：{{ detail.当前证据.来源系统 }}</p>
            <span v-if="detail.relation.证据冲突" class="badge badge-warn">证据冲突待确认</span>
          </article>
          <article v-else class="evidence-card current">
            <h4>当前采用证据</h4>
            <p class="muted">当前采用证据缺失，请先登记并关联证据</p>
          </article>
        </div>

        <h4>后续待办</h4>
        <ul class="todo-list">
          <li v-for="todo in detail.待办" :key="todo" data-testid="detail-todo">{{ todo }}</li>
        </ul>

        <h4>同页未受影响项</h4>
        <table class="data-table">
          <thead>
            <tr><th>关系标识</th><th>下游列</th><th>当前证据</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in detail.未受影响项" :key="row.id">
              <td>{{ row.关系标识 }}</td>
              <td>{{ row.下游列 }}</td>
              <td>{{ row.当前证据标识 }}</td>
              <td>{{ row.status }}</td>
            </tr>
            <tr v-if="!detail.未受影响项.length">
              <td colspan="4" class="empty-state">同页无其他关系</td>
            </tr>
          </tbody>
        </table>

        <h4>复核记录</h4>
        <table class="data-table">
          <thead>
            <tr><th>工单</th><th>证据分类</th><th>复核状态</th><th>复核结论</th></tr>
          </thead>
          <tbody>
            <tr v-for="record in detail.复核记录" :key="record.id">
              <td>{{ record.工单标识 }}</td>
              <td><span class="badge" :class="categoryClass(record.证据分类)">{{ record.证据分类 }}</span></td>
              <td>{{ record.复核状态 }}</td>
              <td>{{ record.复核结论 || '—' }}</td>
            </tr>
            <tr v-if="!detail.复核记录.length">
              <td colspan="4" class="empty-state">该关系尚未进入复核范围</td>
            </tr>
          </tbody>
        </table>

        <div class="page-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- ================= 签核弹窗 ================= -->
    <div v-if="signOffTarget" class="modal-backdrop" data-testid="signoff-modal" @click.self="signOffTarget = null">
      <form class="modal" @submit.prevent="submitSignOff">
        <h3>提交复核 · {{ signOffTarget.工单标识 }}</h3>
        <p class="muted">提交后复核结论回写审计清单，复核项将被冻结。</p>
        <label class="create-field">
          <span>复核人</span>
          <input v-model="signOffForm.复核人" data-testid="signoff-reviewer" required />
        </label>
        <label class="create-field">
          <span>复核结论</span>
          <input v-model="signOffForm.复核结论" data-testid="signoff-conclusion" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="signOffTarget = null">取消</button>
          <button class="btn primary" data-testid="submit-signoff" type="submit">确认签核</button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>{{ footerText }}</span>
      <span v-if="errorMessage" class="error-text" data-testid="audit-error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  claimScope,
  getChecklist,
  getRelationDetail,
  getScope,
  listEvidence,
  listScopes,
  queryRelations,
  registerEvidence,
  replaceEvidence,
  restoreRelation,
  signOffScope,
  type RelationRow,
  type ReviewItem,
  type ScopeRow,
} from '@/api/audit-lineage'

type TabKey = 'relations' | 'scopes' | 'evidence'

const tabs = [
  { key: 'relations' as TabKey, label: '下游关系查询与领取' },
  { key: 'scopes' as TabKey, label: '复核工单与审计清单' },
  { key: 'evidence' as TabKey, label: '证据登记与替换' },
]
const activeTab = ref<TabKey>('relations')

const relationFilter = ref({ 扫描批次: 'BATCH-20261120-A', 下游列: 'balance', 证据版本: 'v1.0' })
const relations = ref<RelationRow[]>([])
const relationTotal = ref(0)

const scopes = ref<ScopeRow[]>([])
const expandedScope = ref<number | null>(null)
const expandedItems = ref<ReviewItem[]>([])
const checklist = ref<ReviewItem[]>([])
const checklistGroups = ref<Record<string, number>>({})
const checklistFilter = ref({ 扫描批次: 'BATCH-20261120-A', 下游列: '' })

const evidenceRows = ref<Awaited<ReturnType<typeof listEvidence>>['items']>([])
const evidenceFields = ['证据标识', '扫描批次', '来源系统', '证据版本', '证据说明', '登记人']
const evidenceForm = ref<Record<string, string>>(
  Object.fromEntries(evidenceFields.map((field) => [field, ''])),
)
const replaceForm = ref({ 原证据标识: 'e-301', 新证据标识: 'e-304' })

const detail = ref<Awaited<ReturnType<typeof getRelationDetail>> | null>(null)
const signOffTarget = ref<ScopeRow | null>(null)
const signOffForm = ref({ 复核人: '审计值班员', 复核结论: '' })

const errorMessage = ref('')
const claimMessage = ref('')
const claimOk = ref(true)

const footerText = computed(() => {
  if (activeTab.value === 'relations') return `共查到 ${relationTotal.value} 条字段血缘关系`
  if (activeTab.value === 'scopes') return `共 ${scopes.value.length} 份复核工单，清单 ${checklist.value.length} 行`
  return `证据台账共 ${evidenceRows.value.length} 条`
})

function categoryClass(category: string): string {
  if (category === '原证据') return 'badge-danger'
  if (category === '当前证据') return 'badge-ok'
  return 'badge-muted'
}

async function loadRelations() {
  errorMessage.value = ''
  try {
    const payload = await queryRelations(relationFilter.value)
    relations.value = payload.items
    relationTotal.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下游关系查询失败'
  }
}

function resetRelationFilter() {
  relationFilter.value = { 扫描批次: '', 下游列: '', 证据版本: '' }
  void loadRelations()
}

async function claimCurrentScope() {
  errorMessage.value = ''
  claimMessage.value = ''
  try {
    const result = await claimScope({
      扫描批次: relationFilter.value.扫描批次,
      下游列: relationFilter.value.下游列,
      证据版本: relationFilter.value.证据版本,
      领取人: '审计值班员',
    })
    claimOk.value = true
    claimMessage.value = result.reused
      ? `相同范围已存在工单 ${result.scope.工单标识}，已复用，未重复生成`
      : `${result.message}（${result.scope.工单标识}）`
    await loadRelations()
    await loadScopes()
  } catch (error) {
    claimOk.value = false
    claimMessage.value = error instanceof Error ? error.message : '领取复核范围失败'
  }
}

async function openDetail(id: number) {
  errorMessage.value = ''
  try {
    detail.value = await getRelationDetail(id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '关系详情读取失败'
  }
}

async function restore(id: number) {
  errorMessage.value = ''
  try {
    await restoreRelation(id)
    await loadRelations()
    if (detail.value?.relation.id === id) await openDetail(id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '断线恢复失败'
  }
}

async function loadScopes() {
  const payload = await listScopes()
  scopes.value = payload.items
}

async function toggleScopeItems(id: number) {
  if (expandedScope.value === id) {
    expandedScope.value = null
    expandedItems.value = []
    return
  }
  expandedScope.value = id
  const detailPayload = await getScope(id)
  expandedItems.value = detailPayload.复核项 ?? []
}

function openSignOff(scope: ScopeRow) {
  signOffTarget.value = scope
  signOffForm.value = { 复核人: '审计值班员', 复核结论: '' }
}

async function submitSignOff() {
  if (!signOffTarget.value) return
  errorMessage.value = ''
  try {
    await signOffScope(signOffTarget.value.id, signOffForm.value)
    const reopenedScopeId = expandedScope.value
    signOffTarget.value = null
    await loadScopes()
    await loadChecklist()
    if (reopenedScopeId) {
      expandedScope.value = reopenedScopeId
      expandedItems.value = (await getScope(reopenedScopeId)).复核项 ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '签核失败'
  }
}

async function loadChecklist() {
  errorMessage.value = ''
  try {
    const payload = await getChecklist(checklistFilter.value)
    checklist.value = payload.items
    checklistGroups.value = payload.groups
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审计清单读取失败'
  }
}

async function loadEvidence() {
  const payload = await listEvidence()
  evidenceRows.value = payload.items
}

async function submitEvidence() {
  errorMessage.value = ''
  try {
    await registerEvidence(evidenceForm.value)
    evidenceForm.value = Object.fromEntries(evidenceFields.map((field) => [field, '']))
    await loadEvidence()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证据登记失败'
  }
}

async function submitReplace() {
  errorMessage.value = ''
  try {
    const result = await replaceEvidence(replaceForm.value.原证据标识, replaceForm.value.新证据标识)
    claimOk.value = true
    claimMessage.value = `${result.message}；同页未受影响关系：${result.同页未受影响关系.join('、') || '无'}`
    await Promise.all([loadRelations(), loadScopes(), loadChecklist(), loadEvidence()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证据替换失败'
  }
}

async function switchTab(tab: TabKey) {
  activeTab.value = tab
  await refreshAll()
}

async function refreshAll() {
  errorMessage.value = ''
  try {
    await Promise.all([
      loadRelations(),
      loadScopes(),
      loadChecklist(),
      loadEvidence(),
    ])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据刷新失败'
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.audit-page { display: flex; flex-direction: column; gap: 12px; }
.tab-bar { display: flex; gap: 8px; border-bottom: 1px solid var(--border); }
.tab-btn { border: none; background: none; padding: 8px 16px; cursor: pointer; font-size: 14px; color: var(--muted); border-bottom: 2px solid transparent; }
.tab-btn.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }
.audit-filter { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.inline-message { font-size: 13px; margin: 0; }
.inline-message.ok { color: #15803d; }
.badge { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; margin-left: 4px; }
.badge-ok { background: #dcfce7; color: #15803d; }
.badge-warn { background: #fef3c7; color: #b45309; }
.badge-danger { background: #fee2e2; color: #b42318; }
.badge-muted { background: #e2e8f0; color: #475569; }
.muted { color: var(--muted); font-size: 12px; }
.path-cell { max-width: 320px; }
.path-step { white-space: nowrap; font-size: 12px; }
tr.conflict { background: #fffbeb; }
tr.broken { background: #fef2f2; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.modeless { position: static; box-shadow: none; width: 100%; max-height: none; }
.hint { margin-top: 8px; }
.detail-modal { width: min(880px, 100%); }
.detail-grid { display: grid; grid-template-columns: 120px 1fr; gap: 6px 12px; }
.detail-grid dt { color: var(--muted); font-size: 12px; }
.detail-grid dd { margin: 0; font-size: 13px; }
.evidence-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
.evidence-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px; background: #fafbfc; }
.evidence-card.dimmed { opacity: 0.85; }
.evidence-card.current { border-color: var(--brand); background: #f0f6ff; }
.evidence-card h4 { margin: 0 0 8px; }
.todo-list { margin: 4px 0 12px; padding-left: 20px; font-size: 13px; }
.scope-items { margin: 12px 0; }
.scope-items h3, .tab-panel h3 { font-size: 14px; margin: 14px 0 8px; }
</style>
