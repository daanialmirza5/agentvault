import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { ExecutionDetailPage } from "./features/executions/ExecutionDetailPage";
import { ExecutionsPage } from "./features/executions/ExecutionsPage";
import { PoliciesPage } from "./features/policies/PoliciesPage";
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
        <Route path="policies" element={<PoliciesPage />} />
        <Route path="tools" element={<ToolsPage />} />
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
