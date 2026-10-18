import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { makeQueryClient } from "../services/queryClient";

type Handler = (url: URL, init: RequestInit) => unknown;

/**
 * Installs a fetch mock routed by "METHOD /path". Handlers return a JSON body, or
 * `{ __status, body }` for non-2xx responses. Every request is recorded.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.split(" ");
      if (m !== method || !p) return false;
      const pattern = new RegExp(`^${p.replace(/:[a-z_]+/gi, "[^/]+")}$`);
      return pattern.test(path);
    });
    if (!key) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: `unmocked ${method} ${path}` } }), { status: 404 });
    }
    const result = routes[key]!(url, init) as { __status?: number; body?: unknown } | unknown;
    if (result && typeof result === "object" && "__status" in (result as object)) {
      const r = result as { __status: number; body: unknown };
      return new Response(JSON.stringify(r.body), { status: r.__status, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify(result), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderRoute(element: ReactElement, { path = "/", route = "/" }: { path?: string; route?: string } = {}) {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const page = <T,>(items: T[]) => ({ items, total: items.length, limit: 50, offset: 0 });
