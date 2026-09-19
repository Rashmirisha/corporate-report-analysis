import { BrowserRouter, Routes, Route } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'

/**
 * App router. Stage 4A shell exposes a single dashboard route.
 *
 * Routing is wired with react-router-dom so the next stage can add
 * /upload, /analyses/:company, /comparison, etc., without an import
 * churn. For now there is exactly one route: `/`.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
      </Routes>
    </BrowserRouter>
  )
}
