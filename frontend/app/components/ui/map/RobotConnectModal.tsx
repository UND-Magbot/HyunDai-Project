"use client";

import { useEffect, useState } from "react";
import { Modal } from "../Modal";
import { apiFetch } from "@/lib/api";
import type { RobotConnectModalProps } from "@/lib/types/map";

type RobotItem = {
  sn: string;
  name: string;
  ip_address: string | null;
};

export function RobotConnectModal({
  open,
  onClose,
  onConnect,
}: RobotConnectModalProps) {
  const [search, setSearch] = useState("");
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [robots, setRobots] = useState<RobotItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 모달이 열릴 때 로봇 목록 조회
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    apiFetch<{ total: number; items: RobotItem[] }>("/api/map/robots")
      .then((data) => setRobots(data.items))
      .catch((err) => setError(err.message ?? "로봇 목록을 불러올 수 없습니다."))
      .finally(() => setLoading(false));
  }, [open]);

  const filtered = search
    ? robots.filter(
        (r) =>
          r.sn.toLowerCase().includes(search.toLowerCase()) ||
          r.name.toLowerCase().includes(search.toLowerCase())
      )
    : robots;

  const handleConnect = async () => {
    if (!selectedSn) return;
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch<{ connected: boolean; sn: string; name: string; ip_address: string }>(
        `/api/map/connect/${selectedSn}`,
        { method: "POST" }
      );
      onConnect(res.sn, res.name, res.ip_address);
      setSearch("");
      setSelectedSn(null);
    } catch (err: any) {
      setError(err.message ?? "로봇에 연결할 수 없습니다.");
    } finally {
      setConnecting(false);
    }
  };

  const handleClose = () => {
    setSearch("");
    setSelectedSn(null);
    setError(null);
    onClose();
  };

  return (
    <Modal open={open} onClose={handleClose} title="로봇 연결" width="420px">
      <div className="robot-connect__search">
        <input
          className="input"
          placeholder="SN 또는 로봇명으로 검색..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="robot-connect__list">
        {loading ? (
          <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "16px" }}>
            로봇 목록을 불러오는 중...
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "16px" }}>
            검색 결과가 없습니다.
          </div>
        ) : (
          filtered.map((robot) => (
            <button
              key={robot.sn}
              className={
                selectedSn === robot.sn
                  ? "robot-connect__item robot-connect__item--selected"
                  : "robot-connect__item"
              }
              onClick={() => setSelectedSn(robot.sn)}
            >
              <span className="robot-connect__item-name">{robot.name}</span>
              <span className="robot-connect__item-sn">{robot.sn}</span>
            </button>
          ))
        )}
      </div>

      {error && (
        <div style={{ color: "var(--danger)", fontSize: "13px", padding: "4px 0" }}>
          {error}
        </div>
      )}

      <div className="robot-connect__actions">
        <button className="btn" onClick={handleClose}>
          취소
        </button>
        <button
          className="btn btn--primary"
          onClick={handleConnect}
          disabled={!selectedSn || connecting}
        >
          {connecting ? "연결 중..." : "연결"}
        </button>
      </div>
    </Modal>
  );
}
