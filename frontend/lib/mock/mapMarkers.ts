import type {
  PoiMarkerData,
  WaypointMarkerData,
  RobotMarkerData,
  VirtualWallData,
} from "@/lib/types/map-markers";

export const mockPois: PoiMarkerData[] = [
  {
    id: "poi-1",
    label: "충전소 A",
    position: { x: 130, y: 480 },
    type: "charging",
  },
  {
    id: "poi-2",
    label: "작업장 B",
    position: { x: 280, y: 320 },
    type: "workstation",
  },
  {
    id: "poi-3",
    label: "픽업 포인트",
    position: { x: 400, y: 250 },
    type: "pickup",
  },
  {
    id: "poi-4",
    label: "드롭오프 C",
    position: { x: 200, y: 550 },
    type: "dropoff",
  },
];

export const mockWaypoints: WaypointMarkerData[] = [
  { id: "wp-1", label: "WP-01", position: { x: 150, y: 300 } },
  { id: "wp-2", label: "WP-02", position: { x: 250, y: 300 } },
  { id: "wp-3", label: "WP-03", position: { x: 350, y: 300 } },
  { id: "wp-4", label: "WP-04", position: { x: 250, y: 420 } },
  { id: "wp-5", label: "WP-05", position: { x: 350, y: 420 } },
  { id: "wp-6", label: "WP-06", position: { x: 300, y: 520 } },
];

export const mockVirtualWalls: VirtualWallData[] = [
  { id: "wall-1", start: { x: 170, y: 260 }, end: { x: 310, y: 260 } },
  { id: "wall-2", start: { x: 400, y: 380 }, end: { x: 400, y: 490 } },
];

export const mockRobotPositions: RobotMarkerData[] = [
  {
    robotId: "a01",
    robotName: "Robot A-01",
    position: { x: 220, y: 350 },
    yaw: 1.57,
    status: "running",
    power: "online",
  },
  {
    robotId: "c07",
    robotName: "Robot C-07",
    position: { x: 360, y: 280 },
    yaw: 0,
    status: "warning",
    power: "online",
  },
  {
    robotId: "f15",
    robotName: "Robot F-15",
    position: { x: 180, y: 500 },
    yaw: 3.14,
    status: "running",
    power: "online",
  },
];
