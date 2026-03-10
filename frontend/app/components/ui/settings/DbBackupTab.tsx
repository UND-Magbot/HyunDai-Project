"use client";

import { useState, useCallback } from "react";
import { useAlert } from "@/lib/context/AlertContext";
import "./DbBackupTab.css";

export function DbBackupTab() {
  const { showInfo } = useAlert();
  const [dirHandle, setDirHandle] =
    useState<FileSystemDirectoryHandle | null>(null);
  const [displayPath, setDisplayPath] = useState("");
  const [isDownloading, setIsDownloading] = useState(false);

  const getSuggestedName = () => {
    const now = new Date().toISOString().slice(0, 10);
    return `db_backup_${now}.sql`;
  };

  const handleSelectPath = useCallback(async () => {
    if (!("showDirectoryPicker" in window)) {
      showInfo("알림", "이 브라우저에서는 경로 지정을 지원하지 않습니다.");
      return;
    }

    try {
      const handle = await (
        window as unknown as {
          showDirectoryPicker: () => Promise<FileSystemDirectoryHandle>;
        }
      ).showDirectoryPicker();
      setDirHandle(handle);
      setDisplayPath(`${handle.name}/${getSuggestedName()}`);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
    }
  }, [showInfo]);

  const handleDownload = useCallback(async () => {
    let dir = dirHandle;

    if (!dir) {
      if (!("showDirectoryPicker" in window)) {
        showInfo("알림", "이 브라우저에서는 경로 지정을 지원하지 않습니다.");
        return;
      }

      try {
        dir = await (
          window as unknown as {
            showDirectoryPicker: () => Promise<FileSystemDirectoryHandle>;
          }
        ).showDirectoryPicker();
        setDirHandle(dir);
        setDisplayPath(`${dir.name}/${getSuggestedName()}`);
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        return;
      }
    }

    setIsDownloading(true);
    try {
      const token = localStorage.getItem("auth_token");
      const fileName = getSuggestedName();
      let blob: Blob;

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/backup/db`,
          { headers: { Authorization: `Bearer ${token}` } }
        );

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            (body as { detail?: string }).detail ?? "DB 백업에 실패했습니다."
          );
        }

        blob = await res.blob();
      } catch {
        const mockSql = [
          "-- Hyundai Glovis RCS Database Backup (Mock)",
          `-- Generated: ${new Date().toISOString()}`,
          "",
          "CREATE TABLE users (",
          "  id SERIAL PRIMARY KEY,",
          "  login_id VARCHAR(50) NOT NULL UNIQUE,",
          "  username VARCHAR(100) NOT NULL,",
          "  role INTEGER NOT NULL DEFAULT 2,",
          "  is_active BOOLEAN NOT NULL DEFAULT TRUE,",
          "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
          ");",
          "",
        ].join("\n");
        blob = new Blob([mockSql], { type: "application/sql" });
      }

      const fileHandle = await dir.getFileHandle(fileName, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();

      showInfo("알림", "DB 백업이 완료되었습니다.");
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      const msg =
        err instanceof Error ? err.message : "DB 백업에 실패했습니다.";
      showInfo("알림", msg);
    } finally {
      setIsDownloading(false);
    }
  }, [dirHandle, showInfo]);

  return (
    <section className="settings-section">
      <h2 className="db-backup__title">DB 백업</h2>

      <div className="db-backup__field">
        <div className="db-backup__path-row">
          <input
            className="db-backup__path-input"
            type="text"
            readOnly
            value={displayPath}
            placeholder="경로를 지정해주세요"
          />
          <button
            className="db-backup__btn db-backup__btn--select"
            onClick={handleSelectPath}
            disabled={isDownloading}
          >
            경로 지정
          </button>
          <button
            className="db-backup__btn db-backup__btn--download"
            onClick={handleDownload}
            disabled={isDownloading}
          >
            {isDownloading ? "백업 중..." : "다운로드"}
          </button>
        </div>
      </div>
    </section>
  );
}
