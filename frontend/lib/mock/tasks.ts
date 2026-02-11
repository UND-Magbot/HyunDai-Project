import type { MockTask } from "@/lib/types/monitoring";

export const mockTasks: MockTask[] = [
  {
    taskNum: "1",
    robot: "Robot A-01",
    endpoint: "Dock 3",
    state: "running",
    duration: "00:12:45",
  },
  {
    taskNum: "2",
    robot: "Robot B-12",
    endpoint: "Gate 1",
    state: "completed",
    duration: "00:05:12",
  },
  {
    taskNum: "3",
    robot: "Robot C-07",
    endpoint: "Zone 2",
    state: "error",
    duration: "00:01:08",
  },
  {
    taskNum: "4",
    robot: "Robot D-03",
    endpoint: "Line 4",
    state: "running",
    duration: "00:08:19",
  },
  {
    taskNum: "5",
    robot: "Robot E-09",
    endpoint: "Dock 1",
    state: "completed",
    duration: "00:15:02",
  },
  {
    taskNum: "6",
    robot: "Robot F-15",
    endpoint: "Zone 5",
    state: "error",
    duration: "00:03:41",
  },
  {
    taskNum: "7",
    robot: "Robot G-04",
    endpoint: "Gate 2",
    state: "running",
    duration: "00:09:27",
  },
  {
    taskNum: "8",
    robot: "Robot H-11",
    endpoint: "Dock 2",
    state: "completed",
    duration: "00:06:33",
  },
  {
    taskNum: "9",
    robot: "Robot I-08",
    endpoint: "Zone 1",
    state: "error",
    duration: "00:02:56",
  },
  {
    taskNum: "10",
    robot: "Robot J-14",
    endpoint: "Line 1",
    state: "running",
    duration: "00:11:04",
  },
];
