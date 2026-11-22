import { Navigate, Route, Routes } from 'react-router-dom'
import { BrowserRouter } from 'react-router-dom'

import { Shell } from './components/Shell'
import { ViewModeProvider } from './components/ViewModeContext'
import { AccountsPage } from './pages/AccountsPage'
import { BaWorkbenchPage } from './pages/BaWorkbenchPage'
import { ConfigurationPage } from './pages/ConfigurationPage'
import { ControlRoomPage } from './pages/ControlRoomPage'
import { EventLogPage } from './pages/EventLogPage'
import { ExceptionsPage } from './pages/ExceptionsPage'
import { InvestigationDetailPage } from './pages/InvestigationDetailPage'
import { InvestigationsPage } from './pages/InvestigationsPage'
import { MessageExplorerPage } from './pages/MessageExplorerPage'
import { MessageTracePage } from './pages/MessageTracePage'
import { MtMxPage } from './pages/MtMxPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PaymentDetailPage } from './pages/PaymentDetailPage'
import { PaymentSearchPage } from './pages/PaymentSearchPage'
import { PaymentSimulatorPage } from './pages/PaymentSimulatorPage'
import { QaFailuresPage } from './pages/QaFailuresPage'
import { QaScenariosPage } from './pages/QaScenariosPage'
import { QaTestCasesPage } from './pages/QaTestCasesPage'
import { ReconciliationDetailPage } from './pages/ReconciliationDetailPage'
import { ReconciliationPage } from './pages/ReconciliationPage'
import { RuleEnginePage } from './pages/RuleEnginePage'
import { SchemesPage } from './pages/SchemesPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />} path="/">
        <Route index element={<ControlRoomPage />} />
        <Route path="payments" element={<PaymentSearchPage />} />
        <Route path="payments/new" element={<PaymentSimulatorPage />} />
        <Route path="payments/:reference" element={<PaymentDetailPage />} />
        <Route path="investigations" element={<InvestigationsPage />} />
        <Route path="investigations/:reference" element={<InvestigationDetailPage />} />
        <Route path="exceptions" element={<ExceptionsPage />} />
        <Route path="reconciliation" element={<ReconciliationPage />} />
        <Route path="reconciliation/:reference" element={<ReconciliationDetailPage />} />
        <Route path="messages" element={<MessageExplorerPage />} />
        <Route path="messages/explorer" element={<MessageExplorerPage />} />
        <Route path="messages/trace" element={<MessageTracePage />} />
        <Route path="messages/mt-mx" element={<MtMxPage />} />
        <Route path="schemes" element={<SchemesPage />} />
        <Route path="schemes/:code" element={<SchemesPage />} />
        <Route path="qa/scenarios" element={<QaScenariosPage />} />
        <Route path="qa/failures" element={<QaFailuresPage />} />
        <Route path="qa/test-cases" element={<QaTestCasesPage />} />
        <Route path="ba" element={<BaWorkbenchPage />} />
        <Route path="ba/requirements" element={<Navigate to="/ba" replace />} />
        <Route path="system/events" element={<EventLogPage />} />
        <Route path="system/rules" element={<RuleEnginePage />} />
        <Route path="system/accounts" element={<AccountsPage />} />
        <Route path="system/configuration" element={<ConfigurationPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <ViewModeProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </ViewModeProvider>
  )
}
