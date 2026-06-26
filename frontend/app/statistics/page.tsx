"use client";

import { useState, useEffect, useCallback } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import { apiFetch } from "@/lib/api";
import "./statistics.css";

type RobotReliability = {
  robot_id: number;
  robot_name: string;
  wcs_label: string | null;
  failure_count: number;
  mttr_seconds: number | null;
  mtbf_seconds: number | null;
  availability_pct: number | null;
  mttr_text: string;
  mtbf_text: string;
  currently_in_failure: boolean;
};

type ReliabilityResponse = {
  period: { from: string; to: string };
  summary: {
    total_failures: number;
    avg_mttr_seconds: number | null;
    avg_mtbf_seconds: number | null;
    avg_availability_pct: number | null;
    avg_mttr_text: string;
    avg_mtbf_text: string;
    any_robot_in_failure: boolean;
    robot_count: number;
  };
  robots: RobotReliability[];
};

type RobotUtilization = {
  robot_id: number;
  robot_name: string;
  wcs_label: string | null;
  total_seconds: number;
  durations_seconds: Record<string, number>;
  ratios_pct: Record<string, number>;
};

type UtilizationResponse = {
  period: { from: string; to: string };
  robots: RobotUtilization[];
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

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function daysAgoStr(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const STATUS_META = [
  { key: "idle",     label: "대기",   color: "#6b7280" },
  { key: "working",  label: "작업중", color: "#22c55e" },
  { key: "charging", label: "충전중", color: "#06b6d4" },
  { key: "error",    label: "에러",   color: "#ef4444" },
  { key: "offline",  label: "오프라인", color: "#374151" },
];

export default function StatisticsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [isLoading, setIsLoading] = useState(true);

  const [startDate, setStartDate] = useState(daysAgoStr(7));
  const [endDate, setEndDate] = useState(todayStr());
  const [appliedFrom, setAppliedFrom] = useState(daysAgoStr(7));
  const [appliedTo, setAppliedTo] = useState(todayStr());

  const [reliability, setReliability] = useState<ReliabilityResponse | null>(null);
  const [utilization, setUtilization] = useState<UtilizationResponse | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  const fetchAll = useCallback(async (from: string, to: string) => {
    setIsLoading(true);
    try {
      const fromIso = `${from}T00:00:00`;
      const toIso = `${to}T23:59:59`;
      const qs = `date_from=${fromIso}&date_to=${toIso}`;
      const [rel, util] = await Promise.all([
        apiFetch<ReliabilityResponse>(`/api/statistics/reliability?${qs}`),
        apiFetch<UtilizationResponse>(`/api/statistics/utilization?${qs}`),
      ]);
      setReliability(rel);
      setUtilization(util);
    } catch {
      setReliability(null);
      setUtilization(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll(appliedFrom, appliedTo);
  }, [appliedFrom, appliedTo, fetchAll]);

  const handleSearch = () => {
    setAppliedFrom(startDate);
    setAppliedTo(endDate);
  };

  const handleReset = () => {
    const f = daysAgoStr(7);
    const t = todayStr();
    setStartDate(f);
    setEndDate(t);
    setAppliedFrom(f);
    setAppliedTo(t);
  };

  const handlePreset = (days: number) => {
    const f = daysAgoStr(days);
    const t = todayStr();
    setStartDate(f);
    setEndDate(t);
    setAppliedFrom(f);
    setAppliedTo(t);
  };

  const summary = reliability?.summary;
  const robots = reliability?.robots ?? [];

  return (
    <>
      {isLoading && <LoadingScreen pageName="통계" />}
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
            <div className="stats-page">
              <header className="stats-page__header">
                <h1 className="stats-page__title">통계 — 가용성 지표</h1>
                <div className="stats-page__presets">
                  <button onClick={() => handlePreset(1)}>1일</button>
                  <button onClick={() => handlePreset(7)}>7일</button>
                  <button onClick={() => handlePreset(30)}>30일</button>
                </div>
              </header>

              <section className="stats-filter">
                <label>
                  시작
                  <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                </label>
                <label>
                  종료
                  <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                </label>
                <button className="stats-filter__btn stats-filter__btn--primary" onClick={handleSearch}>조회</button>
                <button className="stats-filter__btn" onClick={handleReset}>초기화</button>
              </section>

              <section className="stats-kpis">
                <div className="kpi-card kpi-card--avail">
                  <div className="kpi-card__label">가용성</div>
                  <div className="kpi-card__value">
                    {summary?.avg_availability_pct != null ? `${summary.avg_availability_pct}%` : "-"}
                  </div>
                  <div className="kpi-card__hint">평균</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-card__label">MTTR</div>
                  <div className="kpi-card__value">{summary?.avg_mttr_text ?? "-"}</div>
                  <div className="kpi-card__hint">평균 복구 시간</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-card__label">MTBF</div>
                  <div className="kpi-card__value">{summary?.avg_mtbf_text ?? "-"}</div>
                  <div className="kpi-card__hint">평균 고장 간격</div>
                </div>
                <div className="kpi-card kpi-card--fail">
                  <div className="kpi-card__label">고장 횟수</div>
                  <div className="kpi-card__value">{summary?.total_failures ?? "-"}</div>
                  <div className="kpi-card__hint">{summary?.any_robot_in_failure ? "현재 복구 중" : "정상"}</div>
                </div>
              </section>

              <section className="stats-section">
                <h2 className="stats-section__title">로봇별 가용성</h2>
                <div className="stats-table-wrap">
                  <table className="stats-table">
                    <thead>
                      <tr>
                        <th>로봇</th>
                        <th>WCS</th>
                        <th>가용성</th>
                        <th>MTTR</th>
                        <th>MTBF</th>
                        <th>고장 횟수</th>
                        <th>현재 상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {robots.length === 0 && (
                        <tr><td colSpan={7} className="stats-table__empty">데이터가 없습니다.</td></tr>
                      )}
                      {robots.map((r) => (
                        <tr key={r.robot_id}>
                          <td>{r.robot_name}</td>
                          <td>{r.wcs_label ?? "-"}</td>
                          <td>{r.availability_pct != null ? `${r.availability_pct}%` : "-"}</td>
                          <td>{r.mttr_text}</td>
                          <td>{r.mtbf_text}</td>
                          <td>{r.failure_count}</td>
                          <td>
                            {r.currently_in_failure ? (
                              <span className="badge badge--error">복구 중</span>
                            ) : (
                              <span className="badge badge--ok">정상</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="stats-section">
                <h2 className="stats-section__title">로봇별 가동률 (상태 점유 비율)</h2>
                <div className="stats-util-list">
                  {(utilization?.robots ?? []).length === 0 && (
                    <div className="stats-table__empty">데이터가 없습니다.</div>
                  )}
                  {(utilization?.robots ?? []).map((r) => (
                    <div key={r.robot_id} className="util-row">
                      <div className="util-row__name">
                        {r.robot_name}
                        {r.wcs_label && <span className="util-row__wcs"> · {r.wcs_label}</span>}
                      </div>
                      <div className="util-bar" title={`총 ${Math.round(r.total_seconds / 60)}분`}>
                        {STATUS_META.map((s) => {
                          const pct = r.ratios_pct[s.key] ?? 0;
                          if (pct <= 0) return null;
                          return (
                            <span
                              key={s.key}
                              className="util-bar__seg"
                              style={{ width: `${pct}%`, background: s.color }}
                              title={`${s.label}: ${pct}%`}
                            />
                          );
                        })}
                      </div>
                      <div className="util-row__legend">
                        {STATUS_META.map((s) => {
                          const pct = r.ratios_pct[s.key] ?? 0;
                          if (pct <= 0) return null;
                          return (
                            <span key={s.key} className="util-legend">
                              <span className="util-legend__dot" style={{ background: s.color }} />
                              {s.label} {pct}%
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="stats-help">
                <details>
                  <summary>지표 설명</summary>
                  <ul>
                    <li><b>가용성 (Availability)</b> = MTBF / (MTBF + MTTR) × 100. 설비가 정상 동작한 시간 비율.</li>
                    <li><b>MTTR (Mean Time To Repair)</b> = 평균 복구 시간. 짧을수록 좋음.</li>
                    <li><b>MTBF (Mean Time Between Failures)</b> = 평균 고장 간격. 길수록 좋음.</li>
                    <li><b>고장</b>: 로봇 status가 에러(3)로 진입한 시점. <b>복구</b>: 에러에서 다른 상태로 전이한 시점.</li>
                    <li>데이터 출처: <code>robot_status_history</code> 테이블 (status 변경 시점만 기록).</li>
                  </ul>
                </details>
              </section>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}
