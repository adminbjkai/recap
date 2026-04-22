import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import AppShell from "../components/AppShell";

describe("AppShell", () => {
  it("keeps only Library + New recording in the primary nav (no top-bar Legacy link)", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <main />
        </AppShell>
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: /primary/i });
    const links = within(nav).getAllByRole("link");
    const texts = links.map((l) => l.textContent?.trim());
    expect(texts).toContain("Library");
    expect(texts).toContain("New recording");
    // Legacy link must NOT appear in the primary nav after the
    // product-defaults pass. It lives only in the footer now.
    expect(texts.includes("Legacy")).toBe(false);
    expect(texts.includes("Legacy dashboard")).toBe(false);
  });

  it("exposes a quiet legacy-dashboard link in the footer", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <main />
        </AppShell>
      </MemoryRouter>,
    );
    const footer = screen.getByRole("contentinfo");
    expect(
      within(footer).getByRole("link", { name: /legacy dashboard/i }),
    ).toHaveAttribute("href", "/");
  });
});
