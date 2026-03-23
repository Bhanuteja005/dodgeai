"use client";

import dynamic from "next/dynamic";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PanelLeft, Maximize2, Minimize2, Layers, User, X } from "lucide-react";

type GraphNode = {
    id: string;
    type: string;
    label: string;
    metadata: Record<string, unknown>;
    color?: string;
    x?: number;
    y?: number;
};

type GraphEdge = {
    source: string | GraphNode;
    target: string | GraphNode;
    source_type: string;
    target_type: string;
    relationship_label: string;
};

type ChatMessage = {
    id: string;
    role: "user" | "assistant";
    text: string;
    graphNodeIds?: string[];
};

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const edgeKey = (edge: GraphEdge): string => {
    const source = typeof edge.source === "string" ? edge.source : edge.source.id;
    const target = typeof edge.target === "string" ? edge.target : edge.target.id;
    return `${source}|${target}|${edge.relationship_label}`;
};

type DashboardTheme = "dark" | "light";

const calculateDegrees = (edges: GraphEdge[]) => {
    const degrees = new Map<string, number>();
    for (const edge of edges) {
        const source = typeof edge.source === "string" ? edge.source : edge.source.id;
        const target = typeof edge.target === "string" ? edge.target : edge.target.id;
        degrees.set(source, (degrees.get(source) || 0) + 1);
        degrees.set(target, (degrees.get(target) || 0) + 1);
    }
    return degrees;
};

const sanitizeGraph = (nodes: GraphNode[], edges: GraphEdge[]) => {
    const nodeSet = new Set(nodes.map((node) => node.id));
    const filteredEdges = edges.filter((edge) => {
        const source = typeof edge.source === "string" ? edge.source : edge.source.id;
        const target = typeof edge.target === "string" ? edge.target : edge.target.id;
        return nodeSet.has(source) && nodeSet.has(target);
    });
    return { nodes, edges: filteredEdges };
};

const nodeChipLabel = (nodeId: string): string => {
    const parts = nodeId.split("::");
    if (parts.length < 2) {
        return nodeId;
    }
    const entity = parts[0].replaceAll("_", " ");
    const tail = parts.slice(1).join("/");
    return `${entity}: ${tail}`;
};

const Dashboard = () => {
    const fgRef = useRef<any>(null);
    const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
    const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
    const [nodeDegrees, setNodeDegrees] = useState<Map<string, number>>(new Map());
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [isGraphMinimized, setIsGraphMinimized] = useState(false);
    const [hideGranularOverlay, setHideGranularOverlay] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([
        {
            id: "init",
            role: "assistant",
            text: "Hi! I can help you analyze the Order to Cash process.",
        },
    ]);
    const [input, setInput] = useState("");
    const [isSending, setIsSending] = useState(false);
    const [theme, setTheme] = useState<DashboardTheme>("light");
    const [graphNotice, setGraphNotice] = useState<string>("");
    const [chatError, setChatError] = useState<string>("");
    const [apiStatus, setApiStatus] = useState<string>("unknown");

    useEffect(() => {
        const stored = window.localStorage.getItem("dashboard-theme");
        if (stored === "dark" || stored === "light") {
            setTheme(stored);
        } else {
            setTheme("light");
        }
    }, []);

    const toggleTheme = useCallback(() => {
        setTheme((prev) => {
            const next: DashboardTheme = prev === "dark" ? "light" : "dark";
            window.localStorage.setItem("dashboard-theme", next);
            return next;
        });
    }, []);

    const loadGraph = useCallback(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/graph?limit=1200`);
            if (!resp.ok) {
                setApiStatus("unavailable");
                const body = (await resp.json().catch(() => ({}))) as { detail?: string };
                setGraphNotice(body.detail || "Graph data is not available yet.");
                return;
            }

            const data = (await resp.json()) as { nodes: GraphNode[]; edges: GraphEdge[] };
            const safeData = sanitizeGraph(data.nodes ?? [], data.edges ?? []);

            setApiStatus("ok");
            setGraphNodes(safeData.nodes);
            setGraphEdges(safeData.edges);
            setNodeDegrees(calculateDegrees(safeData.edges));
            setGraphNotice("");
        } catch (err) {
            console.error("Graph load failed", err);
            setApiStatus("down");
            setGraphNotice("Backend is unreachable. Start backend at http://localhost:8000.");
        }

        setTimeout(() => {
            fgRef.current?.zoomToFit?.(500, 40);
        }, 100);
    }, []);

    useEffect(() => {
        loadGraph();
    }, [loadGraph]);

    const expandNode = useCallback(async (node: GraphNode) => {
        if (selectedNode?.id === node.id) {
            setSelectedNode(null);
            return;
        }

        setSelectedNode(node);
        const response = await fetch(`${API_BASE}/api/graph/node/${encodeURIComponent(node.id)}`);
        if (!response.ok) {
            return;
        }

        const details = (await response.json()) as {
            metadata: Record<string, unknown>;
            neighbors: GraphNode[];
            edges: Array<{
                source_id: string;
                target_id: string;
                source_type: string;
                target_type: string;
                relationship_label: string;
            }>;
        };

        setSelectedNode((prev) => {
            if (!prev) {
                return prev;
            }
            return {
                ...prev,
                metadata: details.metadata,
            };
        });

        setGraphNodes((prev) => {
            const byId = new Map(prev.map((existing) => [existing.id, existing]));
            details.neighbors.forEach((neighbor) => {
                if (!byId.has(neighbor.id)) {
                    byId.set(neighbor.id, neighbor);
                }
            });
            return Array.from(byId.values());
        });

        setGraphEdges((prev) => {
            const next = [...prev];
            const keys = new Set(prev.map(edgeKey));

            for (const edge of details.edges) {
                const mappedEdge: GraphEdge = {
                    source: edge.source_id,
                    target: edge.target_id,
                    source_type: edge.source_type,
                    target_type: edge.target_type,
                    relationship_label: edge.relationship_label,
                };
                const key = edgeKey(mappedEdge);
                if (!keys.has(key)) {
                    keys.add(key);
                    next.push(mappedEdge);
                }
            }

            const existingNodeIds = new Set([
                ...graphNodes.map((n) => n.id),
                ...details.neighbors.map((n) => n.id),
                node.id,
            ]);

            const safeNext = next.filter((edge) => {
                const source = typeof edge.source === "string" ? edge.source : edge.source.id;
                const target = typeof edge.target === "string" ? edge.target : edge.target.id;
                return existingNodeIds.has(source) && existingNodeIds.has(target);
            });

            setNodeDegrees(calculateDegrees(safeNext));
            return safeNext;
        });
    }, [graphNodes, selectedNode]);

    const focusNodeById = useCallback(async (nodeId: string) => {
        const found = graphNodes.find((node) => node.id === nodeId);
        if (found) {
            await expandNode(found);
            setTimeout(() => {
                fgRef.current?.zoom?.(3, 500);
            }, 120);
            return;
        }

        const response = await fetch(`${API_BASE}/api/graph/node/${encodeURIComponent(nodeId)}`);
        if (!response.ok) {
            return;
        }

        const details = (await response.json()) as {
            id: string;
            type: string;
            label: string;
            metadata: Record<string, unknown>;
            neighbors: GraphNode[];
            edges: Array<{
                source_id: string;
                target_id: string;
                source_type: string;
                target_type: string;
                relationship_label: string;
            }>;
        };

        const primaryNode: GraphNode = {
            id: details.id,
            type: details.type,
            label: details.label,
            metadata: details.metadata,
        };

        setSelectedNode(primaryNode);
        setGraphNodes((prev) => {
            const byId = new Map(prev.map((existing) => [existing.id, existing]));
            byId.set(primaryNode.id, primaryNode);
            details.neighbors.forEach((neighbor) => {
                if (!byId.has(neighbor.id)) {
                    byId.set(neighbor.id, neighbor);
                }
            });
            return Array.from(byId.values());
        });

        setGraphEdges((prev) => {
            const next = [...prev];
            const keys = new Set(prev.map(edgeKey));
            for (const edge of details.edges) {
                const mappedEdge: GraphEdge = {
                    source: edge.source_id,
                    target: edge.target_id,
                    source_type: edge.source_type,
                    target_type: edge.target_type,
                    relationship_label: edge.relationship_label,
                };
                const key = edgeKey(mappedEdge);
                if (!keys.has(key)) {
                    keys.add(key);
                    next.push(mappedEdge);
                }
            }
            setNodeDegrees(calculateDegrees(next));
            return next;
        });

        setTimeout(() => {
            fgRef.current?.zoom?.(3, 500);
        }, 120);
    }, [expandNode, graphNodes]);

    const submitQuestion = useCallback(
        async (event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const trimmed = input.trim();
            if (!trimmed || isSending) {
                return;
            }

            const userMsg: ChatMessage = {
                id: `u-${Date.now()}`,
                role: "user",
                text: trimmed,
            };

            setMessages((prev) => [...prev, userMsg]);
            setInput("");
            setIsSending(true);

            try {
                const resp = await fetch(`${API_BASE}/api/chat`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ message: trimmed }),
                });

                if (!resp.ok) {
                    throw new Error("chat request failed");
                }

                const data = (await resp.json()) as { answer: string; graph_node_ids?: string[] };
                const mappedNodeIds = data.graph_node_ids ?? [];
                setMessages((prev) => [
                    ...prev,
                    {
                        id: `a-${Date.now()}`,
                        role: "assistant",
                        text: data.answer,
                        graphNodeIds: mappedNodeIds,
                    },
                ]);

                if (mappedNodeIds.length > 0) {
                    void focusNodeById(mappedNodeIds[0]);
                }
            } catch {
                setMessages((prev) => [
                    ...prev,
                    {
                        id: `a-${Date.now()}`,
                        role: "assistant",
                        text: "I could not process that query right now. Please try again.",
                    },
                ]);
            } finally {
                setIsSending(false);
            }
        },
        [focusNodeById, input, isSending],
    );

    const metadataEntries = useMemo(() => {
        if (!selectedNode) {
            return [];
        }
        return Object.entries(selectedNode.metadata).slice(0, 10);
    }, [selectedNode]);

    const isDark = theme === "dark";

    const shellClass = isDark
        ? "flex h-screen w-full flex-col overflow-hidden bg-black text-slate-100"
        : "flex h-screen w-full flex-col overflow-hidden bg-[#fafafa] text-slate-900";

    const topBarClass = isDark
        ? "flex h-12 shrink-0 items-center justify-between border-b border-white/10 bg-[#0a0a0a] px-5"
        : "flex h-12 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-5";

    const mainContainerClass = "flex flex-row flex-1 overflow-hidden w-full relative";

    return (
        <div className={shellClass}>
            <header className={topBarClass}>
                <div className="flex items-center gap-3">
                    <PanelLeft size={18} className={isDark ? "text-gray-400" : "text-gray-500"} />
                    <div className={isDark ? "h-4 w-[1px] bg-gray-700" : "h-4 w-[1px] bg-gray-200"} />
                    <p className={isDark ? "text-[13px] font-medium text-gray-400" : "text-[13px] font-medium text-gray-400"}>
                        Mapping <span className="mx-1">/</span> <span className={isDark ? "text-white font-semibold" : "text-gray-900 font-semibold"}>Order to Cash</span>
                    </p>
                </div>
                <button
                    className={isDark
                        ? "rounded-md px-3 py-1.5 text-[11px] font-semibold text-gray-400 hover:text-white transition-colors"
                        : "rounded-md px-3 py-1.5 text-[11px] font-semibold text-gray-400 hover:text-gray-700 transition-colors"
                    }
                    onClick={toggleTheme}
                    type="button"
                >
                    {isDark ? "Light Mode" : "Dark Mode"}
                </button>
            </header>

            <main className={mainContainerClass}>
                <section
                    className={isDark ? "relative flex flex-col bg-[#0a0a0a] min-w-0 overflow-hidden" : "relative flex flex-col bg-white min-w-0 overflow-hidden"}
                    style={{ flexBasis: isGraphMinimized ? "40%" : "65%", flexGrow: 1, flexShrink: 1 }}
                >
                    {graphNotice ? (
                        <div className={isDark
                            ? "absolute right-4 top-4 z-20 max-w-md rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 shadow-lg"
                            : "absolute right-4 top-4 z-20 max-w-md rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 shadow-md"
                        }>
                            {graphNotice}
                        </div>
                    ) : null}

                    <div className="absolute left-6 top-6 z-20 flex gap-2">
                        <button
                            className={isDark
                                ? "flex items-center gap-2 rounded-lg border border-white/15 bg-black px-3.5 py-2 text-[12px] font-semibold text-white shadow-lg hover:bg-white/10 transition-colors"
                                : "flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-[12px] font-semibold text-gray-900 shadow-sm hover:bg-gray-50 transition-colors"
                            }
                            onClick={() => setIsGraphMinimized((prev) => !prev)}
                            type="button"
                        >
                            {isGraphMinimized ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
                            {isGraphMinimized ? "Restore" : "Minimize"}
                        </button>
                        <button
                            className={isDark
                                ? "flex items-center gap-2 rounded-lg bg-white px-3.5 py-2 text-[12px] font-semibold text-black shadow-lg hover:bg-gray-200 transition-colors"
                                : "flex items-center gap-2 rounded-lg bg-black px-3.5 py-2 text-[12px] font-semibold text-white shadow-sm hover:bg-gray-800 transition-colors"
                            }
                            onClick={() => setHideGranularOverlay((prev) => !prev)}
                            type="button"
                        >
                            <Layers size={14} />
                            {hideGranularOverlay ? "Show Granular Overlay" : "Hide Granular Overlay"}
                        </button>
                    </div>

                    <div className="h-full w-full flex-1 relative z-0 min-w-0 overflow-hidden">
                        <ForceGraph2D
                            ref={fgRef}
                            graphData={{ nodes: graphNodes, links: graphEdges }}
                            backgroundColor={isDark ? "#0a0a0a" : "#ffffff"}
                            linkColor={(link: any) => {
                                const sId = typeof link.source === 'string' ? link.source : (link.source as any).id;
                                const tId = typeof link.target === 'string' ? link.target : (link.target as any).id;
                                const isFocused = selectedNode && (sId === selectedNode.id || tId === selectedNode.id);
                                if (isFocused) return isDark ? "#3b82f6" : "#2563eb"; 
                                return isDark ? "rgba(30,58,138,0.5)" : "#c1dbfa";
                            }}
                            linkWidth={(link: any) => {
                                const sId = typeof link.source === 'string' ? link.source : (link.source as any).id;
                                const tId = typeof link.target === 'string' ? link.target : (link.target as any).id;
                                return selectedNode && (sId === selectedNode.id || tId === selectedNode.id) ? 1.5 : 0.8;
                            }}
                            nodeRelSize={4}
                            cooldownTicks={100}
                            linkDirectionalParticles={isDark ? 1 : 0}
                            linkDirectionalParticleWidth={isDark ? 1 : 0}
                            linkDirectionalParticleColor={() => (isDark ? "#3b82f6" : "#8abffc")}
                            onNodeClick={(node) => expandNode(node as GraphNode)}
                            nodeCanvasObject={(node, ctx, globalScale) => {
                                const n = node as GraphNode;
                                const degree = nodeDegrees.get(n.id) || 0;
                                const isSelected = selectedNode?.id === n.id;
                                
                                const isHub = degree > 1;
                                
                                if (isHub) {
                                    ctx.beginPath();
                                    ctx.arc(n.x || 0, n.y || 0, isDark ? 4 : 3.5, 0, 2 * Math.PI, false);
                                    ctx.fillStyle = isDark ? "#3b82f6" : "#2563eb"; 
                                    ctx.fill();
                                    ctx.strokeStyle = isDark ? "#000000" : "#ffffff";
                                    ctx.lineWidth = 0.5;
                                    ctx.stroke();
                                } else {
                                    ctx.beginPath();
                                    ctx.arc(n.x || 0, n.y || 0, isDark ? 1.8 : 1.2, 0, 2 * Math.PI, false);
                                    ctx.fillStyle = isDark ? "#ef4444" : "#ef4444"; 
                                    ctx.fill();
                                    ctx.strokeStyle = isDark ? "#000000" : "#ffffff";
                                    ctx.lineWidth = 0.3;
                                    ctx.stroke();
                                }
                                
                                if (isSelected) {
                                    const selectRadius = isHub ? 5 : 3.5;
                                    ctx.beginPath();
                                    ctx.arc(n.x || 0, n.y || 0, selectRadius, 0, 2 * Math.PI, false);
                                    ctx.strokeStyle = isDark ? "#ffffff" : "#000000";
                                    ctx.lineWidth = 1.5;
                                    ctx.stroke();
                                    
                                    ctx.beginPath();
                                    ctx.arc(n.x || 0, n.y || 0, selectRadius + 1.5, 0, 2 * Math.PI, false);
                                    ctx.fillStyle = isDark ? "rgba(59, 130, 246, 0.2)" : "rgba(37, 99, 235, 0.15)";
                                    ctx.fill();
                                }

                                if (globalScale > 2.5 && isHub) {
                                    const label = n.label.length > 20 ? n.label.slice(0, 20) + '...' : n.label;
                                    ctx.font = `${10 / globalScale}px sans-serif`;
                                    ctx.fillStyle = isDark ? "#6b7280" : "#6b7280";
                                    ctx.fillText(label, (n.x || 0) + 5, (n.y || 0) + 3);
                                }
                            }}
                        />
                    </div>

                    {selectedNode && !hideGranularOverlay ? (
                        <aside className={isDark
                            ? "absolute left-1/2 top-1/2 z-20 w-[340px] max-h-[75vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl bg-[#111111] p-5 shadow-[0_18px_60px_-15px_rgba(0,0,0,0.9)] border border-white/10"
                            : "absolute left-1/2 top-1/2 z-20 w-[340px] max-h-[75vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl bg-white p-5 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] border border-gray-100"
                        }>
                            <button
                                aria-label="Close details"
                                className={isDark
                                    ? "absolute right-3 top-3 rounded-md p-1 text-gray-400 hover:bg-white/10 hover:text-white"
                                    : "absolute right-3 top-3 rounded-md p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                                }
                                onClick={() => setSelectedNode(null)}
                                type="button"
                            >
                                <X size={16} />
                            </button>
                            <h3 className={isDark ? "text-[15px] font-bold text-white mb-4" : "text-[15px] font-bold text-gray-900 mb-4"}>
                                {selectedNode.type}
                            </h3>
                            <div className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-[12.5px] leading-5">
                                <div>
                                    <span className={isDark ? "text-gray-400 w-[120px] shrink-0" : "text-gray-500 w-[120px] shrink-0"}>Entity:</span>
                                </div>
                                <span className={isDark ? "break-words text-gray-200" : "break-words text-gray-800"}>{selectedNode.type}</span>
                                {metadataEntries.map(([key, value]) => (
                                    <div className="contents" key={key}>
                                        <span className={isDark ? "text-gray-400" : "text-gray-500"}>{key}:</span>
                                        <span className={isDark ? "break-all text-gray-200" : "break-all text-gray-800"}>{String(value ?? "-")}</span>
                                    </div>
                                ))}
                            </div>
                            <p className={isDark ? "mt-4 text-[11px] italic text-gray-500" : "mt-4 text-[11px] italic text-gray-400"}>
                                Additional fields hidden for readability
                            </p>
                            <p className={isDark ? "mt-1.5 text-[12px] font-medium text-gray-300" : "mt-1.5 text-[12px] font-medium text-gray-700"}>
                                Connections: {nodeDegrees.get(selectedNode.id) || 0}
                            </p>
                        </aside>
                    ) : null}
                </section>

                <div className={isDark ? "w-[1px] shrink-0 bg-white/10" : "w-[1px] shrink-0 bg-gray-100"} />

                <section className={isDark ? "flex flex-col bg-[#0a0a0a] shrink-0" : "flex flex-col bg-[#fafafa] shrink-0"} style={{ flexBasis: isGraphMinimized ? "60%" : "35%", width: isGraphMinimized ? "60%" : "35%", minWidth: "300px", maxWidth: "420px" }}>
                    <header className={isDark ? "border-b border-white/5 py-4 px-6 shrink-0" : "border-b border-gray-100 py-4 px-6 shrink-0"}>
                        <h2 className={isDark ? "text-[14px] font-bold text-white" : "text-[14px] font-bold text-gray-900"}>Chat with Graph</h2>
                        <p className={isDark ? "text-[12px] font-medium text-gray-500 mt-0.5" : "text-[12px] font-medium text-gray-500 mt-0.5"}>Order to Cash</p>
                    </header>

                    <div className="flex-1 overflow-y-auto px-6 py-8 space-y-7">
                        {apiStatus !== "ok" ? (
                            <div className="rounded-lg border border-red-500 bg-red-50 p-3 text-sm text-red-700">
                                Chat API unavailable. Status: {apiStatus}. Please check backend.
                            </div>
                        ) : null}
                        {chatError ? (
                            <div className="rounded-lg border border-amber-500 bg-amber-50 p-3 text-sm text-amber-800">
                                {chatError}
                            </div>
                        ) : null}
                        {messages.map((message) => (
                            <div key={message.id} className={`flex gap-3 ${message.role === "user" ? "flex-col items-end" : "flex-row items-start"}`}>
                                {message.role === "assistant" && (
                                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-black text-white text-[15px] font-bold mt-1">
                                        D
                                    </div>
                                )}
                                
                                <div className={`flex flex-col ${message.role === "user" ? "items-end" : "items-start w-full"}`}>
                                    <div className="flex items-center gap-2 mb-2">
                                        {message.role === "assistant" ? (
                                            <div className="flex flex-col">
                                                <span className={isDark ? "text-[13.5px] font-bold text-white leading-none" : "text-[13.5px] font-bold text-gray-900 leading-none"}>Dodge AI</span>
                                                <span className={isDark ? "text-[11.5px] text-gray-500 mt-1" : "text-[11.5px] text-gray-500 mt-1"}>Graph Agent</span>
                                            </div>
                                        ) : (
                                            <div className="flex items-center gap-2 flex-row-reverse">
                                                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-500 mt-1">
                                                    <User size={16} />
                                                </div>
                                                <span className={isDark ? "text-[13.5px] font-semibold text-white" : "text-[13.5px] font-semibold text-gray-900"}>You</span>
                                            </div>
                                        )}
                                    </div>
                                    <article
                                        className={`w-full whitespace-pre-wrap break-words px-4 py-3 text-[14px] leading-relaxed ${
                                            message.role === "user"
                                                ? isDark
                                                    ? "rounded-2xl rounded-tr-sm bg-[#1a1a1a] text-white"
                                                    : "rounded-2xl rounded-tr-sm bg-[#111111] text-white"
                                                : isDark
                                                    ? "text-gray-300"
                                                    : "text-gray-800"
                                        }`}
                                    >
                                        {message.text}
                                    </article>
                                    {message.role === "assistant" && (message.graphNodeIds?.length ?? 0) > 0 ? (
                                        <div className="mt-3 flex flex-wrap gap-2">
                                            {message.graphNodeIds?.slice(0, 6).map((nodeId) => (
                                                <button
                                                    className={isDark
                                                        ? "rounded-md border border-blue-400/40 bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-200 hover:bg-blue-500/20"
                                                        : "rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] text-blue-700 hover:bg-blue-100"
                                                    }
                                                    key={nodeId}
                                                    onClick={() => void focusNodeById(nodeId)}
                                                    type="button"
                                                >
                                                    Show in graph: {nodeChipLabel(nodeId)}
                                                </button>
                                            ))}
                                        </div>
                                    ) : null}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="p-5">
                        <form onSubmit={submitQuestion}>
                            <div className={isDark 
                                ? "rounded-xl border border-white/10 bg-[#111111] overflow-hidden" 
                                : "rounded-2xl border border-gray-200 bg-white overflow-hidden shadow-sm"
                            }>
                                <div className={isDark ? "px-4 py-2.5 flex items-center gap-2 border-b border-white/5" : "px-4 py-3 flex items-center gap-2 border-b border-gray-100"}>
                                    <div className="h-2 w-2 rounded-full bg-[#10b981]" />
                                    <span className={isDark ? "text-[12px] font-medium text-gray-400" : "text-[12px] font-medium text-gray-600"}>Dodge AI is awaiting instructions</span>
                                </div>
                                <div className={isDark ? "px-3 pb-3 pt-2" : "px-3 pb-3 pt-2 bg-[#f9f9fb]"}>
                                    <div className={isDark ? "flex bg-[#1a1a1a] rounded-lg p-2" : "flex bg-transparent p-1"}>
                                        <textarea
                                            className={isDark
                                                ? "h-[60px] w-full resize-none bg-transparent px-2 py-1 text-[14px] text-white outline-none placeholder:text-gray-500"
                                                : "h-[50px] w-full resize-none bg-transparent px-2 py-1 text-[14px] text-gray-800 outline-none placeholder:text-gray-400"
                                            }
                                            onChange={(event) => setInput(event.target.value)}
                                            placeholder="Analyze anything"
                                            value={input}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' && !e.shiftKey) {
                                                    e.preventDefault();
                                                    submitQuestion(e as any);
                                                }
                                            }}
                                        />
                                    </div>
                                    <div className="flex justify-end mt-2 pr-1">
                                        <button
                                            className={`cursor-pointer rounded-[8px] px-5 py-2 text-[13px] font-bold text-white transition-colors disabled:cursor-not-allowed ${
                                                isDark
                                                    ? "bg-white text-black hover:bg-gray-200 disabled:bg-white/10 disabled:text-gray-500" 
                                                    : "bg-[#8c8c8c] hover:bg-gray-500 disabled:bg-[#d4d4d4] disabled:text-white"
                                            }`}
                                            disabled={!input.trim() || isSending}
                                            type="submit"
                                        >
                                            {isSending ? "..." : "Send"}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </form>
                    </div>
                </section>
            </main>
        </div>
    );
};

export default Dashboard;
