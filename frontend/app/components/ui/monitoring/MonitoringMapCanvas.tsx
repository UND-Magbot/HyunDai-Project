"use client";

import { useEffect, useRef } from "react";
import type {
  PoiMarkerData,
  WaypointMarkerData,
  RobotMarkerData,
  RouteSegment,
  VirtualWallData,
} from "@/lib/types/map-markers";
import { useCanvasLoop } from "@/lib/hooks/useCanvasLoop";
import "./MonitoringMapCanvas.css";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Props = {
  mapSrc: string;
  pois: PoiMarkerData[];
  waypoints: WaypointMarkerData[];
  routeWaypoints: WaypointMarkerData[];
  routeSegments?: RouteSegment[];
  robots: RobotMarkerData[];
  virtualWalls: VirtualWallData[];
  showMapBackground: boolean;
  showNavigationLine: boolean;
  showDirectionArrows: boolean;
  showVirtualWalls: boolean;
  showNavigationNodes: boolean;
  showPoiMarkers: boolean;
};

type View = { scale: number; offsetX: number; offsetY: number };

type MapBounds = {
  offsetX: number;
  offsetY: number;
  drawWidth: number;
  drawHeight: number;
  natW: number;
  natH: number;
};

type DrawData = Omit<Props, "mapSrc">;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function clamp(v: number, min: number, max: number) {
  return Math.min(max, Math.max(min, v));
}

function w2s(
  p: { x: number; y: number },
  v: View
) {
  return { x: p.x * v.scale + v.offsetX, y: p.y * v.scale + v.offsetY };
}

function s2w(
  p: { x: number; y: number },
  v: View
) {
  return { x: (p.x - v.offsetX) / v.scale, y: (p.y - v.offsetY) / v.scale };
}

/** Map image pixel coordinate → canvas screen coordinate */
function mapToCanvas(
  mapX: number,
  mapY: number,
  bounds: MapBounds
): { cx: number; cy: number } {
  return {
    cx: bounds.offsetX + (mapX / bounds.natW) * bounds.drawWidth,
    cy: bounds.offsetY + (mapY / bounds.natH) * bounds.drawHeight,
  };
}

function isLoopRoute(points: WaypointMarkerData[]): boolean {
  if (points.length < 2) return false;
  const first = points[0].position;
  const last = points[points.length - 1].position;
  return Math.hypot(first.x - last.x, first.y - last.y) < 5;
}

function resetShadow(ctx: CanvasRenderingContext2D) {
  ctx.shadowColor = "transparent";
  ctx.shadowBlur = 0;
  ctx.shadowOffsetX = 0;
  ctx.shadowOffsetY = 0;
}

/** 이미지 가장자리에서 연결된 배경색 픽셀을 투명 처리 (edge flood-fill) */
function removeOutsideBackground(
  img: HTMLImageElement,
  tolerance = 30
): HTMLCanvasElement {
  const w = img.naturalWidth;
  const h = img.naturalHeight;

  const offscreen = document.createElement("canvas");
  offscreen.width = w;
  offscreen.height = h;
  const octx = offscreen.getContext("2d")!;
  octx.drawImage(img, 0, 0);

  const imageData = octx.getImageData(0, 0, w, h);
  const { data } = imageData;

  // 4개 꼭짓점 픽셀 평균으로 배경색 결정
  const corners = [
    0,
    (w - 1) * 4,
    (h - 1) * w * 4,
    ((h - 1) * w + (w - 1)) * 4,
  ];
  let bgR = 0;
  let bgG = 0;
  let bgB = 0;
  for (const idx of corners) {
    bgR += data[idx];
    bgG += data[idx + 1];
    bgB += data[idx + 2];
  }
  bgR = Math.round(bgR / 4);
  bgG = Math.round(bgG / 4);
  bgB = Math.round(bgB / 4);

  const tolSq = tolerance * tolerance;
  const matches = (i: number) => {
    const dr = data[i] - bgR;
    const dg = data[i + 1] - bgG;
    const db = data[i + 2] - bgB;
    return dr * dr + dg * dg + db * db < tolSq;
  };

  // BFS flood fill — 가장자리에서 시작
  const visited = new Uint8Array(w * h);
  const queue: number[] = [];

  for (let x = 0; x < w; x++) {
    if (matches(x * 4)) { queue.push(x); visited[x] = 1; }
    const bi = (h - 1) * w + x;
    if (matches(bi * 4)) { queue.push(bi); visited[bi] = 1; }
  }
  for (let y = 1; y < h - 1; y++) {
    const li = y * w;
    if (matches(li * 4)) { queue.push(li); visited[li] = 1; }
    const ri = y * w + (w - 1);
    if (matches(ri * 4)) { queue.push(ri); visited[ri] = 1; }
  }

  let head = 0;
  while (head < queue.length) {
    const idx = queue[head++];
    const px = idx % w;
    const py = (idx - px) / w;

    const neighbors = [
      py > 0 ? idx - w : -1,
      py < h - 1 ? idx + w : -1,
      px > 0 ? idx - 1 : -1,
      px < w - 1 ? idx + 1 : -1,
    ];

    for (const ni of neighbors) {
      if (ni < 0 || visited[ni]) continue;
      if (matches(ni * 4)) {
        visited[ni] = 1;
        queue.push(ni);
      }
    }
  }

  for (let i = 0; i < visited.length; i++) {
    if (visited[i]) {
      data[i * 4 + 3] = 0;
    }
  }

  octx.putImageData(imageData, 0, 0);
  return offscreen;
}

/* ------------------------------------------------------------------ */
/*  Draw: Map Background                                               */
/* ------------------------------------------------------------------ */

function computeMapBounds(
  img: HTMLImageElement,
  logicalW: number,
  logicalH: number
): MapBounds {
  const natW = img.naturalWidth;
  const natH = img.naturalHeight;
  const imgAr = natW / natH;
  const canvasAr = logicalW / logicalH;

  let drawWidth: number;
  let drawHeight: number;
  if (imgAr > canvasAr) {
    drawWidth = logicalW;
    drawHeight = logicalW / imgAr;
  } else {
    drawHeight = logicalH;
    drawWidth = logicalH * imgAr;
  }

  return {
    offsetX: (logicalW - drawWidth) / 2,
    offsetY: (logicalH - drawHeight) / 2,
    drawWidth,
    drawHeight,
    natW,
    natH,
  };
}

function drawMapImage(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  bounds: MapBounds
) {
  ctx.drawImage(
    img,
    bounds.offsetX,
    bounds.offsetY,
    bounds.drawWidth,
    bounds.drawHeight
  );
}

/* ------------------------------------------------------------------ */
/*  Draw: Routes                                                       */
/* ------------------------------------------------------------------ */

function drawPolylineRoute(
  ctx: CanvasRenderingContext2D,
  points: WaypointMarkerData[],
  bounds: MapBounds,
  strokeStyle: string,
  lineWidth: number,
  shadowColor?: string,
  shadowBlur?: number
) {
  if (points.length < 2) return;

  const scale = bounds.drawWidth / bounds.natW;

  ctx.beginPath();
  const first = mapToCanvas(points[0].position.x, points[0].position.y, bounds);
  ctx.moveTo(first.cx, first.cy);
  for (let i = 1; i < points.length; i++) {
    const p = mapToCanvas(points[i].position.x, points[i].position.y, bounds);
    ctx.lineTo(p.cx, p.cy);
  }

  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth * scale;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (shadowColor && shadowBlur) {
    ctx.shadowColor = shadowColor;
    ctx.shadowBlur = shadowBlur;
  }
  ctx.stroke();
  resetShadow(ctx);
}

function drawRouteSegment(
  ctx: CanvasRenderingContext2D,
  seg: RouteSegment,
  bounds: MapBounds,
  strokeStyle: string,
  lineWidth: number,
  shadowColor?: string,
  shadowBlur?: number
) {
  const scale = bounds.drawWidth / bounds.natW;
  const from = mapToCanvas(seg.from.x, seg.from.y, bounds);
  const to = mapToCanvas(seg.to.x, seg.to.y, bounds);

  ctx.beginPath();
  ctx.moveTo(from.cx, from.cy);

  if (seg.lineType === "curve" && seg.controlPoints && seg.controlPoints.length > 0) {
    if (seg.controlPoints.length === 1) {
      const cp = mapToCanvas(seg.controlPoints[0].x, seg.controlPoints[0].y, bounds);
      ctx.quadraticCurveTo(cp.cx, cp.cy, to.cx, to.cy);
    } else {
      const cp1 = mapToCanvas(seg.controlPoints[0].x, seg.controlPoints[0].y, bounds);
      const cp2 = mapToCanvas(seg.controlPoints[1].x, seg.controlPoints[1].y, bounds);
      ctx.bezierCurveTo(cp1.cx, cp1.cy, cp2.cx, cp2.cy, to.cx, to.cy);
    }
  } else {
    ctx.lineTo(to.cx, to.cy);
  }

  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth * scale;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (shadowColor && shadowBlur) {
    ctx.shadowColor = shadowColor;
    ctx.shadowBlur = shadowBlur;
  }
  ctx.stroke();
  resetShadow(ctx);
}

function drawRoutes(
  ctx: CanvasRenderingContext2D,
  data: DrawData,
  bounds: MapBounds
) {
  const segments = data.routeSegments ?? [];

  if (segments.length > 0) {
    // RouteSegment 기반 렌더링 (direction, curve 지원)
    for (const seg of segments) {
      drawRouteSegment(
        ctx, seg, bounds,
        "rgba(25, 188, 126, 0.35)", 14,
        "rgba(23, 160, 112, 0.2)", 2
      );
    }
  } else {
    // 기존 fallback: routeWaypoints 기반
    const routeSource = data.routeWaypoints.length > 0 ? data.routeWaypoints : data.waypoints;
    const staticWps = routeSource.filter((wp) => !wp.id.startsWith("alloc-"));
    drawPolylineRoute(ctx, staticWps, bounds, "rgba(25, 188, 126, 0.35)", 14, "rgba(23, 160, 112, 0.2)", 2);
  }
}

/* ------------------------------------------------------------------ */
/*  Draw: Direction Arrows                                             */
/* ------------------------------------------------------------------ */

function drawArrow(
  ctx: CanvasRenderingContext2D,
  mx: number,
  my: number,
  angleRad: number,
  color: string,
  scale: number
) {
  ctx.save();
  ctx.translate(mx, my);
  ctx.rotate(angleRad);

  const s = scale;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2 * s;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  // Stem: -5 to 3
  ctx.beginPath();
  ctx.moveTo(-5 * s, 0);
  ctx.lineTo(3 * s, 0);
  ctx.stroke();

  // Arrowhead: 3,-4 → 8,0 → 3,4
  ctx.beginPath();
  ctx.moveTo(3 * s, -4 * s);
  ctx.lineTo(8 * s, 0);
  ctx.lineTo(3 * s, 4 * s);
  ctx.stroke();

  ctx.restore();
}

function drawSegmentArrows(
  ctx: CanvasRenderingContext2D,
  points: WaypointMarkerData[],
  color: string,
  bounds: MapBounds
) {
  if (points.length < 2) return;

  const scale = bounds.drawWidth / bounds.natW;
  const bidirectional = isLoopRoute(points);

  for (let i = 0; i < points.length - 1; i++) {
    const a = mapToCanvas(points[i].position.x, points[i].position.y, bounds);
    const b = mapToCanvas(points[i + 1].position.x, points[i + 1].position.y, bounds);

    const mx = (a.cx + b.cx) / 2;
    const my = (a.cy + b.cy) / 2;
    const angleRad = Math.atan2(b.cy - a.cy, b.cx - a.cx);

    if (bidirectional) {
      const offsetPx = 7 * scale;
      const perpX = -Math.sin(angleRad) * offsetPx;
      const perpY = Math.cos(angleRad) * offsetPx;

      drawArrow(ctx, mx + perpX, my + perpY, angleRad, color, scale);
      drawArrow(ctx, mx - perpX, my - perpY, angleRad + Math.PI, color, scale);
    } else {
      drawArrow(ctx, mx, my, angleRad, color, scale);
    }
  }
}

function drawSegmentDirectionArrow(
  ctx: CanvasRenderingContext2D,
  seg: RouteSegment,
  color: string,
  bounds: MapBounds
) {
  const scale = bounds.drawWidth / bounds.natW;
  const from = mapToCanvas(seg.from.x, seg.from.y, bounds);
  const to = mapToCanvas(seg.to.x, seg.to.y, bounds);

  const mx = (from.cx + to.cx) / 2;
  const my = (from.cy + to.cy) / 2;
  const angleRad = Math.atan2(to.cy - from.cy, to.cx - from.cx);

  if (seg.direction === "bidirectional") {
    const offsetPx = 7 * scale;
    const perpX = -Math.sin(angleRad) * offsetPx;
    const perpY = Math.cos(angleRad) * offsetPx;
    drawArrow(ctx, mx + perpX, my + perpY, angleRad, color, scale);
    drawArrow(ctx, mx - perpX, my - perpY, angleRad + Math.PI, color, scale);
  } else if (seg.direction === "backward") {
    drawArrow(ctx, mx, my, angleRad + Math.PI, color, scale);
  } else {
    drawArrow(ctx, mx, my, angleRad, color, scale);
  }
}

function drawDirectionArrows(
  ctx: CanvasRenderingContext2D,
  data: DrawData,
  bounds: MapBounds
) {
  const segments = data.routeSegments ?? [];

  if (segments.length > 0) {
    // RouteSegment 기반: per-segment direction 지원
    for (const seg of segments) {
      drawSegmentDirectionArrow(ctx, seg, "rgba(25, 188, 126, 0.9)", bounds);
    }
  } else {
    // 기존 fallback
    const routeSource = data.routeWaypoints.length > 0 ? data.routeWaypoints : data.waypoints;
    const staticWps = routeSource.filter((wp) => !wp.id.startsWith("alloc-"));
    drawSegmentArrows(ctx, staticWps, "rgba(25, 188, 126, 0.9)", bounds);
  }
}

/* ------------------------------------------------------------------ */
/*  Draw: Virtual Walls                                                */
/* ------------------------------------------------------------------ */

function drawVirtualWalls(
  ctx: CanvasRenderingContext2D,
  walls: VirtualWallData[],
  bounds: MapBounds
) {
  const scale = bounds.drawWidth / bounds.natW;

  for (const wall of walls) {
    const start = mapToCanvas(wall.start.x, wall.start.y, bounds);
    const end = mapToCanvas(wall.end.x, wall.end.y, bounds);

    ctx.beginPath();
    ctx.moveTo(start.cx, start.cy);
    ctx.lineTo(end.cx, end.cy);
    ctx.strokeStyle = "rgba(255, 80, 80, 0.85)";
    ctx.lineWidth = 8 * scale;
    ctx.setLineDash([16 * scale, 8 * scale]);
    ctx.lineCap = "round";
    ctx.shadowColor = "rgba(255, 50, 50, 0.5)";
    ctx.shadowBlur = 4;
    ctx.stroke();
    ctx.setLineDash([]);
    resetShadow(ctx);
  }
}

/* ------------------------------------------------------------------ */
/*  Draw: Waypoint Markers                                             */
/* ------------------------------------------------------------------ */

function drawWaypoints(
  ctx: CanvasRenderingContext2D,
  waypoints: WaypointMarkerData[],
  bounds: MapBounds,
  viewScale: number
) {
  const counterScale = 1 / viewScale;

  for (const wp of waypoints) {
    const p = mapToCanvas(wp.position.x, wp.position.y, bounds);
    const isAllocated = wp.id.startsWith("alloc-");

    const radius = isAllocated ? 4.5 * counterScale : 6 * counterScale;

    ctx.beginPath();
    ctx.arc(p.cx, p.cy, radius, 0, Math.PI * 2);

    if (isAllocated) {
      ctx.fillStyle = "rgba(170, 237, 255, 0.88)";
      ctx.shadowColor = "rgba(170, 237, 255, 0.65)";
      ctx.shadowBlur = 5 * counterScale;
    } else {
      ctx.fillStyle = "rgba(142, 221, 255, 0.9)";
      ctx.shadowColor = "rgba(138, 216, 255, 0.8)";
      ctx.shadowBlur = 8 * counterScale;
    }

    ctx.fill();
    resetShadow(ctx);
  }
}

/* ------------------------------------------------------------------ */
/*  Draw: Label Helper                                                 */
/* ------------------------------------------------------------------ */

function drawMarkerLabel(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  color: string,
  counterScale: number,
  fontWeight: number = 600
) {
  const fontSize = Math.max(9, 11 * counterScale);
  ctx.font = `${fontWeight} ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = color;
  ctx.shadowColor = "rgba(0, 0, 0, 0.85)";
  ctx.shadowBlur = 5;
  ctx.shadowOffsetY = 1;
  ctx.fillText(text, x, y);
  resetShadow(ctx);
}

/* ------------------------------------------------------------------ */
/*  Draw: POI Markers                                                  */
/* ------------------------------------------------------------------ */

function drawPoiCircle(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  label: string,
  counterScale: number
) {
  const outerR = 9 * counterScale;

  // Outer circle with white border
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(35, 45, 55, 0.86)";
  ctx.fill();
  ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
  ctx.lineWidth = 2 * counterScale;
  ctx.stroke();

  // Inner red dot
  ctx.beginPath();
  ctx.arc(cx, cy, 3 * counterScale, 0, Math.PI * 2);
  ctx.fillStyle = "#ff2b2b";
  ctx.shadowColor = "rgba(255, 74, 74, 0.65)";
  ctx.shadowBlur = 5 * counterScale;
  ctx.fill();
  resetShadow(ctx);

  // Label
  drawMarkerLabel(ctx, cx, cy + outerR + 4 * counterScale, label, "#ffffff", counterScale, 700);
}

function drawPoiTriangle(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  label: string,
  counterScale: number
) {
  const halfW = 10 * counterScale;
  const h = 16 * counterScale;

  ctx.beginPath();
  ctx.moveTo(cx, cy - h * 0.5);
  ctx.lineTo(cx - halfW, cy + h * 0.5);
  ctx.lineTo(cx + halfW, cy + h * 0.5);
  ctx.closePath();
  ctx.fillStyle = "#1f6fff";
  ctx.shadowColor = "rgba(8, 35, 108, 0.45)";
  ctx.shadowOffsetY = 1;
  ctx.shadowBlur = 3;
  ctx.fill();
  resetShadow(ctx);

  // White inner dot
  ctx.beginPath();
  ctx.arc(cx, cy + 1 * counterScale, 3 * counterScale, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
  ctx.fill();

  // Label
  drawMarkerLabel(ctx, cx, cy + h * 0.5 + 4 * counterScale, label, "#ffffff", counterScale, 700);
}

function drawPoiAngleIndicator(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  angleDeg: number,
  counterScale: number
) {
  const angleRad = (angleDeg * Math.PI) / 180;
  const len = 18 * counterScale;
  const endX = cx + Math.cos(angleRad) * len;
  const endY = cy - Math.sin(angleRad) * len;

  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(endX, endY);
  ctx.strokeStyle = "rgba(255, 200, 60, 0.9)";
  ctx.lineWidth = 2 * counterScale;
  ctx.lineCap = "round";
  ctx.stroke();

  // arrowhead
  const headLen = 6 * counterScale;
  const a1 = angleRad + Math.PI + Math.PI / 6;
  const a2 = angleRad + Math.PI - Math.PI / 6;
  ctx.beginPath();
  ctx.moveTo(endX + Math.cos(a1) * headLen, endY - Math.sin(a1) * headLen);
  ctx.lineTo(endX, endY);
  ctx.lineTo(endX + Math.cos(a2) * headLen, endY - Math.sin(a2) * headLen);
  ctx.strokeStyle = "rgba(255, 200, 60, 0.9)";
  ctx.lineWidth = 2 * counterScale;
  ctx.stroke();
}

function drawDockingRadius(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radiusMeters: number,
  bounds: MapBounds,
  counterScale: number
) {
  // dockingRadius는 미터 단위 → 픽셀 스케일 적용
  const pixelRadius = (radiusMeters / bounds.natW) * bounds.drawWidth;

  ctx.beginPath();
  ctx.arc(cx, cy, pixelRadius, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(100, 200, 255, 0.5)";
  ctx.lineWidth = 1.5 * counterScale;
  ctx.setLineDash([6 * counterScale, 4 * counterScale]);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.arc(cx, cy, pixelRadius, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(100, 200, 255, 0.08)";
  ctx.fill();
}

function drawPois(
  ctx: CanvasRenderingContext2D,
  pois: PoiMarkerData[],
  bounds: MapBounds,
  viewScale: number
) {
  const counterScale = 1 / viewScale;

  for (const poi of pois) {
    const p = mapToCanvas(poi.position.x, poi.position.y, bounds);
    const isCharging = poi.type === "charging";
    const renderKind = poi.renderKind ?? (isCharging ? "circle" : "triangle");

    // dockingRadius 원 (POI 뒤에 먼저 그리기)
    if (poi.dockingRadius != null && poi.dockingRadius > 0) {
      drawDockingRadius(ctx, p.cx, p.cy, poi.dockingRadius, bounds, counterScale);
    }

    if (renderKind === "circle") {
      drawPoiCircle(ctx, p.cx, p.cy, poi.label, counterScale);
    } else {
      drawPoiTriangle(ctx, p.cx, p.cy, poi.label, counterScale);
    }

    // angle 방향 표시
    if (poi.angle != null) {
      drawPoiAngleIndicator(ctx, p.cx, p.cy, poi.angle, counterScale);
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Draw: Robot Markers                                                */
/* ------------------------------------------------------------------ */

function drawRobot(
  ctx: CanvasRenderingContext2D,
  robot: RobotMarkerData,
  canvasX: number,
  canvasY: number,
  counterScale: number
) {
  const { yaw, robotName, status, collisionState } = robot;

  // CSS rotation formula: -(yaw * 180/PI) + 90
  const rotationDeg = -(yaw * 180) / Math.PI + 90;
  const rotationRad = (rotationDeg * Math.PI) / 180;

  ctx.save();
  ctx.translate(canvasX, canvasY);

  // --- Rotated body ---
  ctx.save();
  ctx.rotate(rotationRad);

  const triHalfW = 11 * counterScale;
  const triH = 18 * counterScale;

  // Triangle color
  let triColor = "#30d99a";
  if (collisionState === "collision") {
    triColor = "#ff6363";
  } else if (collisionState === "near_miss") {
    triColor = "#ffba24";
  } else if (status === "warning") {
    triColor = "#ffba24";
  } else if (status === "error") {
    triColor = "#ff5757";
  }

  // Triangle body (pointing up in local space)
  ctx.beginPath();
  ctx.moveTo(0, -triH * 0.5);
  ctx.lineTo(-triHalfW, triH * 0.5);
  ctx.lineTo(triHalfW, triH * 0.5);
  ctx.closePath();
  ctx.fillStyle = triColor;
  ctx.shadowColor = "rgba(0, 0, 0, 0.45)";
  ctx.shadowOffsetY = 2;
  ctx.shadowBlur = 3;
  ctx.fill();
  resetShadow(ctx);

  // Beacon ring
  const ringX = 7 * counterScale;
  const ringY = -6 * counterScale;
  const ringOuterR = 6 * counterScale;
  const ringBorderW = 3 * counterScale;

  let ringBorderColor = "#3d62ff";
  let ringGlow = "rgba(61, 98, 255, 0.55)";
  if (collisionState === "near_miss") {
    ringBorderColor = "#ffbf2d";
    ringGlow = "rgba(255, 191, 45, 0.7)";
  } else if (collisionState === "collision") {
    ringBorderColor = "#ff4343";
    ringGlow = "rgba(255, 67, 67, 0.9)";
  }

  ctx.beginPath();
  ctx.arc(ringX, ringY, ringOuterR, 0, Math.PI * 2);
  ctx.fillStyle = "#0a1640";
  ctx.fill();
  ctx.strokeStyle = ringBorderColor;
  ctx.lineWidth = ringBorderW;
  ctx.shadowColor = ringGlow;
  ctx.shadowBlur = 6 * counterScale;
  ctx.stroke();
  resetShadow(ctx);

  ctx.restore(); // undo rotation

  // --- Label (not rotated) ---
  drawMarkerLabel(ctx, 0, 14 * counterScale, robotName, "#42d8ff", counterScale, 700);

  ctx.restore(); // undo translation
}

function drawRobots(
  ctx: CanvasRenderingContext2D,
  robots: RobotMarkerData[],
  bounds: MapBounds,
  viewScale: number
) {
  const counterScale = 1 / viewScale;

  for (const robot of robots) {
    const p = mapToCanvas(robot.position.x, robot.position.y, bounds);
    drawRobot(ctx, robot, p.cx, p.cy, counterScale);
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function MonitoringMapCanvas({
  mapSrc,
  pois,
  waypoints,
  routeWaypoints,
  robots,
  virtualWalls,
  showMapBackground,
  showNavigationLine,
  showDirectionArrows,
  showVirtualWalls: showVirtualWallsFlag,
  showNavigationNodes,
  showPoiMarkers,
}: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewRef = useRef<View>({ scale: 1, offsetX: 0, offsetY: 0 });
  const processedRef = useRef<HTMLCanvasElement | null>(null);
  const imgReadyRef = useRef(false);
  const mapSizeRef = useRef<{ w: number; h: number }>({ w: 0, h: 0 });
  const dragRef = useRef({ dragging: false, lastX: 0, lastY: 0 });

  // Store latest props in a ref for the rAF draw callback
  const dataRef = useRef<DrawData>({
    pois,
    waypoints,
    routeWaypoints,
    robots,
    virtualWalls,
    showMapBackground,
    showNavigationLine,
    showDirectionArrows,
    showVirtualWalls: showVirtualWallsFlag,
    showNavigationNodes,
    showPoiMarkers,
  });
  dataRef.current = {
    pois,
    waypoints,
    routeWaypoints,
    robots,
    virtualWalls,
    showMapBackground,
    showNavigationLine,
    showDirectionArrows,
    showVirtualWalls: showVirtualWallsFlag,
    showNavigationNodes,
    showPoiMarkers,
  };

  // --- Image loading ---
  useEffect(() => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.decoding = "async";
    img.src = mapSrc;

    img.onload = () => {
      processedRef.current = removeOutsideBackground(img);
      imgReadyRef.current = true;
      mapSizeRef.current = { w: img.naturalWidth, h: img.naturalHeight };
      fitToView();
    };

    img.onerror = () => {
      processedRef.current = null;
      imgReadyRef.current = false;
    };

    return () => {
      processedRef.current = null;
      imgReadyRef.current = false;
    };
  }, [mapSrc]);

  // --- Resize observer ---
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;

    const ro = new ResizeObserver(() => {
      resizeCanvas();
      fitToView();
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  function resizeCanvas() {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = wrap.getBoundingClientRect();

    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
  }

  function fitToView(padding = 24) {
    const wrap = wrapRef.current;
    if (!wrap) return;

    const rect = wrap.getBoundingClientRect();
    const cw = rect.width;
    const ch = rect.height;

    const { w, h } = mapSizeRef.current;
    if (w <= 0 || h <= 0 || cw <= 0 || ch <= 0) return;

    const scale = Math.min((cw - padding * 2) / w, (ch - padding * 2) / h);
    const offsetX = (cw - w * scale) / 2;
    const offsetY = (ch - h * scale) / 2;

    viewRef.current = { scale: clamp(scale, 0.1, 10), offsetX, offsetY };
  }

  // --- Pointer events ---
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const getOffset = (e: MouseEvent | WheelEvent) => {
      const r = wrap.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      const p = getOffset(e);
      dragRef.current = { dragging: true, lastX: p.x, lastY: p.y };
      wrap.classList.add("is-panning");
    };

    const onMouseUp = () => {
      dragRef.current.dragging = false;
      wrap.classList.remove("is-panning");
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      const p = getOffset(e);
      const dx = p.x - dragRef.current.lastX;
      const dy = p.y - dragRef.current.lastY;

      const v = viewRef.current;
      viewRef.current = { ...v, offsetX: v.offsetX + dx, offsetY: v.offsetY + dy };

      dragRef.current.lastX = p.x;
      dragRef.current.lastY = p.y;
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();

      const mouse = getOffset(e);
      const v0 = viewRef.current;
      const before = s2w(mouse, v0);

      const zoomIntensity = 0.0015;
      const nextScale = v0.scale * Math.exp(-e.deltaY * zoomIntensity);
      const scale = clamp(nextScale, 0.2, 8);

      const v1: View = { ...v0, scale };
      const after = w2s(before, v1);

      v1.offsetX += mouse.x - after.x;
      v1.offsetY += mouse.y - after.y;

      viewRef.current = v1;

      if (scale > 1) {
        wrap.classList.add("is-pannable");
      } else {
        wrap.classList.remove("is-pannable");
      }
    };

    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      canvas.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, []);

  // --- Draw loop ---
  useCanvasLoop(canvasRef, (ctx, canvas) => {
    const wrap = wrapRef.current;
    if (!wrap) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = wrap.getBoundingClientRect();
    const logicalW = rect.width;
    const logicalH = rect.height;

    // Resize if needed
    const expectedW = Math.max(1, Math.floor(logicalW * dpr));
    const expectedH = Math.max(1, Math.floor(logicalH * dpr));
    if (canvas.width !== expectedW || canvas.height !== expectedH) {
      canvas.width = expectedW;
      canvas.height = expectedH;
      canvas.style.width = `${logicalW}px`;
      canvas.style.height = `${logicalH}px`;
    }

    // Reset transform & clear
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, logicalW, logicalH);

    // Background fill
    ctx.fillStyle = "#A0A0A0";
    ctx.fillRect(0, 0, logicalW, logicalH);

    const v = viewRef.current;
    const data = dataRef.current;

    // Apply view transform
    ctx.save();
    ctx.translate(v.offsetX, v.offsetY);
    ctx.scale(v.scale, v.scale);

    // Draw map image
    if (imgReadyRef.current && processedRef.current) {
      const img = processedRef.current;

      if (data.showMapBackground) {
        ctx.drawImage(img, 0, 0);
      }

      // Compute bounds in world coordinates (image pixel space)
      const bounds: MapBounds = {
        offsetX: 0,
        offsetY: 0,
        drawWidth: img.width,
        drawHeight: img.height,
        natW: img.width,
        natH: img.height,
      };

      // Routes
      if (data.showNavigationLine) {
        drawRoutes(ctx, data, bounds);
      }

      // Direction arrows
      if (data.showDirectionArrows && data.showNavigationLine) {
        drawDirectionArrows(ctx, data, bounds);
      }

      // Virtual walls
      if (data.showVirtualWalls) {
        drawVirtualWalls(ctx, data.virtualWalls, bounds);
      }

      // Waypoint markers
      if (data.showNavigationNodes) {
        drawWaypoints(ctx, data.waypoints, bounds, v.scale);
      }

      // POI markers
      if (data.showPoiMarkers) {
        drawPois(ctx, data.pois, bounds, v.scale);
      }

      // Robot markers (always shown)
      drawRobots(ctx, data.robots, bounds, v.scale);
    }

    ctx.restore();
  });

  return (
    <div ref={wrapRef} className="monitoring-canvas-wrap">
      <canvas ref={canvasRef} />
    </div>
  );
}
