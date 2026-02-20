"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type WheelEvent,
} from "react";
import { usePathname } from "next/navigation";
import { OverlayCard } from "../components/ui/monitoring/OverlayCard";
import { LayerButton } from "../components/ui/monitoring/LayerButton";
import { MapModeButton } from "../components/ui/monitoring/MapModeButton";
import { DeviceRow } from "../components/ui/monitoring/DeviceRow";
// import { TaskRow } from "../components/ui/monitoring/TaskRow";
import { DeviceInfoPopup } from "../components/ui/monitoring/DeviceInfoPopup";
import { TaskInfoModal } from "../components/ui/monitoring/TaskInfoModal";
import { CreateTaskModal } from "../components/ui/tasks/CreateTaskModal";
import { ConfirmModal } from "../components/ui/robots/ConfirmModal";
import { mockDevices, getDeviceCounts } from "@/lib/mock/devices";
import { mockTasks } from "@/lib/mock/tasks";
import type { TaskState } from "@/lib/types/monitoring";
import { SearchInput } from "../components/ui/SearchInput";
import { Panel } from "../components/ui/Panel";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { TopBar } from "../components/shell/TopBar";
import { useImageBackgroundColor } from "@/lib/hooks/useImageBackgroundColor";
import { useMapImageNaturals } from "@/lib/hooks/useMapImageNaturals";
import { MapOverlay } from "../components/ui/monitoring/MapOverlay";
import {
  mockPois,
  mockWaypoints,
  mockRobotPositions,
  mockVirtualWalls,
} from "@/lib/mock/mapMarkers";
import type { MapPixelCoord, RobotMarkerData, WaypointMarkerData } from "@/lib/types/map-markers";
import { LoadingScreen } from "../components/ui/LoadingScreen";

const SIMULATION_TICK_MS = 120;
const NODE_SNAPSHOT_TICK_MS = 700;
const NODE_TRAIL_LIMIT = 80;
const NEAR_THRESHOLD_PX = 40;
const COLLISION_THRESHOLD_PX = 24;
const EVENT_COOLDOWN_MS = 3000;
const COLLISION_EVENT_LIMIT = 60;

type CollisionEventType =
  | "near_miss_detected"
  | "collision_detected"
  | "emergency_stop_triggered"
  | "collision_cleared";

type MonitoringCollisionEvent = {
  eventId: string;
  type: CollisionEventType;
  pairKey: string;
  robotIds: [string, string];
  distancePx: number;
  timestamp: string;
};

type RobotRouteState = {
  route: MapPixelCoord[];
  segmentIndex: number;
  progress: number;
  speed: number;
};

const mockRobotRoutes: Record<string, MapPixelCoord[]> = {
  a01: [
    { x: 150, y: 300 },
    { x: 250, y: 300 },
    { x: 350, y: 300 },
    { x: 350, y: 420 },
    { x: 250, y: 420 },
    { x: 150, y: 300 },
  ],
  c07: [
    { x: 360, y: 280 },
    { x: 420, y: 250 },
    { x: 430, y: 330 },
    { x: 360, y: 420 },
    { x: 300, y: 360 },
    { x: 360, y: 280 },
  ],
  f15: [
    { x: 180, y: 500 },
    { x: 220, y: 560 },
    { x: 300, y: 520 },
    { x: 320, y: 450 },
    { x: 240, y: 430 },
    { x: 180, y: 500 },
  ],
};

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function buildFallbackRoute(position: MapPixelCoord): MapPixelCoord[] {
  const d = 35;
  return [
    { x: position.x - d, y: position.y - d },
    { x: position.x + d, y: position.y - d },
    { x: position.x + d, y: position.y + d },
    { x: position.x - d, y: position.y + d },
    { x: position.x - d, y: position.y - d },
  ];
}

const defaultOverlayItems = [
  { label: "맵 배경", checked: true },
  { label: "내비게이션 경로", checked: true },
  { label: "이동 방향", checked: true },
  { label: "가상 벽", checked: false },
  { label: "내비게이션 노드", checked: true },
  { label: "작업 지점", checked: true },
];

function formatDateTime(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

type Props = {
  initialDateTime: string;
};

export function MonitoringClient({ initialDateTime }: Props) {
  const pathname = usePathname();
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [mapMode, setMapMode] = useState<"2d" | "3d">("2d");
  const [mapScale, setMapScale] = useState(1);
  const [mapOffset, setMapOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [taskTab, setTaskTab] = useState<TaskState>("running");
  const [overlayItems, setOverlayItems] = useState(defaultOverlayItems);
  const [isLayerOpen, setIsLayerOpen] = useState(false);
  const [expandedDeviceId, setExpandedDeviceId] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [openDeviceId, setOpenDeviceId] = useState<string | null>(null);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [mapSrc, setMapSrc] = useState("/map/gumi_map_trans.png");
  const [createTaskOpen, setCreateTaskOpen] = useState(false);
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const [deviceSearch, setDeviceSearch] = useState("");
  const [taskSearch, setTaskSearch] = useState("");
  const [simulatedRobots, setSimulatedRobots] = useState<RobotMarkerData[]>(mockRobotPositions);
  const [allocatedNodes, setAllocatedNodes] = useState<WaypointMarkerData[]>([]);
  const [collisionEvents, setCollisionEvents] = useState<MonitoringCollisionEvent[]>([]);
  const mapViewportRef = useRef<HTMLDivElement | null>(null);
  const panStartRef = useRef<{ x: number; y: number } | null>(null);
  const startOffsetRef = useRef({ x: 0, y: 0 });
  const routeStateRef = useRef<Record<string, RobotRouteState>>({});
  const robotsRef = useRef<RobotMarkerData[]>(mockRobotPositions);
  const nodeSeqRef = useRef(0);
  const collisionEventSeqRef = useRef(0);
  const stoppedRobotIdsRef = useRef<Set<string>>(new Set());
  const activeCollisionPairsRef = useRef<Set<string>>(new Set());
  const eventCooldownRef = useRef<Map<string, number>>(new Map());
  const deviceCounts = getDeviceCounts(mockDevices);

  // const taskCountByRobot = mockTasks.reduce((acc, task) => {
  //   acc[task.robot] = (acc[task.robot] || 0) + 1;
  //   return acc;
  // }, {} as Record<string, number>);

  const [isLoading, setIsLoading] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(initialDateTime);

  const getPairKey = (robotA: string, robotB: string) =>
    [robotA, robotB].sort().join(":");

  const buildCollisionEvent = (
    type: CollisionEventType,
    pairKey: string,
    robotIds: [string, string],
    distancePx: number,
    timestampMs: number
  ): MonitoringCollisionEvent => ({
    eventId: `evt-${collisionEventSeqRef.current++}`,
    type,
    pairKey,
    robotIds,
    distancePx: Number(distancePx.toFixed(2)),
    timestamp: new Date(timestampMs).toISOString(),
  });

  const canEmitEvent = (
    type: CollisionEventType,
    pairKey: string,
    nowMs: number
  ) => {
    const cooldownKey = `${type}:${pairKey}`;
    const lastMs = eventCooldownRef.current.get(cooldownKey);
    if (lastMs != null && nowMs - lastMs < EVENT_COOLDOWN_MS) {
      return false;
    }
    eventCooldownRef.current.set(cooldownKey, nowMs);
    return true;
  };

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (collisionEvents.length === 0) {
      return;
    }
    const latestEvent = collisionEvents[collisionEvents.length - 1];
    console.log("[monitoring-collision]", latestEvent);
    window.dispatchEvent(
      new CustomEvent("monitoring:collision", { detail: latestEvent })
    );
  }, [collisionEvents]);

  useEffect(() => {
    routeStateRef.current = Object.fromEntries(
      mockRobotPositions.map((robot, index) => [
        robot.robotId,
        {
          route: mockRobotRoutes[robot.robotId] ?? buildFallbackRoute(robot.position),
          segmentIndex: 0,
          progress: 0,
          speed: 0.015 + index * 0.005,
        },
      ])
    );
  }, []);

  useEffect(() => {
    robotsRef.current = simulatedRobots;
  }, [simulatedRobots]);

  useEffect(() => {
    const timer = setInterval(() => {
      const nowMs = Date.now();
      const queuedEvents: MonitoringCollisionEvent[] = [];

      setSimulatedRobots((prev) => {
        const movedRobots = prev.map((robot) => {
          if (stoppedRobotIdsRef.current.has(robot.robotId)) {
            return {
              ...robot,
              collisionState: "collision",
            };
          }

          const routeState = routeStateRef.current[robot.robotId];
          if (!routeState || routeState.route.length < 2) {
            return robot;
          }

          let nextProgress = routeState.progress + routeState.speed;
          let segmentIndex = routeState.segmentIndex;
          while (nextProgress >= 1) {
            nextProgress -= 1;
            segmentIndex = (segmentIndex + 1) % (routeState.route.length - 1);
          }

          routeState.segmentIndex = segmentIndex;
          routeState.progress = nextProgress;

          const start = routeState.route[segmentIndex];
          const end = routeState.route[segmentIndex + 1];
          const dx = end.x - start.x;
          const dy = end.y - start.y;

          return {
            ...robot,
            yaw: Math.atan2(dy, dx),
            collisionState: "none",
            position: {
              x: lerp(start.x, end.x, nextProgress),
              y: lerp(start.y, end.y, nextProgress),
            },
          };
        });

        const nextPairCollisions = new Set<string>();
        const robotCollisionState = new Map<
          string,
          "none" | "near_miss" | "collision"
        >();
        movedRobots.forEach((robot) =>
          robotCollisionState.set(robot.robotId, "none")
        );

        for (let i = 0; i < movedRobots.length; i += 1) {
          for (let j = i + 1; j < movedRobots.length; j += 1) {
            const robotA = movedRobots[i];
            const robotB = movedRobots[j];
            const distance = Math.hypot(
              robotA.position.x - robotB.position.x,
              robotA.position.y - robotB.position.y
            );
            const pairKey = getPairKey(robotA.robotId, robotB.robotId);
            const pairRobotIds: [string, string] =
              robotA.robotId < robotB.robotId
                ? [robotA.robotId, robotB.robotId]
                : [robotB.robotId, robotA.robotId];

            if (distance <= COLLISION_THRESHOLD_PX) {
              nextPairCollisions.add(pairKey);
              robotCollisionState.set(robotA.robotId, "collision");
              robotCollisionState.set(robotB.robotId, "collision");

              if (
                canEmitEvent("collision_detected", pairKey, nowMs)
              ) {
                queuedEvents.push(
                  buildCollisionEvent(
                    "collision_detected",
                    pairKey,
                    pairRobotIds,
                    distance,
                    nowMs
                  )
                );
              }

              const shouldStop =
                !stoppedRobotIdsRef.current.has(robotA.robotId) ||
                !stoppedRobotIdsRef.current.has(robotB.robotId);
              if (shouldStop) {
                stoppedRobotIdsRef.current.add(robotA.robotId);
                stoppedRobotIdsRef.current.add(robotB.robotId);
                if (canEmitEvent("emergency_stop_triggered", pairKey, nowMs)) {
                  queuedEvents.push(
                    buildCollisionEvent(
                      "emergency_stop_triggered",
                      pairKey,
                      pairRobotIds,
                      distance,
                      nowMs
                    )
                  );
                }
              }
              continue;
            }

            if (distance <= NEAR_THRESHOLD_PX) {
              const stateA = robotCollisionState.get(robotA.robotId);
              const stateB = robotCollisionState.get(robotB.robotId);
              if (stateA !== "collision") {
                robotCollisionState.set(robotA.robotId, "near_miss");
              }
              if (stateB !== "collision") {
                robotCollisionState.set(robotB.robotId, "near_miss");
              }
              if (canEmitEvent("near_miss_detected", pairKey, nowMs)) {
                queuedEvents.push(
                  buildCollisionEvent(
                    "near_miss_detected",
                    pairKey,
                    pairRobotIds,
                    distance,
                    nowMs
                  )
                );
              }
            }
          }
        }

        for (const activePair of activeCollisionPairsRef.current) {
          if (nextPairCollisions.has(activePair)) {
            continue;
          }
          const [robotA, robotB] = activePair.split(":");
          if (!robotA || !robotB) {
            continue;
          }
          const robotIds: [string, string] = [robotA, robotB];
          if (canEmitEvent("collision_cleared", activePair, nowMs)) {
            queuedEvents.push(
              buildCollisionEvent(
                "collision_cleared",
                activePair,
                robotIds,
                0,
                nowMs
              )
            );
          }
        }
        activeCollisionPairsRef.current = nextPairCollisions;

        return movedRobots.map((robot) => ({
          ...robot,
          collisionState: robotCollisionState.get(robot.robotId) ?? "none",
        }));
      });

      if (queuedEvents.length > 0) {
        setCollisionEvents((prev) => {
          const merged = [...prev, ...queuedEvents];
          if (merged.length <= COLLISION_EVENT_LIMIT) {
            return merged;
          }
          return merged.slice(merged.length - COLLISION_EVENT_LIMIT);
        });
      }
    }, SIMULATION_TICK_MS);

    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setAllocatedNodes((prev) => {
        const snapshots = robotsRef.current.map((robot) => ({
          id: `alloc-${robot.robotId}-${nodeSeqRef.current++}`,
          label: `${robot.robotName}-alloc`,
          position: {
            x: robot.position.x,
            y: robot.position.y,
          },
        }));
        const merged = [...prev, ...snapshots];
        if (merged.length <= NODE_TRAIL_LIMIT) {
          return merged;
        }
        return merged.slice(merged.length - NODE_TRAIL_LIMIT);
      });
    }, NODE_SNAPSHOT_TICK_MS);

    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    setMapScale(1);
    setMapOffset({ x: 0, y: 0 });
  }, [pathname]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1200px)");
    const handleChange = () => {
      if (media.matches) {
        setNavCollapsed(true);
        setLeftCollapsed(true);
        setRightCollapsed(true);
      }
    };

    handleChange();
    if (media.addEventListener) {
      media.addEventListener("change", handleChange);
      return () => media.removeEventListener("change", handleChange);
    }

    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, []);

  const handleNavToggle = () => {
    setNavCollapsed((v) => !v);
  };

  const handleNavItemSelect = () => {
    setNavCollapsed(true);
  };

  const handleItemToggle = (label: string, checked: boolean) => {
    setOverlayItems((prev) =>
      prev.map((item) =>
        item.label === label ? { ...item, checked } : item
      )
    );
  };

  const handleDeviceToggle = (deviceId: string) => {
    setExpandedDeviceId((prev) => (prev === deviceId ? null : deviceId));
  };

  const handleTaskToggle = (taskId: string) => {
    setExpandedTaskId((prev) => (prev === taskId ? null : taskId));
  };

  const clamp = (value: number, min: number, max: number) =>
    Math.min(max, Math.max(min, value));

  const getPanLimits = (
    scale: number,
    viewportWidth: number,
    viewportHeight: number
  ) => ({
    maxX: ((Math.max(scale, 1) - 1) * viewportWidth) / 2,
    maxY: ((Math.max(scale, 1) - 1) * viewportHeight) / 2,
  });

  const clampOffset = (
    nextX: number,
    nextY: number,
    scale: number,
    rect: DOMRect
  ) => {
    if (scale <= 1) {
      return { x: 0, y: 0 };
    }
    const { maxX, maxY } = getPanLimits(scale, rect.width, rect.height);
    return {
      x: clamp(nextX, -maxX, maxX),
      y: clamp(nextY, -maxY, maxY),
    };
  };

  const stopPanning = () => {
    setIsPanning(false);
    panStartRef.current = null;
  };

  const handleMapWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const viewport = mapViewportRef.current;
    if (!viewport) {
      return;
    }

    if (event.deltaY === 0) {
      return;
    }
    const rect = viewport.getBoundingClientRect();
    const zoomFactor = event.deltaY < 0 ? 1.1 : 0.9;
    const nextScale = clamp(mapScale * zoomFactor, 0.5, 4);
    setMapScale(nextScale);
    if (nextScale <= 1) {
      setMapOffset({ x: 0, y: 0 });
    } else {
      setMapOffset((prevOffset) =>
        clampOffset(prevOffset.x, prevOffset.y, nextScale, rect)
      );
    }
  };

  const handleMapMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (mapMode !== "2d" || mapScale <= 1 || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setIsPanning(true);
    panStartRef.current = { x: event.clientX, y: event.clientY };
    startOffsetRef.current = mapOffset;
  };

  const handleMapMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    if (!isPanning || !panStartRef.current) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const viewport = mapViewportRef.current;
    if (!viewport) {
      return;
    }
    const rect = viewport.getBoundingClientRect();
    const dx = event.clientX - panStartRef.current.x;
    const dy = event.clientY - panStartRef.current.y;
    const next = clampOffset(
      startOffsetRef.current.x + dx,
      startOffsetRef.current.y + dy,
      mapScale,
      rect
    );
    setMapOffset(next);
  };

  useEffect(() => {
    const handleWindowMouseUp = () => {
      setIsPanning(false);
      panStartRef.current = null;
    };

    window.addEventListener("mouseup", handleWindowMouseUp);
    return () => {
      window.removeEventListener("mouseup", handleWindowMouseUp);
    };
  }, []);

  const imageNaturals = useMapImageNaturals(mapSrc);

  const mapSceneStyle: CSSProperties = {
    "--map-ar": imageNaturals
      ? `${imageNaturals.width} / ${imageNaturals.height}`
      : "563 / 682",
    transform: `translate3d(${mapOffset.x}px, ${mapOffset.y}px, 0) scale(${mapScale})`,
    transformOrigin: "center",
  } as CSSProperties;

  const mapBgColor = useImageBackgroundColor(mapSrc);
  const mapViewportStyle: CSSProperties = {
    backgroundColor: mapBgColor ?? "var(--bg-map)",
  };

  const mapViewportClassName = [
    "center-map__viewport",
    mapScale > 1 ? "is-pannable" : "",
    isPanning ? "is-panning" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const handleStartAll = () => {
    console.log("Start All tasks");
  };

  const hasRunningTasks = mockTasks.some((task) => task.state === "running");

  const handleStopAll = () => {
    if (hasRunningTasks) {
      setStopConfirmOpen(true);
      return;
    }
    console.log("Stop All tasks");
  };

  const handleConfirmStop = () => {
    setStopConfirmOpen(false);
    console.log("Stop All tasks");
  };

  const filteredDevices = deviceSearch
    ? mockDevices.filter((d) =>
        d.name.toLowerCase().includes(deviceSearch.toLowerCase())
      )
    : mockDevices;

  const filteredTasks = mockTasks
    .filter((task) => task.state === taskTab)
    .filter((task) =>
      taskSearch
        ? task.robot.toLowerCase().includes(taskSearch.toLowerCase())
        : true
    );

  const showMapBackground =
    overlayItems.find((item) => item.label === "맵 배경")?.checked ?? true;
  const showNavigationLine =
    overlayItems.find((item) => item.label === "내비게이션 경로")?.checked ?? false;
  const showDirectionArrows =
    overlayItems.find((item) => item.label === "이동 방향")?.checked ?? false;
  const showVirtualWalls =
    overlayItems.find((item) => item.label === "가상 벽")?.checked ?? false;
  const showNavigationNodes =
    overlayItems.find((item) => item.label === "내비게이션 노드")?.checked ?? false;
  const showPoiMarkers =
    overlayItems.find((item) => item.label === "작업 지점")?.checked ?? false;

  const renderedWaypoints = showNavigationNodes ? mockWaypoints : [];
  const routeWaypoints = showNavigationLine ? mockWaypoints : [];

  return (
    <>
      {isLoading && <LoadingScreen pageName="모니터링" />}
      <div className="app-shell">
      <TopBar
        dateTime={currentDateTime}
        onToggleNav={handleNavToggle}
        navExpanded={!navCollapsed}
      />
      <div className="shell-body">
        <SideNav
          items={defaultNavItems}
          collapsed={navCollapsed}
          onClose={() => setNavCollapsed(true)}
          onItemSelect={handleNavItemSelect}
        />
        <main className="main-content">
          <Panel
            title="로봇 관리"
            collapsed={leftCollapsed}
            collapsedTogglePosition="end"
            onToggle={() => setLeftCollapsed((value) => !value)}
            toggleIcon="right"
            className="panel--overlay panel--overlay-left"
            headerContent={
              <>
                <div className="chip-row">
                  <button className="chip">
                    <span className="chip__label">전체</span>
                    <span className="chip__count">{deviceCounts.all}</span>
                  </button>
                  <button className="chip">
                    <span className="chip__label">온라인</span>
                    <span className="chip__count">{deviceCounts.online}</span>
                  </button>
                  <button className="chip">
                    <span className="chip__label">오프라인</span>
                    <span className="chip__count">{deviceCounts.offline}</span>
                  </button>
                  <button className="chip">
                    <span className="chip__label">오류</span>
                    <span className="chip__count">{deviceCounts.error}</span>
                  </button>
                </div>
                <SearchInput
                  placeholder="로봇명을 입력하세요."
                  onSearch={setDeviceSearch}
                />
              </>
            }
          >
            <div className="device-list">
              <div className="device-row__header">
                <span className="device-row__header-cell">로봇 명</span>
                <span className="device-row__header-cell">전원</span>
                <span className="device-row__header-cell">배터리</span>
                <span className="device-row__header-cell">상태</span>
              </div>
              {filteredDevices.length === 0 ? (
                <div className="device-list__empty">등록된 로봇이 없습니다.</div>
              ) : (
                filteredDevices.map((device) => (
                  <DeviceRow
                    key={device.id}
                    id={device.id}
                    name={device.name}
                    power={device.power}
                    battery={device.battery}
                    status={device.status}
                    isExpanded={expandedDeviceId === device.id}
                    onToggleExpand={handleDeviceToggle}
                    onInfo={setOpenDeviceId}
                  />
                ))
              )}
            </div>
          </Panel>

          <div
            className="monitoring-stage"
            style={
              leftCollapsed
                ? ({ "--overlay-anchor-left": "calc(2% + 40px + var(--overlay-devices-gap))" } as CSSProperties)
                : undefined
            }
          >
            <section className={mapMode === "3d" ? "monitoring-map is-3d" : "monitoring-map"}>
              <div
                className="center-map__canvas"
                onWheel={handleMapWheel}
              >
                {mapMode === "3d" ? (
                  "Map (3D View)"
                ) : (
                  <div
                    className={mapViewportClassName}
                    ref={mapViewportRef}
                    style={mapViewportStyle}
                    onMouseDown={handleMapMouseDown}
                    onMouseMove={handleMapMouseMove}
                    onMouseUp={stopPanning}
                    onMouseLeave={stopPanning}
                  >
                    <div
                      className="center-map__scene"
                      style={mapSceneStyle}
                    >
                      <img
                        className="center-map__image"
                        src={mapSrc}
                        alt="지도"
                        draggable={false}
                        style={showMapBackground ? undefined : { visibility: "hidden" }}
                      />
                      {imageNaturals && (
                        <MapOverlay
                          pois={mockPois}
                          waypoints={renderedWaypoints}
                          routeWaypoints={routeWaypoints}
                          robots={simulatedRobots}
                          showPois={showPoiMarkers}
                          showRoutes={showNavigationLine}
                          showWaypoints={showNavigationNodes}
                          showDirectionArrows={showDirectionArrows}
                          showVirtualWalls={showVirtualWalls}
                          virtualWalls={mockVirtualWalls}
                          imageWidth={imageNaturals.width}
                          imageHeight={imageNaturals.height}
                          mapScale={mapScale}
                        />
                      )}
                    </div>
                  </div>
                )}
              </div>
            </section>
            <div className="overlay-card-layer">
              {isLayerOpen && (
                <OverlayCard
                  items={overlayItems}
                  onItemToggle={handleItemToggle}
                />
              )}
              <div className="overlay-card__footer">
                <LayerButton
                  isActive={isLayerOpen}
                  onToggle={() => setIsLayerOpen((v) => !v)}
                />
                <MapModeButton
                  mapMode={mapMode}
                  onMapModeChange={setMapMode}
                />
              </div>
            </div>
          </div>

          <Panel
            title="작업"
            collapsed={rightCollapsed}
            collapsedTogglePosition="start"
            onToggle={() => setRightCollapsed((value) => !value)}
            toggleIcon="left"
            noBodyWrapper
            className="panel--overlay panel--overlay-right"
            // headerActions={<button className="btn btn--primary" onClick={() => setCreateTaskOpen(true)}>Add Task</button>}
            footer={
              <div className="task-panel__footer-actions">
                <button
                  className="btn btn--primary"
                  onClick={handleStartAll}
                >
                  시작
                </button>
                <button
                  className="btn btn--danger"
                  onClick={handleStopAll}
                >
                  종료
                </button>
              </div>
            }
            // subheader={
            //   <>
            //     <div className="tab-row">
            //       <button
            //         className={taskTab === "running" ? "tab tab--active" : "tab"}
            //         onClick={() => { setTaskTab("running"); setTaskSearch(""); setExpandedTaskId(null); }}
            //       >
            //         Running
            //       </button>
            //       <button
            //         className={taskTab === "completed" ? "tab tab--active" : "tab"}
            //         onClick={() => { setTaskTab("completed"); setTaskSearch(""); setExpandedTaskId(null); }}
            //       >
            //         Completed
            //       </button>
            //       <button
            //         className={taskTab === "error" ? "tab tab--active" : "tab"}
            //         onClick={() => { setTaskTab("error"); setTaskSearch(""); setExpandedTaskId(null); }}
            //       >
            //         Error
            //       </button>
            //     </div>
            //     <SearchInput
            //       key={taskTab}
            //       placeholder="로봇명을 입력하세요."
            //       onSearch={setTaskSearch}
            //     />
            //   </>
            // }
          >
            {/* <div className="task-list">
              <div className="task-row__header">
                <span className="task-row__header-cell">Robot</span>
                <span className="task-row__header-cell">EndPoint</span>
                <span className="task-row__header-cell">State</span>
                <span className="task-row__header-cell">DurTime</span>
              </div>
              {filteredTasks.length === 0 ? (
                <div className="task-row__empty">No tasks</div>
              ) : (
                filteredTasks.map((task) => (
                  <TaskRow
                    key={task.taskNum}
                    robot={task.robot}
                    endpoint={task.endpoint}
                    state={task.state}
                    duration={task.duration}
                    isExpanded={expandedTaskId === task.taskNum}
                    onToggleExpand={() => handleTaskToggle(task.taskNum)}
                    onInfo={() => setOpenTaskId(task.taskNum)}
                  />
                ))
              )}
            </div> */}
          </Panel>
          <DeviceInfoPopup
            deviceId={openDeviceId}
            onClose={() => setOpenDeviceId(null)}
          />
          <TaskInfoModal
            taskId={openTaskId}
            onClose={() => setOpenTaskId(null)}
          />
          <CreateTaskModal
            open={createTaskOpen}
            onClose={() => setCreateTaskOpen(false)}
          />
          <ConfirmModal
            open={stopConfirmOpen}
            title="작업 종료"
            message="진행중인 작업이 있습니다. 작업을 중단하고 종료하시겠습니까?"
            onConfirm={handleConfirmStop}
            onCancel={() => setStopConfirmOpen(false)}
          />
        </main>
      </div>
    </div>
    </>
  );
}

