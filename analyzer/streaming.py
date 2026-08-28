"""
streaming.py
SQLite-backed streaming aggregator for APICall records.

Ingests API calls without retaining raw records, calculating points and endpoints
via existing calculator functions, classifying calls, and persisting aggregated
metrics for reports. Uses batched commits for efficiency.

Core features:
- Single-pass streaming ingestion (no raw call list retained)
- SQLite-backed aggregation tables
- Classification at ingest time
- Batched transaction commits (10K calls per batch)
- Query methods for report-ready aggregate data
- Support for include/exclude unauthenticated classes
"""

import sqlite3
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from collections import defaultdict

from .parser import APICall
from .calculator import (
    get_endpoint_key,
    calculate_points,
    classify_call,
    PER_ISSUE_WRITE_LIMIT,
    BURST_STEADY_STATE_RPS,
    BURST_BUCKET_SIZE,
)


class StreamingAggregator:
    """
    SQLite-backed streaming aggregator for APICall records.
    
    Ingests calls without retaining raw records, persisting aggregated metrics
    for hourly quota, burst rates, per-issue writes, and consumer points.
    """
    
    BATCH_SIZE = 10_000  # Commit transaction every N calls
    
    def __init__(self, db_path: str = ":memory:", excluded_ips: Optional[List[str]] = None):
        """
        Initialize the streaming aggregator.
        
        Args:
            db_path: Path to SQLite database (":memory:" for in-memory)
            excluded_ips: List of IP addresses to exclude from aggregation
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.excluded_ips = set(ip.strip() for ip in (excluded_ips or []) if ip.strip())
        self._call_count = 0
        self._batch_calls = []
    
    def __enter__(self):
        """Context manager entry: initialize database connection and schema."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        self._init_schema()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: flush batch, commit and close connection."""
        try:
            if self._batch_calls:
                self._flush_batch()
        finally:
            if self.conn:
                try:
                    self.conn.commit()
                except Exception as e:
                    pass
                self.conn.close()
                self.conn = None
    
    def _init_schema(self) -> None:
        """Initialize SQLite schema for aggregation tables."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Table 1: Summary by class (classification, calls, points)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summary_by_class (
                classification TEXT PRIMARY KEY,
                call_count INTEGER NOT NULL DEFAULT 0,
                total_points INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        # Table 2: Hourly quota aggregation (hour_bucket, classification, calls, points)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hourly_quota (
                hour_bucket DATETIME NOT NULL,
                classification TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 0,
                total_points INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (hour_bucket, classification)
            )
        """)
        
        # Table 3: Burst rates (per-second, per-endpoint, per-class aggregation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS burst_rates (
                second_bucket DATETIME NOT NULL,
                endpoint_key TEXT NOT NULL,
                classification TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (second_bucket, endpoint_key, classification)
            )
        """)
        
        # Table 4: Per-issue writes (per-minute, per-issue, per-class aggregation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS per_issue_writes (
                minute_bucket DATETIME NOT NULL,
                issue_key TEXT NOT NULL,
                classification TEXT NOT NULL,
                write_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (minute_bucket, issue_key, classification)
            )
        """)
        
        # Table 5: Consumer totals (by classification and consumer ID)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consumer_points (
                classification TEXT NOT NULL,
                consumer_id TEXT NOT NULL,
                total_points INTEGER NOT NULL DEFAULT 0,
                call_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (classification, consumer_id)
            )
        """)
        
        # Table 6: Unique entities (classification, type, value)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unique_entities (
                classification TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_value TEXT NOT NULL,
                PRIMARY KEY (classification, entity_type, entity_value)
            )
        """)
        
        # Table 7: Method counts (classification, method, count)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS method_counts (
                classification TEXT NOT NULL,
                method TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (classification, method)
            )
        """)
        
        # Table 8: Endpoint counts (classification, endpoint_key, count)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_counts (
                classification TEXT NOT NULL,
                endpoint_key TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (classification, endpoint_key)
            )
        """)
        
        # Table 9: IP counts (classification, ip, count)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ip_counts (
                classification TEXT NOT NULL,
                ip TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (classification, ip)
            )
        """)
        
        # Create indexes for query performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hourly_bucket ON hourly_quota(hour_bucket)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_burst_timestamp ON burst_rates(second_bucket)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_writes_minute ON per_issue_writes(minute_bucket)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_consumer_classification ON consumer_points(classification)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_unique_type ON unique_entities(entity_type)")
        
        self.conn.commit()
    
    def ingest(self, call: APICall) -> None:
        """
        Stream-ingest a single API call without retaining raw record.
        
        Enriches with points/endpoint, classifies, and aggregates into tables.
        Uses batched commits for efficiency.
        """
        # Skip excluded IPs
        if call.ip in self.excluded_ips:
            return
        
        # Enrich call
        call.endpoint_key = get_endpoint_key(call.path)
        call.points = calculate_points(call)
        classification = classify_call(call)
        
        # Batch the call
        self._batch_calls.append((call, classification))
        self._call_count += 1
        
        # Flush batch if threshold reached
        if len(self._batch_calls) >= self.BATCH_SIZE:
            self._flush_batch()
    
    def _flush_batch(self) -> None:
        """Flush batched calls to database and aggregate."""
        if not self._batch_calls:
            return
        
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        try:
            for call, classification in self._batch_calls:
                # Aggregate: summary by class
                cursor.execute("""
                    INSERT INTO summary_by_class (classification, call_count, total_points)
                    VALUES (?, 1, ?)
                    ON CONFLICT(classification) DO UPDATE SET
                        call_count = call_count + 1,
                        total_points = total_points + ?
                """, (classification, call.points, call.points))
                
                # Aggregate: hourly quota (with classification)
                hour_bucket = call.timestamp.replace(minute=0, second=0, microsecond=0)
                cursor.execute("""
                    INSERT INTO hourly_quota (hour_bucket, classification, call_count, total_points)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(hour_bucket, classification) DO UPDATE SET
                        call_count = call_count + 1,
                        total_points = total_points + ?
                """, (hour_bucket, classification, call.points, call.points))
                
                # Aggregate: burst rates (per-second, per-endpoint, per-class)
                second_bucket = call.timestamp.replace(microsecond=0)
                cursor.execute("""
                    INSERT INTO burst_rates (second_bucket, endpoint_key, classification, call_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(second_bucket, endpoint_key, classification) DO UPDATE SET
                        call_count = call_count + 1
                """, (second_bucket, call.endpoint_key, classification))
                
                # Aggregate: per-issue writes (per-minute, per-class)
                if call.method in ("POST", "PUT", "PATCH", "DELETE"):
                    # Extract issue key from endpoint
                    import re
                    issue_pattern = re.compile(r"/([A-Z]+-\d+|{issueKey})")
                    match = issue_pattern.search(call.endpoint_key)
                    if match:
                        issue_key = match.group(1)
                        minute_bucket = call.timestamp.replace(second=0, microsecond=0)
                        cursor.execute("""
                            INSERT INTO per_issue_writes (minute_bucket, issue_key, classification, write_count)
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(minute_bucket, issue_key, classification) DO UPDATE SET
                                write_count = write_count + 1
                        """, (minute_bucket, issue_key, classification))
                
                # Aggregate: consumer points (by classification and user/IP)
                consumer_id = call.user if call.user != "-" else call.ip
                cursor.execute("""
                    INSERT INTO consumer_points (classification, consumer_id, total_points, call_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(classification, consumer_id) DO UPDATE SET
                        total_points = total_points + ?,
                        call_count = call_count + 1
                """, (classification, consumer_id, call.points, call.points))
                
                # Aggregate: method counts (by classification and method)
                cursor.execute("""
                    INSERT INTO method_counts (classification, method, call_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(classification, method) DO UPDATE SET
                        call_count = call_count + 1
                """, (classification, call.method))
                
                # Aggregate: endpoint counts (by classification and endpoint_key)
                cursor.execute("""
                    INSERT INTO endpoint_counts (classification, endpoint_key, call_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(classification, endpoint_key) DO UPDATE SET
                        call_count = call_count + 1
                """, (classification, call.endpoint_key))
                
                # Aggregate: IP counts (by classification and IP)
                cursor.execute("""
                    INSERT INTO ip_counts (classification, ip, call_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(classification, ip) DO UPDATE SET
                        call_count = call_count + 1
                """, (classification, call.ip))
                
                # Track unique entities (with classification)
                cursor.execute("""
                    INSERT OR IGNORE INTO unique_entities (classification, entity_type, entity_value)
                    VALUES (?, 'user', ?)
                """, (classification, call.user))
                cursor.execute("""
                    INSERT OR IGNORE INTO unique_entities (classification, entity_type, entity_value)
                    VALUES (?, 'ip', ?)
                """, (classification, call.ip))
                cursor.execute("""
                    INSERT OR IGNORE INTO unique_entities (classification, entity_type, entity_value)
                    VALUES (?, 'method', ?)
                """, (classification, call.method))
            
            assert self.conn is not None
            self.conn.commit()
        finally:
            self._batch_calls = []
    
    # =========================================================================
    # Query Methods: Return Report-Ready Aggregate Data
    # =========================================================================
    
    def _ensure_flushed(self) -> None:
        """Ensure pending batch is flushed before querying."""
        if self._batch_calls:
            self._flush_batch()
    
    def get_summary_stats(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False
    ) -> Dict[str, Any]:
        """
        Return summary statistics: total calls, points, unique users/IPs, methods, endpoints.
        
        Args:
            include_unauthenticated: Include unauthenticated calls in totals
            exclude_unauthenticated: Explicitly exclude unauthenticated calls
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # Total calls and points from summary_by_class (SUM across included classifications)
        cursor.execute(f"""
            SELECT COALESCE(SUM(call_count), 0) as total_calls,
                   COALESCE(SUM(total_points), 0) as total_points
            FROM summary_by_class
            WHERE classification IN ({class_filter})
        """)
        row = cursor.fetchone()
        total_calls = row["total_calls"] if row else 0
        total_points = row["total_points"] if row else 0
        
        # Unique users from unique_entities
        cursor.execute(f"""
            SELECT COUNT(DISTINCT entity_value) as unique_users FROM unique_entities
            WHERE classification IN ({class_filter}) AND entity_type = 'user'
        """)
        row = cursor.fetchone()
        unique_users = row["unique_users"] if row else 0
        
        # Unique IPs from unique_entities
        cursor.execute(f"""
            SELECT COUNT(DISTINCT entity_value) as unique_ips FROM unique_entities
            WHERE classification IN ({class_filter}) AND entity_type = 'ip'
        """)
        row = cursor.fetchone()
        unique_ips = row["unique_ips"] if row else 0
        
        # Unique methods from method_counts
        cursor.execute(f"""
            SELECT COUNT(DISTINCT method) as unique_methods FROM method_counts
            WHERE classification IN ({class_filter})
        """)
        row = cursor.fetchone()
        unique_methods = row["unique_methods"] if row else 0
        
        # Unique endpoints from endpoint_counts
        cursor.execute(f"""
            SELECT COUNT(DISTINCT endpoint_key) as unique_endpoints FROM endpoint_counts
            WHERE classification IN ({class_filter})
        """)
        row = cursor.fetchone()
        unique_endpoints = row["unique_endpoints"] if row else 0
        
        # IP count from ip_counts
        cursor.execute(f"""
            SELECT COUNT(DISTINCT ip) as ip_count FROM ip_counts
            WHERE classification IN ({class_filter})
        """)
        row = cursor.fetchone()
        ip_count = row["ip_count"] if row else 0
        
        return {
            "total_calls": total_calls,
            "total_points": total_points,
            "unique_users": unique_users,
            "unique_ips": unique_ips,
            "unique_methods": unique_methods,
            "unique_endpoints": unique_endpoints,
            "ip_count": ip_count,
        }
    
    def get_hourly_quota(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Return hourly quota consumption report, filtered by include/exclude unauthenticated.
        
        Returns list of dicts with hour_bucket, classification, call_count, total_points.
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # Query aggregated hourly data with exact classification filter
        cursor.execute(f"""
            SELECT hour_bucket, classification, call_count, total_points
            FROM hourly_quota
            WHERE classification IN ({class_filter})
            ORDER BY hour_bucket ASC, classification ASC
        """)
        
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                "hour_bucket": row["hour_bucket"],
                "classification": row["classification"],
                "call_count": row["call_count"],
                "total_points": row["total_points"],
            })
        
        return results
    
    def get_burst_rates(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False
    ) -> Dict[str, Any]:
        """
        Return burst rates per endpoint (max RPS per second by endpoint).
        
        Combines classification rows: SUM calls per second before MAX across seconds.
        
        Returns dict with steady_state_rps_limit and endpoints list.
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build exact classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # Aggregate by endpoint: SUM calls per second across classifications, then MAX per endpoint
        cursor.execute(f"""
            SELECT endpoint_key, second_bucket, SUM(call_count) as rps
            FROM burst_rates
            WHERE classification IN ({class_filter})
            GROUP BY endpoint_key, second_bucket
        """)
        
        # Compute max/avg per endpoint
        endpoint_stats: Dict[str, Any] = {}
        for row in cursor.fetchall():
            endpoint = row["endpoint_key"]
            rps = row["rps"]
            if endpoint not in endpoint_stats:
                endpoint_stats[endpoint] = {"max": rps, "sum": rps, "count": 1, "breach_count": 0}
            else:
                endpoint_stats[endpoint]["max"] = max(endpoint_stats[endpoint]["max"], rps)
                endpoint_stats[endpoint]["sum"] += rps
                endpoint_stats[endpoint]["count"] += 1
            
            # Track breaches
            if rps > BURST_STEADY_STATE_RPS:
                endpoint_stats[endpoint]["breach_count"] += 1
        
        endpoint_analysis = []
        for endpoint_key, stats in sorted(endpoint_stats.items(), key=lambda x: x[1]["max"], reverse=True):
            max_rps = stats["max"]
            avg_rps = stats["sum"] / stats["count"] if stats["count"] > 0 else 0
            breach_seconds = stats["breach_count"]
            
            endpoint_analysis.append({
                "endpoint": endpoint_key,
                "max_rps": max_rps,
                "avg_rps": round(avg_rps, 2),
                "breach_seconds": breach_seconds,
                "steady_state_limit": BURST_STEADY_STATE_RPS,
                "risk_level": (
                    "🔴 HIGH" if max_rps > BURST_BUCKET_SIZE else
                    ("🟡 MEDIUM" if max_rps > BURST_STEADY_STATE_RPS else "🟢 LOW")
                ),
            })
        
        return {
            "steady_state_rps_limit": BURST_STEADY_STATE_RPS,
            "burst_bucket_size": BURST_BUCKET_SIZE,
            "endpoints": endpoint_analysis,
        }
    
    def get_per_issue_writes(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False
    ) -> Dict[str, Any]:
        """
        Return per-issue write limits analysis.
        
        Combines classification rows: SUM writes per minute before MAX per issue.
        
        Returns dict with per_issue_write_limit and risky_issues list.
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build exact classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # SUM writes per minute across classifications, then find max per issue
        cursor.execute(f"""
            SELECT issue_key, minute_bucket, SUM(write_count) as writes
            FROM per_issue_writes
            WHERE classification IN ({class_filter})
            GROUP BY issue_key, minute_bucket
        """)
        
        # Compute max per issue
        issue_stats: Dict[str, int] = {}
        for row in cursor.fetchall():
            issue = row["issue_key"]
            writes = row["writes"]
            if issue not in issue_stats:
                issue_stats[issue] = writes
            else:
                issue_stats[issue] = max(issue_stats[issue], writes)
        
        risky_issues = []
        for issue_key, max_writes in sorted(issue_stats.items(), key=lambda x: x[1], reverse=True):
            if max_writes > PER_ISSUE_WRITE_LIMIT:
                risky_issues.append({
                    "issue": issue_key,
                    "max_writes_per_minute": max_writes,
                    "limit": PER_ISSUE_WRITE_LIMIT,
                    "risk_level": "🔴 HIGH",
                })
        
        return {
            "per_issue_write_limit": PER_ISSUE_WRITE_LIMIT,
            "risky_issues": risky_issues,
        }
    
    def get_top_consumers(
        self, classification: Optional[str] = None,
        include_unauthenticated: bool = True, exclude_unauthenticated: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Return top consumers by points with exact classification filter.
        
        Args:
            classification: Filter to specific classification (e.g. 'service_account')
            include_unauthenticated: Include unauthenticated consumers
            exclude_unauthenticated: Explicitly exclude unauthenticated
            limit: Max results to return
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build WHERE clause for exact classification filter
        if classification:
            where = "WHERE classification = ?"
            params: list[object] = [classification]
        else:
            classifications = ["authenticated_user", "service_account"]
            if include_unauthenticated and not exclude_unauthenticated:
                classifications.append("unauthenticated")
            class_filter = "'" + "','".join(classifications) + "'"
            where = f"WHERE classification IN ({class_filter})"
            params = []
        
        query = f"""
            SELECT classification, consumer_id, total_points, call_count
            FROM consumer_points
            {where}
            ORDER BY total_points DESC
            LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append({
                "classification": row["classification"],
                "consumer_id": row["consumer_id"],
                "total_points": row["total_points"],
                "call_count": row["call_count"],
                "avg_points_per_call": round(row["total_points"] / row["call_count"], 2) if row["call_count"] > 0 else 0,
            })
        
        return results
    
    def get_classification_breakdown(self) -> Dict[str, Dict[str, Any]]:
        """
        Return breakdown of calls and points by classification type.
        
        Returns dict: {
            "authenticated_user": {"calls": N, "points": P},
            "service_account": {"calls": N, "points": P},
            "unauthenticated": {"calls": N, "points": P},
        }
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT classification, call_count, total_points
            FROM summary_by_class
        """)
        
        rows = cursor.fetchall()
        result = {
            "authenticated_user": {"calls": 0, "points": 0},
            "service_account": {"calls": 0, "points": 0},
            "unauthenticated": {"calls": 0, "points": 0},
        }
        
        for row in rows:
            if row["classification"] in result:
                result[row["classification"]] = {
                    "calls": row["call_count"],
                    "points": row["total_points"],
                }
        
        return result
    
    def get_unique_ips(self) -> List[str]:
        """Return list of unique IP addresses."""
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT entity_value FROM unique_entities WHERE entity_type = 'ip' ORDER BY entity_value")
        return [row["entity_value"] for row in cursor.fetchall()]
    
    def get_unique_users(self) -> List[str]:
        """Return list of unique users."""
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT entity_value FROM unique_entities WHERE entity_type = 'user' AND entity_value != '-' ORDER BY entity_value")
        return [row["entity_value"] for row in cursor.fetchall()]
    
    def get_unique_methods(self) -> List[str]:
        """Return list of unique HTTP methods."""
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT method FROM method_counts ORDER BY method")
        return [row["method"] for row in cursor.fetchall()]
    
    def get_unique_endpoints(self) -> List[str]:
        """Return list of unique endpoint keys."""
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT endpoint_key FROM endpoint_counts ORDER BY endpoint_key")
        return [row["endpoint_key"] for row in cursor.fetchall()]
    
    def get_total_ingested(self) -> int:
        """Return total calls ingested (including excluded)."""
        return self._call_count
    
    def get_stored_calls_count(self) -> int:
        """Return count of calls currently stored in database."""
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(call_count), 0) as count FROM summary_by_class")
        row = cursor.fetchone()
        return row["count"] if row else 0
    
    def get_method_counts(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False
    ) -> Dict[str, int]:
        """
        Return method counts by HTTP method, filtered by include/exclude unauthenticated.
        
        Returns dict mapping method (GET, POST, etc.) to call count.
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # Query method counts
        cursor.execute(f"""
            SELECT method, SUM(call_count) as total_count
            FROM method_counts
            WHERE classification IN ({class_filter})
            GROUP BY method
            ORDER BY total_count DESC
        """)
        
        result = {}
        for row in cursor.fetchall():
            result[row["method"]] = row["total_count"]
        
        return result
    
    def get_ip_counts(
        self, include_unauthenticated: bool = True, exclude_unauthenticated: bool = False, limit: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Return top IP addresses by call count, filtered by include/exclude unauthenticated.
        
        Returns list of dicts with ip and call_count.
        """
        self._ensure_flushed()
        assert self.conn is not None
        cursor = self.conn.cursor()
        
        # Build classification filter
        classifications = ["authenticated_user", "service_account"]
        if include_unauthenticated and not exclude_unauthenticated:
            classifications.append("unauthenticated")
        
        class_filter = "'" + "','".join(classifications) + "'"
        
        # Query top IPs
        cursor.execute(f"""
            SELECT ip, SUM(call_count) as total_count
            FROM ip_counts
            WHERE classification IN ({class_filter})
            GROUP BY ip
            ORDER BY total_count DESC
            LIMIT ?
        """, (limit,))
        
        result = []
        for row in cursor.fetchall():
            result.append({
                "ip": row["ip"],
                "call_count": row["total_count"],
            })
        
        return result
