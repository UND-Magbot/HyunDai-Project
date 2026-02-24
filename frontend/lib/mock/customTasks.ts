import type { BusinessType, CustomTask, DestinationOption } from "@/lib/types/custom-tasks";

export const BUSINESS_OPTIONS: BusinessType[] = [
  "Logistics",
  "Manufacturing",
  "Delivery",
  "Warehouse",
];

export const DESTINATION_OPTIONS: DestinationOption[] = [
  { id: "point1", name: "POINT1", floor: "1F" },
  { id: "point2", name: "POINT2", floor: "1F" },
  { id: "discharge", name: "배출", floor: "1F" },
  { id: "input", name: "투입", floor: "1F" },
];

export const ACTION_TYPES: string[] = [
  "Pickup",
  "Dropoff",
  "Wait",
  "Scan",
  "Charge",
];

export const mockCustomTasks: CustomTask[] = [
  {
    id: "ct-001",
    taskName: "Logistics Route A",
    business: "Logistics",
    rcsTasks: true,
    returnTask: false,
    speed: 80,
    steps: [
      { id: "s-001", num: 1, destination: "point1", actionType: "Pickup" },
      { id: "s-002", num: 2, destination: "point2", actionType: "Dropoff" },
    ],
    createTime: "2026-02-10 09:00",
  },
  {
    id: "ct-002",
    taskName: "Manufacturing Line B",
    business: "Manufacturing",
    rcsTasks: false,
    returnTask: true,
    speed: 60,
    steps: [
      { id: "s-003", num: 1, destination: "input", actionType: "Pickup" },
      { id: "s-004", num: 2, destination: "discharge", actionType: "Dropoff", volume: 30 },
    ],
    createTime: "2026-02-10 10:15",
  },
  {
    id: "ct-003",
    taskName: "Delivery Express 1",
    business: "Delivery",
    rcsTasks: true,
    returnTask: true,
    speed: 120,
    steps: [
      { id: "s-005", num: 1, destination: "point1", actionType: "Scan" },
      { id: "s-006", num: 2, destination: "point2", actionType: "Pickup" },
      { id: "s-007", num: 3, destination: "discharge", actionType: "Dropoff" },
    ],
    createTime: "2026-02-10 11:30",
  },
  {
    id: "ct-004",
    taskName: "Warehouse Cycle A",
    business: "Warehouse",
    rcsTasks: false,
    returnTask: false,
    speed: 40,
    steps: [
      { id: "s-008", num: 1, destination: "input", actionType: "Wait", volume: 60 },
      { id: "s-009", num: 2, destination: "point1", actionType: "Pickup" },
    ],
    createTime: "2026-02-10 13:00",
  },
  {
    id: "ct-005",
    taskName: "Logistics Route B",
    business: "Logistics",
    rcsTasks: true,
    returnTask: true,
    speed: 100,
    steps: [
      { id: "s-010", num: 1, destination: "point2", actionType: "Pickup" },
      { id: "s-011", num: 2, destination: "input", actionType: "Dropoff" },
    ],
    createTime: "2026-02-10 14:20",
  },
  {
    id: "ct-006",
    taskName: "Manufacturing Line C",
    business: "Manufacturing",
    rcsTasks: true,
    returnTask: false,
    speed: 70,
    steps: [
      { id: "s-012", num: 1, destination: "discharge", actionType: "Scan" },
      { id: "s-013", num: 2, destination: "input", actionType: "Charge" },
    ],
    createTime: "2026-02-11 08:00",
  },
  {
    id: "ct-007",
    taskName: "Delivery Standard 2",
    business: "Delivery",
    rcsTasks: false,
    returnTask: true,
    speed: 90,
    steps: [
      { id: "s-014", num: 1, destination: "point1", actionType: "Pickup" },
      { id: "s-015", num: 2, destination: "discharge", actionType: "Dropoff" },
    ],
    createTime: "2026-02-11 09:30",
  },
  {
    id: "ct-008",
    taskName: "Warehouse Sort B",
    business: "Warehouse",
    rcsTasks: true,
    returnTask: false,
    speed: 50,
    steps: [
      { id: "s-016", num: 1, destination: "point2", actionType: "Scan" },
      { id: "s-017", num: 2, destination: "point1", actionType: "Pickup" },
      { id: "s-018", num: 3, destination: "discharge", actionType: "Dropoff" },
    ],
    createTime: "2026-02-11 10:45",
  },
  {
    id: "ct-009",
    taskName: "Logistics Route C",
    business: "Logistics",
    rcsTasks: false,
    returnTask: false,
    speed: 110,
    steps: [
      { id: "s-019", num: 1, destination: "input", actionType: "Pickup" },
      { id: "s-020", num: 2, destination: "point2", actionType: "Dropoff" },
    ],
    createTime: "2026-02-11 12:00",
  },
  {
    id: "ct-010",
    taskName: "Manufacturing Line D",
    business: "Manufacturing",
    rcsTasks: true,
    returnTask: true,
    speed: 80,
    steps: [
      { id: "s-021", num: 1, destination: "point1", actionType: "Pickup", audio: "alert.mp3" },
      { id: "s-022", num: 2, destination: "discharge", actionType: "Wait", volume: 45 },
    ],
    createTime: "2026-02-11 14:15",
  },
  {
    id: "ct-011",
    taskName: "Delivery Priority 3",
    business: "Delivery",
    rcsTasks: true,
    returnTask: false,
    speed: 120,
    steps: [
      { id: "s-023", num: 1, destination: "point2", actionType: "Pickup" },
      { id: "s-024", num: 2, destination: "input", actionType: "Dropoff" },
    ],
    createTime: "2026-02-12 08:30",
  },
  {
    id: "ct-012",
    taskName: "Warehouse Restock C",
    business: "Warehouse",
    rcsTasks: false,
    returnTask: true,
    speed: 60,
    steps: [
      { id: "s-025", num: 1, destination: "discharge", actionType: "Pickup" },
      { id: "s-026", num: 2, destination: "point1", actionType: "Dropoff" },
    ],
    createTime: "2026-02-12 09:45",
  },
  {
    id: "ct-013",
    taskName: "Logistics Route D",
    business: "Logistics",
    rcsTasks: true,
    returnTask: true,
    speed: 90,
    steps: [
      { id: "s-027", num: 1, destination: "input", actionType: "Scan" },
      { id: "s-028", num: 2, destination: "point2", actionType: "Pickup" },
      { id: "s-029", num: 3, destination: "discharge", actionType: "Dropoff" },
    ],
    createTime: "2026-02-12 11:00",
  },
];
