import { useState } from 'react'
import Section from './Section'

/**
 * Reusable bulleted list section. Stage 4B renders both Stage 2 and
 * Stage 3 entry shapes:
 *
 *   Stage 2 (BulletWithEvidence):
 *     { point: str, evidence: [EvidenceRef, ...] }
 *
 *   Stage 3 (KeyDifference / Trend / ComparativeInsight):
 *     { title: str, description?: str, claim?: str, kind?:
 *       'fact'|'derived'|'insight', evidence: [ComparisonEvidence, ...] }
 *
 * The component normalizes both shapes into the same display row.
 * No fabrication: if title/description/claim are missing, the cell
 * falls back to "Not available".
 *
 * Each entry also gets an inline evidence preview (ref_id + page +
 * truncated snippet) so the user can audit any claim without leaving
 * the section.
 */
const CLAIM_KIND_CHIP = {
  fact: 'bg-blue-50 text-blue-700',
  derived: 'bg-amber-50 text-amber-700',
  insight: 'bg-purple-50 text-purple-700',
}

function Entry({ entry }) {
  const title = entry.title || entry.summary || entry.point || 'Untitled'
  const description =
    entry.description || entry.detail || entry.claim || entry.summary || null
  const kind = entry.kind
  const evidence = Array.isArray(entry.evidence) ? entry.evidence : []

  const [expanded, setExpanded] = useState(false)
  const visibleEvidence = expanded ? evidence : evidence.slice(0, 2)

  return (
    <li className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-medium text-slate-900">{title}</div>
        {kind && CLAIM_KIND_CHIP[kind] ? (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${CLAIM_KIND_CHIP[kind]}`}
          >
            {kind}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-slate-500">
          {evidence.length} source{evidence.length === 1 ? '' : 's'}
        </span>
      </div>
      {description ? (
        <p className="mt-1 text-sm text-slate-700">{description}</p>
      ) : null}
      {evidence.length > 0 ? (
        <div className="mt-2 space-y-1">
          {visibleEvidence.map((ev, idx) => (
            <div
              key={`${ev.ref_id || idx}`}
              className="text-xs text-slate-500"
            >
              <span className="font-mono text-[10px] text-slate-400">
                {ev.ref_id}
              </span>
              {ev.page_number ? (
                <span className="ml-2">p.{ev.page_number}</span>
              ) : null}
              {ev.snippet ? (
                <span className="ml-2 truncate text-slate-600">
                  “{ev.snippet.length > 80 ? `${ev.snippet.slice(0, 80)}…` : ev.snippet}”
                </span>
              ) : null}
            </div>
          ))}
          {evidence.length > 2 ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-brand-700 hover:underline"
            >
              {expanded ? 'Show fewer sources' : `Show all ${evidence.length} sources`}
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

export default function ListSection({
  title,
  subtitle,
  items = null,
  emptyText = 'Not available',
}) {
  const isEmpty = !Array.isArray(items) || items.length === 0
  return (
    <Section
      title={title}
      subtitle={subtitle}
      isEmpty={isEmpty}
      emptyText={emptyText}
    >
      {!isEmpty ? (
        <ul className="space-y-2">
          {items.map((entry, idx) => (
            <Entry key={`${entry.ref_id || entry.title || entry.point || idx}-${idx}`} entry={entry} />
          ))}
        </ul>
      ) : null}
    </Section>
  )
}
