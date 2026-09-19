/**
 * Three-button analysis controls row. Stage 4B: wired.
 *
 * Buttons are enabled when their precondition is met:
 *   - Analyze Company A / B — that company's PDF must be ingested.
 *   - Compare Companies  — both agents must have completed (so the
 *     comparator has two analyses to compare).
 *
 * While a button's request is in flight it shows a spinner and is
 * disabled so a click cannot fire a duplicate request.
 */

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-60'

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
        className="opacity-25"
      />
      <path
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
        className="opacity-75"
      />
    </svg>
  )
}

function ActionButton({ label, tone = 'slate', loading, disabled, onClick }) {
  const toneClass = {
    brand: 'bg-brand-600 text-white hover:bg-brand-700 focus:ring-brand-400',
    emerald: 'bg-emerald-600 text-white hover:bg-emerald-700 focus:ring-emerald-400',
    slate: 'bg-slate-800 text-white hover:bg-slate-900 focus:ring-slate-500',
  }[tone]

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`${BUTTON_BASE} ${toneClass}`}
    >
      {loading ? <Spinner /> : null}
      {label}
    </button>
  )
}

export default function AnalysisControls({
  busy = {},
  ready = { A: false, B: false, bothAnalyses: false },
  agents = { A: null, B: null },
  comparison = null,
  onAnalyzeA = () => {},
  onAnalyzeB = () => {},
  onCompare = () => {},
  onReset = () => {},
}) {
  const aBusy = !!busy.analyzeA
  const bBusy = !!busy.analyzeB
  const cBusy = !!busy.compare
  const rBusy = !!busy.reset

  const aStatus = agents?.A?.status || 'idle'
  const bStatus = agents?.B?.status || 'idle'

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Analysis controls
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Triggers isolated per-company analysis and the comparator. Each
            agent reads only its own PDF; the comparator only runs after
            both agents have completed.
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          disabled={rBusy}
          className="rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {rBusy ? 'Resetting…' : 'Reset all'}
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <ActionButton
          label="Analyze Company A"
          tone="brand"
          loading={aBusy}
          disabled={!ready.A}
          onClick={onAnalyzeA}
        />
        <ActionButton
          label="Analyze Company B"
          tone="emerald"
          loading={bBusy}
          disabled={!ready.B}
          onClick={onAnalyzeB}
        />
        <ActionButton
          label="Compare Companies"
          tone="slate"
          loading={cBusy}
          disabled={!ready.bothAnalyses}
          onClick={onCompare}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-1 text-xs text-slate-500 sm:grid-cols-3">
        <span>
          Agent A:{' '}
          <span className="font-medium text-slate-700">{aStatus}</span>
        </span>
        <span>
          Agent B:{' '}
          <span className="font-medium text-slate-700">{bStatus}</span>
        </span>
        <span>
          Comparator:{' '}
          <span className="font-medium text-slate-700">
            {comparison?.status || 'idle'}
          </span>
        </span>
      </div>
    </div>
  )
}
