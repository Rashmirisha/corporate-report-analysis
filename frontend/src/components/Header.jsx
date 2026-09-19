/**
 * Project header. Stage 4B: subtitle is supplied by the dashboard so it
 * can show the comparator-derived company names once they are known.
 */
export default function Header({ subtitle }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Corporate Report Analysis and Decision Support System
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {subtitle ||
            'Compare two annual reports with isolated AI agents and evidence-grounded insights.'}
        </p>
      </div>
    </header>
  )
}
