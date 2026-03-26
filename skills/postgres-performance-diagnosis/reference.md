# PostgreSQL Diagnostic SQL Queries Reference

All queries should be executed using a database connection from `config.py`.

## Connection Setup

```python
import psycopg2
from config import Config

def get_connection():
    return psycopg2.connect(Config.DATABASE_URL)

def run_query(sql: str) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql)
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results
```

---

## 1. Connection Pool Status

### 1.1 Current Connections

```sql
SELECT
    state,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state
ORDER BY count DESC;
```

### 1.2 Connection Details

```sql
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    wait_event_type,
    wait_event,
    query_start,
    NOW() - query_start as duration,
    LEFT(query, 100) as query_preview
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY query_start;
```

### 1.3 Max Connections Setting

```sql
SELECT
    setting as max_connections,
    (SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()) as current_connections,
    ROUND((SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()) * 100.0 / CAST(setting AS INT), 2) as usage_percentage
FROM pg_settings
WHERE name = 'max_connections';
```

### 1.4 Idle Connections

```sql
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    NOW() - query_start as idle_duration
FROM pg_stat_activity
WHERE datname = current_database()
  AND state = 'idle'
  AND query_start < NOW() - INTERVAL '5 minutes'
ORDER BY query_start;
```

---

## 2. Slow Queries Analysis

### 2.1 Enable pg_stat_statements Extension

```sql
-- First, enable the extension (requires superuser)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

### 2.2 Top Slow Queries

```sql
SELECT
    calls,
    ROUND(total_exec_time::numeric, 2) as total_time_ms,
    ROUND(mean_exec_time::numeric, 2) as avg_time_ms,
    ROUND(min_exec_time::numeric, 2) as min_time_ms,
    ROUND(max_exec_time::numeric, 2) as max_time_ms,
    rows,
    queryid,
    LEFT(query, 200) as query_preview
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

### 2.3 Queries with Highest Average Time

```sql
SELECT
    calls,
    ROUND(mean_exec_time::numeric, 2) as avg_time_ms,
    ROUND(total_exec_time::numeric, 2) as total_time_ms,
    rows,
    LEFT(query, 200) as query_preview
FROM pg_stat_statements
WHERE calls > 10
ORDER BY mean_exec_time DESC
LIMIT 15;
```

### 2.4 Currently Running Long Queries

```sql
SELECT
    pid,
    NOW() - query_start as duration,
    state,
    usename,
    LEFT(query, 150) as query_preview
FROM pg_stat_activity
WHERE state = 'active'
  AND query_start < NOW() - INTERVAL '1 second'
ORDER BY query_start;
```

### 2.5 Query Without pg_stat_statements

If `pg_stat_statements` is not available, check current activity:

```sql
SELECT
    pid,
    NOW() - query_start as duration,
    wait_event_type,
    wait_event,
    state,
    LEFT(query, 200) as query_preview
FROM pg_stat_activity
WHERE datname = current_database()
  AND state != 'idle'
ORDER BY query_start DESC;
```

---

## 3. Memory & Buffer Analysis

### 3.1 Buffer Cache Hit Ratio

```sql
SELECT
    'Index Hit Ratio' as metric,
    ROUND((sum(idx_blks_hit) * 100.0 / NULLIF(sum(idx_blks_hit + idx_blks_read), 0))::numeric, 2) as ratio
FROM pg_statio_user_indexes
UNION ALL
SELECT
    'Table Hit Ratio',
    ROUND((sum(heap_blks_hit) * 100.0 / NULLIF(sum(heap_blks_hit + heap_blks_read), 0))::numeric, 2)
FROM pg_statio_user_tables;
```

### 3.2 Shared Buffers Setting

```sql
SELECT
    name,
    setting,
    unit,
    short_desc
FROM pg_settings
WHERE name IN ('shared_buffers', 'work_mem', 'maintenance_work_mem', 'effective_cache_size', 'wal_buffers');
```

### 3.3 Memory by Process

```sql
SELECT
    pid,
    usename,
    application_name,
    state,
    backend_type,
    pg_size_pretty(pg_backend_memory_contexts(pid, 'Total').value) as memory_usage
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY pg_backend_memory_contexts(pid, 'Total').value DESC
LIMIT 10;
```

Note: `pg_backend_memory_contexts` is available in PostgreSQL 14+.

### 3.4 Table Cache Statistics

```sql
SELECT
    schemaname,
    relname as table_name,
    heap_blks_read,
    heap_blks_hit,
    CASE WHEN heap_blks_hit + heap_blks_read > 0
        THEN ROUND(heap_blks_hit * 100.0 / (heap_blks_hit + heap_blks_read), 2)
        ELSE 0
    END as cache_hit_ratio
FROM pg_statio_user_tables
WHERE heap_blks_hit + heap_blks_read > 0
ORDER BY heap_blks_read DESC
LIMIT 15;
```

---

## 4. Index Efficiency

### 4.1 Unused Indexes

```sql
SELECT
    schemaname,
    relname as table_name,
    indexrelname as index_name,
    idx_scan as index_scans,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexrelname NOT LIKE '%_pkey'
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 20;
```

### 4.2 Index Usage Statistics

```sql
SELECT
    schemaname,
    relname as table_name,
    indexrelname as index_name,
    idx_scan as scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC
LIMIT 20;
```

### 4.3 Tables Missing Indexes

```sql
SELECT
    schemaname,
    relname as table_name,
    seq_scan,
    idx_scan,
    CASE WHEN seq_scan + idx_scan > 0
        THEN ROUND(idx_scan * 100.0 / (seq_scan + idx_scan), 2)
        ELSE 0
    END as index_usage_ratio,
    n_live_tup as row_count
FROM pg_stat_user_tables
WHERE seq_scan > idx_scan
  AND n_live_tup > 1000
ORDER BY seq_scan DESC
LIMIT 15;
```

### 4.4 Duplicate/Redundant Indexes

```sql
SELECT
    pg_size_pretty(sum(pg_relation_size(idx))::bigint) as size,
    (array_agg(idx))[1] as idx1,
    (array_agg(idx))[2] as idx2,
    (array_agg(idx))[3] as idx3,
    (array_agg(idx))[4] as idx4
FROM (
    SELECT
        indexrelid::regclass as idx,
        indrelid::regclass as table,
        indkey,
        indpred
    FROM pg_index
) sub
GROUP BY table, indkey, indpred
HAVING count(*) > 1
ORDER BY sum(pg_relation_size(idx)) DESC;
```

### 4.5 Index Bloat Estimation

```sql
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    idx_scan,
    idx_tup_read
FROM pg_stat_user_indexes
JOIN pg_class ON pg_class.oid = indexrelid
WHERE pg_relation_size(indexrelid) > 1024 * 1024  -- Only indexes > 1MB
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 15;
```

---

## 5. Lock Contention

### 5.1 Current Locks

```sql
SELECT
    locktype,
    database,
    relation::regclass as table,
    mode,
    granted,
    COUNT(*) as count
FROM pg_locks
WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
GROUP BY locktype, database, relation, mode, granted
ORDER BY count DESC;
```

### 5.2 Blocking Queries

```sql
SELECT
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_query,
    blocking_activity.query AS blocking_query,
    NOW() - blocked_activity.query_start AS blocked_duration,
    NOW() - blocking_activity.query_start AS blocking_duration
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### 5.3 Long-Running Transactions

```sql
SELECT
    pid,
    NOW() - xact_start AS duration,
    usename,
    state,
    LEFT(query, 100) as query_preview
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND NOW() - xact_start > INTERVAL '1 minute'
ORDER BY xact_start;
```

### 5.4 Deadlocks Statistics

```sql
SELECT
    datname,
    deadlocks,
    conflicts,
    xact_commit,
    xact_rollback
FROM pg_stat_database
WHERE datname = current_database();
```

---

## 6. Table Statistics

### 6.1 Table Sizes

```sql
SELECT
    schemaname,
    relname as table_name,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
    pg_size_pretty(pg_relation_size(relid)) as table_size,
    pg_size_pretty(pg_indexes_size(relid)) as indexes_size,
    n_live_tup as row_count,
    n_dead_tup as dead_tuples,
    CASE WHEN n_live_tup > 0
        THEN ROUND(n_dead_tup * 100.0 / n_live_tup, 2)
        ELSE 0
    END as dead_tuple_ratio
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 20;
```

### 6.2 Tables Needing Vacuum

```sql
SELECT
    schemaname,
    relname as table_name,
    n_live_tup as live_tuples,
    n_dead_tup as dead_tuples,
    CASE WHEN n_live_tup > 0
        THEN ROUND(n_dead_tup * 100.0 / n_live_tup, 2)
        ELSE 0
    END as dead_ratio,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC
LIMIT 15;
```

### 6.3 Sequential vs Index Scans

```sql
SELECT
    schemaname,
    relname as table_name,
    seq_scan,
    idx_scan,
    CASE WHEN seq_scan + idx_scan > 0
        THEN ROUND(seq_scan * 100.0 / (seq_scan + idx_scan), 2)
        ELSE 0
    END as seq_scan_ratio,
    n_live_tup as row_count
FROM pg_stat_user_tables
WHERE n_live_tup > 100
ORDER BY seq_scan DESC
LIMIT 15;
```

### 6.4 Table Bloat Estimation

```sql
-- Requires pgstattuple extension
CREATE EXTENSION IF NOT EXISTS pgstattuple;

SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) as table_size,
    dead_tuple_count,
    dead_tuple_percent
FROM pg_stat_user_tables
JOIN pgstattuple(schemaname || '.' || tablename) ON true
WHERE dead_tuple_percent > 10
ORDER BY dead_tuple_percent DESC
LIMIT 10;
```

Alternative without pgstattuple:

```sql
SELECT
    schemaname,
    relname as table_name,
    n_live_tup,
    n_dead_tup,
    CASE WHEN n_live_tup > 0
        THEN ROUND(n_dead_tup * 100.0 / n_live_tup, 2)
        ELSE 0
    END as dead_tuple_percent,
    pg_size_pretty(pg_relation_size(relid)) as table_size
FROM pg_stat_user_tables
WHERE n_dead_tup > 0
ORDER BY n_dead_tup DESC
LIMIT 15;
```

---

## 7. Database Configuration

### 7.1 Key Settings

```sql
SELECT
    name,
    setting,
    unit,
    short_desc,
    source,
    sourcefile
FROM pg_settings
WHERE name IN (
    'max_connections',
    'shared_buffers',
    'effective_cache_size',
    'work_mem',
    'maintenance_work_mem',
    'wal_buffers',
    'checkpoint_completion_target',
    'random_page_cost',
    'effective_io_concurrency',
    'max_worker_processes',
    'max_parallel_workers_per_gather',
    'max_parallel_workers',
    'autovacuum',
    'autovacuum_max_workers',
    'log_min_duration_statement',
    'log_lock_waits',
    'deadlock_timeout'
)
ORDER BY name;
```

### 7.2 Background Writer Stats

```sql
SELECT
    checkpoints_timed,
    checkpoints_req,
    ROUND(checkpoints_req * 100.0 / NULLIF(checkpoints_timed + checkpoints_req, 0), 2) as req_checkpoint_ratio,
    buffers_checkpoint,
    buffers_clean,
    buffers_backend
FROM pg_stat_bgwriter;
```

### 7.3 WAL Statistics

```sql
SELECT
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')) as wal_written,
    pg_current_wal_lsn() as current_lsn;
```

---

## 8. Application-Specific Queries

### 8.1 Sessions Table Statistics

```sql
SELECT
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN updated_at > NOW() - INTERVAL '1 hour' THEN 1 END) as active_last_hour,
    COUNT(CASE WHEN updated_at > NOW() - INTERVAL '24 hours' THEN 1 END) as active_last_day,
    MIN(created_at) as oldest_session,
    MAX(updated_at) as last_activity
FROM sessions;
```

### 8.2 Messages Table Statistics

```sql
SELECT
    COUNT(*) as total_messages,
    COUNT(CASE WHEN timestamp > NOW() - INTERVAL '1 hour' THEN 1 END) as messages_last_hour,
    COUNT(CASE WHEN timestamp > NOW() - INTERVAL '24 hours' THEN 1 END) as messages_last_day,
    pg_size_pretty(pg_total_relation_size('messages')) as table_size
FROM messages;
```

### 8.3 Messages per Session Distribution

```sql
SELECT
    COUNT(*) as message_count,
    COUNT(*) as sessions_with_this_many_messages
FROM (
    SELECT session_id, COUNT(*) as msg_count
    FROM messages
    GROUP BY session_id
) t
GROUP BY msg_count
ORDER BY msg_count DESC
LIMIT 20;
```

---

## 9. Health Check Summary

### Quick Health Query

```sql
SELECT
    'Connections' as category,
    (SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()) as current_value,
    (SELECT setting FROM pg_settings WHERE name = 'max_connections') as max_value,
    ROUND((SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()) * 100.0 /
          CAST((SELECT setting FROM pg_settings WHERE name = 'max_connections') AS INT), 2) as usage_pct
UNION ALL
SELECT
    'Cache Hit Ratio',
    ROUND((sum(heap_blks_hit) * 100.0 / NULLIF(sum(heap_blks_hit + heap_blks_read), 0))::numeric, 2),
    100,
    ROUND((sum(heap_blks_hit) * 100.0 / NULLIF(sum(heap_blks_hit + heap_blks_read), 0))::numeric, 2)
FROM pg_statio_user_tables
UNION ALL
SELECT
    'Dead Tuples',
    (SELECT SUM(n_dead_tup) FROM pg_stat_user_tables),
    (SELECT SUM(n_live_tup) FROM pg_stat_user_tables),
    CASE WHEN (SELECT SUM(n_live_tup) FROM pg_stat_user_tables) > 0
        THEN ROUND((SELECT SUM(n_dead_tup) FROM pg_stat_user_tables) * 100.0 /
             (SELECT SUM(n_live_tup) FROM pg_stat_user_tables), 2)
        ELSE 0
    END;
```
