"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

export default function Home() {
  const [msg, setMsg] = useState("loading...");

  useEffect(() => {
    apiFetch("/ping").then((data) => {
      setMsg(data.message);
    });
  }, []);

  return (
    <main style={{ padding: 40 }}>
      <h1>Frontend ↔ Backend Test</h1>
      <p>Backend says: {msg}</p>
    </main>
  );
}
