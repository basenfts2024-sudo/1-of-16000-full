import os
from datetime import datetime, timezone
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

# Neon/Vercel integrations may expose any of these names. Never hard-code a DB password.
DATABASE_URL = next((os.getenv(k, '') for k in (
    'DATABASE_URL','NEON_DATABASE_URL','POSTGRES_URL','POSTGRES_URL_NON_POOLING','POSTGRES_PRISMA_URL'
) if os.getenv(k)), '')

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(token_id INTEGER PRIMARY KEY,updated_at TEXT NOT NULL,metadata_json JSONB NOT NULL,live_metadata_uri TEXT,image_uri TEXT);
CREATE TABLE IF NOT EXISTS version_history(id BIGSERIAL PRIMARY KEY,created_at TEXT NOT NULL,label TEXT,base_uri TEXT,cid TEXT,notes TEXT,payload_json JSONB);
CREATE TABLE IF NOT EXISTS events(event_key TEXT PRIMARY KEY,event_type TEXT NOT NULL,source_id TEXT NOT NULL,project_uuid TEXT,project_name TEXT,contributor_address TEXT,image_id TEXT,image_uuid TEXT,source_created_at TEXT,first_seen_at TEXT NOT NULL,status TEXT NOT NULL,burn_value INTEGER NOT NULL DEFAULT 1,raw_json JSONB);
CREATE TABLE IF NOT EXISTS scans(id BIGSERIAL PRIMARY KEY,engine TEXT NOT NULL DEFAULT 'main',started_at TEXT NOT NULL,completed_at TEXT,global_set_total BIGINT,recent_submission_window BIGINT NOT NULL DEFAULT 0,open_projects BIGINT NOT NULL DEFAULT 0,contribution_records BIGINT NOT NULL DEFAULT 0,new_submissions BIGINT NOT NULL DEFAULT 0,new_contributions BIGINT NOT NULL DEFAULT 0,failures BIGINT NOT NULL DEFAULT 0,incomplete_projects BIGINT NOT NULL DEFAULT 0,certified BOOLEAN NOT NULL DEFAULT FALSE,notes TEXT);
CREATE TABLE IF NOT EXISTS burn_batches(id BIGSERIAL PRIMARY KEY,engine TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,payload_json JSONB NOT NULL,event_keys_json JSONB NOT NULL,preflight_json JSONB,verified_json JSONB,notes TEXT);
CREATE TABLE IF NOT EXISTS vg_reference_images(id BIGSERIAL PRIMARY KEY,ref_key TEXT UNIQUE NOT NULL,set_number TEXT,set_name TEXT,artist TEXT,local_file TEXT,source_url TEXT,width INTEGER,height INTEGER,animated BOOLEAN DEFAULT FALSE,sha256 TEXT,embedding_index INTEGER,raw_json JSONB);
CREATE TABLE IF NOT EXISTS vg_remixes(id BIGSERIAL PRIMARY KEY,remix_key TEXT UNIQUE NOT NULL,token_id INTEGER,image_name TEXT,image_url TEXT,raw_json JSONB);
CREATE TABLE IF NOT EXISTS vg_match_candidates(id BIGSERIAL PRIMARY KEY,remix_key TEXT NOT NULL,rank INTEGER NOT NULL,set_number TEXT,set_name TEXT,artist TEXT,score DOUBLE PRECISION,confidence TEXT,best_reference_file TEXT,best_reference_url TEXT,supporting_matches JSONB,raw_json JSONB,UNIQUE(remix_key,rank));
CREATE TABLE IF NOT EXISTS vg_reviews(remix_key TEXT PRIMARY KEY,token_id INTEGER,status TEXT NOT NULL DEFAULT 'unreviewed',approved_sources JSONB NOT NULL DEFAULT '[]'::jsonb,remixed_elements JSONB NOT NULL DEFAULT '{}'::jsonb,visual_traits JSONB NOT NULL DEFAULT '{}'::jsonb,notes TEXT,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vg_activity(id BIGSERIAL PRIMARY KEY,created_at TEXT NOT NULL,remix_key TEXT,action TEXT NOT NULL,payload JSONB);
'''

def nowiso():
    return datetime.now(timezone.utc).isoformat()

def configured():
    return bool(DATABASE_URL and psycopg is not None)

def conn():
    if not configured():
        return None
    c = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    c.execute(SCHEMA)
    c.commit()
    return c
