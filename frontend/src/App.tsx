import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditPage } from "./features/audit/AuditPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { EvaluationDetailPage } from "./features/evaluations/EvaluationDetailPage";
import { EvaluationsPage } from "./features/evaluations/EvaluationsPage";
import { ExecutionDetailPage } from "./features/executions/ExecutionDetailPage";
import { ExecutionsPage } from "./features/executions/ExecutionsPage";
import { PoliciesPage } from "./features/policies/PoliciesPage";
import { ReplayPage } from "./features/replay/ReplayPage";
import { ToolsPage } from "./features/tools/ToolsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { makeQueryClient } from "./services/queryClient";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="executions" element={<ExecutionsPage />} />
        <Route path="executions/:executionId" element={<ExecutionDetailPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="replay" element={<ReplayPage />} />
        <Route path="policies" element={<PoliciesPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="evaluations" element={<EvaluationsPage />} />
        <Route path="evaluations/:evaluationId" element={<EvaluationDetailPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

const client = makeQueryClient();

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
