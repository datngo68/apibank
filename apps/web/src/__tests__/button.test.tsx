import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders children", () => {
    render(<Button>Test label</Button>);
    expect(screen.getByRole("button", { name: "Test label" })).toBeInTheDocument();
  });

  it("disables when loading", () => {
    render(<Button loading>Saving</Button>);
    expect(screen.getByRole("button", { name: /Saving/i })).toBeDisabled();
  });

  it("applies variant classes", () => {
    render(<Button variant="destructive">Delete</Button>);
    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn.className).toMatch(/bg-destructive/);
  });
});
