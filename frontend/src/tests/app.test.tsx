import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "../App";
import { makeQueryClient } from "../services/queryClient";
import { tool } from "./fixtures";
import { mockApi, page } from "./utils";

function renderApp(route: string) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App shell", () => {
  it("lazy-loads a route inside the layout and shows the pending-approval badge", async () => {
    mockApi({
      "GET /tools": () => page([tool()]),
      "GET /approvals": () => ({ items: [], total: 3, limit: 1, offset: 0 }),
      "GET /ready": () => ({ status: "ready", checks: {}, auth_mode: "single_user_local", llm_adapter_enabled: false }),
    });
    renderApp("/tools");
    expect(await screen.findByRole("heading", { name: "Tool registry" })).toBeInTheDocument();
    expect(await screen.findByLabelText("3 pending")).toBeInTheDocument();
    expect(await screen.findByText("API ready")).toBeInTheDocument();
  });

  it("shows a not-found page for unknown routes", async () => {
    mockApi({ "GET /approvals": () => page([]), "GET /ready": () => ({ __status: 503, body: { status: "not_ready" } }) });
    renderApp("/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });
});
