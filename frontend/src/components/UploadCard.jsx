import { useRef, useState } from 'react'

/**
 * Per-company PDF upload area. Stage 4B: wired to the backend.
 *
 * Local-only state: the chosen file is held in this component so the
 * user can re-pick without an immediate upload. The actual POST
 * `/api/ingest/upload` is invoked when the user clicks "Upload". A
 * successful upload replaces local file state with the server's
 * `meta` (document_name, page_count, chunk_count, table_count) so the
 * user sees the real ingestion result, not what we fabricated.
 *
 * Loading state comes from the parent (`status="uploading"` disables
 * the picker and shows a spinner) so duplicate uploads are blocked at
 * the dashboard level.
 *
 * Empty-state text uses the literal "Not available" phrasing for
 * unavailable values, matching the backend's UNAVAILABLE marker.
 */
export default function UploadCard({
  company,
  label,
  accent = 'brand',
  meta = null,            // UploadResponse from /api/ingest/upload
  status = 'idle',        // 'idle' | 'uploading' | 'uploaded' | 'error'
  errorMsg = '',
  onUpload = null,        // (company, file) => Promise
  onClear = null,         // (company) => void  -- clears meta + local file
}) {
  const [file, setFile] = useState(null)
  const [localError, setLocalError] = useState('')
  const inputRef = useRef(null)

  const isUploading = status === 'uploading'
  const isUploaded = status === 'uploaded' && !!meta

  const handleSelect = (event) => {
    const next = event.target.files?.[0]
    if (!next) {
      setFile(null)
      setLocalError('')
      return
    }
    if (!next.name.toLowerCase().endsWith('.pdf')) {
      setFile(null)
      setLocalError('Only PDF files are accepted.')
      return
    }
    setLocalError('')
    setFile(next)
  }

  const handleReset = () => {
    setFile(null)
    setLocalError('')
    if (inputRef.current) inputRef.current.value = ''
    if (onClear) onClear(company)
  }

  const handleUpload = async () => {
    if (!file || !onUpload) return
    await onUpload(company, file)
    // On success the parent will pass `meta` and `status="uploaded"`,
    // which clears the local file picker (replace mode below).
  }

  const accentRing = {
    brand: 'ring-brand-200 focus:ring-brand-500',
    emerald: 'ring-emerald-200 focus:ring-emerald-500',
  }[accent] || 'ring-slate-200 focus:ring-slate-400'

  const errorToShow = localError || (status === 'error' ? errorMsg : '')

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {label}
          </h3>
          <p className="text-xs text-slate-500">Company identifier: {company}</p>
        </div>
        <span
          className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-700"
          aria-hidden="true"
        >
          {company}
        </span>
      </div>

      <label
        className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center ring-2 ring-transparent transition hover:bg-slate-100 ${accentRing} ${
          isUploading ? 'pointer-events-none opacity-60' : ''
        }`}
      >
        <span className="text-sm font-medium text-slate-700">
          {isUploaded ? 'Replace PDF' : file ? 'Replace selection' : 'Click to choose a PDF'}
        </span>
        <span className="mt-1 text-xs text-slate-500">
          Annual report or financial filing
        </span>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={handleSelect}
          disabled={isUploading}
          className="hidden"
        />
      </label>

      <div className="mt-3 min-h-[1.5rem] text-sm">
        {file && !isUploaded ? (
          <div className="flex items-center justify-between gap-3">
            <div className="truncate">
              <span className="font-medium text-slate-800">{file.name}</span>
              <span className="ml-2 text-xs text-slate-500">
                {(file.size / 1024).toFixed(1)} KB
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleUpload}
                disabled={isUploading || !onUpload}
                className="rounded-md bg-slate-800 px-3 py-1 text-xs font-medium text-white hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isUploading ? 'Uploading…' : 'Upload'}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={isUploading}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear
              </button>
            </div>
          </div>
        ) : isUploaded && meta ? (
          <div>
            <div className="flex items-center justify-between gap-3">
              <div className="truncate">
                <span className="font-medium text-slate-800">
                  {meta.document_name}
                </span>
                <span className="ml-2 text-xs text-slate-500">
                  {meta.page_count} page{meta.page_count === 1 ? '' : 's'}
                </span>
              </div>
              <button
                type="button"
                onClick={handleReset}
                disabled={isUploading}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear
              </button>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {meta.chunk_count} chunks · {meta.table_count} tables ·
              sha256 {meta.document_sha256?.slice(0, 10) || ''}…
            </div>
          </div>
        ) : isUploading ? (
          <p className="italic text-slate-500">Uploading and extracting…</p>
        ) : errorToShow ? (
          <p className="text-rose-600">{errorToShow}</p>
        ) : (
          <p className="italic text-slate-400">Not available</p>
        )}
      </div>
    </div>
  )
}
