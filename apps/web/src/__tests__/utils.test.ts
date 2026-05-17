import { describe, it, expect } from "vitest";
import { formatVnd, formatDateTime, cn } from "@/lib/utils";

describe("utils", () => {
  it("formats vnd", () => {
    expect(formatVnd(50000)).toMatch(/50\.000/);
    expect(formatVnd(undefined)).toBe("—");
    expect(formatVnd("invalid")).toBe("—");
  });
  it("formats datetime", () => {
    expect(formatDateTime(new Date(2026, 0, 1, 12, 30))).toMatch(/2026/);
    expect(formatDateTime(undefined)).toBe("—");
  });
  it("cn merges classes", () => {
    expect(cn("a", false && "b", "c")).toBe("a c");
    expect(cn("p-2", "p-4")).toBe("p-4");
  });
});
