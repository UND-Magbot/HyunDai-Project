import type { MockDevice } from "@/lib/types/monitoring";

export const mockDevices: MockDevice[] = [
  {
    id: "a01",
    name: "Robot A-01",
    power: "online",
    battery: "82%",
    status: "running",
  },
  {
    id: "b12",
    name: "Robot B-12",
    power: "offline",
    battery: "--",
    status: "idle",
  },
  {
    id: "c07",
    name: "Robot C-07",
    power: "online",
    battery: "45%",
    status: "warning",
  },
  {
    id: "d03",
    name: "Robot D-03",
    power: "online",
    battery: "91%",
    status: "idle",
  },
  {
    id: "e09",
    name: "Robot E-09",
    power: "offline",
    battery: "--",
    status: "error",
  },
  {
    id: "f15",
    name: "Robot F-15",
    power: "online",
    battery: "67%",
    status: "running",
  },
];

export function getDeviceCounts(devices: MockDevice[]) {
  return {
    all: devices.length,
    online: devices.filter((d) => d.power === "online").length,
    offline: devices.filter((d) => d.power === "offline").length,
    error: devices.filter((d) => d.status === "error").length,
  };
}
