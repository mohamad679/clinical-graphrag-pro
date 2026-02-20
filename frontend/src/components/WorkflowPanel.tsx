"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";
import ToolCallCard from "./ToolCallCard";
import {
    runAgentWorkflow,
    getWorkflows,
    type WorkflowInfo,
    type AgentStreamEvent,
} from "@/lib/api";

// ── Types ───────────────────────────────────────────────

interface LiveStep {
    step: number;
    title: string;
    description: string;
    status: "pending" | "running" | "done";
}

interface LiveToolCall {
    tool: string;
    status: "running" | "done" | "error";
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    duration?: number;
}

// ── Component ───────────────────────────────────────────

export default function WorkflowPanel() {
    const [query, setQuery] = useState("");
    const [workflowType, setWorkflowType] = useState("general");
    const [isRunning, setIsRunning] = useState(false);
    const [steps, setSteps] = useState<LiveStep[]>([]);
    const [toolCalls, setToolCalls] = useState<LiveToolCall[]>([]);
    const [answer, setAnswer] = useState("");
    const [verification, setVerification] = useState<{ status: string, flags: string[], score: number } | null>(null);
    const [pastWorkflows, setPastWorkflows] = useState<WorkflowInfo[]>([]);
    const [view, setView] = useState<"run" | "history">("run");
    const answerRef = useRef<HTMLDivElement>(null);

    // Load past workflows
    useEffect(() => {
        getWorkflows()
            .then((data) => setPastWorkflows(data.workflows))
            .catch(console.error);
    }, []);

    const handleRun = useCallback(async () => {
        if (!query.trim() || isRunning) return;
        setIsRunning(true);
        setSteps([]);
        setToolCalls([]);
        setAnswer("");
        setVerification(null);

        try {
            await runAgentWorkflow(query, workflowType, (event: AgentStreamEvent) => {
                switch (event.type) {
                    case "reasoning":
                        setSteps((prev) => {
                            const existing = prev.findIndex((s) => s.step === event.step);
                            const updated: LiveStep = {
                                step: event.step!,
                                title: event.title || "",
                                description: event.description || "",
                                status: (event.status as LiveStep["status"]) || "running",
                            };
                            if (existing >= 0) {
                                const copy = [...prev];
                                copy[existing] = updated;
                                return copy;
                            }
                            return [...prev, updated];
                        });
                        break;

                    case "tool_call":
                        setToolCalls((prev) => {
                            if (event.status === "running") {
                                return [
                                    ...prev,
                                    {
                                        tool: event.tool || "",
                                        status: "running",
                                        input: event.input,
                                    },
                                ];
                            }
                            // Update the last matching tool call
                            const copy = [...prev];
                            for (let i = copy.length - 1; i >= 0; i--) {
                                if (copy[i].tool === event.tool && copy[i].status === "running") {
                                    copy[i] = {
                                        ...copy[i],
                                        status: (event.status as "done" | "error") || "done",
                                        output: event.output,
                                        duration: event.duration,
                                    };
                                    break;
                                }
                            }
                            return copy;
                        });
                        break;

                    case "token":
                        setAnswer((prev) => prev + (event.content || ""));
                        break;

                    case "verification":
                        setVerification({
                            status: event.status || "UNKNOWN",
                            flags: event.flags || [],
                            score: event.confidence_score || 0
                        });
                        break;

                    case "workflow_done":
                        // Refresh history
                        getWorkflows()
                            .then((data) => setPastWorkflows(data.workflows))
                            .catch(console.error);
                        break;
                }
            });
        } catch (err) {
            console.error("Workflow failed:", err);
        } finally {
            setIsRunning(false);
        }
    }, [query, workflowType, isRunning]);

    // Auto-scroll answer
    useEffect(() => {
        if (answerRef.current) {
            answerRef.current.scrollTop = answerRef.current.scrollHeight;
        }
    }, [answer]);

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div
                className="p-6 border-b flex items-center justify-between"
                style={{ borderColor: "var(--border)" }}
            >
                <div>
                    <h2
                        className="text-xl font-semibold"
                        style={{ color: "var(--text-primary)" }}
                    >
                        🤖 Agent Workflows
                    </h2>
                    <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                        Multi-step clinical AI agent with tool execution
                    </p>
                </div>

                {/* View toggle */}
                <div
                    className="flex rounded-lg overflow-hidden"
                    style={{ border: "1px solid var(--border)" }}
                >
                    {(["run", "history"] as const).map((v) => (
                        <button
                            key={v}
                            onClick={() => setView(v)}
                            className="px-4 py-1.5 text-sm font-medium transition-colors"
                            style={{
                                background: view === v ? "var(--primary)" : "transparent",
                                color: view === v ? "#fff" : "var(--text-secondary)",
                            }}
                        >
                            {v === "run" ? "New Run" : "History"}
                        </button>
                    ))}
                </div>
            </div>

            {view === "run" ? (
                <div className="flex-1 overflow-y-auto p-6 space-y-5">
                    {/* Input Form */}
                    <div className="glass rounded-xl p-5 space-y-4">
                        <div>
                            <label
                                className="block text-sm font-medium mb-1.5"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                Clinical Query
                            </label>
                            <textarea
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                placeholder="e.g., What are the treatment options for Type 2 Diabetes with CKD stage 3?"
                                className="w-full rounded-lg p-3 text-sm resize-none"
                                style={{
                                    background: "var(--bg-primary)",
                                    color: "var(--text-primary)",
                                    border: "1px solid var(--border)",
                                    minHeight: "80px",
                                }}
                                rows={3}
                                disabled={isRunning}
                            />
                        </div>

                        <div className="flex items-end gap-3">
                            <div className="flex-1">
                                <label
                                    className="block text-sm font-medium mb-1.5"
                                    style={{ color: "var(--text-secondary)" }}
                                >
                                    Workflow Type
                                </label>
                                <select
                                    value={workflowType}
                                    onChange={(e) => setWorkflowType(e.target.value)}
                                    className="w-full rounded-lg p-2.5 text-sm"
                                    style={{
                                        background: "var(--bg-primary)",
                                        color: "var(--text-primary)",
                                        border: "1px solid var(--border)",
                                    }}
                                    disabled={isRunning}
                                >
                                    <option value="general">General</option>
                                    <option value="diagnosis">Diagnosis</option>
                                    <option value="treatment">Treatment</option>
                                    <option value="research">Research</option>
                                </select>
                            </div>

                            <button
                                onClick={handleRun}
                                disabled={!query.trim() || isRunning}
                                className="px-6 py-2.5 rounded-lg text-sm font-semibold transition-all"
                                style={{
                                    background:
                                        !query.trim() || isRunning
                                            ? "var(--bg-tertiary)"
                                            : "var(--primary)",
                                    color:
                                        !query.trim() || isRunning
                                            ? "var(--text-tertiary)"
                                            : "#fff",
                                    cursor:
                                        !query.trim() || isRunning ? "not-allowed" : "pointer",
                                }}
                            >
                                {isRunning ? "Running..." : "▶ Run Agent"}
                            </button>
                        </div>
                    </div>

                    {/* Steps + Tool Calls */}
                    {steps.length > 0 && (
                        <div className="space-y-3">
                            <h3
                                className="text-sm font-semibold"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                Workflow Steps
                            </h3>

                            {steps.map((step) => (
                                <div
                                    key={step.step}
                                    className="glass rounded-lg p-4 animate-fade-in"
                                    style={{
                                        borderLeft: `3px solid ${step.status === "done"
                                            ? "var(--success)"
                                            : step.status === "running"
                                                ? "var(--primary)"
                                                : "var(--border)"
                                            }`,
                                    }}
                                >
                                    <div className="flex items-center gap-2 mb-1">
                                        {step.status === "running" && (
                                            <span
                                                className="inline-block w-2 h-2 rounded-full animate-pulse"
                                                style={{ background: "var(--primary)" }}
                                            />
                                        )}
                                        {step.status === "done" && (
                                            <svg
                                                width="14"
                                                height="14"
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
                                        <span
                                            className="text-sm font-medium"
                                            style={{ color: "var(--text-primary)" }}
                                        >
                                            Step {step.step}: {step.title}
                                        </span>
                                    </div>
                                    <p
                                        className="text-xs ml-4"
                                        style={{ color: "var(--text-tertiary)" }}
                                    >
                                        {step.description}
                                    </p>

                                    {/* Tool calls for this step */}
                                    {toolCalls
                                        .filter(
                                            (_, idx) =>
                                                idx >= step.step - 1 &&
                                                idx < (steps[step.step]?.step ?? toolCalls.length)
                                        )
                                        .map((tc, idx) => (
                                            <div key={idx} className="mt-2 ml-4">
                                                <ToolCallCard
                                                    toolName={tc.tool}
                                                    status={tc.status}
                                                    input={tc.input}
                                                    output={tc.output}
                                                    duration={tc.duration}
                                                />
                                            </div>
                                        ))}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Verification Banner */}
                    {verification && (
                        <div className="rounded-xl p-5 animate-fade-in" style={{
                            background: verification.status === "APPROVED" ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
                            border: `1px solid ${verification.status === "APPROVED" ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`
                        }}>
                            <div className="flex items-center gap-3 mb-2">
                                <span className="text-xl">{verification.status === "APPROVED" ? "✅" : "🛑"}</span>
                                <h3 className="text-sm font-semibold" style={{ color: verification.status === "APPROVED" ? "var(--success)" : "var(--error)" }}>
                                    Adjudicator Verification: {verification.status}
                                </h3>
                                <span className="ml-auto text-xs font-mono px-2 py-1 rounded bg-black bg-opacity-20 text-[var(--text-secondary)]">
                                    Score: {verification.score.toFixed(2)}
                                </span>
                            </div>

                            {verification.flags.length > 0 ? (
                                <ul className="mt-3 space-y-1">
                                    {verification.flags.map((flag, idx) => (
                                        <li key={idx} className="text-sm flex gap-2" style={{ color: "var(--text-primary)" }}>
                                            <span style={{ color: "var(--error)" }}>•</span> {flag}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                                    The drafted response passed all safety and faithfulness checks.
                                </p>
                            )}
                        </div>
                    )}

                    {/* Final Answer */}
                    {answer && (
                        <div className="glass rounded-xl p-5 animate-fade-in">
                            <h3
                                className="text-sm font-semibold mb-3"
                                style={{ color: "var(--text-secondary)" }}
                            >
                                ✨ Synthesized Answer
                            </h3>
                            <div
                                ref={answerRef}
                                className="prose prose-sm max-w-none"
                                style={{
                                    color: "var(--text-primary)",
                                    maxHeight: "400px",
                                    overflow: "auto",
                                }}
                            >
                                <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
                                    {answer}
                                </pre>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                /* History View */
                <div className="flex-1 overflow-y-auto p-6">
                    {pastWorkflows.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-full gap-3">
                            <div
                                className="w-16 h-16 rounded-2xl flex items-center justify-center"
                                style={{ background: "var(--bg-tertiary)" }}
                            >
                                <span className="text-2xl">📋</span>
                            </div>
                            <p
                                className="text-sm"
                                style={{ color: "var(--text-tertiary)" }}
                            >
                                No workflow runs yet
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {pastWorkflows.map((wf) => (
                                <div
                                    key={wf.id}
                                    className="glass rounded-lg p-4 animate-fade-in"
                                >
                                    <div className="flex items-center justify-between mb-2">
                                        <span
                                            className="text-sm font-medium"
                                            style={{ color: "var(--text-primary)" }}
                                        >
                                            {wf.workflow_type} workflow
                                        </span>
                                        <span
                                            className="text-xs px-2 py-0.5 rounded-full"
                                            style={{
                                                background:
                                                    wf.status === "completed"
                                                        ? "rgba(34,197,94,0.15)"
                                                        : wf.status === "failed"
                                                            ? "rgba(239,68,68,0.15)"
                                                            : "rgba(59,130,246,0.15)",
                                                color:
                                                    wf.status === "completed"
                                                        ? "var(--success)"
                                                        : wf.status === "failed"
                                                            ? "var(--error)"
                                                            : "var(--primary)",
                                            }}
                                        >
                                            {wf.status}
                                        </span>
                                    </div>
                                    <p
                                        className="text-xs truncate"
                                        style={{ color: "var(--text-tertiary)" }}
                                    >
                                        {String(wf.input_data?.query ?? "No query")}
                                    </p>
                                    <p
                                        className="text-xs mt-1"
                                        style={{ color: "var(--text-tertiary)" }}
                                    >
                                        {new Date(wf.created_at).toLocaleString()}
                                    </p>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
