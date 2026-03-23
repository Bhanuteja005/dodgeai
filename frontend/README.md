# Graph-Based O2C Insights UX (frontend)

## 🔥 Introduction

This frontend is part of the DodgeAI project: a graph-based Order-to-Cash analytics app with an integrated natural language query chat.

## 🌟 Features

- Interactive entity graph view (nodes, edges, drag/zoom)
- Node details and expansions
- Chat interface for business queries (backed by dataset SQL)
- Node highlighting via NLP output (`graph_node_ids` mapping)
- Clustering mode for entity clusters
- Responsive layout with sidebar + graph panel

## 🛠️ Tech Stack

- Next.js 16 (App Router)
- React 19
- TypeScript
- Tailwind CSS
- react-force-graph-2d

## 🚀 Local Run

1. `cd frontend`
2. `npm install` (or `pnpm install`)
3. copy `.env.example` to `.env.local`
4. set backend URL if needed, e.g. `NEXT_PUBLIC_API_URL=http://localhost:8000`
5. `npm run dev`

Open [http://localhost:3000](http://localhost:3000)

## 🧩 Backend contract

- `GET /api/graph` - graph snapshot
- `POST /api/chat` - NL query => data-backed response + graph node IDs
- `GET /api/graph/node/{id}` - node details
- `GET /api/graph/clusters` - clustering

## 📝 Notes

- The UI expects backend to provide structured nodes with `id`, `name`, `category`, `properties`, `neighbors`.
- Chat bubble actions can 
