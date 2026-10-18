import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { LoadingState } from "./components/ui";
import { NotFoundPage } from "./pages/NotFoundPage";
import { makeQueryClient } from "./services/queryClient";

// Route-level code splitting keeps the initial bundle small (the graph and chart libraries
// are only loaded by the pages that use them).
const named = <K extends string>(loader: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(async () => ({ default: (await loader())[name] }));

const DashboardPage = named(() => import("./features/dashboard/DashboardPage"), "DashboardPage");
const ExecutionsPage = named(() => import("./features/executions/ExecutionsPage"), "ExecutionsPage");
const ExecutionDetailPage = named(() => import("./features/executions/ExecutionDetailPage"), "ExecutionDetailPage");
const ApprovalsPage = named(() => import("./features/approvals/ApprovalsPage"), "ApprovalsPage");
const ReplayPage = named(() => import("./features/replay/ReplayPage"), "ReplayPage");
const PoliciesPage = named(() => import("./features/policies/PoliciesPage"), "PoliciesPage");
const ToolsPage = named(() => import("./features/tools/ToolsPage"), "ToolsPage");
const EvaluationsPage = named(() => import("./features/evaluations/EvaluationsPage"), "EvaluationsPage");
const EvaluationDetailPage = named(() => import("./features/evaluations/EvaluationDetailPage"), "EvaluationDetailPage");
const AuditPage = named(() => import("./features/audit/AuditPage"), "AuditPage");

export function AppRoutes() {
  return (
    <Suspense fallback={<LoadingState />}>
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
    </Suspense>
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
