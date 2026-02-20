"use client";

import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendMessageStream, getSession, type StreamEvent, type ReasoningStep, type SourceReference, uploadImage, uploadDocument, uploadAudioForTranscription, type MedicalImageInfo } from "@/lib/api";
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

const PaperclipIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
);

const ImageIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <polyline points="21 15 16 10 5 21" />
    </svg>
);

const DocIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
    </svg>
);

const MicIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" x2="12" y1="19" y2="22" />
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
    attachment?: { id: string, name: string, type: "image" | "document" };
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
    const [attachedFile, setAttachedFile] = useState<{ id: string, name: string, type: "image" | "document" } | null>(null);
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const docInputRef = useRef<HTMLInputElement>(null);
    const audioInputRef = useRef<HTMLInputElement>(null);
    const [isRecording, setIsRecording] = useState(false);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunksRef = useRef<Blob[]>([]);

    const isStreamingRef = useRef(false);

    useEffect(() => {
        if (sessionId && messages.length === 0) {
            setIsLoading(true);
            getSession(sessionId)
                .then((res) => {
                    const loadedMessages: Message[] = res.messages.map((m: any) => ({
                        id: m.id,
                        role: m.role as "user" | "assistant",
                        content: m.content,
                        sources: m.sources,
                        reasoning: m.reasoning_steps,
                        isStreaming: false
                    }));
                    setMessages(loadedMessages);
                })
                .catch(console.error)
                .finally(() => setIsLoading(false));
        }
    }, [sessionId]);

    useEffect(() => {
        const behavior = isStreamingRef.current ? "auto" : "smooth";
        messagesEndRef.current?.scrollIntoView({ behavior });
    }, [messages, currentReasoning]);

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>, type: 'image' | 'document' | 'audio') {
        const file = e.target.files?.[0];
        if (!file) return;

        setIsMenuOpen(false);
        setIsUploading(true);
        try {
            if (type === 'image') {
                const res = await uploadImage(file);
                setAttachedFile({ id: res.id, name: (res as any).original_filename || res.filename || file.name, type: 'image' });
            } else if (type === 'document') {
                const res = await uploadDocument(file);
                setAttachedFile({ id: res.id, name: res.filename || file.name, type: 'document' });
            } else if (type === 'audio') {
                const res = await uploadAudioForTranscription(file);
                setInput((prev) => prev ? prev + " " + res.text : res.text);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setIsUploading(false);
            if (e.target) e.target.value = "";
        }
    }

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream);
            mediaRecorderRef.current = mediaRecorder;
            audioChunksRef.current = [];

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    audioChunksRef.current.push(e.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
                setIsUploading(true);
                try {
                    const res = await uploadAudioForTranscription(audioBlob);
                    setInput((prev) => prev ? prev + " " + res.text : res.text);
                } catch (err) {
                    console.error("Transcription failed", err);
                } finally {
                    setIsUploading(false);
                }
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start();
            setIsRecording(true);
        } catch (err) {
            console.error("Microphone access denied or error:", err);
            alert("Could not access microphone.");
        }
    }

    function stopRecording() {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop();
            setIsRecording(false);
        }
    }

    function toggleRecording() {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    }

    async function handleSend() {
        const trimmed = input.trim();
        if ((!trimmed && !attachedFile) || isLoading || isUploading) return;

        const currentAttachment = attachedFile ? { ...attachedFile } : undefined;
        const msgContent = trimmed || (currentAttachment?.type === 'image' ? "Analyze this image." : "Analyze this document.");

        const userMsg: Message = {
            id: crypto.randomUUID(),
            role: "user",
            content: msgContent,
            attachment: currentAttachment,
        };

        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setAttachedFile(null);
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

        isStreamingRef.current = true;

        try {
            let imgId = currentAttachment?.type === 'image' ? currentAttachment.id : undefined;
            // The sendMessageStream signature in api.ts takes attachedImageId as the 4th param.
            // But we actually need to pass attached_document_id as well.
            // wait, we need to modify api.ts to accept attachedDocumentId too. Let's do that right after this.
            // For now, if we pass attachedDocumentId we might need to change the API call directly or modify api.ts.
            // I will modify api.ts directly after this, so I will pass an object instead or pass a 5th param. Let's pass 5th param.

            await sendMessageStream(
                msgContent,
                sessionId,
                (event: StreamEvent) => {
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
                },
                currentAttachment?.type === 'image' ? currentAttachment.id : undefined,
                currentAttachment?.type === 'document' ? currentAttachment.id : undefined
            );
        } catch (err: any) {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantId
                        ? { ...m, content: `⚠️ Error: ${err.message}`, isStreaming: false }
                        : m
                )
            );
        } finally {
            isStreamingRef.current = false;
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

    // Show empty state only if no messages and not currently loading them
    if (messages.length === 0 && !isLoading) {
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
                    <div className="max-w-3xl mx-auto flex flex-col gap-2">
                        {/* Attachment Preview Container */}
                        {attachedFile && (
                            <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] w-max max-w-full">
                                <div className="p-1.5 rounded-md bg-[var(--primary)]/10 text-[var(--primary)] shrink-0">
                                    {attachedFile.type === 'document' ? <DocIcon /> : <ImageIcon />}
                                </div>
                                <div className="text-xs font-medium text-[var(--text-primary)] truncate">
                                    {attachedFile.name}
                                </div>
                                <button
                                    onClick={() => setAttachedFile(null)}
                                    className="ml-2 w-5 h-5 flex shrink-0 items-center justify-center rounded-full hover:bg-[var(--border)] text-[var(--text-secondary)] transition-colors"
                                >
                                    ✕
                                </button>
                            </div>
                        )}
                        {/* Input Row */}
                        <div className="flex gap-2 relative">
                            <input
                                type="file"
                                className="hidden"
                                ref={fileInputRef}
                                onChange={(e) => handleFileSelect(e, 'image')}
                                accept=".png,.jpg,.jpeg,.webp,.tiff,.dcm"
                            />
                            <input
                                type="file"
                                className="hidden"
                                ref={docInputRef}
                                onChange={(e) => handleFileSelect(e, 'document')}
                                accept=".pdf,.doc,.docx,.txt"
                            />

                            <div className="relative">
                                <button
                                    onClick={() => setIsMenuOpen(!isMenuOpen)}
                                    disabled={isLoading || isUploading}
                                    className="w-[44px] h-[44px] flex-shrink-0 flex items-center justify-center rounded-lg border border-[var(--border)] hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] transition-colors disabled:opacity-50"
                                    title="Attach File"
                                    tabIndex={-1}
                                >
                                    {isUploading ? (
                                        <span className="loading-dot w-2 h-2 rounded-full bg-[var(--text-tertiary)]" />
                                    ) : (
                                        <PaperclipIcon />
                                    )}
                                </button>

                                {isMenuOpen && (
                                    <>
                                        <div className="fixed inset-0 z-40" onClick={() => setIsMenuOpen(false)} />
                                        <div className="absolute bottom-full left-0 mb-2 w-48 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-lg shadow-lg overflow-hidden flex flex-col z-50 animate-fade-in">
                                            <button
                                                onClick={() => { setIsMenuOpen(false); fileInputRef.current?.click(); }}
                                                className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] text-left transition-colors"
                                            >
                                                <ImageIcon /> Upload Image
                                            </button>
                                            <button
                                                onClick={() => { setIsMenuOpen(false); docInputRef.current?.click(); }}
                                                className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] text-left transition-colors border-t border-[var(--border)]"
                                            >
                                                <DocIcon /> Upload Document
                                            </button>
                                            <button
                                                disabled
                                                className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-secondary)] opacity-50 text-left border-t border-[var(--border)] cursor-not-allowed"
                                                title="Voice support coming in next version"
                                            >
                                                <MicIcon /> Record Voice
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>

                            <textarea
                                ref={inputRef}
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder={isRecording ? "Listening..." : "Ask a question or select attachment type..."}
                                rows={1}
                                className="input-field flex-1 resize-none py-3"
                                style={{ minHeight: "44px", maxHeight: "120px" }}
                                disabled={isLoading || isRecording}
                            />
                            <button
                                onClick={toggleRecording}
                                disabled={isLoading || isUploading}
                                className={`w-[44px] h-[44px] flex-shrink-0 flex items-center justify-center rounded-lg border border-[var(--border)] transition-colors ${isRecording ? "bg-red-500/20 text-red-500 border-red-500/50 animate-pulse" : "hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)]"
                                    } disabled:opacity-50`}
                                title={isRecording ? "Stop Recording" : "Record Voice"}
                            >
                                {isRecording ? (
                                    <span className="w-3 h-3 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
                                ) : (
                                    <MicIcon />
                                )}
                            </button>
                            <button
                                onClick={handleSend}
                                disabled={(!input.trim() && !attachedFile) || isLoading || isUploading || isRecording}
                                className="btn-primary px-4 flex-shrink-0 flex items-center justify-center disabled:opacity-50"
                            >
                                <SendIcon />
                            </button>
                        </div>
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

                                    {msg.role === "user" && msg.attachment && (
                                        <div className="mb-2 w-max max-w-[200px] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)]">
                                            <div className="flex items-center gap-2 p-2 px-3 text-xs text-[var(--text-primary)] bg-[var(--primary)]/10 truncate">
                                                {msg.attachment.type === 'document' ? <DocIcon /> : <ImageIcon />} {msg.attachment.name}
                                            </div>
                                        </div>
                                    )}

                                    {/* Reasoning Steps (for assistant with active reasoning) */}
                                    {msg.role === "assistant" && msg.reasoning && msg.reasoning.length > 0 && (
                                        <ReasoningStepsComponent steps={msg.reasoning} />
                                    )}

                                    <div
                                        className="prose text-sm"
                                        style={{ color: "var(--text-primary)" }}
                                    >
                                        {msg.content ? (
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                {msg.content}
                                            </ReactMarkdown>
                                        ) : (
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
                <div className="max-w-3xl mx-auto flex flex-col gap-2">
                    {/* Attachment Preview Container */}
                    {attachedFile && (
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] w-max max-w-full">
                            <div className="p-1.5 rounded-md bg-[var(--primary)]/10 text-[var(--primary)] shrink-0">
                                {attachedFile.type === 'document' ? <DocIcon /> : <ImageIcon />}
                            </div>
                            <div className="text-xs font-medium text-[var(--text-primary)] truncate">
                                {attachedFile.name}
                            </div>
                            <button
                                onClick={() => setAttachedFile(null)}
                                className="ml-2 w-5 h-5 flex shrink-0 items-center justify-center rounded-full hover:bg-[var(--border)] text-[var(--text-secondary)] transition-colors"
                            >
                                ✕
                            </button>
                        </div>
                    )}
                    <div className="flex gap-2 relative">
                        <input
                            type="file"
                            className="hidden"
                            ref={fileInputRef}
                            onChange={(e) => handleFileSelect(e, 'image')}
                            accept=".png,.jpg,.jpeg,.webp,.tiff,.dcm"
                        />
                        <input
                            type="file"
                            className="hidden"
                            ref={docInputRef}
                            onChange={(e) => handleFileSelect(e, 'document')}
                            accept=".pdf,.doc,.docx,.txt"
                        />
                        <input
                            type="file"
                            className="hidden"
                            ref={audioInputRef}
                            onChange={(e) => handleFileSelect(e, 'audio')}
                            accept="audio/*"
                        />

                        <div className="relative">
                            <button
                                onClick={() => setIsMenuOpen(!isMenuOpen)}
                                disabled={isLoading || isUploading}
                                className="w-[44px] h-[44px] flex-shrink-0 flex items-center justify-center rounded-lg border border-[var(--border)] hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] transition-colors disabled:opacity-50"
                                title="Attach File"
                            >
                                {isUploading ? (
                                    <span className="loading-dot w-2 h-2 rounded-full bg-[var(--text-tertiary)]" />
                                ) : (
                                    <PaperclipIcon />
                                )}
                            </button>

                            {isMenuOpen && (
                                <>
                                    <div className="fixed inset-0 z-40" onClick={() => setIsMenuOpen(false)} />
                                    <div className="absolute bottom-full left-0 mb-2 w-48 bg-[var(--bg-elevated)] border border-[var(--border)] rounded-lg shadow-lg overflow-hidden flex flex-col z-50 animate-fade-in">
                                        <button
                                            onClick={() => { setIsMenuOpen(false); fileInputRef.current?.click(); }}
                                            className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] text-left transition-colors"
                                        >
                                            <ImageIcon /> Upload Image
                                        </button>
                                        <button
                                            onClick={() => { setIsMenuOpen(false); docInputRef.current?.click(); }}
                                            className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] text-left transition-colors border-t border-[var(--border)]"
                                        >
                                            <DocIcon /> Upload Document
                                        </button>
                                        <button
                                            onClick={() => { setIsMenuOpen(false); audioInputRef.current?.click(); }}
                                            className="flex items-center gap-3 px-4 py-3 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] text-left transition-colors border-t border-[var(--border)]"
                                        >
                                            <MicIcon /> Upload Audio
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                        <textarea
                            ref={inputRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={isRecording ? "Listening..." : "Ask a follow-up question or attach a file..."}
                            rows={1}
                            className="input-field flex-1 resize-none py-3"
                            style={{ minHeight: "44px", maxHeight: "120px" }}
                            disabled={isLoading || isRecording}
                        />
                        <button
                            onClick={toggleRecording}
                            disabled={isLoading || isUploading}
                            className={`w-[44px] h-[44px] flex-shrink-0 flex items-center justify-center rounded-lg border border-[var(--border)] transition-colors ${isRecording ? "bg-red-500/20 text-red-500 border-red-500/50 animate-pulse" : "hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)]"
                                } disabled:opacity-50`}
                            title={isRecording ? "Stop Recording" : "Record Voice"}
                        >
                            {isRecording ? (
                                <span className="w-3 h-3 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
                            ) : (
                                <MicIcon />
                            )}
                        </button>
                        <button
                            onClick={handleSend}
                            disabled={(!input.trim() && !attachedFile) || isLoading || isUploading || isRecording}
                            className="btn-primary px-4 flex-shrink-0 flex items-center justify-center disabled:opacity-50"
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
                </div>
                <p className="text-center text-xs mt-2" style={{ color: "var(--text-tertiary)" }}>
                    Clinical GraphRAG Pro — AI-powered medical document analysis
                </p>
            </div>
        </div>
    );
}
