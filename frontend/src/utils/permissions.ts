export type Role = "worker" | "planner" | "manager" | "admin";

const hierarchy: Record<Role, number> = { worker: 1, planner: 2, manager: 3, admin: 4 };

export function hasRole(role: string, required: Role): boolean {
  return (hierarchy[role as Role] ?? 0) >= hierarchy[required];
}

export function canAccessRoute(role: string, route: string): boolean {
  if (route === "/settings/database") return true;
  if (route === "/prices" || route === "/purchases") return hasRole(role, "planner");
  if (route === "/") return hasRole(role, "worker");
  return true;
}
