"use client";

import React, { useState } from "react";

interface LoginModalProps {
    onLogin: (token: string, user: { id: string; email: string; name: string; role: string }) => void;
    onClose: () => void;
}

export default function LoginModal({ onLogin, onClose }: LoginModalProps) {
    const [email, setEmail] = useState("admin@clinicalgraph.ai");
    const [password, setPassword] = useState("admin123");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setLoading(true);
        setError("");

        try {
            const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
            const res = await fetch(`${API}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || "Login failed");
            }

            const data = await res.json();
            localStorage.setItem("auth_token", data.token);
            onLogin(data.token, data.user);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Login failed");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)" }}>
            <div
                className="w-full max-w-sm rounded-2xl p-8 animate-scale-in"
                style={{
                    background: "linear-gradient(135deg, rgba(30,30,45,0.95), rgba(20,20,35,0.98))",
                    border: "1px solid rgba(255,255,255,0.08)",
                    boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
                }}
            >
                {/* Header */}
                <div className="text-center mb-6">
                    <div className="w-12 h-12 mx-auto mb-3 rounded-xl flex items-center justify-center" style={{ background: "linear-gradient(135deg, #6366f1, #8b5cf6)" }}>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                    </div>
                    <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Sign In</h2>
                    <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>Clinical GraphRAG Pro</p>
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Email</label>
                        <input
                            type="email"
                            value={email}
                            onChange={e => setEmail(e.target.value)}
                            className="w-full px-3 py-2.5 rounded-lg text-sm"
                            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                            required
                        />
                    </div>
                    <div>
                        <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            className="w-full px-3 py-2.5 rounded-lg text-sm"
                            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                            required
                        />
                    </div>

                    {error && (
                        <p className="text-xs text-center" style={{ color: "#ef4444" }}>{error}</p>
                    )}

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-2.5 rounded-lg text-sm font-medium transition-all"
                        style={{
                            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                            color: "white",
                            opacity: loading ? 0.6 : 1,
                        }}
                    >
                        {loading ? "Signing in..." : "Sign In"}
                    </button>
                </form>

                {/* Demo credentials hint */}
                <div className="mt-4 p-3 rounded-lg" style={{ background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.15)" }}>
                    <p className="text-xs text-center" style={{ color: "var(--text-tertiary)" }}>
                        Demo: <strong style={{ color: "var(--text-secondary)" }}>admin@clinicalgraph.ai</strong> / <strong style={{ color: "var(--text-secondary)" }}>admin123</strong>
                    </p>
                </div>

                {/* Close */}
                <button
                    onClick={onClose}
                    className="w-full mt-3 py-2 rounded-lg text-xs transition-all"
                    style={{ color: "var(--text-tertiary)" }}
                >
                    Cancel
                </button>
            </div>
        </div>
    );
}
