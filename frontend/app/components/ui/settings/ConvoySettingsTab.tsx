"use client";

import { useState, useEffect, useCallback } from "react";
import { useAlert } from "@/lib/context/AlertContext";
import { apiFetch } from "@/lib/api";
import { ConfirmModal } from "../robots/ConfirmModal";
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

  // ── 강제 초기화 (이상 상황 전용) ──
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [resetting, setResetting] = useState(false);

  // ── 로봇별 저장 위치만 삭제 (다음 시작을 새로 시작하게) ──
  const [clearSavedModalOpen, setClearSavedModalOpen] = useState(false);
  const [clearingSaved, setClearingSaved] = useState(false);

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

  const handleConfirmReset = useCallback(async () => {
    setResetModalOpen(false);
    setResetting(true);
    try {
      const res = await apiFetch<{ message?: string }>("/api/convoy/reset", { method: "POST" });
      showInfo("알림", res?.message ?? "작업 상태가 강제 초기화되었습니다.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "강제 초기화에 실패했습니다.";
      showInfo("알림", msg);
    } finally {
      setResetting(false);
    }
  }, [showInfo]);

  const handleConfirmClearSaved = useCallback(async () => {
    setClearSavedModalOpen(false);
    setClearingSaved(true);
    try {
      const res = await apiFetch<{ message?: string }>("/api/convoy/clear-saved-state", { method: "POST" });
      showInfo("알림", res?.message ?? "저장된 위치가 삭제되었습니다.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "저장 위치 삭제에 실패했습니다.";
      showInfo("알림", msg);
    } finally {
      setClearingSaved(false);
    }
  }, [showInfo]);

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

      {/* ── 비상 도구 ── */}
      <div className="convoy-settings__danger-zone">
        <h3 className="convoy-settings__label" style={{ color: "#c0392b", marginTop: 32 }}>
          비상 도구
        </h3>

        {/* 1) 가벼운 리셋 — 저장된 위치만 삭제 */}
        <div className="convoy-settings__field">
          <label className="convoy-settings__label">로봇별 저장 위치 삭제</label>
          <p className="convoy-settings__desc">
            저장된 재개 위치만 삭제합니다. 다음 작업 시작 시 재개 모드 대신 처음부터 새로 시작됩니다.
            실행 중인 작업에는 영향을 주지 않습니다.
          </p>
          <div className="convoy-settings__row">
            <button
              className="convoy-settings__btn"
              style={{ background: "#e67e22", color: "#fff" }}
              onClick={() => setClearSavedModalOpen(true)}
              disabled={clearingSaved}
            >
              {clearingSaved ? "삭제 중..." : "저장 위치 삭제"}
            </button>
          </div>
        </div>

        {/* 2) 강력한 리셋 — 작업 자체 강제 초기화 */}
        <div className="convoy-settings__field">
          <label className="convoy-settings__label">작업 상태 강제 초기화</label>
          <p className="convoy-settings__desc">
            복귀 중 화면이 풀리지 않거나 작업 상태가 비정상적으로 멈춘 경우에만 사용합니다.
            모든 작업 상태와 저장된 위치 정보가 초기화되며, 다음 시작은 무조건 새로 시작됩니다.
          </p>
          <div className="convoy-settings__row">
            <button
              className="convoy-settings__btn"
              style={{ background: "#c0392b", color: "#fff" }}
              onClick={() => setResetModalOpen(true)}
              disabled={resetting}
            >
              {resetting ? "초기화 중..." : "작업 상태 강제 초기화"}
            </button>
          </div>
        </div>
      </div>

      <ConfirmModal
        open={clearSavedModalOpen}
        title="저장 위치 삭제"
        message={
          "저장된 로봇별 재개 위치를 모두 삭제하시겠습니까?\n\n" +
          "다음 작업 시작 시 재개 모드가 아닌 새로 시작됩니다.\n" +
          "실행 중인 작업에는 영향이 없습니다."
        }
        onConfirm={handleConfirmClearSaved}
        onCancel={() => setClearSavedModalOpen(false)}
      />

      <ConfirmModal
        open={resetModalOpen}
        title="작업 상태 강제 초기화"
        message={
          "정말로 작업 상태를 강제 초기화하시겠습니까?\n\n" +
          "이 작업은 진행 중인 모든 작업을 즉시 중단하고,\n" +
          "저장된 재개 위치 정보까지 모두 삭제합니다.\n\n" +
          "정상 종료가 가능한 경우에는 사용하지 마세요."
        }
        onConfirm={handleConfirmReset}
        onCancel={() => setResetModalOpen(false)}
      />
    </section>
  );
}
