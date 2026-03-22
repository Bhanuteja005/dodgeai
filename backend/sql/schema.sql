create extension if not exists pgcrypto;

create table if not exists ingest_runs (
    id bigserial primary key,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null,
    notes jsonb not null default '[]'::jsonb
);

create table if not exists o2c_entity_records (
    id bigserial primary key,
    entity_type text not null,
    external_id text not null,
    label text not null,
    source_file text,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    unique (entity_type, external_id)
);

create index if not exists idx_o2c_entity_records_entity_type on o2c_entity_records(entity_type);
create index if not exists idx_o2c_entity_records_payload on o2c_entity_records using gin(payload);

create table if not exists graph_edges (
    id bigserial primary key,
    source_id text not null,
    target_id text not null,
    source_type text not null,
    target_type text not null,
    relationship_label text not null,
    created_at timestamptz not null default now(),
    unique (source_id, target_id, relationship_label)
);

create index if not exists idx_graph_edges_source on graph_edges(source_id);
create index if not exists idx_graph_edges_target on graph_edges(target_id);
create index if not exists idx_graph_edges_types on graph_edges(source_type, target_type);
