"use client";

import React, { useState } from "react";

interface ToolCallCardProps {
    toolName: string;
    status: "running" | "done" | "error";
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    duration?: number;
}

const TOOL_ICONS: Record<string, string> = {
    search_documents: "🔍",
    medical_calculator: "🧮",
    pubmed_search: "📚",
    drug_interaction: "💊",
    analyze_image: "🩻",
};

export default function ToolCallCard({
    toolName,
    status,
    input,
    output,
    duration,
}: ToolCallCardProps) {
    const [expanded, setExpanded] = useState(false);
    const icon = TOOL_ICONS[toolName] || "🔧";

    return (
        <div
            className="glass rounded-lg overflow-hidden animate-fade-in"
            style={{
                border: `1px solid ${status === "error"
                        ? "var(--error)"
                        : status === "done"
                            ? "var(--success)"
                            : "var(--border)"
                    }`,
            }}
        >
            {/* Header */}
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between p-3 text-left"
                style={{ background: "var(--bg-tertiary)" }}
            >
                <div className="flex items-center gap-2">
                    <span className="text-lg">{icon}</span>
                    <span
                        className="text-sm font-medium"
                        style={{ color: "var(--text-primary)" }}
                    >
                        {toolName.replace(/_/g, " ")}
                    </span>
                    {duration != null && (
                        <span
                            className="text-xs px-2 py-0.5 rounded-full"
                            style={{
                                background: "var(--bg-secondary)",
                                color: "var(--text-tertiary)",
                            }}
                        >
                            {duration}ms
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    {/* Status indicator */}
                    {status === "running" && (
                        <span
                            className="inline-block w-2 h-2 rounded-full animate-pulse"
                            style={{ background: "var(--primary)" }}
                        />
                    )}
                    {status === "done" && (
                        <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="var(--success)"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        >
                            <polyline points="20 6 9 17 4 12" />
                        </svg>
                    )}
                    {status === "error" && (
                        <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="var(--error)"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        >
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    )}

                    {/* Expand chevron */}
                    <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--text-tertiary)"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        style={{
                            transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                            transition: "transform 0.2s ease",
                        }}
                    >
                        <polyline points="6 9 12 15 18 9" />
                    </svg>
                </div>
            </button>

            {/* Expanded content */}
            {expanded && (
                <div
                    className="p-3 text-xs space-y-2"
                    style={{ borderTop: "1px solid var(--border)" }}
                >
                    {input && (
                        <div>
                            <p
                                className="font-semibold mb-1"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                Input
                            </p>
                            <pre
                                className="p-2 rounded overflow-x-auto"
                                style={{
                                    background: "var(--bg-primary)",
                                    color: "var(--text-secondary)",
                                }}
                            >
                                {JSON.stringify(input, null, 2)}
                            </pre>
                        </div>
                    )}
                    {output && (
                        <div>
                            <p
                                className="font-semibold mb-1"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                Output
                            </p>
                            <pre
                                className="p-2 rounded overflow-x-auto"
                                style={{
                                    background: "var(--bg-primary)",
                                    color: "var(--text-secondary)",
                                    maxHeight: "200px",
                                }}
                            >
                                {JSON.stringify(output, null, 2)}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
