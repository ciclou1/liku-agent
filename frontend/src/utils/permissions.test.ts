import { describe, expect, it } from "vitest";
import { canAccessRoute, hasRole } from "./permissions";

describe("route permissions", () => {
  it("uses role hierarchy", () => {
    expect(hasRole("manager", "planner")).toBe(true);
    expect(hasRole("worker", "planner")).toBe(false);
  });

  it("protects planner routes", () => {
    expect(canAccessRoute("worker", "/purchases")).toBe(false);
    expect(canAccessRoute("planner", "/purchases")).toBe(true);
  });

  it("keeps database settings visible but admin-only", () => {
    expect(canAccessRoute("worker", "/settings/database")).toBe(true);
    expect(hasRole("worker", "admin")).toBe(false);
    expect(hasRole("admin", "admin")).toBe(true);
  });
});
