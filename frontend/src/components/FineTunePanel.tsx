"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
    getFineTuneDatasets,
    createFineTuneDataset,
    generateSamples,
    getFineTuneJobs,
    startTraining,
    getJobDetail,
    getFineTuneModels,
    deployModel,
    undeployModel,
    type FineTuneDataset,
    type FineTuneJob,
    type FineTuneModel,
    type JobDetail,
} from "@/lib/api";

// ── SVG Loss Chart ──────────────────────────────────────

function LossChart({ metrics }: { metrics: { step: number; loss: number; eval_loss?: number | null }[] }) {
    if (!metrics || metrics.length === 0) return null;

    const w = 500, h = 200, pad = 40;
    const maxStep = Math.max(...metrics.map(m => m.step));
    const maxLoss = Math.max(...metrics.map(m => Math.max(m.loss, m.eval_loss ?? 0))) * 1.1;
    const minLoss = Math.min(...metrics.map(m => m.loss)) * 0.9;
    const range = maxLoss - minLoss || 1;

    const x = (step: number) => pad + ((step / (maxStep || 1)) * (w - pad * 2));
    const y = (loss: number) => pad + ((maxLoss - loss) / range) * (h - pad * 2);

    const trainPath = metrics.map((m, i) => `${i === 0 ? "M" : "L"} ${x(m.step)} ${y(m.loss)}`).join(" ");
    const evalPoints = metrics.filter(m => m.eval_loss != null);

    // Y-axis labels
    const yLabels = [0, 0.25, 0.5, 0.75, 1].map(f => {
        const val = minLoss + f * range;
        return { y: y(val), label: val.toFixed(2) };
    });

    return (
        <svg width="100%" viewBox={`0 0 ${w} ${h}`} className="mx-auto">
            {/* Grid */}
            {yLabels.map((yl, i) => (
                <g key={i}>
                    <line x1={pad} y1={yl.y} x2={w - pad} y2={yl.y} stroke="rgba(255,255,255,0.06)" strokeWidth={0.5} />
                    <text x={pad - 5} y={yl.y + 3} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize="9">{yl.label}</text>
                </g>
            ))}

            {/* Train loss line */}
            <path d={trainPath} fill="none" stroke="#6366f1" strokeWidth={1.5} />

            {/* Eval loss dots */}
            {evalPoints.map((m, i) => (
                <circle key={i} cx={x(m.step)} cy={y(m.eval_loss!)} r={3} fill="#f59e0b" stroke="rgba(0,0,0,0.3)" strokeWidth={1} />
            ))}

            {/* Legend */}
            <line x1={w - 120} y1={10} x2={w - 100} y2={10} stroke="#6366f1" strokeWidth={2} />
            <text x={w - 95} y={14} fill="rgba(255,255,255,0.6)" fontSize="9">Train Loss</text>
            <circle cx={w - 110} cy={25} r={3} fill="#f59e0b" />
            <text x={w - 95} y={28} fill="rgba(255,255,255,0.6)" fontSize="9">Eval Loss</text>
        </svg>
    );
}

// ── Tab Buttons ─────────────────────────────────────────

type Tab = "datasets" | "training" | "models" | "logs";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
    const tabs: { key: Tab; label: string }[] = [
        { key: "datasets", label: "Datasets" },
        { key: "training", label: "Training" },
        { key: "models", label: "Models" },
        { key: "logs", label: "Logs" },
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

// ── Main Component ──────────────────────────────────────

export default function FineTunePanel() {
    const [tab, setTab] = useState<Tab>("datasets");
    const [datasets, setDatasets] = useState<FineTuneDataset[]>([]);
    const [jobs, setJobs] = useState<FineTuneJob[]>([]);
    const [models, setModels] = useState<FineTuneModel[]>([]);
    const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Form state
    const [dsName, setDsName] = useState("");
    const [dsDesc, setDsDesc] = useState("");
    const [dsTemplate, setDsTemplate] = useState("alpaca");
    const [trainDatasetId, setTrainDatasetId] = useState("");
    const [adapterName, setAdapterName] = useState("");
    const [loraRank, setLoraRank] = useState(16);
    const [numEpochs, setNumEpochs] = useState(3);
    const [lr, setLr] = useState(0.0002);

    const refresh = useCallback(async () => {
        try {
            const [dsData, jobData, modelData] = await Promise.all([
                getFineTuneDatasets(),
                getFineTuneJobs(),
                getFineTuneModels(),
            ]);
            setDatasets(dsData.datasets);
            setJobs(jobData.jobs);
            setModels(modelData.models);
        } catch { /* ignore */ }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    async function handleCreateDataset() {
        if (!dsName.trim()) return;
        setError(null);
        try {
            await createFineTuneDataset(dsName, dsDesc, dsTemplate);
            setDsName(""); setDsDesc("");
            refresh();
        } catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed"); }
    }

    async function handleGenerate(datasetId: string) {
        setLoading(true); setError(null);
        try {
            const res = await generateSamples(datasetId, 20);
            alert(`Generated ${res.generated} training pairs`);
            refresh();
        } catch (e: unknown) { setError(e instanceof Error ? e.message : "Generation failed"); }
        finally { setLoading(false); }
    }

    async function handleStartTraining() {
        if (!trainDatasetId) return;
        setLoading(true); setError(null);
        try {
            await startTraining({
                dataset_id: trainDatasetId,
                adapter_name: adapterName,
                lora_rank: loraRank,
                num_epochs: numEpochs,
                learning_rate: lr,
            });
            setTab("logs");
            refresh();
        } catch (e: unknown) { setError(e instanceof Error ? e.message : "Training failed"); }
        finally { setLoading(false); }
    }

    async function handleViewJob(jobId: string) {
        try {
            const detail = await getJobDetail(jobId);
            setSelectedJob(detail);
        } catch { /* ignore */ }
    }

    async function handleDeploy(modelId: string, isActive: boolean) {
        try {
            if (isActive) { await undeployModel(modelId); }
            else { await deployModel(modelId); }
            refresh();
        } catch { /* ignore */ }
    }

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
                            Fine-Tuning Lab
                        </h2>
                        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                            LoRA adapter training for clinical domain specialization
                        </p>
                    </div>
                    <TabBar active={tab} onChange={setTab} />
                </div>
            </div>

            {/* Error banner */}
            {error && (
                <div className="mx-6 mt-4 glass rounded-xl p-3 border-l-4" style={{ borderColor: "var(--error)" }}>
                    <p className="text-sm" style={{ color: "var(--error)" }}>{error}</p>
                </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6">
                <div className="max-w-4xl mx-auto space-y-6">

                    {/* ── Datasets Tab ───────────────────────────── */}
                    {tab === "datasets" && (
                        <>
                            {/* Create form */}
                            <div className="glass rounded-xl p-5">
                                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text-secondary)" }}>Create Dataset</h3>
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                    <input
                                        value={dsName} onChange={e => setDsName(e.target.value)}
                                        placeholder="Dataset name"
                                        className="px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    />
                                    <input
                                        value={dsDesc} onChange={e => setDsDesc(e.target.value)}
                                        placeholder="Description (optional)"
                                        className="px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    />
                                    <div className="flex gap-2">
                                        <select
                                            value={dsTemplate} onChange={e => setDsTemplate(e.target.value)}
                                            className="flex-1 px-3 py-2 rounded-lg text-sm"
                                            style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                        >
                                            <option value="alpaca">Alpaca</option>
                                            <option value="sharegpt">ShareGPT</option>
                                        </select>
                                        <button onClick={handleCreateDataset} className="btn-primary px-4 py-2 rounded-lg text-sm">Create</button>
                                    </div>
                                </div>
                            </div>

                            {/* Dataset list */}
                            {datasets.length === 0 ? (
                                <div className="glass rounded-xl p-8 text-center">
                                    <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                                        No datasets yet. Create one to start curating training data.
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {datasets.map(ds => (
                                        <div key={ds.id} className="glass rounded-xl p-4 animate-fade-in">
                                            <div className="flex items-center justify-between mb-2">
                                                <div>
                                                    <span className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{ds.name}</span>
                                                    {ds.description && (
                                                        <span className="text-xs ml-2" style={{ color: "var(--text-tertiary)" }}>{ds.description}</span>
                                                    )}
                                                </div>
                                                <span className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}>
                                                    {ds.template}
                                                </span>
                                            </div>
                                            <div className="flex items-center justify-between">
                                                <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{ds.sample_count} samples</span>
                                                <button
                                                    onClick={() => handleGenerate(ds.id)}
                                                    disabled={loading}
                                                    className="btn-ghost px-3 py-1 text-xs rounded-lg"
                                                    style={{ opacity: loading ? 0.5 : 1 }}
                                                >
                                                    {loading ? "Generating..." : "Auto-Generate Pairs"}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    )}

                    {/* ── Training Tab ───────────────────────────── */}
                    {tab === "training" && (
                        <div className="glass rounded-xl p-6">
                            <h3 className="text-sm font-medium mb-4" style={{ color: "var(--text-secondary)" }}>Configure Training Job</h3>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Dataset</label>
                                    <select
                                        value={trainDatasetId} onChange={e => setTrainDatasetId(e.target.value)}
                                        className="w-full px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    >
                                        <option value="">Select dataset...</option>
                                        {datasets.map(ds => (
                                            <option key={ds.id} value={ds.id}>{ds.name} ({ds.sample_count} samples)</option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Adapter Name</label>
                                    <input
                                        value={adapterName} onChange={e => setAdapterName(e.target.value)}
                                        placeholder="clinical-lora-v1"
                                        className="w-full px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    />
                                </div>
                                <div>
                                    <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>LoRA Rank</label>
                                    <select
                                        value={loraRank} onChange={e => setLoraRank(Number(e.target.value))}
                                        className="w-full px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    >
                                        {[4, 8, 16, 32, 64].map(r => <option key={r} value={r}>{r}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Epochs</label>
                                    <select
                                        value={numEpochs} onChange={e => setNumEpochs(Number(e.target.value))}
                                        className="w-full px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    >
                                        {[1, 2, 3, 5, 10].map(e => <option key={e} value={e}>{e}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="text-xs block mb-1" style={{ color: "var(--text-tertiary)" }}>Learning Rate</label>
                                    <select
                                        value={lr} onChange={e => setLr(Number(e.target.value))}
                                        className="w-full px-3 py-2 rounded-lg text-sm"
                                        style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
                                    >
                                        {[1e-5, 5e-5, 1e-4, 2e-4, 5e-4].map(v => (
                                            <option key={v} value={v}>{v.toExponential(0)}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <button
                                onClick={handleStartTraining}
                                disabled={loading || !trainDatasetId}
                                className="btn-primary mt-6 w-full py-3 rounded-lg text-sm font-medium"
                                style={{ opacity: loading || !trainDatasetId ? 0.5 : 1 }}
                            >
                                {loading ? "Starting..." : "🚀 Start Training"}
                            </button>
                        </div>
                    )}

                    {/* ── Models Tab ─────────────────────────────── */}
                    {tab === "models" && (
                        <>
                            {models.length === 0 ? (
                                <div className="glass rounded-xl p-8 text-center">
                                    <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                                        No adapters registered yet. Complete a training job to create one.
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {models.map(m => (
                                        <div key={m.id} className="glass rounded-xl p-4 animate-fade-in">
                                            <div className="flex items-center justify-between mb-2">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>
                                                        {m.name}
                                                    </span>
                                                    <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--bg-tertiary)", color: "var(--text-tertiary)" }}>
                                                        v{m.version}
                                                    </span>
                                                    {m.is_active && (
                                                        <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: "rgba(16,185,129,0.15)", color: "#10b981" }}>
                                                            Active
                                                        </span>
                                                    )}
                                                </div>
                                                <button
                                                    onClick={() => handleDeploy(m.id, m.is_active)}
                                                    className="px-3 py-1 rounded-lg text-xs font-medium transition-all"
                                                    style={{
                                                        background: m.is_active ? "rgba(239,68,68,0.1)" : "rgba(99,102,241,0.1)",
                                                        color: m.is_active ? "#ef4444" : "#6366f1",
                                                    }}
                                                >
                                                    {m.is_active ? "Undeploy" : "Deploy"}
                                                </button>
                                            </div>
                                            <div className="flex gap-6 text-xs" style={{ color: "var(--text-tertiary)" }}>
                                                <span>LoRA r={m.lora_rank}</span>
                                                {m.training_loss != null && <span>Loss: {m.training_loss.toFixed(4)}</span>}
                                                <span>{m.dataset_name || "—"}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    )}

                    {/* ── Logs Tab ───────────────────────────────── */}
                    {tab === "logs" && (
                        <>
                            {jobs.length === 0 ? (
                                <div className="glass rounded-xl p-8 text-center">
                                    <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                                        No training jobs yet. Start one from the Training tab.
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {jobs.map(job => (
                                        <div key={job.id} className="glass rounded-xl p-4 animate-fade-in">
                                            <div className="flex items-center justify-between mb-2">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{job.adapter_name}</span>
                                                    <span
                                                        className="text-xs px-2 py-0.5 rounded-full font-medium"
                                                        style={{
                                                            background: job.status === "completed" ? "rgba(16,185,129,0.15)"
                                                                : job.status === "running" ? "rgba(99,102,241,0.15)"
                                                                    : job.status === "failed" ? "rgba(239,68,68,0.15)"
                                                                        : "rgba(255,255,255,0.05)",
                                                            color: job.status === "completed" ? "#10b981"
                                                                : job.status === "running" ? "#6366f1"
                                                                    : job.status === "failed" ? "#ef4444"
                                                                        : "var(--text-tertiary)",
                                                        }}
                                                    >
                                                        {job.status}
                                                    </span>
                                                </div>
                                                <button
                                                    onClick={() => handleViewJob(job.id)}
                                                    className="btn-ghost px-3 py-1 text-xs rounded-lg"
                                                >
                                                    View Details
                                                </button>
                                            </div>
                                            <div className="flex gap-6 text-xs" style={{ color: "var(--text-tertiary)" }}>
                                                <span>r={job.lora_rank}</span>
                                                {job.final_loss != null && <span>Final loss: {job.final_loss.toFixed(4)}</span>}
                                                {job.duration != null && <span>Duration: {Math.round(job.duration)}s</span>}
                                            </div>
                                        </div>
                                    ))}

                                    {/* Selected job detail */}
                                    {selectedJob && (
                                        <div className="glass rounded-xl p-5 animate-scale-in">
                                            <div className="flex items-center justify-between mb-4">
                                                <h3 className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                                                    {selectedJob.adapter_name} — Training Curve
                                                </h3>
                                                <button onClick={() => setSelectedJob(null)} className="btn-ghost px-2 py-1 text-xs rounded">✕</button>
                                            </div>
                                            <LossChart metrics={selectedJob.metrics} />
                                            <div className="grid grid-cols-3 gap-3 mt-4">
                                                <div className="text-center p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                                    <p className="text-lg font-bold" style={{ color: "#6366f1" }}>
                                                        {selectedJob.config.lora_rank}
                                                    </p>
                                                    <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>LoRA Rank</p>
                                                </div>
                                                <div className="text-center p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                                    <p className="text-lg font-bold" style={{ color: "#06b6d4" }}>
                                                        {selectedJob.config.num_epochs}
                                                    </p>
                                                    <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Epochs</p>
                                                </div>
                                                <div className="text-center p-3 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                                                    <p className="text-lg font-bold" style={{ color: "#10b981" }}>
                                                        {selectedJob.final_loss?.toFixed(4) ?? "—"}
                                                    </p>
                                                    <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Final Loss</p>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </>
                    )}

                </div>
            </div>
        </div>
    );
}
