"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { MapTopBar } from "../components/ui/map/MapTopBar";
import { MapCanvas } from "../components/ui/map/MapCanvas";
import { MapToolbarTop } from "../components/ui/map/MapToolbarTop";
import { MapToolbarLeft } from "../components/ui/map/MapToolbarLeft";
import { MapFloatingPanel } from "../components/ui/map/MapFloatingPanel";
import { RobotConnectModal } from "../components/ui/map/RobotConnectModal";
import { MappingSetupModal } from "../components/ui/map/MappingSetupModal";
import { MappingModal } from "../components/ui/map/MappingModal";
import { MapSyncModal } from "../components/ui/map/MapSyncModal";
import { POIEditPopup } from "../components/ui/map/POIEditPopup";
import { LineDirectionPopup } from "../components/ui/map/LineDirectionPopup";
import type {
  MapTool,
  POI,
  PathLine,
  PolygonShape,
  LineDirection,
  ConnectedRobot,
  RobotPose,
  MapMeta,
} from "@/lib/types/map";
import { apiFetch } from "@/lib/api";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import "./map.css";

type BusinessItem = {
  business_id: number;
  name: string;
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

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

let nextId = 1;
function generateId(prefix: string) {
  return `${prefix}-${nextId++}`;
}

/** DB에서 불러온 ID들("poi-123" 등)과 충돌하지 않도록 nextId를 갱신 */
function syncNextId(ids: string[]) {
  for (const id of ids) {
    const num = parseInt(id.split("-")[1] ?? "0", 10);
    if (num >= nextId) nextId = num + 1;
  }
}

export default function MapPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [isLoading, setIsLoading] = useState(true);

  // Map state
  const [pois, setPois] = useState<POI[]>([]);
  const [lines, setLines] = useState<PathLine[]>([]);
  const [polygons, setPolygons] = useState<PolygonShape[]>([]);
  const [activeTool, setActiveTool] = useState<MapTool>("select");
  const [selectedPOI, setSelectedPOI] = useState<string | null>(null);
  const [lineStartPOI, setLineStartPOI] = useState<string | null>(null);
  const [polygonPoints, setPolygonPoints] = useState<{ x: number; y: number }[]>([]);

  // Zoom/Pan/Rotation
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [rotation, setRotation] = useState(0);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const offsetInitialized = useRef(false);
  const initialLoadRef = useRef(true);

  // Center the map on first render
  useEffect(() => {
    if (offsetInitialized.current) return;
    const el = canvasWrapRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      setOffset({ x: rect.width / 2, y: rect.height / 2 });
      offsetInitialized.current = true;
    }
  });

  // UI state
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [floatingPanelOpen, setFloatingPanelOpen] = useState(true);
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  const [connectedRobot, setConnectedRobot] = useState<ConnectedRobot>(null);

  // Mapping flow
  const [mappingSetupOpen, setMappingSetupOpen] = useState(false);
  const [mappingModalOpen, setMappingModalOpen] = useState(false);
  const [mappingBusinessId, setMappingBusinessId] = useState<number | null>(null);
  const [mappingAreaId, setMappingAreaId] = useState("");
  const [mappingAreaName, setMappingAreaName] = useState("");

  // Popups
  const [editingPOI, setEditingPOI] = useState<POI | null>(null);
  const [lineDirectionPopup, setLineDirectionPopup] = useState<{
    fromId: string;
    toId: string;
    position: { x: number; y: number };
  } | null>(null);

  // Selectors
  const [businesses, setBusinesses] = useState<BusinessItem[]>([]);
  const [selectedBusiness, setSelectedBusiness] = useState("");
  const [areas, setAreas] = useState<AreaItem[]>([]);
  const [selectedArea, setSelectedArea] = useState("");
  const [areaMaps, setAreaMaps] = useState<MapItem[]>([]);
  const [selectedMapId, setSelectedMapId] = useState<number | null>(null);
  const [selectedMappingId, setSelectedMappingId] = useState<number | null>(null);
  const [mapImageUrl, setMapImageUrl] = useState<string | null>(null);
  const [mapMeta, setMapMeta] = useState<MapMeta>(null);

  // Robot pose (real-time)
  const [robotPose, setRobotPose] = useState<RobotPose>(null);
  const poseWsRef = useRef<WebSocket | null>(null);
  const [mapImageSize, setMapImageSize] = useState<{ w: number; h: number } | null>(null);

  // Undo history
  const [history, setHistory] = useState<{
    pois: POI[];
    lines: PathLine[];
    polygons: PolygonShape[];
  }[]>([]);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  // Esc 키 → select 모드로 복귀
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setActiveTool("select");
        setSelectedPOI(null);
        setEditingPOI(null);
        setLineStartPOI(null);
        setLineDirectionPopup(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // 사업장 목록 로드 (초기 로드 시 "구미본사" 자동 선택)
  useEffect(() => {
    apiFetch<{ total: number; items: BusinessItem[] }>("/api/map/businesses")
      .then((data) => {
        setBusinesses(data.items);
        if (!selectedBusiness) {
          const defaultBiz = data.items.find((b) => b.name === "구미 본사");
          if (defaultBiz) setSelectedBusiness(String(defaultBiz.business_id));
        }
      })
      .catch(() => {});
  }, []);

  // Business 변경 시 영역 목록 로드
  useEffect(() => {
    if (!selectedBusiness) {
      setAreas([]);
      setSelectedArea("");
      setAreaMaps([]);
      setMapImageUrl(null);
      return;
    }
    setAreaMaps([]);
    setMapImageUrl(null);
    apiFetch<{ total: number; items: AreaItem[] }>(
      `/api/map/businesses/${selectedBusiness}/areas`
    )
      .then((data) => {
        setAreas(data.items);
        // 초기 로드 시 "area-B001" 자동 선택
        if (initialLoadRef.current) {
          const defaultArea = data.items.find((a) => a.name === "area-B001");
          if (defaultArea) {
            setSelectedArea(String(defaultArea.area_id));
            initialLoadRef.current = false;
            return;
          }
        }
        setSelectedArea("");
      })
      .catch(() => setAreas([]));
  }, [selectedBusiness]);

  // Area 변경 시 맵 목록 로드 및 첫 번째 맵 이미지 표시
  useEffect(() => {
    if (!selectedArea) {
      setAreaMaps([]);
      setSelectedMapId(null);
      setSelectedMappingId(null);
      setMapImageUrl(null);
      setMapMeta(null);
      setPois([]);
      setLines([]);
      return;
    }
    apiFetch<{ total: number; items: MapItem[] }>(
      `/api/map/areas/${selectedArea}/maps`
    )
      .then((data) => {
        setAreaMaps(data.items);
        // 첫 번째 맵의 이미지를 자동으로 로드
        if (data.items.length > 0 && data.items[0].image_url) {
          const map = data.items[0];
          setSelectedMapId(map.id);
          setSelectedMappingId(map.mapping_id);
          const imgUrl = map.image_url!;
          if (imgUrl.startsWith("/static/")) {
            setMapImageUrl(`${process.env.NEXT_PUBLIC_API_URL}${imgUrl}`);
          } else {
            setMapImageUrl(`${process.env.NEXT_PUBLIC_API_URL}/api/map/proxy-image?url=${encodeURIComponent(imgUrl)}`);
          }
          setMapMeta({
            grid_origin_x: map.grid_origin_x,
            grid_origin_y: map.grid_origin_y,
            grid_resolution: map.grid_resolution,
          });
          // 저장된 POI·라인 로드
          apiFetch<{ pois: any[]; lines: any[] }>(
            `/api/map/maps/${map.id}/elements`
          )
            .then((elems) => {
              const loadedPois = elems.pois.map((p: any) => ({
                id: p.id,
                x: p.x,
                y: p.y,
                name: p.name,
                type: p.type,
                phoneNumber: p.phoneNumber ?? undefined,
                angle: p.angle ?? undefined,
                loadType: p.loadType ?? undefined,
                robotSns: p.robotSns ?? undefined,
                address: p.address ?? undefined,
                dockingRadius: p.dockingRadius ?? undefined,
              }));
              const loadedLines = elems.lines.map((l: any) => ({
                id: l.id,
                fromId: l.fromId,
                toId: l.toId,
                direction: l.direction,
                lineType: l.lineType,
                controlPoints: l.controlPoints ?? undefined,
              }));
              setPois(loadedPois);
              setLines(loadedLines);
              syncNextId([
                ...loadedPois.map((p: any) => p.id),
                ...loadedLines.map((l: any) => l.id),
              ]);
            })
            .catch(() => {
              setPois([]);
              setLines([]);
            });
        } else {
          setSelectedMapId(null);
          setSelectedMappingId(null);
          setMapImageUrl(null);
          setMapMeta(null);
          setPois([]);
          setLines([]);
        }
      })
      .catch(() => {
        setAreaMaps([]);
        setSelectedMapId(null);
        setSelectedMappingId(null);
        setMapImageUrl(null);
        setMapMeta(null);
        setPois([]);
        setLines([]);
      });
  }, [selectedArea]);

  // ── 로봇 실시간 위치 WS 연결 ──
  useEffect(() => {
    // 기존 WS 정리
    if (poseWsRef.current) {
      poseWsRef.current.close();
      poseWsRef.current = null;
    }
    setRobotPose(null);

    if (!connectedRobot) return;

    const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
    const wsUrl = `${API_URL.replace(/^http/, "ws")}/api/map/ws/${connectedRobot.ip}?topics=/tracked_pose`;
    const ws = new WebSocket(wsUrl);
    poseWsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.topic === "/tracked_pose" && msg.pos) {
          setRobotPose({ pos: msg.pos, ori: msg.ori ?? 0 });
        }
      } catch {
        // ignore
      }
    };
    ws.onerror = () => console.error("[PoseWS] error");
    ws.onclose = () => console.log("[PoseWS] closed");

    return () => {
      ws.close();
      poseWsRef.current = null;
    };
  }, [connectedRobot]);

  const pushHistory = useCallback(() => {
    setHistory((prev) => [
      ...prev.slice(-19),
      {
        pois: pois.map((p) => ({ ...p })),
        lines: lines.map((l) => ({ ...l })),
        polygons: polygons.map((p) => ({ ...p, points: [...p.points] })),
      },
    ]);
  }, [pois, lines, polygons]);

  const handleUndo = useCallback(() => {
    setHistory((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      setPois(last.pois);
      setLines(last.lines);
      setPolygons(last.polygons);
      return prev.slice(0, -1);
    });
  }, []);

  const handleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  }, []);

  // ── Canvas Click Handler ──
  const handleCanvasClick = useCallback(
    (x: number, y: number) => {
      if (activeTool === "point") {
        pushHistory();
        const newPOI: POI = {
          id: generateId("poi"),
          x,
          y,
          name: `POINT${pois.length + 1}`,
          type: "waypoint",
        };
        setPois((prev) => [...prev, newPOI]);
        setEditingPOI(newPOI);
        setSelectedPOI(newPOI.id);
      } else if (activeTool === "polygon") {
        setPolygonPoints((prev) => [...prev, { x, y }]);
      }
    },
    [activeTool, pois.length, pushHistory]
  );

  // ── POI Click Handler ──
  const handlePOIClick = useCallback(
    (id: string) => {
      if (activeTool === "del") {
        pushHistory();
        setPois((prev) => prev.filter((p) => p.id !== id));
        setLines((prev) =>
          prev.filter((l) => l.fromId !== id && l.toId !== id)
        );
        setSelectedPOI(null);
        setEditingPOI(null);
        return;
      }

      if (activeTool === "line" || activeTool === "curveLine") {
        if (!lineStartPOI) {
          setLineStartPOI(id);
        } else if (lineStartPOI !== id) {
          // Show direction popup
          const from = pois.find((p) => p.id === lineStartPOI);
          const to = pois.find((p) => p.id === id);
          if (from && to) {
            setLineDirectionPopup({
              fromId: lineStartPOI,
              toId: id,
              position: {
                x: ((from.x + to.x) / 2) * zoom + offset.x,
                y: ((from.y + to.y) / 2) * zoom + offset.y,
              },
            });
          }
        } else {
          setLineStartPOI(null);
        }
        return;
      }

      // Select mode — open edit popup
      if (activeTool === "select") {
        const poi = pois.find((p) => p.id === id);
        if (poi) {
          setSelectedPOI(id);
          setEditingPOI(poi);
        }
      }
    },
    [activeTool, lineStartPOI, pois, zoom, offset, pushHistory]
  );

  // ── Line Click Handler ──
  const handleLineClick = useCallback(
    (id: string) => {
      if (activeTool === "del") {
        pushHistory();
        setLines((prev) => prev.filter((l) => l.id !== id));
      }
    },
    [activeTool, pushHistory]
  );

  // ── Polygon Click Handler ──
  const handlePolygonClick = useCallback(
    (id: string) => {
      if (activeTool === "del") {
        pushHistory();
        setPolygons((prev) => prev.filter((p) => p.id !== id));
      }
    },
    [activeTool, pushHistory]
  );

  // ── Line Direction Selection ──
  const handleLineDirectionSelect = useCallback(
    (direction: LineDirection) => {
      if (!lineDirectionPopup) return;
      pushHistory();
      const newLine: PathLine = {
        id: generateId("line"),
        fromId: lineDirectionPopup.fromId,
        toId: lineDirectionPopup.toId,
        direction,
        lineType: activeTool === "curveLine" ? "curve" : "straight",
      };
      setLines((prev) => [...prev, newLine]);
      setLineStartPOI(null);
      setLineDirectionPopup(null);
    },
    [lineDirectionPopup, activeTool, pushHistory]
  );

  // ── POI Edit Handlers ──
  const handlePOIUpdate = useCallback(
    (id: string, data: Partial<POI>) => {
      pushHistory();
      setPois((prev) =>
        prev.map((p) => (p.id === id ? { ...p, ...data } : p))
      );
    },
    [pushHistory]
  );

  const handlePOIDelete = useCallback(
    (id: string) => {
      pushHistory();
      setPois((prev) => prev.filter((p) => p.id !== id));
      setLines((prev) =>
        prev.filter((l) => l.fromId !== id && l.toId !== id)
      );
      setEditingPOI(null);
      setSelectedPOI(null);
    },
    [pushHistory]
  );

  // ── Tool Change ──
  const handleToolChange = useCallback((tool: MapTool) => {
    setActiveTool(tool);
    setSelectedPOI(null);
    setEditingPOI(null);
    setLineStartPOI(null);
    setLineDirectionPopup(null);

    // If switching away from polygon, finalize current polygon
    if (tool !== "polygon") {
      setPolygonPoints((prev) => {
        if (prev.length >= 3) {
          const newPolygon: PolygonShape = {
            id: generateId("poly"),
            points: [...prev],
            name: `Wall${polygons.length + 1}`,
          };
          setPolygons((prevPolygons) => [...prevPolygons, newPolygon]);
        }
        return [];
      });
    }

    // currentPos / chargingPile: immediately create POI at robot position
    if ((tool === "currentPos" || tool === "chargingPile") && robotPose && mapMeta && mapMeta.grid_resolution > 0 && mapImageSize) {
      // 월드 좌표 → SVG 좌표 변환 (MapCanvas 로봇 표시와 동일 공식)
      const ipx = (robotPose.pos[0] - mapMeta.grid_origin_x) / mapMeta.grid_resolution;
      const ipy = mapImageSize.h - (robotPose.pos[1] - mapMeta.grid_origin_y) / mapMeta.grid_resolution;
      const svgX = ipx - mapImageSize.w / 2;
      const svgY = ipy - mapImageSize.h / 2;

      const isCharging = tool === "chargingPile";
      const newPOI: POI = {
        id: generateId("poi"),
        x: svgX,
        y: svgY,
        name: isCharging ? `CHARGE${pois.length + 1}` : `CURPOS${pois.length + 1}`,
        type: isCharging ? "charging" : "waypoint",
      };
      setPois((prev) => [...prev, newPOI]);
      setEditingPOI(newPOI);
      setSelectedPOI(newPOI.id);
      setActiveTool("select");
    }
  }, [polygons.length, robotPose, mapMeta, mapImageSize, pois.length]);

  // ── Robot Connection ──
  const handleRobotConnect = useCallback((sn: string, name: string, ip: string) => {
    setConnectedRobot({ sn, name, ip });
    setConnectModalOpen(false);
  }, []);

  // ── Zoom Controls ──
  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(prev * 1.2, 6));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(prev / 1.2, 0.2));
  }, []);

  const handleResetBearing = useCallback(() => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setRotation(0);
  }, []);

  const handleRotateLeft = useCallback(() => {
    setRotation((prev) => prev - 15);
  }, []);

  const handleRotateRight = useCallback(() => {
    setRotation((prev) => prev + 15);
  }, []);

  // ── Clear Map ──
  const handleClearMap = useCallback(() => {
    pushHistory();
    setPois([]);
    setLines([]);
    setPolygons([]);
    setSelectedPOI(null);
    setEditingPOI(null);
    setLineStartPOI(null);
    setPolygonPoints([]);
  }, [pushHistory]);

  // ── SVG 좌표 → 로봇 물리계(월드) 좌표 변환 ──
  const svgToWorld = useCallback(
    (svgX: number, svgY: number): { worldX: number; worldY: number } | null => {
      if (!mapMeta || !mapImageSize || mapMeta.grid_resolution <= 0) return null;
      const ipx = svgX + mapImageSize.w / 2;
      const ipy = svgY + mapImageSize.h / 2;
      return {
        worldX: ipx * mapMeta.grid_resolution + mapMeta.grid_origin_x,
        worldY: (mapImageSize.h - ipy) * mapMeta.grid_resolution + mapMeta.grid_origin_y,
      };
    },
    [mapMeta, mapImageSize]
  );

  // ── Action buttons (placeholder handlers) ──
  const handleSave = useCallback(() => {
    if (!selectedMapId) {
      alert("저장할 맵을 먼저 선택해주세요.");
      return;
    }

    // POI에 월드 좌표 추가
    const poisWithWorld = pois.map((p) => {
      const w = svgToWorld(p.x, p.y);
      return { ...p, worldX: w?.worldX ?? null, worldY: w?.worldY ?? null };
    });

    // 라인에 양 끝 월드 좌표 추가
    const linesWithWorld = lines.map((l) => {
      const fromPoi = pois.find((p) => p.id === l.fromId);
      const toPoi = pois.find((p) => p.id === l.toId);
      const fw = fromPoi ? svgToWorld(fromPoi.x, fromPoi.y) : null;
      const tw = toPoi ? svgToWorld(toPoi.x, toPoi.y) : null;
      return {
        ...l,
        fromWorldX: fw?.worldX ?? null,
        fromWorldY: fw?.worldY ?? null,
        toWorldX: tw?.worldX ?? null,
        toWorldY: tw?.worldY ?? null,
      };
    });

    apiFetch(`/api/map/maps/${selectedMapId}/elements`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pois: poisWithWorld, lines: linesWithWorld }),
    })
      .then(() => alert("저장되었습니다."))
      .catch((err) => alert(`저장 실패: ${err.message ?? err}`));
  }, [selectedMapId, pois, lines, svgToWorld]);
  const handleSync = () => {
    if (!selectedMappingId) {
      alert("동기화할 맵을 먼저 선택해주세요.");
      return;
    }
    setSyncModalOpen(true);
  };
  const handleCreate = () => console.log("Create");
  const handleDelete = () => console.log("Delete");

  const handleStartMapping = () => setMappingSetupOpen(true);
  const handleMappingSetupConfirm = (businessId: number, areaId: string, areaName: string) => {
    setMappingBusinessId(businessId);
    setMappingAreaId(areaId);
    setMappingAreaName(areaName);
    setMappingSetupOpen(false);
    setMappingModalOpen(true);
  };
  const handleMappingComplete = useCallback(() => {
    // 사업장 목록 갱신
    apiFetch<{ total: number; items: BusinessItem[] }>("/api/map/businesses")
      .then((data) => setBusinesses(data.items))
      .catch(() => {});
    // 현재 선택된 사업장의 영역 목록 갱신
    if (selectedBusiness) {
      apiFetch<{ total: number; items: AreaItem[] }>(
        `/api/map/businesses/${selectedBusiness}/areas`
      )
        .then((data) => setAreas(data.items))
        .catch(() => {});
    }
    // 현재 선택된 영역의 맵 목록 갱신
    if (selectedArea) {
      apiFetch<{ total: number; items: MapItem[] }>(
        `/api/map/areas/${selectedArea}/maps`
      )
        .then((data) => setAreaMaps(data.items))
        .catch(() => {});
    }
  }, [selectedBusiness, selectedArea]);
  const handleRemoteImage = () => console.log("Remote Image");
  const handleRemoteControl = () => console.log("Remote Control");

  return (
    <>
      {isLoading && <LoadingScreen pageName="맵 관리" />}
      <div className="app-shell">
      <TopBar
        dateTime={currentDateTime}
        onToggleNav={() => setNavCollapsed((v) => !v)}
        navExpanded={!navCollapsed}
      />
      <div className="shell-body">
        <SideNav
          items={defaultNavItems}
          collapsed={navCollapsed}
          onClose={() => setNavCollapsed(true)}
          onItemSelect={() => setNavCollapsed(true)}
        />
        <main className="main-content">
          <div className="map-workspace">
            {/* Map-specific top bar */}
            <MapTopBar
              connectedRobot={connectedRobot}
              onConnectClick={() => setConnectModalOpen(true)}
              businesses={businesses}
              selectedBusiness={selectedBusiness}
              onBusinessChange={setSelectedBusiness}
              areas={areas}
              selectedArea={selectedArea}
              onAreaChange={setSelectedArea}
              onSave={handleSave}
              onSync={handleSync}
              onCreate={handleCreate}
              onDelete={handleDelete}
            />

            {/* Map Canvas Area */}
            <div ref={canvasWrapRef} style={{ position: "relative", flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <MapCanvas
                pois={pois}
                lines={lines}
                polygons={polygons}
                activeTool={activeTool}
                selectedPOI={selectedPOI}
                lineStartPOI={lineStartPOI}
                zoom={zoom}
                offset={offset}
                rotation={rotation}
                mapImageUrl={mapImageUrl}
                robotPose={robotPose}
                mapMeta={mapMeta}
                onCanvasClick={handleCanvasClick}
                onPOIClick={handlePOIClick}
                onLineClick={handleLineClick}
                onPolygonClick={handlePolygonClick}
                onZoomChange={setZoom}
                onOffsetChange={setOffset}
                onImageLoad={(w, h) => setMapImageSize({ w, h })}
              />

              {/* Toolbar: Top (horizontal) */}
              <MapToolbarTop
                onUndo={handleUndo}
                onFullscreen={handleFullscreen}
                isFullscreen={isFullscreen}
                onChargingPile={() => handleToolChange("chargingPile")}
                onCurrentPos={() => handleToolChange("currentPos")}
              />

              {/* Toolbar: Left (vertical) */}
              <MapToolbarLeft
                activeTool={activeTool}
                onToolChange={handleToolChange}
              />

              {/* Floating Panel: Right */}
              <MapFloatingPanel
                open={floatingPanelOpen}
                onToggle={() => setFloatingPanelOpen((v) => !v)}
                robotConnected={!!connectedRobot}
                onStartMapping={handleStartMapping}
                onClearMap={handleClearMap}
                onRemoteImage={handleRemoteImage}
                onRemoteControl={handleRemoteControl}
              />

              {/* Bottom Left: Zoom, Rotate, Reset */}
              <div className="map-bottom-left">
                <button className="map-bottom-left__btn" onClick={handleZoomIn} title="Zoom In">
                  <span className="map-bottom-left__icon">+</span>
                  <span className="map-bottom-left__label">In</span>
                </button>
                <button className="map-bottom-left__btn" onClick={handleZoomOut} title="Zoom Out">
                  <span className="map-bottom-left__icon">−</span>
                  <span className="map-bottom-left__label">Out</span>
                </button>
                <div className="map-bottom-left__divider" />
                <button className="map-bottom-left__btn" onClick={handleRotateLeft} title="Rotate Left">
                  <span className="map-bottom-left__icon">↺</span>
                  <span className="map-bottom-left__label">Left</span>
                </button>
                <button className="map-bottom-left__btn" onClick={handleRotateRight} title="Rotate Right">
                  <span className="map-bottom-left__icon">↻</span>
                  <span className="map-bottom-left__label">Right</span>
                </button>
                <div className="map-bottom-left__divider" />
                <button className="map-bottom-left__btn" onClick={handleResetBearing} title="Reset">
                  <span className="map-bottom-left__icon">⊙</span>
                  <span className="map-bottom-left__label">Reset</span>
                </button>
              </div>

              {/* POI Edit Popup */}
              {editingPOI && (
                <POIEditPopup
                  poi={editingPOI}
                  onUpdate={handlePOIUpdate}
                  onDelete={handlePOIDelete}
                  onClose={() => {
                    setEditingPOI(null);
                    setSelectedPOI(null);
                  }}
                />
              )}

              {/* Line Direction Popup */}
              {lineDirectionPopup && (
                <LineDirectionPopup
                  position={lineDirectionPopup.position}
                  onSelect={handleLineDirectionSelect}
                  onCancel={() => {
                    setLineDirectionPopup(null);
                    setLineStartPOI(null);
                  }}
                />
              )}
            </div>
          </div>

          {/* Robot Connect Modal */}
          <RobotConnectModal
            open={connectModalOpen}
            onClose={() => setConnectModalOpen(false)}
            onConnect={handleRobotConnect}
          />

          {/* Mapping Setup Modal (Business/Area selection) */}
          <MappingSetupModal
            open={mappingSetupOpen}
            businesses={businesses}
            onClose={() => setMappingSetupOpen(false)}
            onConfirm={handleMappingSetupConfirm}
          />

          {/* Mapping Modal (real-time mapping UI) */}
          <MappingModal
            open={mappingModalOpen}
            businessId={mappingBusinessId}
            areaId={mappingAreaId}
            areaName={mappingAreaName}
            connectedRobot={connectedRobot}
            onClose={() => setMappingModalOpen(false)}
            onMappingComplete={handleMappingComplete}
          />

          {/* Map Sync Modal (맵을 복수 로봇에 로드) */}
          {selectedMappingId && (
            <MapSyncModal
              open={syncModalOpen}
              onClose={() => setSyncModalOpen(false)}
              mappingId={selectedMappingId}
            />
          )}
        </main>
      </div>
    </div>
    </>
  );
}
