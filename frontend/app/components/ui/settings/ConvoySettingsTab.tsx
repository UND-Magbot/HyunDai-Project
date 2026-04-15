"use client";

import { useState, useEffect, useCallback } from "react";
import { useAlert } from "@/lib/context/AlertContext";
import { apiFetch } from "@/lib/api";
import "./ConvoySettingsTab.css";

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTES = ["00", "10", "20", "30", "40", "50"];

const BATTERY_STEPS = Array.from({ length: 24 }, (_, i) => (i + 1) * 5); // 5~120분

export function ConvoySettingsTab() {
  const { showInfo } = useAlert();
  const [hour, setHour] = useState("08");
  const [minute, setMinute] = useState("00");
  const [batteryInterval, setBatteryInterval] = useState(5);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<{ reset_time?: string; battery_check_interval?: number }>("/api/convoy/config")
      .then((res) => {
        if (res.reset_time) {
          const [h, m] = res.reset_time.split(":");
          if (h) setHour(h);
          if (m) setMinute(m);
        }
        if (res.battery_check_interval) setBatteryInterval(res.battery_check_interval);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = useCallback(async () => {
    const resetTime = `${hour}:${minute}`;
    setSaving(true);
    try {
      await apiFetch("/api/convoy/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset_time: resetTime, battery_check_interval: batteryInterval }),
      });
      showInfo("알림", `설정이 저장되었습니다.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "저장에 실패했습니다.";
      showInfo("알림", msg);
    } finally {
      setSaving(false);
    }
  }, [hour, minute, batteryInterval, showInfo]);

  if (loading) return <div className="convoy-settings__loading">불러오는 중...</div>;

  return (
    <section className="settings-section">
      <h2 className="convoy-settings__title">작업 설정</h2>

      <div className="convoy-settings__field">
        <label className="convoy-settings__label">작업 리셋 시각</label>
        <p className="convoy-settings__desc">
          설정된 시각 이후 시작 시 저장 위치가 초기화됩니다.
        </p>
        <div className="convoy-settings__row">
          <select
            className="convoy-settings__select"
            value={hour}
            onChange={(e) => setHour(e.target.value)}
          >
            {HOURS.map((h) => (
              <option key={h} value={h}>{h}시</option>
            ))}
          </select>
          <span className="convoy-settings__colon">:</span>
          <select
            className="convoy-settings__select"
            value={minute}
            onChange={(e) => setMinute(e.target.value)}
          >
            {MINUTES.map((m) => (
              <option key={m} value={m}>{m}분</option>
            ))}
          </select>
        </div>
      </div>

      <div className="convoy-settings__field">
        <label className="convoy-settings__label">배터리 체크 주기</label>
        <p className="convoy-settings__desc">
          설정된 주기마다 배터리를 확인하여 부족 시 교체합니다.
        </p>
        <div className="convoy-settings__slider-wrap">
          <input
            type="range"
            className="convoy-settings__slider"
            min={1}
            max={24}
            step={1}
            value={BATTERY_STEPS.indexOf(batteryInterval) + 1}
            onChange={(e) => setBatteryInterval(BATTERY_STEPS[Number(e.target.value) - 1])}
          />
          <span className="convoy-settings__slider-value">
            {batteryInterval >= 60
              ? `${Math.floor(batteryInterval / 60)}시간${batteryInterval % 60 ? ` ${batteryInterval % 60}분` : ""}`
              : `${batteryInterval}분`}
          </span>
        </div>
      </div>

      <div className="convoy-settings__row">
        <button
          className="convoy-settings__btn"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "저장 중..." : "저장"}
        </button>
      </div>
    </section>
  );
}
