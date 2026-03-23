from collections import Counter, deque

from app.services.graph_service import fetch_graph


def _cluster_color(index: int) -> str:
    palette = [
        "#2563eb",
        "#16a34a",
        "#d97706",
        "#7c3aed",
        "#db2777",
        "#0891b2",
        "#65a30d",
        "#ea580c",
        "#0f766e",
        "#6d28d9",
    ]
    return palette[index % len(palette)]


def fetch_graph_clusters(limit: int = 1200, min_cluster_size: int = 4, max_clusters: int = 25):
    graph = fetch_graph(limit=limit)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    node_by_id = {node["id"]: node for node in nodes}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}

    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)

    visited: set[str] = set()
    raw_components: list[list[str]] = []

    for node_id in adjacency:
        if node_id in visited:
            continue
        queue = deque([node_id])
        visited.add(node_id)
        component: list[str] = []

        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        raw_components.append(component)

    filtered = [c for c in raw_components if len(c) >= min_cluster_size]
    filtered.sort(key=len, reverse=True)
    filtered = filtered[:max_clusters]

    node_cluster_map: dict[str, int] = {}
    clusters = []

    for idx, component in enumerate(filtered, start=1):
        type_counts = Counter(node_by_id[nid]["type"] for nid in component if nid in node_by_id)
        dominant_type = type_counts.most_common(1)[0][0] if type_counts else "unknown"
        hub = max(component, key=lambda nid: len(adjacency.get(nid, set())))

        for nid in component:
            node_cluster_map[nid] = idx

        clusters.append(
            {
                "cluster_id": idx,
                "size": len(component),
                "dominant_type": dominant_type,
                "hub_node_id": hub,
                "color": _cluster_color(idx - 1),
                "sample_node_ids": component[:20],
            }
        )

    return {
        "clusters": clusters,
        "node_cluster_map": node_cluster_map,
        "unclustered_count": max(0, len(nodes) - len(node_cluster_map)),
        "limit": limit,
    }
