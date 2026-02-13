import type { RouteItem } from "@/lib/types/tasks";

export const mockRoutes: RouteItem[] = [
  {
    id: "route-1",
    pathName: "Path(2-1)",
    robotLabel: "Robot A-01",
    description: "Dock A-3 → Station B-7",
  },
  {
    id: "route-2",
    pathName: "Path(3-2)",
    robotLabel: "Robot C-07",
    description: "Gate 1 → Zone 2",
  },
  {
    id: "route-3",
    pathName: "Path(1-4)",
    robotLabel: "Robot D-03",
    description: "Line 4 → Dock 1",
  },
  {
    id: "route-4",
    pathName: "Path(5-3)",
    robotLabel: "Robot F-15",
    description: "Zone 5 → Gate 2",
  },
  {
    id: "route-5",
    pathName: "Path(4-2)",
    robotLabel: "Robot A-01",
    description: "Station B-7 → Line 1",
  },
];
