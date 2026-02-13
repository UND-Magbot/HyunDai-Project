"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    router.replace(token ? "/monitoring" : "/auth/login");
  }, [router]);

  return null;
}
