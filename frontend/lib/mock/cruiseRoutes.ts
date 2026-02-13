import type { CruiseRoute, CruiseRouteSite } from "@/lib/types/cruise-route";

export type SiteOption = {
  id: string;
  name: string;
  floor: string;
};

export type FloorGroup = {
  floor: string;
  sites: SiteOption[];
};

export const SITE_OPTIONS: FloorGroup[] = [
  {
    floor: "1Floor",
    sites: [
      { id: "site-l1", name: "L1", floor: "1Floor" },
      { id: "site-l2", name: "L2", floor: "1Floor" },
      { id: "site-l3", name: "L3", floor: "1Floor" },
    ],
  },
  {
    floor: "2Floor",
    sites: [
      { id: "site-l4", name: "L4", floor: "2Floor" },
      { id: "site-l5", name: "L5", floor: "2Floor" },
    ],
  },
];

const s = (id: string, name: string, floor: string): CruiseRouteSite => ({
  id,
  name,
  floor,
});

export const mockCruiseRoutes: CruiseRoute[] = [
  {
    id: "cr-001",
    routeName: "Main Patrol Route",
    businessId: "biz-1",
    businessName: "UND HQ",
    sites: [s("site-l1", "L1", "1Floor"), s("site-l2", "L2", "1Floor"), s("site-l3", "L3", "1Floor"), s("site-l1", "L1", "1Floor")],
    siteCount: 4,
    createTime: "2026-02-10 09:00",
  },
  {
    id: "cr-002",
    routeName: "Warehouse Inspection",
    businessId: "biz-2",
    businessName: "Samsung Logistics",
    sites: [s("site-l4", "L4", "2Floor"), s("site-l5", "L5", "2Floor"), s("site-l4", "L4", "2Floor")],
    siteCount: 3,
    createTime: "2026-02-10 10:30",
  },
  {
    id: "cr-003",
    routeName: "Factory Loop A",
    businessId: "biz-3",
    businessName: "Hyundai Motors",
    sites: [s("site-l1", "L1", "1Floor"), s("site-l2", "L2", "1Floor")],
    siteCount: 2,
    createTime: "2026-02-10 14:00",
  },
  {
    id: "cr-004",
    routeName: "Campus Security Round",
    businessId: "biz-4",
    businessName: "LG Factory",
    sites: [s("site-l1", "L1", "1Floor"), s("site-l3", "L3", "1Floor"), s("site-l5", "L5", "2Floor"), s("site-l2", "L2", "1Floor")],
    siteCount: 4,
    createTime: "2026-02-11 08:15",
  },
  {
    id: "cr-005",
    routeName: "Night Patrol",
    businessId: "biz-1",
    businessName: "UND HQ",
    sites: [s("site-l2", "L2", "1Floor"), s("site-l4", "L4", "2Floor"), s("site-l5", "L5", "2Floor")],
    siteCount: 3,
    createTime: "2026-02-11 11:00",
  },
  {
    id: "cr-006",
    routeName: "Express Delivery Route",
    businessId: "biz-2",
    businessName: "Samsung Logistics",
    sites: [s("site-l1", "L1", "1Floor"), s("site-l2", "L2", "1Floor"), s("site-l4", "L4", "2Floor")],
    siteCount: 3,
    createTime: "2026-02-11 15:30",
  },
  {
    id: "cr-007",
    routeName: "Assembly Line Check",
    businessId: "biz-3",
    businessName: "Hyundai Motors",
    sites: [s("site-l3", "L3", "1Floor"), s("site-l5", "L5", "2Floor"), s("site-l3", "L3", "1Floor")],
    siteCount: 3,
    createTime: "2026-02-12 09:00",
  },
  {
    id: "cr-008",
    routeName: "Full Floor Sweep",
    businessId: "biz-4",
    businessName: "LG Factory",
    sites: [s("site-l1", "L1", "1Floor"), s("site-l2", "L2", "1Floor"), s("site-l3", "L3", "1Floor"), s("site-l4", "L4", "2Floor"), s("site-l5", "L5", "2Floor")],
    siteCount: 5,
    createTime: "2026-02-12 13:45",
  },
];
