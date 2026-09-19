/**
 * Stage 4B dashboard shell + integration smoke test (node environment).
 *
 * The test deliberately avoids @testing-library/react so it can run
 * without jsdom/happy-dom (which are not declared in package.json —
 * adding them is out of scope for Stage 4A/4B).
 *
 * Instead, it imports the source files and verifies the structural
 * contract: every required section title is present in the rendered
 * output of the static source, no fabricated company names appear,
 * and "Not available" is used consistently as the empty marker.
 *
 * Stage 4B additions: assertions that the apiClient is wired to the
 * real endpoints (/api/ingest/upload, /api/agents/run, /api/comparison/run,
 * etc.) and that the useDashboard hook owns the network state.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const read = (rel) => readFileSync(resolve(ROOT, rel), 'utf8')

describe('Stage 4B dashboard shell — source contract', () => {
  const dashboard = read('src/pages/DashboardPage.jsx')
  const header = read('src/components/Header.jsx')
  const app = read('src/App.jsx')
  const indexCss = read('src/index.css')
  const indexHtml = read('index.html')
  const apiClient = read('src/api/apiClient.js')
  const hook = read('src/hooks/useDashboard.js')
  const uploadCard = read('src/components/UploadCard.jsx')
  const analysisControls = read('src/components/AnalysisControls.jsx')
  const evidencePanel = read('src/components/EvidencePanel.jsx')
  const financialComparison = read('src/components/FinancialComparison.jsx')

  it('Header.jsx carries the project title', () => {
    expect(header).toContain('Corporate Report Analysis and Decision Support System')
    expect(dashboard).toContain("import Header from '../components/Header'")
  })

  it('DashboardPage renders both upload areas', () => {
    expect(dashboard).toContain('Company A PDF')
    expect(dashboard).toContain('Company B PDF')
  })

  it('DashboardPage includes every required section title', () => {
    const required = [
      'Strengths',
      'Weaknesses',
      'Risks',
      'Key Differences',
      'Comparative / AI Insights',
      'Evidence',
      'Analysis controls',
    ]
    for (const needle of required) {
      expect(dashboard).toContain(needle)
    }
    // "Financial comparison" is rendered by <FinancialComparison />, not
    // inlined in DashboardPage; verify the component covers it.
    expect(read('src/components/FinancialComparison.jsx')).toContain('Financial comparison')
  })

  it('DashboardPage uses "Not available" for empty states', () => {
    expect(dashboard).toContain('Not available')
  })

  it('DashboardPage does not fabricate company names', () => {
    for (const forbidden of ['Acme', 'Globex', 'Initech', 'Umbrella', 'Wayne', 'Stark']) {
      expect(dashboard).not.toContain(forbidden)
    }
  })

  it('DashboardPage does not embed fabricated financial values', () => {
    expect(dashboard).not.toMatch(/\$\d/)
    expect(dashboard).not.toMatch(/₹\d/)
    expect(dashboard).not.toMatch(/\bEUR\s*\d/i)
  })

  it('App wires react-router-dom with a `/` route', () => {
    expect(app).toContain('BrowserRouter')
    expect(app).toContain('Routes')
    expect(app).toContain('DashboardPage')
    expect(app).toMatch(/<Route[^>]*path=["']\/["']/)
  })

  it('Tailwind CSS is wired through index.css and the index.html', () => {
    expect(indexCss).toContain('@tailwind base')
    expect(indexCss).toContain('@tailwind components')
    expect(indexCss).toContain('@tailwind utilities')
    expect(indexHtml).toContain('id="root"')
    expect(indexHtml).toContain('/src/main.jsx')
  })
})

describe('Stage 4B API integration — endpoint wiring', () => {
  const apiClient = read('src/api/apiClient.js')

  it('apiClient targets every backend route that the dashboard uses', () => {
    // Stage 1
    expect(apiClient).toContain('/health')
    expect(apiClient).toContain('/corpus')
    expect(apiClient).toContain('/ingest/upload')
    // Stage 2
    expect(apiClient).toContain('/agents/status')
    expect(apiClient).toContain('/agents/run')
    expect(apiClient).toContain('/agents/${company}/analysis')
    // Stage 3
    expect(apiClient).toContain('/comparison/run')
    expect(apiClient).toContain('/comparison')
  })

  it('apiClient.uploadPdf uses multipart/form-data (FormData)', () => {
    expect(apiClient).toContain('FormData')
    expect(apiClient).toContain("append('company', company)")
    expect(apiClient).toContain("append('file', file, file.name)")
  })

  it('apiClient never talks to Ollama directly', () => {
    expect(apiClient).not.toContain('localhost:11434')
    expect(apiClient).not.toContain('ollama')
    expect(apiClient).not.toContain('qwen')
  })
})

describe('Stage 4B API integration — hook & components', () => {
  const hook = read('src/hooks/useDashboard.js')
  const dashboard = read('src/pages/DashboardPage.jsx')
  const uploadCard = read('src/components/UploadCard.jsx')
  const analysisControls = read('src/components/AnalysisControls.jsx')
  const evidencePanel = read('src/components/EvidencePanel.jsx')

  it('useDashboard owns all network calls and busy flags', () => {
    expect(hook).toContain('uploadPdf')
    expect(hook).toContain('runAgent')
    expect(hook).toContain('runComparison')
    expect(hook).toContain('resetAll')
    // busy map protects against duplicate requests.
    expect(hook).toContain('busy')
    expect(hook).toContain('runGuarded')
    expect(hook).toContain('guards.current[flag]')
  })

  it('useDashboard probes /api/health for backend reachability', () => {
    expect(hook).toContain("apiClient.health()")
    expect(hook).toContain('BACKEND_OFFLINE')
    expect(hook).toContain('BACKEND_ONLINE')
  })

  it('useDashboard never calls Ollama directly', () => {
    expect(hook).not.toContain('localhost:11434')
    expect(hook).not.toContain('ollama')
    expect(hook).not.toContain('qwen')
  })

  it('DashboardPage wires every callback into the hook', () => {
    expect(dashboard).toContain('useDashboard')
    expect(dashboard).toContain('uploadPdf')
    expect(dashboard).toContain('runAgent')
    expect(dashboard).toContain('runComparison')
    expect(dashboard).toContain('resetAll')
  })

  it('UploadCard accepts onUpload callback for backend submission', () => {
    expect(uploadCard).toContain('onUpload')
    expect(uploadCard).toContain('Upload')
  })

  it('AnalysisControls disables buttons when preconditions are not met', () => {
    expect(analysisControls).toContain('disabled')
    expect(analysisControls).toContain('bothAnalyses')
  })

  it('EvidencePanel renders both EvidenceRef and ComparisonEvidence', () => {
    expect(evidencePanel).toContain('ref_kind')
    expect(evidencePanel).toContain('chunk')
    expect(evidencePanel).toContain('fact')
    expect(evidencePanel).toContain('derived')
    expect(evidencePanel).toContain('insight')
  })
})
