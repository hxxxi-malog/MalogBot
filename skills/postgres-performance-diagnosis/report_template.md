# PostgreSQL Performance Diagnosis Report Template

Use this template to generate comprehensive diagnosis reports.

---

## Report Template

```markdown
# PostgreSQL 数据库性能诊断报告

**生成时间**: {timestamp}
**数据库**: {database_name}
**PostgreSQL 版本**: {pg_version}
**诊断执行者**: LLM Agent

---

## 执行摘要

{executive_summary}

### 健康状态总览

| 指标 | 当前值 | 阈值 | 状态 |
|------|--------|------|------|
| 连接数使用率 | {conn_usage}% | < 80% | {conn_status} |
| 缓存命中率 | {cache_hit_ratio}% | > 95% | {cache_status} |
| 死元组比例 | {dead_tuple_ratio}% | < 10% | {dead_tuple_status} |
| 慢查询数量 | {slow_query_count} | < 10 | {slow_query_status} |
| 锁等待 | {lock_wait_count} | 0 | {lock_status} |

---

## 详细分析

### 1. 连接池状态

#### 1.1 连接概览

| 状态 | 数量 | 占比 |
|------|------|------|
| active | {active_count} | {active_pct}% |
| idle | {idle_count} | {idle_pct}% |
| idle in transaction | {idle_txn_count} | {idle_txn_pct}% |

#### 1.2 最大连接数配置

- **max_connections**: {max_connections}
- **当前连接数**: {current_connections}
- **使用率**: {conn_usage_pct}%

#### 1.3 问题与建议

{connection_issues_and_recommendations}

---

### 2. 慢查询分析

#### 2.1 慢查询统计

- **总慢查询数 (>1s)**: {total_slow_queries}
- **最长查询时间**: {max_query_time}
- **平均查询时间**: {avg_query_time}

#### 2.2 Top 5 最慢查询

| 排名 | 平均时间 (ms) | 调用次数 | 总时间 (ms) | 查询预览 |
|------|--------------|---------|-------------|----------|
| 1 | {q1_avg} | {q1_calls} | {q1_total} | {q1_preview} |
| 2 | {q2_avg} | {q2_calls} | {q2_total} | {q2_preview} |
| 3 | {q3_avg} | {q3_calls} | {q3_total} | {q3_preview} |
| 4 | {q4_avg} | {q4_calls} | {q4_total} | {q4_preview} |
| 5 | {q5_avg} | {q5_calls} | {q5_total} | {q5_preview} |

#### 2.3 问题与建议

{slow_query_issues_and_recommendations}

---

### 3. 内存与缓冲区分析

#### 3.1 缓存命中率

| 指标 | 命中率 | 状态 |
|------|--------|------|
| 索引命中率 | {idx_hit_ratio}% | {idx_hit_status} |
| 表命中率 | {table_hit_ratio}% | {table_hit_status} |

#### 3.2 内存配置

| 参数 | 当前值 | 建议值 |
|------|--------|--------|
| shared_buffers | {shared_buffers} | 25% RAM |
| work_mem | {work_mem} | 4-64MB |
| maintenance_work_mem | {maint_work_mem} | 256MB-1GB |
| effective_cache_size | {eff_cache_size} | 75% RAM |

#### 3.3 问题与建议

{memory_issues_and_recommendations}

---

### 4. 索引效率分析

#### 4.1 未使用的索引

| 表名 | 索引名 | 大小 | 扫描次数 |
|------|--------|------|----------|
| {t1_name} | {i1_name} | {i1_size} | {i1_scans} |
| {t2_name} | {i2_name} | {i2_size} | {i2_scans} |

#### 4.2 缺少索引的表

| 表名 | 顺序扫描次数 | 索引扫描次数 | 索引使用率 |
|------|-------------|-------------|-----------|
| {t1_name} | {t1_seq_scan} | {t1_idx_scan} | {t1_idx_ratio}% |

#### 4.3 问题与建议

{index_issues_and_recommendations}

---

### 5. 锁竞争分析

#### 5.1 当前锁状态

| 锁类型 | 已授予 | 等待中 |
|--------|--------|--------|
| {lock1_type} | {lock1_granted} | {lock1_waiting} |

#### 5.2 阻塞查询

{blocking_queries_table_or_none}

#### 5.3 长事务

| PID | 用户 | 持续时间 | 状态 | 查询预览 |
|-----|------|---------|------|----------|
| {pid} | {user} | {duration} | {state} | {query_preview} |

#### 5.4 问题与建议

{lock_issues_and_recommendations}

---

### 6. 表统计信息

#### 6.1 表大小概览

| 表名 | 总大小 | 数据大小 | 索引大小 | 行数 |
|------|--------|---------|---------|------|
| {t1_name} | {t1_total} | {t1_data} | {t1_idx} | {t1_rows} |

#### 6.2 需要清理的表

| 表名 | 死元组 | 死元组比例 | 上次清理时间 |
|------|--------|-----------|-------------|
| {t1_name} | {t1_dead} | {t1_dead_pct}% | {t1_last_vacuum} |

#### 6.3 问题与建议

{table_issues_and_recommendations}

---

## 优化建议汇总

### 紧急 (Critical)

{critical_recommendations}

### 重要 (High Priority)

{high_priority_recommendations}

### 建议 (Medium Priority)

{medium_priority_recommendations}

---

## 执行的优化命令

### 可立即执行的 SQL

```sql
-- 清理死元组
{vacuum_commands}

-- 重建索引
{reindex_commands}

-- 分析表统计信息
{analyze_commands}
```

### 配置修改建议

```postgresql
-- postgresql.conf 建议修改
{config_changes}
```

---

## 附录

### 诊断环境

- **主机**: {hostname}
- **操作系统**: {os_info}
- **PostgreSQL 配置文件**: {config_file_path}

### 诊断查询执行时间

| 步骤 | 执行时间 |
|------|---------|
| 连接检查 | {step1_time} |
| 连接池分析 | {step2_time} |
| 慢查询分析 | {step3_time} |
| 内存分析 | {step4_time} |
| 索引分析 | {step5_time} |
| 锁分析 | {step6_time} |
| 表统计 | {step7_time} |

---

*报告生成于 {timestamp}*
```

---

## Status Indicators

Use these indicators in the report:

| Status | Color | Description |
|--------|-------|-------------|
| Healthy | Green | Within normal range |
| Warning | Yellow | Approaching threshold |
| Critical | Red | Exceeds threshold |
| Unknown | Gray | Unable to determine |

---

## File Saving Convention

Save reports to the project's docs directory:

```
docs/diagnosis_reports/{YYYY-MM-DD_HH-MM-SS}_diagnosis_report.md
```

Example:
```
docs/diagnosis_reports/2026-03-26_14-30-00_diagnosis_report.md
```

Create the directory if it doesn't exist:

```bash
mkdir -p docs/diagnosis_reports
```
