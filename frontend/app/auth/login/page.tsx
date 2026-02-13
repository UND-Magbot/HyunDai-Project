"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { LoginFormState, LoginFormErrors } from "@/lib/types/auth";
import { ForgotPasswordModal } from "./ForgotPasswordModal";
import "./login.css";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PW_REGEX = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[^a-zA-Z0-9\s]).{6,}$/;

// 임시 계정 (API 연동 시 제거)
const MOCK_USER = { id: "admin", password: "1234" };

export default function LoginPage() {
  const router = useRouter();
  const [form, setForm] = useState<LoginFormState>({ email: "", password: "" });
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

    if (!form.email.trim()) {
      newErrors.email = "이메일을 입력해주세요";
    } else if (!EMAIL_REGEX.test(form.email)) {
      newErrors.email = "올바른 이메일 형식을 입력해주세요";
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // 임시 계정 체크 (유효성 검사 우회)
    if (form.email === MOCK_USER.id && form.password === MOCK_USER.password) {
      localStorage.setItem("auth_token", "mock_token");
      router.push("/monitoring");
      return;
    }

    if (!validate()) return;

    // TODO: API 연동 - 로그인 요청
    setErrors({ email: "아이디 또는 비밀번호가 올바르지 않습니다" });
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <h1 className="login__title">Login</h1>

        <div className="login__field">
          <label className="login__label" htmlFor="email">
            이메일
          </label>
          <input
            id="email"
            className={`login__input${errors.email ? " login__input--error" : ""}`}
            type="email"
            placeholder="이메일을 입력해주세요"
            value={form.email}
            onChange={(e) => updateField("email", e.target.value)}
            autoComplete="off"
          />
          <span className="login__error">{errors.email ?? ""}</span>
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

        <button
          className="login__forgot"
          type="button"
          onClick={() => setForgotOpen(true)}
        >
          비밀번호 찾기
        </button>
      </form>

      <ForgotPasswordModal
        open={forgotOpen}
        onClose={() => setForgotOpen(false)}
      />
    </div>
  );
}
