/**
 * Generic section wrapper used across the dashboard. Renders a title,
 * optional subtitle, and either children or an empty-state line.
 *
 * Empty-state line intentionally uses the exact phrase "Not available"
 * so the demo behaviour is consistent with the Stage 1–3 backend
 * contract (UNAVAILABLE marker) and easy to scan in a walkthrough.
 */
export default function Section({
  title,
  subtitle,
  children,
  isEmpty = false,
  emptyText = 'Not available',
  className = '',
}) {
  return (
    <section
      className={`rounded-lg border border-slate-200 bg-white p-5 shadow-sm ${className}`}
    >
      <header className="mb-3">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
        ) : null}
      </header>
      {isEmpty ? (
        <p className="text-sm italic text-slate-400">{emptyText}</p>
      ) : (
        children
      )}
    </section>
  )
}
