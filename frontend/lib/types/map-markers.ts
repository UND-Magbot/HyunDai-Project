export type MapPixelCoord = {
  x: number;
  y: number;
};

export type PoiMarkerData = {
  id: string;
  label: string;
  position: MapPixelCoord;
  type: "workstation" | "charging" | "pickup" | "dropoff";
  renderKind?: "circle" | "triangle";
};

export type WaypointMarkerData = {
  id: string;
  label: string;
  position: MapPixelCoord;
};

export type RobotMarkerData = {
  robotId: string;
  robotName: string;
  position: MapPixelCoord;
  yaw: number;
  status: "idle" | "running" | "error" | "warning" | "disable";
  power: "online" | "offline";
  collisionState?: "none" | "near_miss" | "collision";
};

export type VirtualWallData = {
  id: string;
  start: MapPixelCoord;
  end: MapPixelCoord;
};
