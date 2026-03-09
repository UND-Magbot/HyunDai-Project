"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { LoginFormState, LoginFormErrors } from "@/lib/types/auth";
import { apiFetch } from "@/lib/api";
import { MENU_ITEMS } from "@/lib/types/settings";
import type { MenuPermissionItem } from "@/lib/types/settings";
import { ForgotPasswordModal } from "./ForgotPasswordModal";
import "./login.css";

const ID_REGEX = /^[a-zA-Z][a-zA-Z0-9]*$/;
const PW_REGEX = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[^a-zA-Z0-9\s]).{6,}$/;

const DEFAULT_USER_MENUS = new Set(["모니터링", "설정"]);

export default function LoginPage() {
  const router = useRouter();
  const [form, setForm] = useState<LoginFormState>({ loginId: "", password: "" });
  const [errors, setErrors] = useState<LoginFormErrors>({});
  const [forgotOpen, setForgotOpen] = useState(false);

  const updateField = <K extends keyof LoginFormState>(
    key: K,
    value: LoginFormState[K]
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const validate = (): boolean => {
    const newErrors: LoginFormErrors = {};

    if (!form.loginId.trim()) {
      newErrors.loginId = "아이디를 입력해 주세요.";
    }

    if (!form.password) {
      newErrors.password = "비밀번호를 입력해 주세요.";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    try {
      const res = await apiFetch<{
        access_token: string;
        user: { id: number; login_id: string; role: number };
      }>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login_id: form.loginId, password: form.password }),
      });
      localStorage.setItem("auth_token", res.access_token);
      localStorage.setItem("user_id", String(res.user.id));
      localStorage.setItem("user_login_id", res.user.login_id);
      localStorage.setItem("user_role", String(res.user.role));

      // 메뉴 권한 로드
      const isAdmin = res.user.role === 1;
      let allowedLabels: string[];

      if (isAdmin) {
        allowedLabels = MENU_ITEMS.map((m) => m.label);
      } else {
        const stored = localStorage.getItem(`menu_perm_${res.user.id}`);
        if (stored) {
          const perms = JSON.parse(stored) as MenuPermissionItem[];
          allowedLabels = perms.filter((p) => p.isAllowed).map((p) => p.menuLabel);
        } else {
          allowedLabels = MENU_ITEMS.filter((m) => DEFAULT_USER_MENUS.has(m.label)).map((m) => m.label);
        }
      }
      localStorage.setItem("allowed_menus", JSON.stringify(allowedLabels));

      router.push("/monitoring");
    } catch (err: any) {
      const msg = err?.message ?? "";
      if (msg.includes("존재")) {
        setErrors({ loginId: "존재하지 않는 아이디입니다." });
      } else if (msg.includes("아이디")) {
        setErrors({ loginId: "아이디가 올바르지 않습니다. 다시 확인해 주세요." });
      } else if (msg.includes("비밀번호")) {
        setErrors({ password: "비밀번호가 올바르지 않습니다. 다시 확인해 주세요." });
      } else {
        setErrors({ loginId: "로그인에 실패했습니다." });
      }
    }
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <h1 className="login__title">Login</h1>

        <div className="login__field">
          <label className="login__label" htmlFor="loginId">
            아이디
          </label>
          <input
            id="loginId"
            className={`login__input${errors.loginId ? " login__input--error" : ""}`}
            type="text"
            placeholder="아이디를 입력해주세요"
            value={form.loginId}
            onChange={(e) => updateField("loginId", e.target.value)}
            autoComplete="off"
          />
          <span className="login__error">{errors.loginId ?? ""}</span>
        </div>

        <div className="login__field">
          <label className="login__label" htmlFor="password">
            비밀번호
          </label>
          <input
            id="password"
            className={`login__input${errors.password ? " login__input--error" : ""}`}
            type="password"
            placeholder="비밀번호를 입력해주세요"
            value={form.password}
            onChange={(e) => updateField("password", e.target.value)}
            autoComplete="off"
          />
          <span className="login__error">{errors.password ?? ""}</span>
        </div>

        <button className="login__btn" type="submit">
          로그인
        </button>

        {/* <button
          className="login__forgot"
          type="button"
          onClick={() => setForgotOpen(true)}
        >
          비밀번호 찾기
        </button> */}
      </form>

      <ForgotPasswordModal
        open={forgotOpen}
        onClose={() => setForgotOpen(false)}
      />
    </div>
  );
}
