/** 数据审计-证据版本血缘复核接口封装。 */
import { request } from './client'

export type RelationRow = {
  id: number
  关系标识: string
  扫描批次: string
  上游表: string
  上游列: string
  下游表: string
  下游列: string
  当前证据标识: string
  原证据标识: string
  证据版本: string
  血缘路径: string[]
  替换关系: string
  证据冲突: boolean
  待办说明: string
  status: string
}

export type EvidenceRow = {
  id: number
  证据标识: string
  扫描批次: string
  来源系统: string
  证据版本: string
  证据说明: string
  登记人: string
  登记时间: string
}

export type ReviewItem = {
  id: number | string
  relation_id: number
  关系标识: string
  工单标识: string
  扫描批次: string
  下游表: string
  下游列: string
  血缘路径: string[]
  替换关系: string
  原证据标识: string
  原证据版本: string
  当前证据标识: string
  当前证据版本: string
  证据来源系统: string
  证据冲突: boolean
  证据冻结?: boolean
  证据分类: string
  复核状态: string
  复核结论: string
  复核人: string
  复核时间: string
}

export type ScopeRow = {
  id: number
  工单标识: string
  扫描批次: string
  下游列: string
  工单状态: string
  领取人: string
  领取时间: string
  签核时间: string
  复核结论: string
  范围关系数: number
  复核项?: ReviewItem[]
}

async function asJson<T>(response: Response): Promise<T> {
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload?.detail ?? '接口调用失败')
  }
  return payload as T
}

function toQuery(params: Record<string, string>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value)
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}

export async function queryRelations(filters: Record<string, string>) {
  const response = await request(`/api/audit-lineage/relations${toQuery(filters)}`)
  return asJson<{ items: RelationRow[]; total: number }>(response)
}

export async function getRelationDetail(id: number) {
  const response = await request(`/api/audit-lineage/relations/${id}`)
  return asJson<{
    relation: RelationRow
    原证据: EvidenceRow | null
    当前证据: EvidenceRow | null
    未受影响项: RelationRow[]
    复核记录: ReviewItem[]
    待办: string[]
  }>(response)
}

export async function listEvidence(scanBatch = '') {
  const response = await request(`/api/audit-lineage/evidence${toQuery({ 扫描批次: scanBatch })}`)
  return asJson<{ items: EvidenceRow[]; total: number }>(response)
}

export async function registerEvidence(values: Record<string, string>) {
  const response = await request('/api/audit-lineage/evidence', {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return asJson<{ ok: boolean; message: string; entry: EvidenceRow }>(response)
}

export async function replaceEvidence(原证据标识: string, 新证据标识: string) {
  const response = await request('/api/audit-lineage/evidence/replace', {
    method: 'POST',
    body: JSON.stringify({ 原证据标识, 新证据标识 }),
  })
  return asJson<{
    ok: boolean
    message: string
    更新关系数: number
    更新复核项数: number
    冻结签核项数: number
    同页未受影响关系: string[]
  }>(response)
}

export async function claimScope(payload: Record<string, string>) {
  const response = await request('/api/audit-lineage/scopes/claim', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return asJson<{ ok: boolean; reused: boolean; message: string; scope: ScopeRow }>(response)
}

export async function listScopes(工单状态 = '') {
  const response = await request(`/api/audit-lineage/scopes${toQuery({ 工单状态 })}`)
  return asJson<{ items: ScopeRow[]; total: number }>(response)
}

export async function getScope(id: number) {
  const response = await request(`/api/audit-lineage/scopes/${id}`)
  return asJson<ScopeRow>(response)
}

export async function signOffScope(id: number, payload: Record<string, string>) {
  const response = await request(`/api/audit-lineage/scopes/${id}/sign-off`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return asJson<{ ok: boolean; message: string; scope: ScopeRow }>(response)
}

export async function restoreRelation(id: number) {
  const response = await request(`/api/audit-lineage/relations/${id}/restore`, { method: 'POST' })
  return asJson<{ ok: boolean; message: string }>(response)
}

export async function markRelationBroken(id: number) {
  const response = await request(`/api/audit-lineage/relations/${id}/broken`, { method: 'POST' })
  return asJson<{ ok: boolean; message: string }>(response)
}

export async function getChecklist(filters: Record<string, string>) {
  const response = await request(`/api/audit-lineage/checklist${toQuery(filters)}`)
  return asJson<{ items: ReviewItem[]; total: number; groups: Record<string, number> }>(response)
}
