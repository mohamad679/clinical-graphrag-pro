"use client";

import { useState } from "react";
import type { ImageAnalysisResult, Finding, ImageAnnotation } from "@/lib/api";

interface AnalysisPanelProps {
    analysis: ImageAnalysisResult;
    annotations: ImageAnnotation[];
    isAnalyzing?: boolean;
    onAnnotationHover?: (annotationId: string | null) => void;
    onReanalyze?: () => void;
}

/* Severity badge component */
function SeverityBadge({ severity }: { severity: string }) {
    const colors: Record<string, string> = {
        normal: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
        mild: "bg-amber-500/20 text-amber-400 border-amber-500/30",
        moderate: "bg-orange-500/20 text-orange-400 border-orange-500/30",
        severe: "bg-red-500/20 text-red-400 border-red-500/30",
    };
    return (
        <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider border ${colors[severity] || colors.normal}`}
        >
            {severity}
        </span>
    );
}

/* Confidence bar */
function ConfidenceBar({ value }: { value: number }) {
    const pct = Math.round(value * 100);
    const color =
        pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-500" : "bg-red-500";
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div
                    className={`h-full rounded-full ${color} transition-all duration-500`}
                    style={{ width: `${pct}%` }}
                />
            </div>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)] min-w-[2rem]">
                {pct}%
            </span>
        </div>
    );
}

export default function AnalysisPanel({
    analysis,
    annotations,
    isAnalyzing,
    onAnnotationHover,
    onReanalyze,
}: AnalysisPanelProps) {
    const [expandedFinding, setExpandedFinding] = useState<number | null>(null);

    if (isAnalyzing) {
        return (
            <div className="glass-card p-6 flex flex-col items-center justify-center gap-3 min-h-[200px]">
                <div className="w-10 h-10 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-[var(--text-secondary)]">
                    Analyzing image with Vision AI...
                </p>
                <p className="text-xs text-[var(--text-tertiary)]">
                    This may take 10-30 seconds
                </p>
            </div>
        );
    }

    if (analysis.error) {
        return (
            <div className="glass-card p-4 border-red-500/30">
                <p className="text-sm text-red-400">⚠️ {analysis.error}</p>
                {onReanalyze && (
                    <button onClick={onReanalyze} className="btn-primary mt-3 text-xs">
                        Retry Analysis
                    </button>
                )}
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            {/* Summary card */}
            <div className="glass-card p-4">
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                        AI Analysis
                    </h3>
                    <div className="flex items-center gap-2">
                        {analysis.modality_detected && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[var(--primary)]/20 text-[var(--primary)] border border-[var(--primary)]/30">
                                {analysis.modality_detected}
                            </span>
                        )}
                        {analysis.body_part_detected && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30">
                                {analysis.body_part_detected}
                            </span>
                        )}
                    </div>
                </div>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    {analysis.summary}
                </p>
                {analysis.model_used && (
                    <p className="text-[10px] text-[var(--text-tertiary)] mt-2 font-mono">
                        Model: {analysis.model_used}
                    </p>
                )}
            </div>

            {/* Findings */}
            {analysis.findings.length > 0 && (
                <div className="glass-card p-4">
                    <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
                        Findings ({analysis.findings.length})
                    </h3>
                    <div className="flex flex-col gap-2">
                        {analysis.findings.map((finding, i) => (
                            <div
                                key={i}
                                className="p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-primary)] cursor-pointer hover:border-[var(--primary)]/50 transition-colors"
                                onClick={() =>
                                    setExpandedFinding(expandedFinding === i ? null : i)
                                }
                                onMouseEnter={() => {
                                    const matchingAnnotation = annotations.find(
                                        (a) => a.label.startsWith(finding.description.slice(0, 30))
                                    );
                                    onAnnotationHover?.(matchingAnnotation?.id || null);
                                }}
                                onMouseLeave={() => onAnnotationHover?.(null)}
                            >
                                <div className="flex items-center justify-between mb-1">
                                    <SeverityBadge severity={finding.severity} />
                                    <span className="text-[10px] text-[var(--text-tertiary)]">
                                        {finding.location}
                                    </span>
                                </div>
                                <p className="text-sm text-[var(--text-primary)] mt-1">
                                    {finding.description}
                                </p>
                                {finding.confidence > 0 && (
                                    <div className="mt-2">
                                        <ConfidenceBar value={finding.confidence} />
                                    </div>
                                )}
                                {expandedFinding === i && finding.bbox && (
                                    <div className="mt-2 text-[10px] font-mono text-[var(--text-tertiary)] p-2 bg-black/20 rounded">
                                        Region: x={Math.round(finding.bbox.x * 100)}%,
                                        y={Math.round(finding.bbox.y * 100)}%,
                                        {Math.round(finding.bbox.width * 100)}×
                                        {Math.round(finding.bbox.height * 100)}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Differential Diagnosis */}
            {analysis.differential_diagnosis &&
                analysis.differential_diagnosis.length > 0 && (
                    <div className="glass-card p-4">
                        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
                            Differential Diagnosis
                        </h3>
                        <div className="flex flex-col gap-2">
                            {analysis.differential_diagnosis.map((dd, i) => (
                                <div
                                    key={i}
                                    className="flex items-center justify-between p-2 rounded bg-[var(--bg-tertiary)]"
                                >
                                    <span className="text-sm text-[var(--text-primary)]">
                                        {dd.condition}
                                    </span>
                                    <ConfidenceBar value={dd.probability} />
                                </div>
                            ))}
                        </div>
                    </div>
                )}

            {/* Recommendations */}
            {analysis.recommendations.length > 0 && (
                <div className="glass-card p-4">
                    <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
                        Recommendations
                    </h3>
                    <ul className="flex flex-col gap-2">
                        {analysis.recommendations.map((rec, i) => (
                            <li
                                key={i}
                                className="flex items-start gap-2 text-sm text-[var(--text-secondary)]"
                            >
                                <span className="text-[var(--accent)] mt-0.5">→</span>
                                {rec}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Re-analyze button */}
            {onReanalyze && (
                <button
                    onClick={onReanalyze}
                    className="btn-secondary text-xs self-start"
                >
                    Re-analyze
                </button>
            )}
        </div>
    );
}
