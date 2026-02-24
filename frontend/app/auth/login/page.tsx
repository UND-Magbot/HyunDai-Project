"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { LoginFormState, LoginFormErrors } from "@/lib/types/auth";
import { apiFetch } from "@/lib/api";
import { ForgotPasswordModal } from "./ForgotPasswordModal";
import "./login.css";

const ID_REGEX = /^[a-zA-Z][a-zA-Z0-9]*$/;
const PW_REGEX = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[^a-zA-Z0-9\s]).{6,}$/;

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
      newErrors.loginId = "아이디를 입력해주세요";
    } else if (!ID_REGEX.test(form.loginId)) {
      newErrors.loginId = "영문 또는 영문+숫자 조합만 입력 가능합니다";
    }

    if (!form.password) {
      newErrors.password = "비밀번호를 입력해주세요";
    } else if (!PW_REGEX.test(form.password)) {
      newErrors.password =
        "비밀번호는 영문, 숫자, 특수문자 조합 6자 이상이어야 합니다";
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
        user: { login_id: string; role: number };
      }>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login_id: form.loginId, password: form.password }),
      });
      localStorage.setItem("auth_token", res.access_token);
      localStorage.setItem("user_login_id", res.user.login_id);
      localStorage.setItem("user_role", String(res.user.role));
      router.push("/monitoring");
    } catch {
      setErrors({ loginId: "아이디 또는 비밀번호가 올바르지 않습니다" });
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
