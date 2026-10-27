import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { DocumentDetailPage } from './pages/admin/DocumentDetailPage'
import { DocumentsPage } from './pages/admin/DocumentsPage'
import { FinancePage } from './pages/admin/FinancePage'
import { LoginPage } from './pages/admin/LoginPage'
import { PageReviewPage } from './pages/admin/PageReviewPage'
import { ToolsPage } from './pages/admin/ToolsPage'
import { ChatPage } from './pages/chat/ChatPage'
import { DashboardPage } from './pages/dashboard/DashboardPage'
import { EvalPage } from './pages/eval/EvalPage'
import { QueryDetailPage } from './pages/queries/QueryDetailPage'
import { UserDocumentsPage } from './pages/library/UserDocumentsPage'
import { QueryListPage } from './pages/queries/QueryListPage'

const guarded = (el: JSX.Element) => <RequireAuth>{el}</RequireAuth>

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="documents" element={<UserDocumentsPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="dashboard" element={guarded(<DashboardPage />)} />
        <Route path="queries" element={guarded(<QueryListPage />)} />
        <Route path="queries/:queryId" element={guarded(<QueryDetailPage />)} />
        <Route path="eval" element={guarded(<EvalPage />)} />
        <Route path="admin/documents" element={guarded(<DocumentsPage />)} />
        <Route path="admin/documents/:documentId" element={guarded(<DocumentDetailPage />)} />
        <Route path="admin/documents/:documentId/pages/:page" element={guarded(<PageReviewPage />)} />
        <Route path="admin/finance" element={guarded(<FinancePage />)} />
        <Route path="admin/tools" element={guarded(<ToolsPage />)} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
