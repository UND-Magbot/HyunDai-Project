"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { OverlayCard } from "../components/ui/monitoring/OverlayCard";
import { LayerButton } from "../components/ui/monitoring/LayerButton";
import { MapModeButton } from "../components/ui/monitoring/MapModeButton";
import { DeviceRow } from "../components/ui/monitoring/DeviceRow";
// import { TaskRow } from "../components/ui/monitoring/TaskRow";
import { RobotDeviceInfo } from "../components/ui/RobotDeviceInfo";
import type { RobotDevice, RunState } from "@/lib/types/robots";
import {
  mapBackendStatusToDeviceStatus,
  mapBackendStatusToPower,
  mapLiveRunStateToDeviceStatus,
  mapLiveOnlineToPower,
  formatBattery,
  formatLiveBattery,
} from "@/lib/utils/robotStatus";
import { TaskInfoModal } from "../components/ui/monitoring/TaskInfoModal";
import { CreateTaskModal } from "../components/ui/tasks/CreateTaskModal";
import { ConfirmModal } from "../components/ui/robots/ConfirmModal";
import { Modal } from "../components/ui/Modal";
import { mockTasks } from "@/lib/mock/tasks";
import type { TaskState } from "@/lib/types/monitoring";
import { SearchInput } from "../components/ui/SearchInput";
import { Panel } from "../components/ui/Panel";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { TopBar } from "../components/shell/TopBar";
import { MonitoringMapCanvas } from "../components/ui/monitoring/MonitoringMapCanvas";
import dynamic from "next/dynamic";

const MonitoringMap3D = dynamic(
  () =>
    import("../components/ui/monitoring/MonitoringMap3D").then((mod) => ({
      default: mod.MonitoringMap3D,
    })),
  { ssr: false, loading: () => <div className="monitoring-map3d-loading">Loading 3D...</div> }
);
import {
  mockVirtualWalls,
} from "@/lib/mock/mapMarkers";
import type { PoiMarkerData, RobotMarkerData, RouteSegment, WaypointMarkerData } from "@/lib/types/map-markers";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import { BusinessSelectBox } from "../components/ui/monitoring/BusinessSelectBox";
import { apiFetch, apiPost } from "@/lib/api";
import type { Business } from "@/lib/types/robots";
import type { MapMeta } from "@/lib/types/map";

type BusinessItem = {
  business_id: number;
  name: string;
  areas: { area_id: number; name: string }[];
};

type AreaItem = {
  area_id: number;
  name: string;
};

type MapItem = {
  id: number;
  name: string | null;
  image_url: string | null;
  mapping_id: number | null;
  state: string | null;
  grid_origin_x: number;
  grid_origin_y: number;
  grid_resolution: number;
};

function mapPoiTypeToMonitorType(
  apiType: string
): "workstation" | "charging" | "pickup" | "dropoff" {
  switch (apiType) {
    case "charging":
      return "charging";
    case "standby":
      return "workstation";
    default:
      return "workstation";
  }
}

type ApiRobot = {
  serial_number: string;
  name: string;
  ip_address: string;
};

type ApiRobotStatus = {
  battery_level: number;
  charging_status: number;
  charging_status_name: string;
  position_x: number;
  position_y: number;
  position_yaw: number;
  status: number;
  status_name: string;
  updated_at: string;
};

type ApiRobotFull = {
  id: number;
  name: string;
  serial_number: string;
  site: string | null;
  model: string | null;
  ip_address: string | null;
  max_battery: number;
  min_battery: number;
  is_active: boolean;
  business_id: string | null;
  area_id: string | null;
  status: ApiRobotStatus | null;
  created_at: string;
  updated_at: string;
};

type LiveRobot = {
  IP: string;
  SN: string;
  ROBOTNAME: string;
  MODEL: string;
  NICKNAME: string | null;
  AXBOT_VERSION: string | null;
  PLATFORM: string | null;
  RUNSTATE: string;
  ONLINE: string;
  SIGNAL: string;
  "POWER(%)": string;
};

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
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [mapMode, setMapMode] = useState<"2d" | "3d">("2d");
  const [taskTab, setTaskTab] = useState<TaskState>("running");
  const [overlayItems, setOverlayItems] = useState(defaultOverlayItems);
  const [isLayerOpen, setIsLayerOpen] = useState(false);
  const [expandedDeviceId, setExpandedDeviceId] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [openDeviceId, setOpenDeviceId] = useState<string | null>(null);
  const [togglingDeviceId, setTogglingDeviceId] = useState<string | null>(null);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [mapSrc, setMapSrc] = useState("");
  const [createTaskOpen, setCreateTaskOpen] = useState(false);
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const [alertModal, setAlertModal] = useState<{ title: string; message: string } | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [loopRunning, setLoopRunning] = useState(false);
  const [loopStopping, setLoopStopping] = useState(false);
  const [deviceSearch, setDeviceSearch] = useState("");
  const [taskSearch, setTaskSearch] = useState("");
  const [simulatedRobots, setSimulatedRobots] = useState<RobotMarkerData[]>([]);

  // ── 실제 로봇 데이터 (mock 대체) ──
  const [apiRobotsFull, setApiRobotsFull] = useState<ApiRobotFull[]>([]);
  const [liveRobots, setLiveRobots] = useState<LiveRobot[]>([]);
  const livePollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleDeviceEnableToggle = useCallback((deviceId: string) => {
    if (togglingDeviceId) return;
    setTogglingDeviceId(deviceId);
    // TODO: Replace with real API call
    setTimeout(() => setTogglingDeviceId(null), 300);
  }, [togglingDeviceId]);

  // const taskCountByRobot = mockTasks.reduce((acc, task) => {
  //   acc[task.robot] = (acc[task.robot] || 0) + 1;
  //   return acc;
  // }, {} as Record<string, number>);

  const [isLoading, setIsLoading] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(initialDateTime);
  const [selectedBusiness, setSelectedBusiness] = useState("");

  // API data state
  const [apiBusinesses, setApiBusinesses] = useState<BusinessItem[]>([]);
  const [areas, setAreas] = useState<AreaItem[]>([]);
  const [selectedArea, setSelectedArea] = useState("");
  const [areaMaps, setAreaMaps] = useState<MapItem[]>([]);
  const [selectedMapId, setSelectedMapId] = useState<number | null>(null);
  const [mapImageSize, setMapImageSize] = useState<{ w: number; h: number } | null>(null);
  const [rawApiElements, setRawApiElements] = useState<{ pois: any[]; lines: any[] } | null>(null);
  const [apiPois, setApiPois] = useState<PoiMarkerData[]>([]);
  const [apiWaypoints, setApiWaypoints] = useState<WaypointMarkerData[]>([]);
  const [apiRouteWaypoints, setApiRouteWaypoints] = useState<WaypointMarkerData[]>([]);
  const [apiRouteSegments, setApiRouteSegments] = useState<RouteSegment[]>([]);


  // 로봇 실시간 위치 (다중 로봇)
  const [mapMeta, setMapMeta] = useState<MapMeta | null>(null);
  const defaultMapRef = useRef<{ image_url: string | null; grid_origin_x: number; grid_origin_y: number; grid_resolution: number; area_id: number | null } | null>(null);
  const [apiRobots, setApiRobots] = useState<ApiRobot[]>([]);
  const [robotPoses, setRobotPoses] = useState<Map<string, { pos: [number, number]; ori: number }>>(new Map());
  const poseWsRefs = useRef<Map<string, WebSocket>>(new Map());

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── 기본 맵 + 사업장 목록을 동시에 로드 (race condition 방지) ──
  useEffect(() => {
    Promise.all([
      apiFetch<{ image_url: string | null; grid_origin_x: number; grid_origin_y: number; grid_resolution: number; area_id: number | null }>("/api/map/default-map").catch(() => null),
      apiFetch<{ total: number; items: BusinessItem[] }>("/api/map/businesses").catch(() => ({ total: 0, items: [] as BusinessItem[] })),
    ]).then(([defaultMap, bizData]) => {
      // 기본 맵 정보 설정
      if (defaultMap) {
        defaultMapRef.current = defaultMap;
        if (defaultMap.image_url && !mapSrc) {
          if (defaultMap.image_url.startsWith("/static/")) {
            setMapSrc(`${process.env.NEXT_PUBLIC_API_URL}${defaultMap.image_url}`);
          } else {
            setMapSrc(`${process.env.NEXT_PUBLIC_API_URL}/api/map/proxy-image?url=${encodeURIComponent(defaultMap.image_url)}`);
          }
        }
        if (!mapMeta) {
          setMapMeta({ grid_origin_x: defaultMap.grid_origin_x, grid_origin_y: defaultMap.grid_origin_y, grid_resolution: defaultMap.grid_resolution });
        }
      }
      // 사업장 목록 설정
      setApiBusinesses(bizData.items);
      if (!selectedBusiness) {
        const defaultBiz = bizData.items.find((b) => b.name === "구미 본사");
        if (defaultBiz) setSelectedBusiness(String(defaultBiz.business_id));
      }
    });
  }, []);

  // ── Business 변경 시 영역 목록 (apiBusinesses에서 직접 추출) ──
  useEffect(() => {
    if (!selectedBusiness) {
      setAreas([]);
      setSelectedArea("");
      setAreaMaps([]);
      setMapSrc("");
      return;
    }
    setAreaMaps([]);
    setMapSrc("");
    apiFetch<{ total: number; items: AreaItem[] }>(
      `/api/map/businesses/${selectedBusiness}/areas`
    )
      .then((data) => {
        setAreas(data.items);
        if (initialLoadRef.current) {
          const defAreaId = defaultMapRef.current?.area_id;
          const defaultArea = defAreaId
            ? data.items.find((a) => a.area_id === defAreaId)
            : null;
          if (defaultArea) {
            setSelectedArea(String(defaultArea.area_id));
            initialLoadRef.current = false;
            return;
          }
        }
        if (data.items.length > 0) {
          setSelectedArea(String(data.items[0].area_id));
        } else {
          setSelectedArea("");
        }
      })
      .catch(() => setAreas([]));
  }, [selectedBusiness]);

  // ── Area 변경 시 맵 목록 로드 및 첫 번째 맵 이미지 + 요소 로드 ──
  const applyDefaultMap = () => {
    const def = defaultMapRef.current;
    if (def?.image_url) {
      if (def.image_url.startsWith("/static/")) {
        setMapSrc(`${process.env.NEXT_PUBLIC_API_URL}${def.image_url}`);
      } else {
        setMapSrc(`${process.env.NEXT_PUBLIC_API_URL}/api/map/proxy-image?url=${encodeURIComponent(def.image_url)}`);
      }
      setMapMeta({ grid_origin_x: def.grid_origin_x, grid_origin_y: def.grid_origin_y, grid_resolution: def.grid_resolution });
    } else {
      setMapSrc("");
      setMapMeta(null);
    }
  };

  useEffect(() => {
    if (!selectedArea) {
      setAreaMaps([]);
      setSelectedMapId(null);
      applyDefaultMap();
      setRawApiElements(null);
      setApiPois([]);
      setApiWaypoints([]);
      setApiRouteWaypoints([]);
      setApiRouteSegments([]);
      setMapImageSize(null);
      return;
    }
    apiFetch<{ total: number; items: MapItem[] }>(
      `/api/map/areas/${selectedArea}/maps`
    )
      .then((data) => {
        setAreaMaps(data.items);
        if (data.items.length > 0 && data.items[0].image_url) {
          const map = data.items[0];
          setSelectedMapId(map.id);
          setMapMeta({
            grid_origin_x: map.grid_origin_x,
            grid_origin_y: map.grid_origin_y,
            grid_resolution: map.grid_resolution,
          });
          const imgUrl = map.image_url!;
          if (imgUrl.startsWith("/static/")) {
            setMapSrc(`${process.env.NEXT_PUBLIC_API_URL}${imgUrl}`);
          } else {
            setMapSrc(
              `${process.env.NEXT_PUBLIC_API_URL}/api/map/proxy-image?url=${encodeURIComponent(imgUrl)}`
            );
          }
          // 저장된 POI·라인 로드
          apiFetch<{ pois: any[]; lines: any[] }>(
            `/api/map/maps/${map.id}/elements`
          )
            .then((elems) => setRawApiElements(elems))
            .catch(() => setRawApiElements(null));
        } else {
          setSelectedMapId(null);
          applyDefaultMap();
          setRawApiElements(null);
          setApiPois([]);
          setApiWaypoints([]);
          setApiRouteWaypoints([]);
          setApiRouteSegments([]);
        }
      })
      .catch(() => {
        setAreaMaps([]);
        setSelectedMapId(null);
        setMapSrc("");
        setMapMeta(null);
        setRawApiElements(null);
      });
  }, [selectedArea]);

  // ── 맵 이미지 크기 로드 (좌표 변환용) ──
  useEffect(() => {
    if (!mapSrc) {
      setMapImageSize(null);
      return;
    }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      setMapImageSize({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = () => setMapImageSize(null);
    img.src = mapSrc;
  }, [mapSrc]);

  // ── SVG 좌표 → 이미지 픽셀 좌표 변환 (rawApiElements + mapImageSize) ──
  useEffect(() => {
    if (!rawApiElements || !mapImageSize) {
      setApiPois([]);
      setApiWaypoints([]);
      setApiRouteWaypoints([]);
      setApiRouteSegments([]);
      return;
    }

    const halfW = mapImageSize.w / 2;
    const halfH = mapImageSize.h / 2;

    const convertedPois: PoiMarkerData[] = [];
    const convertedWaypoints: WaypointMarkerData[] = [];

    const hiddenPoiNames = new Set(["CHARGING1", "ENTERPOS1", "ENTERPOS2", "ENTERPOS3"]);

    for (const p of rawApiElements.pois) {
      if (hiddenPoiNames.has(p.name)) continue;

      const px = p.x + halfW;
      const py = p.y + halfH;

      if (p.type === "waypoint") {
        convertedWaypoints.push({
          id: p.id,
          label: p.name,
          position: { x: px, y: py },
        });
      } else {
        convertedPois.push({
          id: p.id,
          label: p.name,
          position: { x: px, y: py },
          type: mapPoiTypeToMonitorType(p.type),
          angle: p.angle ?? undefined,
          dockingRadius: p.dockingRadius ?? undefined,
        });
      }
    }

    // 라인 → 경로 웨이포인트 + RouteSegment 변환
    const posMap = new Map<string, { x: number; y: number; name: string }>();
    for (const p of rawApiElements.pois) {
      posMap.set(p.id, { x: p.x + halfW, y: p.y + halfH, name: p.name });
    }

    const routePoints: WaypointMarkerData[] = [];
    const segments: RouteSegment[] = [];

    for (const line of rawApiElements.lines) {
      const fromPos = posMap.get(line.fromId);
      const toPos = posMap.get(line.toId);
      if (fromPos && toPos) {
        // routeWaypoints (기존 호환)
        if (
          routePoints.length === 0 ||
          routePoints[routePoints.length - 1].id !== line.fromId
        ) {
          routePoints.push({
            id: line.fromId,
            label: fromPos.name,
            position: { x: fromPos.x, y: fromPos.y },
          });
        }
        routePoints.push({
          id: line.toId,
          label: toPos.name,
          position: { x: toPos.x, y: toPos.y },
        });

        // RouteSegment (direction, curve 정보 포함)
        const controlPts = line.controlPoints
          ? line.controlPoints.map((cp: { x: number; y: number }) => ({
              x: cp.x + halfW,
              y: cp.y + halfH,
            }))
          : undefined;

        segments.push({
          id: line.id,
          from: { x: fromPos.x, y: fromPos.y },
          to: { x: toPos.x, y: toPos.y },
          direction: line.direction ?? "forward",
          lineType: line.lineType ?? "straight",
          controlPoints: controlPts,
        });
      }
    }

    setApiPois(convertedPois);
    setApiWaypoints(convertedWaypoints);
    setApiRouteWaypoints(routePoints);
    setApiRouteSegments(segments);
  }, [rawApiElements, mapImageSize]);

  // API 사업장 → BusinessSelectBox 형식 변환
  const businessesForSelectBox: Business[] = useMemo(
    () => apiBusinesses.map((b) => {
      const defaultArea = b.areas?.find((a) => a.name === "area-O002");
      return {
        id: String(b.business_id),
        name: b.name,
        value: defaultArea ? String(defaultArea.area_id) : "",
      };
    }),
    [apiBusinesses]
  );

  // ── 로봇 목록 API 로드 (selectedArea 기반) ──
  useEffect(() => {
    if (!selectedArea) {
      setApiRobotsFull([]);
      setApiRobots([]);
      return;
    }
    apiFetch<{ total: number; items: ApiRobotFull[] }>(
      `/api/robots?area_id=${selectedArea}`
    )
      .then((data) => {
        setApiRobotsFull(data.items);
        setApiRobots(
          data.items
            .filter((r) => r.ip_address)
            .map((r) => ({
              serial_number: r.serial_number,
              name: r.name,
              ip_address: r.ip_address!,
            }))
        );
      })
      .catch(() => {
        setApiRobotsFull([]);
        setApiRobots([]);
      });
  }, [selectedArea]);

  // ── 다중 로봇 실시간 위치 WS 연결 ──
  useEffect(() => {
    // 기존 연결 정리
    poseWsRefs.current.forEach((ws) => ws.close());
    poseWsRefs.current.clear();
    setRobotPoses(new Map());

    if (!apiRobots.length) return;

    const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
    const wsBase = API_URL.replace(/^http/, "ws");

    apiRobots.forEach((robot) => {
      const wsUrl = `${wsBase}/api/map/ws/${robot.ip_address}?topics=/tracked_pose`;
      const ws = new WebSocket(wsUrl);
      poseWsRefs.current.set(robot.serial_number, ws);

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.topic === "/tracked_pose" && msg.pos) {
            setRobotPoses((prev) => {
              const next = new Map(prev);
              next.set(robot.serial_number, {
                pos: msg.pos,
                ori: msg.ori ?? 0,
              });
              return next;
            });
          }
        } catch {
          // ignore
        }
      };
      ws.onerror = () =>
        console.warn(`[MonitoringPoseWS] ${robot.name} (${robot.ip_address}) error`);
      ws.onclose = () =>
        console.log(`[MonitoringPoseWS] ${robot.name} closed`);
    });

    return () => {
      poseWsRefs.current.forEach((ws) => ws.close());
      poseWsRefs.current.clear();
    };
  }, [apiRobots]);

  // ── 로봇 실시간 상태 폴링 (5초 간격) ──
  useEffect(() => {
    if (livePollingRef.current) {
      clearInterval(livePollingRef.current);
      livePollingRef.current = null;
    }

    if (apiRobotsFull.length === 0) {
      setLiveRobots([]);
      return;
    }

    const fetchLive = () => {
      apiFetch<{ total: number; items: LiveRobot[] }>("/api/robots/live")
        .then((data) => setLiveRobots(data.items))
        .catch(() => {});
    };

    fetchLive();
    livePollingRef.current = setInterval(fetchLive, 5000);

    return () => {
      if (livePollingRef.current) {
        clearInterval(livePollingRef.current);
        livePollingRef.current = null;
      }
    };
  }, [apiRobotsFull]);

  // ── IP 기준 live 데이터 lookup ──
  const liveByIp = useMemo(() => {
    const map = new Map<string, LiveRobot>();
    for (const lr of liveRobots) {
      map.set(lr.IP, lr);
    }
    return map;
  }, [liveRobots]);

  // ── 다중 로봇 월드 좌표 → 이미지 픽셀 좌표 변환 (live 상태 반영) ──
  useEffect(() => {
    if (!mapMeta || !mapImageSize || mapMeta.grid_resolution <= 0) {
      return;
    }
    if (robotPoses.size === 0) {
      setSimulatedRobots([]);
      return;
    }

    const markers: RobotMarkerData[] = [];
    robotPoses.forEach((pose, sn) => {
      const ipx =
        (pose.pos[0] - mapMeta.grid_origin_x) / mapMeta.grid_resolution;
      const ipy =
        mapImageSize.h -
        (pose.pos[1] - mapMeta.grid_origin_y) / mapMeta.grid_resolution;

      const robot = apiRobots.find((r) => r.serial_number === sn);
      const fullRobot = apiRobotsFull.find((r) => r.serial_number === sn);
      const live = fullRobot?.ip_address ? liveByIp.get(fullRobot.ip_address) : null;

      markers.push({
        robotId: sn,
        robotName: robot?.name ?? sn,
        position: { x: ipx, y: ipy },
        yaw: pose.ori,
        status: live ? mapLiveRunStateToDeviceStatus(live.RUNSTATE) : "running",
        power: live ? mapLiveOnlineToPower(live.ONLINE) : "online",
      });
    });

    setSimulatedRobots(markers);
  }, [robotPoses, mapMeta, mapImageSize, apiRobots, apiRobotsFull, liveByIp]);

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


  // ─── 무한반복 작업 제어 ───
  const LOOP_ROBOT_ID = 7;
  const LOOP_ENTRY_NAMES = ["ENTERPOS1", "ENTERPOS2", "ENTERPOS3"];
  const LOOP_POI_NAMES = ["CURPOS1", "CURPOS2", "CURPOS3", "CURPOS4", "CURPOS5", "CURPOS6"];
  const LOOP_STOP_NAMES = ["CURPOS2", "CURPOS4"];

  const handleStartAll = async () => {
    try {
      await apiPost("/api/tasks/loop/start", {
        robot_id: LOOP_ROBOT_ID,
        poi_names: LOOP_POI_NAMES,
        stop_names: LOOP_STOP_NAMES,
        entry_poi_names: LOOP_ENTRY_NAMES,
      });
      setLoopRunning(true);
      setIsRunning(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "시작 실패";
      setAlertModal({ title: "작업 시작 실패", message: msg });
    }
  };

  const CHARGE_ROUTE_NAMES = ["ENTERPOS3", "ENTERPOS2", "ENTERPOS1"];

  const handleCharge = async (deviceId: string) => {
    const robot = apiRobotsFull.find((r) => String(r.id) === deviceId);
    if (!robot) return;
    try {
      await apiPost(`/api/tasks/charge/${robot.id}`, {
        route_poi_names: CHARGE_ROUTE_NAMES,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "충전소 이동 실패";
      setAlertModal({ title: "충전소 이동 실패", message: msg });
    }
  };

  const handleStopAll = () => {
    setStopConfirmOpen(true);
  };

  const handleConfirmStop = async () => {
    setStopConfirmOpen(false);
    try {
      await apiPost(`/api/tasks/loop/stop/${LOOP_ROBOT_ID}`);
      setLoopStopping(true);
    } catch {
      /* 이미 중단된 경우 무시 */
    }
  };

  // 루프 상태 폴링 (3초 간격)
  useEffect(() => {
    if (!loopRunning && !loopStopping) return;
    const timer = setInterval(async () => {
      try {
        const res = await apiFetch<{ status: string }>(`/api/tasks/loop/status/${LOOP_ROBOT_ID}`);
        if (res.status === "error" || res.status === "stopped" || res.status === "idle" || res.status === "charging") {
          setLoopRunning(false);
          setLoopStopping(false);
          setIsRunning(false);
        }
      } catch {
        /* 무시 */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [loopRunning, loopStopping]);

  // ── API 로봇 → DeviceRow 형식 변환 ──
  const deviceList = useMemo(() => {
    return apiRobotsFull.map((robot) => {
      const live = robot.ip_address ? liveByIp.get(robot.ip_address) : null;

      let power: "online" | "offline";
      let battery: string;
      let status: "idle" | "running" | "charging" | "error" | "warning" | "disable";

      if (live) {
        power = mapLiveOnlineToPower(live.ONLINE);
        battery = formatLiveBattery(live["POWER(%)"], live.ONLINE);
        status = mapLiveRunStateToDeviceStatus(live.RUNSTATE);
      } else if (robot.status) {
        power = mapBackendStatusToPower(robot.status.status);
        battery = formatBattery(robot.status.battery_level, power);
        status = mapBackendStatusToDeviceStatus(robot.status.status);
      } else {
        power = "offline";
        battery = "--";
        status = "disable";
      }

      return {
        id: String(robot.id),
        name: robot.name,
        power,
        battery,
        status,
      };
    });
  }, [apiRobotsFull, liveByIp]);

  const filteredDevices = useMemo(() => {
    if (!deviceSearch) return deviceList;
    return deviceList.filter((d) =>
      d.name.toLowerCase().includes(deviceSearch.toLowerCase())
    );
  }, [deviceList, deviceSearch]);

  const deviceCounts = useMemo(() => ({
    all: deviceList.length,
    online: deviceList.filter((d) => d.power === "online").length,
    offline: deviceList.filter((d) => d.power === "offline").length,
    error: deviceList.filter((d) => d.status === "error").length,
  }), [deviceList]);

  // ── 로봇 정보 모달 (실제 데이터) ──
  const selectedDevice: RobotDevice | null = useMemo(() => {
    if (!openDeviceId) return null;
    const robot = apiRobotsFull.find((r) => String(r.id) === openDeviceId);
    if (!robot) return null;

    const live = robot.ip_address ? liveByIp.get(robot.ip_address) : null;

    let runState: RunState | null = null;
    if (live) {
      if (live.RUNSTATE === "EXECUTING") runState = "EXECUTING";
      else if (live.RUNSTATE === "CHARGING") runState = "CHARGING";
      else if (live.RUNSTATE === "IDLE") runState = "IDLE";
    }

    return {
      id: String(robot.id),
      sn: robot.serial_number,
      robotName: robot.name,
      model: robot.model ?? "-",
      runState,
      online: live ? live.ONLINE === "Online" : (robot.status?.status !== 4),
      signal: live && live.SIGNAL !== "N/A" ? parseInt(live.SIGNAL, 10) || null : null,
      power: live && live.ONLINE === "Online"
        ? parseInt(live["POWER(%)"], 10) || null
        : robot.status?.battery_level ?? null,
      enable: robot.is_active,
      nickname: live?.NICKNAME ?? null,
      axbotVersion: live?.AXBOT_VERSION ?? null,
      platform: live?.PLATFORM ?? null,
      busiName: null,
      buildingName: null,
      currentTask: [],
    };
  }, [openDeviceId, apiRobotsFull, liveByIp]);

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

  const renderedWaypoints = showNavigationNodes ? apiWaypoints : [];
  const routeWaypoints = showNavigationLine ? apiRouteWaypoints : [];
  const routeSegments = showNavigationLine ? apiRouteSegments : [];

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
                  placeholder="로봇 명"
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
                    onCharge={handleCharge}
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
              <BusinessSelectBox
                businesses={businessesForSelectBox}
                selectedId={selectedBusiness}
                onChange={setSelectedBusiness}
              />
              {mapMode === "3d" ? (
                <MonitoringMap3D
                  mapSrc={mapSrc}
                  pois={apiPois}
                  waypoints={renderedWaypoints}
                  routeWaypoints={routeWaypoints}
                  routeSegments={routeSegments}
                  robots={simulatedRobots}
                  virtualWalls={mockVirtualWalls}
                  showMapBackground={showMapBackground}
                  showNavigationLine={showNavigationLine}
                  showDirectionArrows={showDirectionArrows}
                  showVirtualWalls={showVirtualWalls}
                  showNavigationNodes={showNavigationNodes}
                  showPoiMarkers={showPoiMarkers}
                />
              ) : (
                <MonitoringMapCanvas
                  mapSrc={mapSrc}
                  pois={apiPois}
                  waypoints={renderedWaypoints}
                  routeWaypoints={routeWaypoints}
                  routeSegments={routeSegments}
                  robots={simulatedRobots}
                  virtualWalls={mockVirtualWalls}

                  showMapBackground={showMapBackground}
                  showNavigationLine={showNavigationLine}
                  showDirectionArrows={showDirectionArrows}
                  showVirtualWalls={showVirtualWalls}
                  showNavigationNodes={showNavigationNodes}
                  showPoiMarkers={showPoiMarkers}
                />
              )}
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
                  disabled={loopRunning || loopStopping}
                >
                  {loopRunning || loopStopping ? "작업중" : "시작"}
                </button>
                <button
                  className="btn btn--danger"
                  onClick={handleStopAll}
                  disabled={!isRunning || loopStopping}
                >
                  {loopStopping ? "종료중..." : "종료"}
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
          {selectedDevice && (
            <RobotDeviceInfo
              device={selectedDevice}
              onClose={() => setOpenDeviceId(null)}
              onEnableToggle={handleDeviceEnableToggle}
              togglingDeviceId={togglingDeviceId}
              showChargingStation={false}
            />
          )}
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
            message={"현재 진행 중인 작업을 마친 후 종료됩니다.\n종료하시겠습니까?"}
            onConfirm={handleConfirmStop}
            onCancel={() => setStopConfirmOpen(false)}
          />
          <Modal
            open={!!alertModal}
            onClose={() => setAlertModal(null)}
            title={alertModal?.title ?? ""}
            width="400px"
          >
            <div className="confirm-modal">
              <p className="confirm-modal__message">{alertModal?.message}</p>
              <div className="confirm-modal__actions">
                <button
                  className="btn btn--primary"
                  onClick={() => setAlertModal(null)}
                >
                  확인
                </button>
              </div>
            </div>
          </Modal>
        </main>
      </div>
    </div>
    </>
  );
}

