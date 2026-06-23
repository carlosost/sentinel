# Infra Doc: db-primary Architecture

`db-primary` is a single Postgres 16 instance (no automatic failover in v1)
serving as the primary datastore for the incident/account/billing schemas. It
also hosts the `pgvector` extension used by Sentinel's own `documents` table
(corpus-tagged runbook/postmortem/infra-doc embeddings) and the LangGraph
`PostgresSaver` checkpoint tables — all three concerns share this one
instance per ADR-002, to minimize the number of moving parts in early
versions.

**Logical replication:** one outbound logical replication slot feeds the
analytics ETL pipeline (`analytics_etl_consumer`). This slot is the most
common source of WAL-driven disk-usage incidents (see the corresponding
postmortem) because Postgres will not reclaim WAL for an inactive slot,
regardless of disk pressure.

**Disk layout:** `/var/lib/postgresql/data` is a dedicated volume, separate
from the OS volume and from `/var/log`. The disk-usage-high runbook's triage
steps assume this separation when distinguishing "WAL buildup" from "log
buildup" as the cause.

**Connection limits:** `max_connections=200`, fronted by a connection pooler
(PgBouncer) in transaction-pooling mode for application traffic. Sentinel's
own checkpointer and pgvector queries connect directly, bypassing the pooler,
since they are low-volume relative to application traffic.
