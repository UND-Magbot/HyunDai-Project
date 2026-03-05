"use client";

import {
  useRef,
  useState,
  useEffect,
  useCallback,
  type MouseEvent,
  type WheelEvent,
} from "react";
import type { MapCanvasProps } from "@/lib/types/map";

// Helper: snap end point to orthogonal (horizontal or vertical) relative to start
function snapToOrthogonal(
  startX: number,
  startY: number,
  endX: number,
  endY: number
): { x: number; y: number } {
  const dx = Math.abs(endX - startX);
  const dy = Math.abs(endY - startY);
  // Snap to whichever axis is dominant
  if (dx >= dy) {
    return { x: endX, y: startY }; // horizontal
  } else {
    return { x: startX, y: endY }; // vertical
  }
}

export function MapCanvas({
  pois,
  lines,
  polygons,
  activeTool,
  selectedPOI,
  lineStartPOI,
  zoom,
  offset,
  rotation,
  mapImageUrl,
  robotPose,
  mapMeta,
  onCanvasClick,
  onPOIClick,
  onLineClick,
  onPolygonClick,
  onZoomChange,
  onOffsetChange,
  onImageLoad,
}: MapCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const isPanningRef = useRef(false);
  const panStartRef = useRef<{ x: number; y: number } | null>(null);
  const offsetStartRef = useRef({ x: 0, y: 0 });
  const mousePosRef = useRef<{ x: number; y: number } | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);

  // lineStartPOI 해제 시 mousePos 초기화
  useEffect(() => {
    if (!lineStartPOI) setMousePos(null);
  }, [lineStartPOI]);
  const [processedImg, setProcessedImg] = useState<{
    url: string; w: number; h: number;
  } | null>(null);

  // Load image, remove gray outer area, produce transparent PNG data URL
  useEffect(() => {
    if (!mapImageUrl) { setProcessedImg(null); return; }
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(img, 0, 0);
      const imageData = ctx.getImageData(0, 0, c.width, c.height);
      const d = imageData.data;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], g = d[i + 1], b = d[i + 2];
        // Gray pixels: R≈G≈B and in mid-gray range (100~180)
        const avg = (r + g + b) / 3;
        const spread = Math.max(Math.abs(r - avg), Math.abs(g - avg), Math.abs(b - avg));
        if (spread < 15 && avg > 100 && avg < 180) {
          d[i + 3] = 0; // make transparent
        }
      }
      ctx.putImageData(imageData, 0, 0);
      setProcessedImg({
        url: c.toDataURL("image/png"),
        w: img.naturalWidth,
        h: img.naturalHeight,
      });
      onImageLoad?.(img.naturalWidth, img.naturalHeight);
    };
    img.onerror = () => {
      console.error("[맵 이미지 로드 실패]", mapImageUrl);
      setProcessedImg(null);
    };
    img.src = mapImageUrl;
  }, [mapImageUrl]);

  const clamp = (val: number, min: number, max: number) =>
    Math.min(max, Math.max(min, val));

  const screenToCanvas = useCallback(
    (clientX: number, clientY: number) => {
      const svg = svgRef.current;
      if (!svg) return { x: 0, y: 0 };
      const rect = svg.getBoundingClientRect();
      return {
        x: (clientX - rect.left - offset.x) / zoom,
        y: (clientY - rect.top - offset.y) / zoom,
      };
    },
    [zoom, offset]
  );

  const handleWheel = (e: WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    if (e.deltaY === 0) return;

    const svg = svgRef.current;
    if (!svg) return;

    const rect = svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    const nextZoom = clamp(zoom * factor, 0.2, 6);
    const ratio = nextZoom / zoom;

    const nextOffsetX = mouseX - (mouseX - offset.x) * ratio;
    const nextOffsetY = mouseY - (mouseY - offset.y) * ratio;

    onZoomChange(nextZoom);
    onOffsetChange({ x: nextOffsetX, y: nextOffsetY });
  };

  const handleMouseDown = (e: MouseEvent<SVGSVGElement>) => {
    if (e.button === 1 || (e.button === 0 && activeTool === "select")) {
      isPanningRef.current = true;
      panStartRef.current = { x: e.clientX, y: e.clientY };
      offsetStartRef.current = { ...offset };
      e.preventDefault();
    }
  };

  const handleMouseMove = (e: MouseEvent<SVGSVGElement>) => {
    const pos = screenToCanvas(e.clientX, e.clientY);
    mousePosRef.current = pos;

    // 라인 그리기 중이면 직교 스냅된 위치로 state 갱신 (임시 라인 렌더용)
    if (lineStartPOI && (activeTool === "line" || activeTool === "curveLine")) {
      const startPoi = pois.find((p) => p.id === lineStartPOI);
      if (startPoi) {
        setMousePos(snapToOrthogonal(startPoi.x, startPoi.y, pos.x, pos.y));
      } else {
        setMousePos(pos);
      }
    }

    if (isPanningRef.current && panStartRef.current) {
      // 좌클릭(1) 또는 휠클릭(4)이 눌린 상태에서만 패닝
      if (!(e.buttons & 1) && !(e.buttons & 4)) {
        isPanningRef.current = false;
        panStartRef.current = null;
        return;
      }
      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      onOffsetChange({
        x: offsetStartRef.current.x + dx,
        y: offsetStartRef.current.y + dy,
      });
      e.preventDefault();
    }
  };

  const handleMouseUp = (e: MouseEvent<SVGSVGElement>) => {
    if (isPanningRef.current) {
      const wasDragging =
        panStartRef.current &&
        (Math.abs(e.clientX - panStartRef.current.x) > 3 ||
          Math.abs(e.clientY - panStartRef.current.y) > 3);

      isPanningRef.current = false;
      panStartRef.current = null;

      if (wasDragging) return;
    }

    if (
      activeTool === "point" ||
      activeTool === "line" ||
      activeTool === "curveLine" ||
      activeTool === "polygon"
    ) {
      const pos = screenToCanvas(e.clientX, e.clientY);
      // 라인 모드에서 시작 POI가 있으면 직교 스냅 좌표 전달
      if ((activeTool === "line" || activeTool === "curveLine") && lineStartPOI) {
        const startPoi = pois.find((p) => p.id === lineStartPOI);
        if (startPoi) {
          const snapped = snapToOrthogonal(startPoi.x, startPoi.y, pos.x, pos.y);
          onCanvasClick(snapped.x, snapped.y);
          return;
        }
      }
      onCanvasClick(pos.x, pos.y);
    }
  };

  const cursorClass = (() => {
    if (isPanningRef.current) return "map-canvas-area__svg--panning";
    switch (activeTool) {
      case "point":
        return "map-canvas-area__svg--point";
      case "line":
      case "curveLine":
        return "map-canvas-area__svg--line";
      case "del":
        return "map-canvas-area__svg--del";
      case "select":
        return "map-canvas-area__svg--pan";
      default:
        return "";
    }
  })();

  const renderArrow = (
    fromX: number,
    fromY: number,
    toX: number,
    toY: number,
    lineId: string,
    suffix: string,
    isSelected: boolean
  ) => {
    const dx = toX - fromX;
    const dy = toY - fromY;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len === 0) return null;
    const nx = dx / len;
    const ny = dy / len;
    const midX = (fromX + toX) / 2;
    const midY = (fromY + toY) / 2;
    const arrowSize = 4;
    const p1x = midX + nx * arrowSize;
    const p1y = midY + ny * arrowSize;
    const p2x = midX - nx * arrowSize * 0.4 - ny * arrowSize * 0.5;
    const p2y = midY - ny * arrowSize * 0.4 + nx * arrowSize * 0.5;
    const p3x = midX - nx * arrowSize * 0.4 + ny * arrowSize * 0.5;
    const p3y = midY - ny * arrowSize * 0.4 - nx * arrowSize * 0.5;

    return (
      <polygon
        key={`arrow-${lineId}-${suffix}`}
        points={`${p1x},${p1y} ${p2x},${p2y} ${p3x},${p3y}`}
        className={isSelected ? "map-line__arrow map-line__arrow--selected" : "map-line__arrow"}
      />
    );
  };

  return (
    <div className="map-canvas-area">
      <svg
        ref={svgRef}
        className={`map-canvas-area__svg ${cursorClass}`}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onContextMenu={(e) => e.preventDefault()}
      >
        <g transform={`translate(${offset.x}, ${offset.y}) scale(${zoom}) rotate(${rotation})`}>
          {/* Background map image (gray removed) */}
          {processedImg && (
            <image
              href={processedImg.url}
              x={-processedImg.w / 2}
              y={-processedImg.h / 2}
              width={processedImg.w}
              height={processedImg.h}
              className="map-canvas-area__bg-image"
            />
          )}

          {/* Polygons (virtual walls) */}
          {polygons.map((poly) => (
            <polygon
              key={poly.id}
              points={poly.points.map((p) => `${p.x},${p.y}`).join(" ")}
              className="map-polygon__shape"
              onClick={(e) => {
                e.stopPropagation();
                onPolygonClick(poly.id);
              }}
            />
          ))}

          {/* Lines */}
          {lines.map((line) => {
            const from = pois.find((p) => p.id === line.fromId);
            const to = pois.find((p) => p.id === line.toId);
            if (!from || !to) return null;

            const isSelected = false;

            return (
              <g
                key={line.id}
                className="map-line"
                onClick={(e) => {
                  e.stopPropagation();
                  onLineClick(line.id);
                }}
              >
                <line
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  className={
                    isSelected
                      ? "map-line__path map-line__path--selected"
                      : "map-line__path"
                  }
                />
                {/* Click target (wider invisible line) */}
                <line
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="transparent"
                  strokeWidth={12}
                />
                {/* Direction arrows */}
                {(line.direction === "forward" ||
                  line.direction === "bidirectional") &&
                  renderArrow(from.x, from.y, to.x, to.y, line.id, "fwd", isSelected)}
                {(line.direction === "backward" ||
                  line.direction === "bidirectional") &&
                  renderArrow(to.x, to.y, from.x, from.y, line.id, "bwd", isSelected)}
              </g>
            );
          })}

          {/* Orthogonal guide lines from start POI */}
          {lineStartPOI && (activeTool === "line" || activeTool === "curveLine") && (() => {
            const startPoi = pois.find((p) => p.id === lineStartPOI);
            if (!startPoi) return null;
            return (
              <g className="map-ortho-guides">
                {/* Horizontal guide */}
                <line
                  x1={-10000} y1={startPoi.y}
                  x2={10000} y2={startPoi.y}
                  className="map-ortho-guide"
                />
                {/* Vertical guide */}
                <line
                  x1={startPoi.x} y1={-10000}
                  x2={startPoi.x} y2={10000}
                  className="map-ortho-guide"
                />
              </g>
            );
          })()}

          {/* Temporary line while drawing (snapped to orthogonal) */}
          {lineStartPOI && (activeTool === "line" || activeTool === "curveLine") && mousePos && (() => {
            const startPoi = pois.find((p) => p.id === lineStartPOI);
            if (!startPoi) return null;
            return (
              <>
                <line
                  x1={startPoi.x}
                  y1={startPoi.y}
                  x2={mousePos.x}
                  y2={mousePos.y}
                  className="map-temp-line"
                />
                {/* Snap indicator at endpoint */}
                <circle
                  cx={mousePos.x}
                  cy={mousePos.y}
                  r={3}
                  className="map-snap-indicator"
                />
              </>
            );
          })()}

          {/* POI Markers */}
          {pois.map((poi) => {
            const isSelected = selectedPOI === poi.id;
            const isLineStart = lineStartPOI === poi.id;
            const circleClass = [
              "map-poi__circle",
              `map-poi__circle--${poi.type}`,
              isSelected || isLineStart ? "map-poi__circle--selected" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <g
                key={poi.id}
                className="map-poi"
                onClick={(e) => {
                  e.stopPropagation();
                  onPOIClick(poi.id);
                }}
              >
                <circle
                  cx={poi.x}
                  cy={poi.y}
                  r={3}
                  className={circleClass}
                  strokeWidth={1}
                />
                <text
                  x={poi.x}
                  y={poi.y - 6}
                  className="map-poi__label"
                >
                  {poi.name}
                </text>
              </g>
            );
          })}

          {/* Robot position indicator (red arrow) */}
          {robotPose && mapMeta && processedImg && mapMeta.grid_resolution > 0 && (() => {
            const imgW = processedImg.w;
            const imgH = processedImg.h;
            const ipx = (robotPose.pos[0] - mapMeta.grid_origin_x) / mapMeta.grid_resolution;
            const ipy = imgH - (robotPose.pos[1] - mapMeta.grid_origin_y) / mapMeta.grid_resolution;
            const cx = ipx - imgW / 2;
            const cy = ipy - imgH / 2;
            const ori = -robotPose.ori; // canvas Y is flipped


            const sz = 3;

            return (
              <g
                className="robot-indicator"
                transform={`translate(${cx}, ${cy}) rotate(${(ori * 180) / Math.PI})`}
              >
                <polygon
                  points={`${sz * 1.5},0 ${-sz * 0.8},${-sz * 0.8} ${-sz * 0.8},${sz * 0.8}`}
                  className="robot-indicator__arrow"
                />
              </g>
            );
          })()}
        </g>
      </svg>
    </div>
  );
}
