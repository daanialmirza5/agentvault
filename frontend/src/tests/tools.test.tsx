import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ToolsPage } from "../features/tools/ToolsPage";
import { tool } from "./fixtures";
import { mockApi, page, renderRoute } from "./utils";

const tools = [
  tool(),
  tool({ tool_id: "docs.read", name: "Read document", category: "knowledge", risk_level: "low", mutating: false, requires_approval: false }),
];

describe("Tool registry", () => {
  it("lists tools and shows schema details for the selected tool", async () => {
    mockApi({ "GET /tools": () => page(tools) });
    renderRoute(<ToolsPage />);
    expect(await screen.findByText("2 tool versions")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Read document/ }));
    expect(screen.getByRole("heading", { name: "Read document" })).toBeInTheDocument();
    expect(screen.getByText("read-only")).toBeInTheDocument();
    expect(screen.getByLabelText("Input schema")).toHaveTextContent('"additionalProperties": false');
  });

  it("filters by risk level", async () => {
    mockApi({ "GET /tools": () => page(tools) });
    renderRoute(<ToolsPage />);
    await screen.findByText("2 tool versions");
    await userEvent.selectOptions(screen.getByLabelText("Filter by risk"), "high");
    expect(screen.getByText("1 tool version")).toBeInTheDocument();
  });

  it("registers a custom tool and surfaces API validation errors", async () => {
    let attempts = 0;
    const { calls } = mockApi({
      "GET /tools": () => page(tools),
      "POST /tools": () => {
        attempts += 1;
        return attempts === 1
          ? { __status: 409, body: { error: { code: "conflict", message: "tool weather.lookup@1.0.0 already exists; bump the version" } } }
          : tool({ tool_id: "weather.lookup", name: "Weather lookup", builtin: false });
      },
    });
    renderRoute(<ToolsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Register tool" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Register tool" }));
    expect(await within(dialog).findByText(/already exists/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Register tool" }));
    await waitFor(() => expect(within(dialog).getByText(/Registered weather.lookup/)).toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ tool_id: "weather.lookup", implementation: "mock.static_response",
      input_schema: { additionalProperties: false } });
  });

  it("shows an error state when the API is unreachable", async () => {
    mockApi({ "GET /tools": () => ({ __status: 500, body: { error: { code: "internal_error", message: "boom" } } }) });
    renderRoute(<ToolsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
