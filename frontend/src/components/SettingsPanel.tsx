"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
    getAdminHealth,
    getAdminMetrics,
    getAdminConfig,
    getAdminSessions,
    type AdminHealth,
    type AdminMetrics,
    type AdminConfig,
    type AdminSession,
} from "@/lib/api";

// ── SVG Gauge ───────────────────────────────────────────

function Gauge({ value, max, label, color }: { value: number; max: number; label: string; color: string }) {
    const pct = Math.min(value / (max || 1), 1);
    const r = 40, cx = 50, cy = 50;
    const circumference = 2 * Math.PI * r;
    const offset = circumference * (1 - pct * 0.75); // 270° arc

    return (
        <div className="flex flex-col items-center">
            <svg width="100" height="90" viewBox="0 0 100 100">
                {/* Background arc */}
                <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8"
                    strokeDasharray={`${circumference * 0.75} ${circumference * 0.25}`}
                    strokeLinecap="round" transform={`rotate(135 ${cx} ${cy})`} />
                {/* Value arc */}
                <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="8"
                    strokeDasharray={`${circumference * 0.75 * pct} ${circumference}`}
                    strokeLinecap="round" transform={`rotate(135 ${cx} ${cy})`}
                    style={{ transition: "stroke-dasharray 0.6s ease" }} />
                {/* Value text */}
                <text x={cx} y={cy - 2} textAnchor="middle" fill="white" fontSize="16" fontWeight="bold">
                    {typeof value === "number" ? (value > 999 ? `${(value / 1000).toFixed(1)}k` : Math.round(value)) : value}
                </text>
                <text x={cx} y={cy + 14} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="9">
                    {label}
                </text>
            </svg>
        </div>
    );
}

// ── Tabs ─────────────────────────────────────────────────

type Tab = "health" | "metrics" | "config";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
    const tabs: { key: Tab; label: string }[] = [
        { key: "health", label: "System Health" },
        { key: "metrics", label: "API Metrics" },
        { key: "config", label: "Configuration" },
    ];

    return (
        <div className="flex gap-1 p-1 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
            {tabs.map(t => (
                <button
                    key={t.key}
                    onClick={() => onChange(t.key)}
                    className="px-4 py-2 rounded-md text-sm font-medium transition-all"
                    style={{
                        background: active === t.key ? "var(--bg-secondary)" : "transparent",
                        color: active === t.key ? "var(--text-primary)" : "var(--text-tertiary)",
                        boxShadow: active === t.key ? "0 1px 3px rgba(0,0,0,0.2)" : "none",
                    }}
                >
                    {t.label}
                </button>
            ))}
        </div>
    );
}

// ── Status Badge ────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
    const isUp = status === "up" || status === "healthy";
    return (
        <span
            className="text-xs px-2 py-0.5 rounded-full font-medium"
            style={{
                background: isUp ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                color: isUp ? "#10b981" : "#ef4444",
            }}
        >
            {status}
        </span>
    );
}

// ── Main Component ──────────────────────────────────────

export default function SettingsPanel() {
    const [tab, setTab] = useState<Tab>("health");
    const [health, setHealth] = useState<AdminHealth | null>(null);
    const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
    const [config, setConfig] = useState<AdminConfig | null>(null);
    const [sessions, setSessions] = useState<AdminSession[]>([]);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const [h, m, c, s] = await Promise.all([
                getAdminHealth(),
                getAdminMetrics(),
                getAdminConfig(),
                getAdminSessions(),
            ]);
            setHealth(h);
            setMetrics(m);
            setConfig(c);
            setSessions(s.sessions);
        } catch { /* ignore */ }
        finally { setLoading(false); }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    // Auto-refresh every 10s
    useEffect(() => {
        const iv = setInterval(refresh, 10000);
        return () => clearInterval(iv);
    }, [refresh]);

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
                            Settings & Admin
                        </h2>
                        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                            System health, metrics, and configuration
                        </p>
                    </div>
                    <TabBar active={tab} onChange={setTab} />
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6">
                <div className="max-w-4xl mx-auto space-y-6">

                    {loading && !health && (
                        <div className="glass rounded-xl p-8 text-center">
                            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Loading...</p>
                        </div>
                    )}

                    {/* ── Health Tab ──────────────────────────────── */}
                    {tab === "health" && health && (
                        <>
                            {/* Status overview */}
                            <div className="glass rounded-xl p-5">
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>System Status</h3>
                                    <StatusBadge status={health.status} />
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                                    <Gauge value={parseFloat(health.uptime_seconds.toString())} max={86400} label="Uptime" color="#10b981" />
                                    <Gauge
                                        value={health.services.vector_store.total_chunks}
                                        max={Math.max(health.services.vector_store.total_chunks, 100)}
                                        label="Chunks" color="#6366f1"
                                    />
                                    <Gauge
                                        value={health.services.vector_store.total_documents}
                                        max={Math.max(health.services.vector_store.total_documents, 10)}
                                        label="Documents" color="#f59e0b"
                                    />
                                    <Gauge
                                        value={health.services.rate_limiter.active_buckets}
                                        max={Math.max(health.services.rate_limiter.active_buckets, 10)}
                                        label="Active IPs" color="#06b6d4"
                                    />
                                </div>
                            </div>

                            {/* Service status */}
                            <div className="glass rounded-xl p-5">
                                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Services</h3>
                                <div className="space-y-2">
                                    {Object.entries(health.services).map(([name, svc]) => (
                                        <div key={name} className="flex items-center justify-between py-2 px-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                            <span className="text-sm capitalize" style={{ color: "var(--text-primary)" }}>{name.replace("_", " ")}</span>
                                            <StatusBadge status={(svc as { status: string }).status} />
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* System info */}
                            <div className="glass rounded-xl p-5">
                                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>System Info</h3>
                                <div className="grid grid-cols-2 gap-3 text-xs">
                                    <div className="p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                        <span style={{ color: "var(--text-tertiary)" }}>Uptime</span>
                                        <p className="font-medium mt-0.5" style={{ color: "var(--text-primary)" }}>{health.uptime_human}</p>
                                    </div>
                                    <div className="p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                        <span style={{ color: "var(--text-tertiary)" }}>Python</span>
                                        <p className="font-medium mt-0.5" style={{ color: "var(--text-primary)" }}>{health.python_version}</p>
                                    </div>
                                    <div className="p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                        <span style={{ color: "var(--text-tertiary)" }}>Platform</span>
                                        <p className="font-medium mt-0.5" style={{ color: "var(--text-primary)" }}>{health.platform}</p>
                                    </div>
                                    <div className="p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                        <span style={{ color: "var(--text-tertiary)" }}>Rate Limit</span>
                                        <p className="font-medium mt-0.5" style={{ color: "var(--text-primary)" }}>
                                            {health.services.rate_limiter.max_requests_per_minute}/min
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}

                    {/* ── Metrics Tab ────────────────────────────── */}
                    {tab === "metrics" && metrics && (
                        <>
                            {/* Overview cards */}
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                                {[
                                    { label: "Total Requests", value: metrics.total_requests, color: "#6366f1" },
                                    { label: "Error Rate", value: `${metrics.error_rate_pct}%`, color: metrics.error_rate_pct > 5 ? "#ef4444" : "#10b981" },
                                    { label: "Avg Latency", value: `${metrics.avg_latency_ms}ms`, color: metrics.avg_latency_ms > 500 ? "#f59e0b" : "#06b6d4" },
                                    { label: "P95 Latency", value: `${metrics.p95_latency_ms}ms`, color: "#8b5cf6" },
                                ].map((card, i) => (
                                    <div key={i} className="glass rounded-xl p-4 text-center">
                                        <p className="text-2xl font-bold" style={{ color: card.color }}>{card.value}</p>
                                        <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>{card.label}</p>
                                    </div>
                                ))}
                            </div>

                            {/* Status breakdown */}
                            <div className="glass rounded-xl p-5">
                                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Status Codes</h3>
                                <div className="space-y-2">
                                    {Object.entries(metrics.status_counts).map(([code, count]) => {
                                        const pct = (count as number) / metrics.total_requests * 100;
                                        const color = parseInt(code) < 400 ? "#10b981" : parseInt(code) < 500 ? "#f59e0b" : "#ef4444";
                                        return (
                                            <div key={code} className="flex items-center gap-3">
                                                <span className="text-xs font-mono w-8" style={{ color }}>{code}</span>
                                                <div className="flex-1 h-2 rounded-full" style={{ background: "var(--bg-tertiary)" }}>
                                                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
                                                </div>
                                                <span className="text-xs w-12 text-right" style={{ color: "var(--text-tertiary)" }}>{count as number}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Top endpoints */}
                            <div className="glass rounded-xl p-5">
                                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Top Endpoints</h3>
                                <div className="space-y-1">
                                    {Object.entries(metrics.top_endpoints).map(([path, count]) => (
                                        <div key={path} className="flex items-center justify-between py-1.5 px-3 rounded text-xs" style={{ background: "var(--bg-tertiary)" }}>
                                            <span className="font-mono" style={{ color: "var(--text-primary)" }}>{path}</span>
                                            <span style={{ color: "var(--text-tertiary)" }}>{count as number}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Sessions */}
                            {sessions.length > 0 && (
                                <div className="glass rounded-xl p-5">
                                    <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Recent Sessions</h3>
                                    <div className="space-y-2">
                                        {sessions.slice(0, 10).map((s, i) => (
                                            <div key={i} className="flex items-center justify-between py-2 px-3 rounded-lg text-xs" style={{ background: "var(--bg-tertiary)" }}>
                                                <div className="flex items-center gap-2">
                                                    <span className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium" style={{ background: "rgba(99,102,241,0.15)", color: "#6366f1" }}>
                                                        {s.name.charAt(0)}
                                                    </span>
                                                    <div>
                                                        <p style={{ color: "var(--text-primary)" }}>{s.name}</p>
                                                        <p style={{ color: "var(--text-tertiary)" }}>{s.email}</p>
                                                    </div>
                                                </div>
                                                <span className="text-xs px-2 py-0.5 rounded" style={{ background: "rgba(99,102,241,0.1)", color: "#6366f1" }}>
                                                    {s.role}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </>
                    )}

                    {/* ── Config Tab ─────────────────────────────── */}
                    {tab === "config" && config && (
                        <div className="space-y-4">
                            {Object.entries(config).map(([section, values]) => (
                                <div key={section} className="glass rounded-xl p-5">
                                    <h3 className="text-sm font-medium capitalize mb-3" style={{ color: "var(--text-secondary)" }}>
                                        {section.replace("_", " ")}
                                    </h3>
                                    <div className="grid grid-cols-2 gap-2">
                                        {Object.entries(values as Record<string, unknown>).map(([key, val]) => (
                                            <div key={key} className="p-3 rounded-lg text-xs" style={{ background: "var(--bg-tertiary)" }}>
                                                <span style={{ color: "var(--text-tertiary)" }}>{key.replace(/_/g, " ")}</span>
                                                <p className="font-mono mt-0.5 truncate" style={{ color: "var(--text-primary)" }}>
                                                    {typeof val === "boolean" ? (val ? "✓ Enabled" : "✗ Disabled") : String(val)}
                                                </p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                </div>
            </div>
        </div>
    );
}
