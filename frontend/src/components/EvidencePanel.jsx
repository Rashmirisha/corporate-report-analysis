import Section from './Section'

/**
 * Evidence / Sources panel. Stage 4B: handles BOTH evidence shapes:
 *
 *  1. Stage 2 EvidenceRef (AgentAnalysis):
 *       { company, document_name, document_sha256, page_number,
 *         kind: "chunk"|"table", ref_id, snippet }
 *
 *  2. Stage 3 ComparisonEvidence (ComparativeAnalysis):
 *       { company, document_name, document_sha256, page_number,
 *         ref_kind: "chunk"|"table", ref_id, snippet,
 *         kind: "fact"|"derived"|"insight" }
 *
 * The component picks the right field (`kind` vs `ref_kind`) and shows
 * the comparator's claim-kind badge when present.
 *
 * Stage 4B rule: every field is rendered verbatim. We never strip
 * `document_name`, `document_sha256`, `page_number`, or `ref_id` — those
 * are the audit trail back to the source PDF.
 */

const COMPANY_CHIP = {
  A: 'bg-brand-50 text-brand-700',
  B: 'bg-emerald-50 text-emerald-700',
}

const REF_KIND_CHIP = 'bg-slate-200 text-slate-700'

const CLAIM_KIND_CHIP = {
  fact: 'bg-blue-50 text-blue-700',
  derived: 'bg-amber-50 text-amber-700',
  insight: 'bg-purple-50 text-purple-700',
}

function EvidenceItem({ item }) {
  const company = item.company
  const refKind = item.ref_kind || item.kind || 'chunk'
  const claimKind = item.kind && (item.kind === 'fact' || item.kind === 'derived' || item.kind === 'insight')
    ? item.kind
    : null
  const companyChip = COMPANY_CHIP[company] || 'bg-slate-100 text-slate-700'

  return (
    <li className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {company ? (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${companyChip}`}
          >
            Company {company}
          </span>
        ) : null}
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${REF_KIND_CHIP}`}
        >
          {refKind}
        </span>
        {claimKind ? (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${
              CLAIM_KIND_CHIP[claimKind] || 'bg-slate-200 text-slate-700'
            }`}
          >
            {claimKind}
          </span>
        ) : null}
        {item.page_number ? (
          <span className="text-slate-500">page {item.page_number}</span>
        ) : null}
        {item.document_name ? (
          <span className="truncate text-slate-500">— {item.document_name}</span>
        ) : null}
        {item.ref_id ? (
          <span className="ml-auto font-mono text-[10px] text-slate-400">
            {item.ref_id}
          </span>
        ) : null}
      </div>
      {item.snippet ? (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-700">
          {item.snippet}
        </blockquote>
      ) : null}
    </li>
  )
}

export default function EvidencePanel({ items = null, title = 'Evidence & Sources' }) {
  const isEmpty = !Array.isArray(items) || items.length === 0
  return (
    <Section
      title={title}
      subtitle="Every claim above cites a source chunk or table. Each item shows the company, claim kind, page, and snippet."
      isEmpty={isEmpty}
      emptyText="Not available"
    >
      {!isEmpty ? (
        <ul className="space-y-2">
          {items.map((item, idx) => (
            <EvidenceItem key={`${item.ref_id || item.snippet || idx}-${idx}`} item={item} />
          ))}
        </ul>
      ) : null}
    </Section>
  )
}
