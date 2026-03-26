---
name: postgres-performance-diagnosis
description: Diagnose PostgreSQL database performance issues including slow queries, memory usage, connection pool status, index efficiency, and lock contention. Use when the user asks to diagnose database performance, analyze slow queries, check connection pool, or generate database health reports.
---

# PostgreSQL Performance Diagnosis

Diagnose PostgreSQL database performance issues and generate comprehensive health reports.

## Quick Start

1. **Connect to database** using connection info from `config.py` or environment variable `DATABASE_URL`
2. **Run diagnostic queries** from [reference.md](reference.md) in sequence
3. **Analyze results** against thresholds defined below
4. **Generate report** using template from [report_template.md](report_template.md)

## Diagnosis Workflow

```
Progress Checklist:
- [ ] Step 1: Database connection verification
- [ ] Step 2: Connection pool status analysis
- [ ] Step 3: Slow query identification
- [ ] Step 4: Memory and buffer analysis
- [ ] Step 5: Index efficiency check
- [ ] Step 6: Lock contention detection
- [ ] Step 7: Table statistics review
- [ ] Step 8: Generate diagnosis report
```

### Step 1: Database Connection Verification

Verify database connectivity first:

```python
import psycopg2
from config import Config

conn = psycopg2.connect(Config.DATABASE_URL)
cur = conn.cursor()
cur.execute("SELECT version();")
print(cur.fetchone())
cur.close()
conn.close()
```

### Step 2-7: Run Diagnostic Queries

Execute queries from [reference.md](reference.md) sections:

| Step | Section | Purpose |
|------|---------|---------|
| 2 | Connection Pool | Check active connections, idle connections |
| 3 | Slow Queries | Find queries exceeding threshold |
| 4 | Memory & Buffers | Analyze shared buffers, cache hit ratio |
| 5 | Index Efficiency | Find unused/missing indexes |
| 6 | Lock Contention | Detect blocking locks |
| 7 | Table Statistics | Check table bloat, dead tuples |

## Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Active connections | > 80% max | > 95% max | Increase max_connections or optimize connection pooling |
| Slow queries (>1s) | > 10/min | > 50/min | Analyze and optimize queries |
| Cache hit ratio | < 95% | < 90% | Increase shared_buffers |
| Index bloat | > 30% | > 50% | REINDEX |
| Table bloat | > 30% | > 50% | VACUUM FULL |
| Lock wait time | > 1s | > 5s | Investigate long transactions |
| Dead tuples ratio | > 10% | > 20% | Run VACUUM |

## Common Issues & Solutions

### High Connection Count
- Check for connection leaks
- Implement connection pooling (PgBouncer)
- Reduce `pool_timeout` in application

### Slow Queries
- Enable `log_min_duration_statement` in postgresql.conf
- Use `EXPLAIN ANALYZE` for query plans
- Add appropriate indexes

### Low Cache Hit Ratio
- Increase `shared_buffers` (25% of RAM recommended)
- Check for sequential scans on large tables
- Consider adding indexes

### Lock Contention
- Identify blocking queries with pg_locks
- Reduce transaction duration
- Avoid long-running transactions

## Report Generation

After completing all diagnostic steps, generate a comprehensive report following the template in [report_template.md](report_template.md).

Save the report to: `docs/diagnosis_reports/YYYY-MM-DD_HH-MM-S diagnosis_report.md`

## Additional Resources

- For all diagnostic SQL queries, see [reference.md](reference.md)
- For report output format, see [report_template.md](report_template.md)
