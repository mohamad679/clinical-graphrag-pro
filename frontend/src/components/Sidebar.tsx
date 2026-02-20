"use client";

import React, { useState, useEffect } from "react";
import { getSessions, deleteSession, type ChatSession } from "@/lib/api";

// ── Icons (inline SVG for zero dependencies) ────────────

const ChatIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
);

const GraphIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <circle cx="19" cy="5" r="2" />
        <circle cx="5" cy="19" r="2" />
        <circle cx="5" cy="5" r="2" />
        <line x1="12" y1="9" x2="7" y2="6" />
        <line x1="12" y1="9" x2="17" y2="6" />
        <line x1="12" y1="15" x2="7" y2="18" />
    </svg>
);

const WorkflowIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
);

const EvalIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 12l2 2 4-4" />
        <circle cx="12" cy="12" r="10" />
    </svg>
);

const FineTuneIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
);

const SettingsIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" y1="21" x2="4" y2="14" />
        <line x1="4" y1="10" x2="4" y2="3" />
        <line x1="12" y1="21" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12" y2="3" />
        <line x1="20" y1="21" x2="20" y2="16" />
        <line x1="20" y1="12" x2="20" y2="3" />
        <line x1="1" y1="14" x2="7" y2="14" />
        <line x1="9" y1="8" x2="15" y2="8" />
        <line x1="17" y1="16" x2="23" y2="16" />
    </svg>
);

const PlusIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="5" x2="12" y2="19" />
        <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
);

const TrashIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
);

const MenuIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
);

// ── Types ───────────────────────────────────────────────

interface SidebarProps {
    currentView: "chat" | "graph" | "workflows" | "evaluation" | "finetune" | "settings";
    onViewChange: (view: "chat" | "graph" | "workflows" | "evaluation" | "finetune" | "settings") => void;
    currentSessionId?: string;
    onSessionSelect: (sessionId: string) => void;
    onNewChat: () => void;
}

// ── Component ───────────────────────────────────────────

export default function Sidebar({
    currentView,
    onViewChange,
    currentSessionId,
    onSessionSelect,
    onNewChat,
}: SidebarProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (currentView === "chat") {
            loadSessions();
        }
    }, [currentView]);

    async function loadSessions() {
        setLoading(true);
        try {
            const data = await getSessions();
            setSessions(data);
        } catch (err) {
            console.error("Failed to load sessions:", err);
        } finally {
            setLoading(false);
        }
    }

    async function handleDelete(e: React.MouseEvent, sessionId: string) {
        e.stopPropagation();
        try {
            await deleteSession(sessionId);
            setSessions((prev) => prev.filter((s) => s.id !== sessionId));
            if (currentSessionId === sessionId) {
                onNewChat();
            }
        } catch (err) {
            console.error("Failed to delete session:", err);
        }
    }

    const navItems = [
        { key: "chat" as const, label: "Chat", icon: <ChatIcon /> },
        { key: "graph" as const, label: "Knowledge Graph", icon: <GraphIcon /> },
        { key: "workflows" as const, label: "Workflows", icon: <WorkflowIcon /> },
        { key: "evaluation" as const, label: "Evaluation", icon: <EvalIcon /> },
        { key: "finetune" as const, label: "Fine-Tune", icon: <FineTuneIcon /> },
        { key: "settings" as const, label: "Settings", icon: <SettingsIcon /> },
    ];

    return (
        <aside
            style={{
                width: collapsed ? "var(--sidebar-collapsed)" : "var(--sidebar-width)",
                minWidth: collapsed ? "var(--sidebar-collapsed)" : "var(--sidebar-width)",
                transition: "width var(--transition), min-width var(--transition)",
            }}
            className="h-screen flex flex-col border-r"
            css-border-color="var(--border)"
        >
            {/* Header */}
            <div
                className="flex items-center justify-between p-3 border-b"
                style={{ borderColor: "var(--border)" }}
            >
                {!collapsed && (
                    <div className="flex items-center gap-2 animate-fade-in">
                        <img
                            src="/logo.png"
                            alt="CGR Logo"
                            className="w-10 h-10 object-contain rounded-lg"
                        />
                        <div>
                            <h1 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                                Clinical GraphRAG
                            </h1>
                            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                                Pro v1.0
                            </p>
                        </div>
                    </div>
                )}
                <button
                    onClick={() => setCollapsed(!collapsed)}
                    className="btn-ghost p-2"
                    aria-label="Toggle sidebar"
                >
                    <MenuIcon />
                </button>
            </div>

            {/* Navigation */}
            <nav className="p-2 space-y-1">
                {navItems.map((item) => (
                    <button
                        key={item.key}
                        onClick={() => onViewChange(item.key)}
                        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all"
                        style={{
                            background: currentView === item.key ? "var(--bg-tertiary)" : "transparent",
                            color: currentView === item.key ? "var(--text-primary)" : "var(--text-secondary)",
                        }}
                        title={collapsed ? item.label : undefined}
                    >
                        {item.icon}
                        {!collapsed && <span>{item.label}</span>}
                    </button>
                ))}
            </nav>

            {/* New Chat Button */}
            {currentView === "chat" && (
                <div className="px-2 mt-1">
                    <button
                        onClick={onNewChat}
                        className="btn-primary w-full flex items-center justify-center gap-2"
                    >
                        <PlusIcon />
                        {!collapsed && <span>New Chat</span>}
                    </button>
                </div>
            )}

            {/* Session History */}
            {currentView === "chat" && !collapsed && (
                <div className="flex-1 overflow-y-auto mt-3 px-2">
                    <p
                        className="text-xs font-medium uppercase tracking-wider px-2 mb-2"
                        style={{ color: "var(--text-tertiary)" }}
                    >
                        History
                    </p>

                    {loading && (
                        <div className="flex items-center justify-center py-4">
                            <div className="loading-dot w-1.5 h-1.5 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                            <div className="loading-dot w-1.5 h-1.5 rounded-full mx-1" style={{ background: "var(--text-tertiary)" }} />
                            <div className="loading-dot w-1.5 h-1.5 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                        </div>
                    )}

                    {!loading && sessions.length === 0 && (
                        <p className="text-xs px-2 py-4 text-center" style={{ color: "var(--text-tertiary)" }}>
                            No conversations yet
                        </p>
                    )}

                    <div className="space-y-0.5">
                        {sessions.map((session) => (
                            <div
                                key={session.id}
                                onClick={() => onSessionSelect(session.id)}
                                className="group flex items-center justify-between px-2 py-2 rounded-lg cursor-pointer transition-all text-sm"
                                style={{
                                    background: currentSessionId === session.id ? "var(--bg-tertiary)" : "transparent",
                                    color: currentSessionId === session.id ? "var(--text-primary)" : "var(--text-secondary)",
                                }}
                            >
                                <span className="truncate flex-1 mr-2">{session.title}</span>
                                <button
                                    onClick={(e) => handleDelete(e, session.id)}
                                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-red-500/20"
                                    style={{ color: "var(--error)" }}
                                    aria-label="Delete session"
                                >
                                    <TrashIcon />
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Footer */}
            {!collapsed && (
                <div
                    className="p-3 border-t text-xs"
                    style={{ borderColor: "var(--border)", color: "var(--text-tertiary)" }}
                >
                    <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }} />
                        <span>Backend connected</span>
                    </div>
                </div>
            )}
        </aside>
    );
}
