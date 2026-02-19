"use client";

import React, { useState, useRef, useEffect } from "react";
import { sendMessageStream, type StreamEvent, type ReasoningStep, type SourceReference } from "@/lib/api";
import ReasoningStepsComponent from "@/components/ReasoningSteps";

// ── Icons ───────────────────────────────────────────────

const SendIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
);

const BotIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="10" rx="2" />
        <circle cx="12" cy="5" r="3" />
        <line x1="12" y1="8" x2="12" y2="11" />
        <line x1="8" y1="16" x2="8" y2="16" />
        <line x1="16" y1="16" x2="16" y2="16" />
    </svg>
);

const UserIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
    </svg>
);

const SourceIcon = () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
    </svg>
);

// ── Types ───────────────────────────────────────────────

interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    sources?: SourceReference[];
    reasoning?: ReasoningStep[];
    isStreaming?: boolean;
}

interface ChatInterfaceProps {
    sessionId?: string;
    onSessionCreated: (sessionId: string) => void;
}

// ── Component ───────────────────────────────────────────

export default function ChatInterface({ sessionId, onSessionCreated }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [currentReasoning, setCurrentReasoning] = useState<ReasoningStep[]>([]);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, currentReasoning]);

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    async function handleSend() {
        const trimmed = input.trim();
        if (!trimmed || isLoading) return;

        const userMsg: Message = {
            id: crypto.randomUUID(),
            role: "user",
            content: trimmed,
        };

        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setIsLoading(true);
        setCurrentReasoning([]);

        // Prepare streaming assistant message
        const assistantId = crypto.randomUUID();
        let assistantContent = "";
        let collectedSources: SourceReference[] = [];

        setMessages((prev) => [
            ...prev,
            { id: assistantId, role: "assistant", content: "", isStreaming: true },
        ]);

        try {
            await sendMessageStream(trimmed, sessionId, (event: StreamEvent) => {
                switch (event.type) {
                    case "reasoning":
                        setCurrentReasoning((prev) => {
                            const existing = prev.findIndex((s) => s.step === event.step);
                            const step: ReasoningStep = {
                                step: event.step!,
                                title: event.title || "",
                                description: event.description || "",
                                status: (event.status as "pending" | "running" | "done") || "pending",
                            };
                            if (existing >= 0) {
                                const updated = [...prev];
                                updated[existing] = step;
                                return updated;
                            }
                            return [...prev, step];
                        });
                        break;

                    case "source":
                        if (event.sources) {
                            collectedSources = event.sources;
                        }
                        break;

                    case "token":
                        assistantContent += event.content || "";
                        setMessages((prev) =>
                            prev.map((m) =>
                                m.id === assistantId
                                    ? { ...m, content: assistantContent, isStreaming: true }
                                    : m
                            )
                        );
                        break;

                    case "done":
                        if (event.session_id) {
                            onSessionCreated(event.session_id);
                        }
                        setMessages((prev) =>
                            prev.map((m) =>
                                m.id === assistantId
                                    ? {
                                        ...m,
                                        content: assistantContent,
                                        sources: collectedSources,
                                        reasoning: [...(currentReasoning || [])],
                                        isStreaming: false,
                                    }
                                    : m
                            )
                        );
                        break;

                    case "error":
                        setMessages((prev) =>
                            prev.map((m) =>
                                m.id === assistantId
                                    ? { ...m, content: `⚠️ ${event.content}`, isStreaming: false }
                                    : m
                            )
                        );
                        break;
                }
            });
        } catch (err: any) {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantId
                        ? { ...m, content: `⚠️ Error: ${err.message}`, isStreaming: false }
                        : m
                )
            );
        } finally {
            setIsLoading(false);
            setCurrentReasoning([]);
        }
    }

    function handleKeyDown(e: React.KeyboardEvent) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }

    // ── Empty State ───────────────────────────────────────

    if (messages.length === 0) {
        return (
            <div className="flex flex-col h-full">
                <div className="flex-1 flex items-center justify-center">
                    <div className="text-center max-w-md px-6 animate-fade-in">
                        <div
                            className="w-16 h-16 mx-auto mb-5 rounded-2xl flex items-center justify-center"
                            style={{
                                background: "linear-gradient(135deg, var(--primary), var(--accent))",
                            }}
                        >
                            <BotIcon />
                        </div>
                        <h2 className="text-2xl font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
                            Clinical GraphRAG Pro
                        </h2>
                        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
                            Ask questions about your uploaded medical documents.
                            AI-powered analysis with source citations and chain-of-thought reasoning.
                        </p>

                        {/* Quick prompts */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {[
                                "What are the side effects of metformin?",
                                "Explain hypertension treatment guidelines",
                                "Summarize the uploaded clinical trial data",
                                "What drug interactions should I watch for?",
                            ].map((prompt) => (
                                <button
                                    key={prompt}
                                    onClick={() => {
                                        setInput(prompt);
                                        inputRef.current?.focus();
                                    }}
                                    className="glass glass-hover rounded-lg p-3 text-left text-xs transition-all"
                                    style={{ color: "var(--text-secondary)" }}
                                >
                                    {prompt}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Input */}
                <div className="p-4 border-t" style={{ borderColor: "var(--border)" }}>
                    <div className="flex gap-2 max-w-3xl mx-auto">
                        <textarea
                            ref={inputRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Ask a medical question..."
                            rows={1}
                            className="input-field flex-1 resize-none"
                            style={{ minHeight: "44px", maxHeight: "120px" }}
                        />
                        <button
                            onClick={handleSend}
                            disabled={!input.trim() || isLoading}
                            className="btn-primary px-4 flex items-center justify-center disabled:opacity-50"
                        >
                            <SendIcon />
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── Chat View ─────────────────────────────────────────

    return (
        <div className="flex flex-col h-full">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-4 py-6">
                <div className="max-w-3xl mx-auto space-y-4">
                    {messages.map((msg) => (
                        <div key={msg.id} className="animate-fade-in">
                            {/* Message */}
                            <div className="flex gap-3">
                                {/* Avatar */}
                                <div
                                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
                                    style={{
                                        background:
                                            msg.role === "user"
                                                ? "var(--bg-tertiary)"
                                                : "linear-gradient(135deg, var(--primary), var(--accent))",
                                        color: msg.role === "user" ? "var(--text-secondary)" : "white",
                                    }}
                                >
                                    {msg.role === "user" ? <UserIcon /> : <BotIcon />}
                                </div>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                    <p
                                        className="text-xs font-medium mb-1"
                                        style={{ color: "var(--text-tertiary)" }}
                                    >
                                        {msg.role === "user" ? "You" : "Clinical AI"}
                                    </p>

                                    {/* Reasoning Steps (for assistant with active reasoning) */}
                                    {msg.role === "assistant" && msg.reasoning && msg.reasoning.length > 0 && (
                                        <ReasoningStepsComponent steps={msg.reasoning} />
                                    )}

                                    <div
                                        className="prose text-sm"
                                        style={{ color: "var(--text-primary)" }}
                                    >
                                        {msg.content || (
                                            <span className="flex gap-1">
                                                <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                                                <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                                                <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                                            </span>
                                        )}
                                        {msg.isStreaming && (
                                            <span
                                                className="inline-block w-2 h-4 ml-0.5"
                                                style={{
                                                    background: "var(--primary)",
                                                    animation: "pulse-dot 1s ease-in-out infinite",
                                                }}
                                            />
                                        )}
                                    </div>

                                    {/* Sources */}
                                    {msg.sources && msg.sources.length > 0 && !msg.isStreaming && (
                                        <div className="mt-3">
                                            <p
                                                className="text-xs font-medium uppercase tracking-wider mb-1.5"
                                                style={{ color: "var(--text-tertiary)" }}
                                            >
                                                Sources
                                            </p>
                                            <div className="flex flex-wrap gap-1.5">
                                                {msg.sources.map((src, i) => (
                                                    <span
                                                        key={i}
                                                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs"
                                                        style={{
                                                            background: "var(--bg-tertiary)",
                                                            color: "var(--accent)",
                                                            border: "1px solid var(--border)",
                                                        }}
                                                        title={src.text}
                                                    >
                                                        <SourceIcon />
                                                        {src.document_name} · #{src.chunk_index}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}

                    {/* Live Reasoning Steps */}
                    {isLoading && currentReasoning.length > 0 && (
                        <div className="ml-11">
                            <ReasoningStepsComponent steps={currentReasoning} />
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>
            </div>

            {/* Input */}
            <div className="p-4 border-t" style={{ borderColor: "var(--border)" }}>
                <div className="flex gap-2 max-w-3xl mx-auto">
                    <textarea
                        ref={inputRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask a follow-up question..."
                        rows={1}
                        className="input-field flex-1 resize-none"
                        style={{ minHeight: "44px", maxHeight: "120px" }}
                        disabled={isLoading}
                    />
                    <button
                        onClick={handleSend}
                        disabled={!input.trim() || isLoading}
                        className="btn-primary px-4 flex items-center justify-center disabled:opacity-50"
                    >
                        {isLoading ? (
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: "spin 1s linear infinite" }}>
                                <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
                            </svg>
                        ) : (
                            <SendIcon />
                        )}
                    </button>
                </div>
                <p className="text-center text-xs mt-2" style={{ color: "var(--text-tertiary)" }}>
                    Clinical GraphRAG Pro — AI-powered medical document analysis
                </p>
            </div>
        </div>
    );
}
