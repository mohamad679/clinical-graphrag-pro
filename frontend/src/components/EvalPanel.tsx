"use client";

import React, { useState, useEffect, useCallback } from "react";
import { runEvaluation, getEvalHistory, type EvalRunResponse } from "@/lib/api";

// ── Radar Chart (pure SVG) ──────────────────────────────

interface RadarChartProps {
    data: { label: string; value: number; color: string }[];
    size?: number;
}

function RadarChart({ data, size = 280 }: RadarChartProps) {
    const cx = size / 2;
    const cy = size / 2;
    const r = size * 0.38;
    const levels = 5;
    const angleStep = (2 * Math.PI) / data.length;

    const getPoint = (index: number, value: number) => {
        const angle = angleStep * index - Math.PI / 2;
        return {
            x: cx + r * value * Math.cos(angle),
            y: cy + r * value * Math.sin(angle),
        };
    };

    // Grid circles and labels
    const grid = [];
    for (let l = 1; l <= levels; l++) {
        const frac = l / levels;
        const pts = data.map((_, i) => getPoint(i, frac));
        const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") + " Z";
        grid.push(
            <path
                key={`grid-${l}`}
                d={path}
                fill="none"
                stroke="rgba(255,255,255,0.08)"
                strokeWidth={l === levels ? 1.5 : 0.8}
            />
        );
    }

    // Spokes
    const spokes = data.map((_, i) => {
        const p = getPoint(i, 1);
        return <line key={`spoke-${i}`} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="rgba(255,255,255,0.06)" strokeWidth={0.8} />;
    });

    // Data polygon
    const dataPoints = data.map((d, i) => getPoint(i, d.value));
    const dataPath = dataPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") + " Z";

    // Labels
    const labels = data.map((d, i) => {
        const p = getPoint(i, 1.22);
        return (
            <text
                key={`label-${i}`}
                x={p.x}
                y={p.y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="rgba(255,255,255,0.7)"
                fontSize="11"
                fontWeight="500"
            >
                {d.label}
            </text>
        );
    });

    return (
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mx-auto">
            {grid}
            {spokes}
            <path d={dataPath} fill="rgba(99, 102, 241, 0.15)" stroke="rgba(99, 102, 241, 0.8)" strokeWidth={2} />
            {dataPoints.map((p, i) => (
                <circle key={`dot-${i}`} cx={p.x} cy={p.y} r={4} fill={data[i].color} stroke="rgba(0,0,0,0.3)" strokeWidth={1} />
            ))}
            {labels}
        </svg>
    );
}

// ── Score Card ──────────────────────────────────────────

function ScoreCard({ label, score, explanation, color }: {
    label: string;
    score: number;
    explanation: string;
    color: string;
}) {
    const pct = Math.round(score * 100);
    const getGrade = (s: number) => {
        if (s >= 0.9) return "A+";
        if (s >= 0.8) return "A";
        if (s >= 0.7) return "B";
        if (s >= 0.6) return "C";
        if (s >= 0.5) return "D";
        return "F";
    };

    return (
        <div className="glass rounded-xl p-4 animate-scale-in" style={{ borderLeft: `3px solid ${color}` }}>
            <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                    {label}
                </span>
                <span className="text-xs font-bold px-2 py-0.5 rounded" style={{ background: `${color}22`, color }}>
                    {getGrade(score)}
                </span>
            </div>
            <div className="flex items-end gap-2 mb-2">
                <span className="text-2xl font-bold" style={{ color }}>{pct}%</span>
                {/* Mini bar */}
                <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
                    <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${pct}%`, background: color }}
                    />
                </div>
            </div>
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                {explanation}
            </p>
        </div>
    );
}

// ── Main EvalPanel ──────────────────────────────────────

export default function EvalPanel() {
    const [query, setQuery] = useState("");
    const [topK, setTopK] = useState(5);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<EvalRunResponse | null>(null);
    const [history, setHistory] = useState<EvalRunResponse[]>([]);
    const [showHistory, setShowHistory] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const loadHistory = useCallback(async () => {
        try {
            const data = await getEvalHistory();
            setHistory(data.evaluations);
        } catch {
            console.error("Failed to load eval history");
        }
    }, []);

    useEffect(() => {
        loadHistory();
    }, [loadHistory]);

    async function handleRun() {
        if (!query.trim()) return;
        setLoading(true);
        setError(null);
        setResult(null);

        try {
            const res = await runEvaluation(query, topK);
            setResult(res);
            loadHistory();
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Evaluation failed");
        } finally {
            setLoading(false);
        }
    }

    const metricColors = {
        faithfulness: "#6366f1",
        relevance: "#06b6d4",
        citation_accuracy: "#f59e0b",
        context_precision: "#10b981",
    };

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
                            RAG Evaluation
                        </h2>
                        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                            Measure retrieval quality with Faithfulness, Relevance, Citation Accuracy &amp; Context Precision
                        </p>
                    </div>
                    <button
                        onClick={() => setShowHistory(!showHistory)}
                        className="btn-ghost px-3 py-1.5 text-sm rounded-lg"
                    >
                        {showHistory ? "← Run Eval" : `History (${history.length})`}
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6">
                {showHistory ? (
                    /* ── History View ────────────────────────────── */
                    <div className="max-w-4xl mx-auto space-y-3">
                        {history.length === 0 ? (
                            <div className="glass rounded-xl p-8 text-center">
                                <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                                    No evaluations yet. Run one to get started.
                                </p>
                            </div>
                        ) : (
                            history.map((ev) => (
                                <div
                                    key={ev.id}
                                    className="glass rounded-xl p-4 cursor-pointer hover:scale-[1.01] transition-transform"
                                    onClick={() => { setResult(ev); setShowHistory(false); }}
                                >
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-sm font-medium truncate flex-1 mr-4" style={{ color: "var(--text-primary)" }}>
                                            {ev.query}
                                        </span>
                                        <span
                                            className="text-lg font-bold"
                                            style={{ color: ev.overall_score >= 0.7 ? "var(--success)" : ev.overall_score >= 0.5 ? "var(--warning)" : "var(--error)" }}
                                        >
                                            {Math.round(ev.overall_score * 100)}%
                                        </span>
                                    </div>
                                    <div className="flex gap-4 text-xs" style={{ color: "var(--text-tertiary)" }}>
                                        <span>F: {Math.round(ev.faithfulness.score * 100)}%</span>
                                        <span>R: {Math.round(ev.relevance.score * 100)}%</span>
                                        <span>C: {Math.round(ev.citation_accuracy.score * 100)}%</span>
                                        <span>P: {Math.round(ev.context_precision.score * 100)}%</span>
                                        <span className="ml-auto">{new Date(ev.created_at).toLocaleString()}</span>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                ) : (
                    /* ── Run + Results View ─────────────────────── */
                    <div className="max-w-4xl mx-auto space-y-6">
                        {/* Query form */}
                        <div className="glass rounded-xl p-5">
                            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
                                Medical Query
                            </label>
                            <div className="flex gap-3">
                                <input
                                    type="text"
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && handleRun()}
                                    placeholder="e.g. What are the side effects of metformin?"
                                    className="flex-1 px-4 py-2.5 rounded-lg text-sm"
                                    style={{
                                        background: "var(--bg-tertiary)",
                                        color: "var(--text-primary)",
                                        border: "1px solid var(--border)",
                                    }}
                                    disabled={loading}
                                />
                                <select
                                    value={topK}
                                    onChange={(e) => setTopK(Number(e.target.value))}
                                    className="px-3 py-2.5 rounded-lg text-sm"
                                    style={{
                                        background: "var(--bg-tertiary)",
                                        color: "var(--text-primary)",
                                        border: "1px solid var(--border)",
                                    }}
                                >
                                    {[3, 5, 10].map((k) => (
                                        <option key={k} value={k}>Top {k}</option>
                                    ))}
                                </select>
                                <button
                                    onClick={handleRun}
                                    disabled={loading || !query.trim()}
                                    className="btn-primary px-5 py-2.5 rounded-lg text-sm font-medium"
                                    style={{ opacity: loading || !query.trim() ? 0.5 : 1 }}
                                >
                                    {loading ? (
                                        <span className="flex items-center gap-2">
                                            <span className="loading-dot w-1.5 h-1.5 rounded-full bg-white" />
                                            <span className="loading-dot w-1.5 h-1.5 rounded-full bg-white" />
                                            <span className="loading-dot w-1.5 h-1.5 rounded-full bg-white" />
                                        </span>
                                    ) : "Evaluate"}
                                </button>
                            </div>
                        </div>

                        {error && (
                            <div className="glass rounded-xl p-4 border-l-4" style={{ borderColor: "var(--error)" }}>
                                <p className="text-sm" style={{ color: "var(--error)" }}>{error}</p>
                            </div>
                        )}

                        {/* Results */}
                        {result && (
                            <>
                                {/* Overall Score */}
                                <div className="glass rounded-xl p-6 text-center animate-fade-in">
                                    <p className="text-sm mb-2" style={{ color: "var(--text-tertiary)" }}>Overall Quality Score</p>
                                    <p
                                        className="text-5xl font-bold"
                                        style={{
                                            color: result.overall_score >= 0.7
                                                ? "var(--success)"
                                                : result.overall_score >= 0.5
                                                    ? "var(--warning)"
                                                    : "var(--error)",
                                        }}
                                    >
                                        {Math.round(result.overall_score * 100)}%
                                    </p>
                                </div>

                                {/* Radar chart + score cards */}
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                    {/* Radar */}
                                    <div className="glass rounded-xl p-6 flex items-center justify-center animate-scale-in">
                                        <RadarChart
                                            data={[
                                                { label: "Faithfulness", value: result.faithfulness.score, color: metricColors.faithfulness },
                                                { label: "Relevance", value: result.relevance.score, color: metricColors.relevance },
                                                { label: "Citation", value: result.citation_accuracy.score, color: metricColors.citation_accuracy },
                                                { label: "Precision", value: result.context_precision.score, color: metricColors.context_precision },
                                            ]}
                                        />
                                    </div>

                                    {/* Score Cards */}
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <ScoreCard
                                            label="Faithfulness"
                                            score={result.faithfulness.score}
                                            explanation={result.faithfulness.explanation}
                                            color={metricColors.faithfulness}
                                        />
                                        <ScoreCard
                                            label="Relevance"
                                            score={result.relevance.score}
                                            explanation={result.relevance.explanation}
                                            color={metricColors.relevance}
                                        />
                                        <ScoreCard
                                            label="Citation Acc."
                                            score={result.citation_accuracy.score}
                                            explanation={result.citation_accuracy.explanation}
                                            color={metricColors.citation_accuracy}
                                        />
                                        <ScoreCard
                                            label="Context Prec."
                                            score={result.context_precision.score}
                                            explanation={result.context_precision.explanation}
                                            color={metricColors.context_precision}
                                        />
                                    </div>
                                </div>

                                {/* Answer preview */}
                                <div className="glass rounded-xl p-5 animate-fade-in">
                                    <p className="text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
                                        Generated Answer
                                    </p>
                                    <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
                                        {result.answer}
                                    </p>
                                </div>
                            </>
                        )}

                        {/* Empty state */}
                        {!result && !loading && !error && (
                            <div className="glass rounded-xl p-12 text-center animate-fade-in">
                                <div
                                    className="w-16 h-16 mx-auto mb-4 rounded-2xl flex items-center justify-center"
                                    style={{ background: "var(--bg-tertiary)" }}
                                >
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--accent)" }}>
                                        <path d="M9 12l2 2 4-4" />
                                        <circle cx="12" cy="12" r="10" />
                                    </svg>
                                </div>
                                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                                    Enter a medical query to evaluate RAG quality
                                </p>
                                <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
                                    The system will run a full RAG pipeline and measure 4 quality dimensions
                                </p>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
