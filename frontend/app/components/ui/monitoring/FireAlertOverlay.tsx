"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./FireAlertOverlay.css";

type Props = {
  safePoiName?: string;
};

export function FireAlertOverlay({ safePoiName }: Props) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return createPortal(
    <div className="fire-overlay">
      {/* 배경 깜빡임 */}
      <div className="fire-overlay__bg" />

      <div className="fire-overlay__content">
        {/* 불꽃 SVG */}
        <div className="fire-overlay__icon">
          <svg viewBox="0 0 64 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M32 4C32 4 20 20 20 34C20 41.2 25.4 47 32 47C38.6 47 44 41.2 44 34C44 20 32 4 32 4Z"
              fill="#FF6B00"
              className="fire-overlay__flame fire-overlay__flame--outer"
            />
            <path
              d="M32 16C32 16 24 28 24 37C24 42.5 27.6 47 32 47C36.4 47 40 42.5 40 37C40 28 32 16 32 16Z"
              fill="#FFA500"
              className="fire-overlay__flame fire-overlay__flame--mid"
            />
            <path
              d="M32 28C32 28 28 34 28 39C28 42.3 29.8 47 32 47C34.2 47 36 42.3 36 39C36 34 32 28 32 28Z"
              fill="#FFD700"
              className="fire-overlay__flame fire-overlay__flame--inner"
            />
            {/* 연기 */}
            <ellipse cx="32" cy="52" rx="14" ry="5" fill="rgba(80,80,80,0.5)" className="fire-overlay__smoke" />
          </svg>
        </div>

        {/* 경고 텍스트 */}
        <div className="fire-overlay__title">
          <span className="fire-overlay__icon-text">🚨</span>
          화&nbsp;&nbsp;재&nbsp;&nbsp;발&nbsp;&nbsp;생
          <span className="fire-overlay__icon-text">🚨</span>
        </div>

        <div className="fire-overlay__subtitle">
          모든 로봇이 안전 지점으로 이동 중입니다
        </div>

        {safePoiName && (
          <div className="fire-overlay__poi">
            대피 지점 :&nbsp;<strong>{safePoiName}</strong>
          </div>
        )}

        <div className="fire-overlay__warning">
          ⚠ 작업자는 즉시 대피하십시오
        </div>
      </div>
    </div>,
    document.body
  );
}
