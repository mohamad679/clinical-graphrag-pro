"use client";

import React from "react";
import type { ReasoningStep } from "@/lib/api";

// ── Icons ───────────────────────────────────────────────

const CheckIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="20 6 9 17 4 12" />
    </svg>
);

const SpinnerIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: "spin 1s linear infinite" }}>
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
);

// ── Props ───────────────────────────────────────────────

interface ReasoningStepsProps {
    steps: ReasoningStep[];
}

// ── Component ───────────────────────────────────────────

export default function ReasoningSteps({ steps }: ReasoningStepsProps) {
    if (!steps || steps.length === 0) return null;

    return (
        <div
            className="rounded-xl p-3 mb-3 animate-fade-in"
            style={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
            }}
        >
            <p
                className="text-xs font-medium uppercase tracking-wider mb-2"
                style={{ color: "var(--text-tertiary)" }}
            >
                Reasoning
            </p>

            <div className="space-y-2">
                {steps.map((step, index) => (
                    <div
                        key={`${step.step}-${index}`}
                        className="flex items-start gap-2.5 animate-slide-in"
                        style={{ animationDelay: `${index * 100}ms` }}
                    >
                        {/* Status indicator */}
                        <div className="mt-0.5 flex-shrink-0">
                            {step.status === "done" ? (
                                <div
                                    className="w-5 h-5 rounded-full flex items-center justify-center"
                                    style={{ background: "var(--success)", color: "white" }}
                                >
                                    <CheckIcon />
                                </div>
                            ) : step.status === "running" ? (
                                <div
                                    className="w-5 h-5 rounded-full flex items-center justify-center"
                                    style={{ background: "var(--primary)", color: "white" }}
                                >
                                    <SpinnerIcon />
                                </div>
                            ) : (
                                <div
                                    className="w-5 h-5 rounded-full border-2"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            )}
                        </div>

                        {/* Step content */}
                        <div className="flex-1 min-w-0">
                            <p
                                className="text-sm font-medium"
                                style={{
                                    color: step.status === "done" ? "var(--text-primary)" : "var(--text-secondary)",
                                }}
                            >
                                {step.title}
                            </p>
                            <p
                                className="text-xs mt-0.5"
                                style={{ color: "var(--text-tertiary)" }}
                            >
                                {step.description}
                            </p>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
