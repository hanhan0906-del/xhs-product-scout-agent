from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .db import enqueue, get_monitor_state, set_monitor_state
from .product_keyword_terms import load_discovery_roots


DEFAULT_DISCOVERY_ROOTS = ("虚拟资料",)
APPROVED_KEYWORD_SOURCE = "approved_discovery_keyword"
CONTINUOUS_ROOT_SOURCE = "continuous_24h_root"
CONTINUOUS_APPROVED_SOURCE = "continuous_24h_approved"
ACTIVE_TASK_STATUSES = ("pending", "running")
NON_REUSABLE_TASK_STATUSES = ("paused", "needs_manual_detail", "risk_stopped")
DISCOVERY_ROOT_TERMS_RELATIVE = Path("config") / "discovery_root_terms.txt"


def load_continuous_discovery_roots(
    project_root: str | Path,
    *,
    expected_count: int = 100,
) -> tuple[str, ...]:
    """Load the audited root-term rotation in its configured file order.

    The scheduler can pass ``Settings.root`` to this helper.  The conservative
    one-term default remains available for callers that have not explicitly
    connected a project root yet.
    """
    return load_discovery_roots(
        Path(project_root) / DISCOVERY_ROOT_TERMS_RELATIVE,
        expected_count=expected_count,
    )


@dataclass(frozen=True)
class ContinuousDiscoveryPlan:
    selected: bool
    task_id: int | None
    keyword: str | None
    search_result_rank: int | None
    created: bool
    reason: str
    allowed_keyword_count: int
    deferred: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return {
            "selected": self.selected,
            "task_id": self.task_id,
            "keyword": self.keyword,
            "search_result_rank": self.search_result_rank,
            "created": self.created,
            "reason": self.reason,
            "allowed_keyword_count": self.allowed_keyword_count,
            "deferred": list(self.deferred),
        }


def plan_continuous_discovery_round(
    conn,
    *,
    roots: Sequence[str] = DEFAULT_DISCOVERY_ROOTS,
    now: datetime | None = None,
    cooldown_seconds: int = 3600,
    card_slots: int = 3,
) -> ContinuousDiscoveryPlan:
    """Select one rank from an explicitly allowed keyword batch.

    The old seed/portfolio queue is deliberately ignored. Allowed keywords are
    the configured discovery roots plus phrases previously written through the
    approved discovery-keyword path.  The cursor stays on the selected keyword
    while ranks 1..``card_slots`` are collected; the scheduler advances it only
    after the final rank succeeds.
    """
    if cooldown_seconds < 60:
        raise ValueError("cooldown_seconds must be at least 60")
    if card_slots < 1 or card_slots > 10:
        raise ValueError("card_slots must be between 1 and 10")

    state = get_monitor_state(conn)
    if state.get("risk_stop_reason"):
        return ContinuousDiscoveryPlan(
            selected=False,
            task_id=None,
            keyword=None,
            search_result_rank=None,
            created=False,
            reason="risk_stop_active",
            allowed_keyword_count=0,
        )

    allowed = _allowed_keywords(conn, roots)
    if not allowed:
        return ContinuousDiscoveryPlan(
            selected=False,
            task_id=None,
            keyword=None,
            search_result_rank=None,
            created=False,
            reason="no_allowed_keyword",
            allowed_keyword_count=0,
        )

    current = now or datetime.now(timezone.utc).astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    cursor = int(state.get("continuous_discovery_cursor") or 0) % len(allowed)
    ordered = allowed[cursor:] + allowed[:cursor]
    cutoff = current - timedelta(seconds=cooldown_seconds)
    deferred: list[dict] = []

    for offset, (keyword, kind) in enumerate(ordered):
        active = conn.execute(
            """
            SELECT id FROM search_tasks
            WHERE keyword=? AND status IN ('pending', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (keyword,),
        ).fetchone()
        if active is not None:
            selected_cursor = (cursor + offset) % len(allowed)
            set_monitor_state(
                conn, "continuous_discovery_cursor", selected_cursor
            )
            return ContinuousDiscoveryPlan(
                selected=True,
                task_id=int(active["id"]),
                keyword=keyword,
                search_result_rank=_next_card_rank(conn, keyword, card_slots),
                created=False,
                reason="existing_allowed_task",
                allowed_keyword_count=len(allowed),
                deferred=tuple(deferred),
            )

        blocker = conn.execute(
            """
            SELECT id, status, attempts FROM search_tasks
            WHERE keyword=? AND status IN ('paused', 'needs_manual_detail', 'risk_stopped')
            ORDER BY id DESC LIMIT 1
            """,
            (keyword,),
        ).fetchone()
        if blocker is not None:
            deferred.append(
                {
                    "keyword": keyword,
                    "reason": "enqueue_conflict",
                    "task_id": int(blocker["id"]),
                    "status": blocker["status"],
                    "attempts": int(blocker["attempts"]),
                }
            )
            continue

        next_rank = _next_card_rank(conn, keyword, card_slots)
        recent = conn.execute(
            """
            SELECT COALESCE(last_finished_at, updated_at) AS last_at
            FROM search_tasks
            WHERE keyword=?
            ORDER BY id DESC LIMIT 1
            """,
            (keyword,),
        ).fetchone()
        if recent is not None and recent["last_at"]:
            try:
                last_at = datetime.fromisoformat(recent["last_at"])
            except (TypeError, ValueError):
                last_at = current
            if last_at.tzinfo is None or last_at.utcoffset() is None:
                last_at = current
            # A partially collected batch must continue immediately through
            # ranks 2..N.  Cooldown applies only when the next cycle would
            # start again at rank 1.
            if next_rank == 1 and last_at >= cutoff:
                deferred.append(
                    {
                        "keyword": keyword,
                        "reason": "keyword_cooldown",
                        "last_at": recent["last_at"],
                    }
                )
                continue

        source = (
            CONTINUOUS_ROOT_SOURCE
            if kind == "root"
            else CONTINUOUS_APPROVED_SOURCE
        )
        inserted = enqueue(conn, [keyword], source=source)
        task = conn.execute(
            """
            SELECT id FROM search_tasks
            WHERE keyword=? AND status='pending'
            ORDER BY id DESC LIMIT 1
            """,
            (keyword,),
        ).fetchone()
        if task is None:
            conflict = conn.execute(
                """
                SELECT id, status, attempts FROM search_tasks
                WHERE keyword=?
                  AND status IN ('pending', 'running', 'paused',
                                 'needs_manual_detail', 'risk_stopped')
                ORDER BY id DESC LIMIT 1
                """,
                (keyword,),
            ).fetchone()
            detail = {"keyword": keyword, "reason": "enqueue_conflict"}
            if conflict is not None:
                detail.update(
                    task_id=int(conflict["id"]),
                    status=conflict["status"],
                    attempts=int(conflict["attempts"]),
                )
            deferred.append(detail)
            continue
        selected_cursor = (cursor + offset) % len(allowed)
        set_monitor_state(conn, "continuous_discovery_cursor", selected_cursor)
        return ContinuousDiscoveryPlan(
            selected=True,
            task_id=int(task["id"]),
            keyword=keyword,
            search_result_rank=next_rank,
            created=bool(inserted),
            reason="new_allowed_task",
            allowed_keyword_count=len(allowed),
            deferred=tuple(deferred),
        )

    return ContinuousDiscoveryPlan(
        selected=False,
        task_id=None,
        keyword=None,
        search_result_rank=None,
        created=False,
        reason=(
            "all_allowed_keywords_cooling_down"
            if deferred and all(
                item.get("reason") == "keyword_cooldown" for item in deferred
            )
            else "all_allowed_keywords_deferred"
        ),
        allowed_keyword_count=len(allowed),
        deferred=tuple(deferred),
    )


def _allowed_keywords(conn, roots: Sequence[str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        keyword = str(root).strip()
        normalized = "".join(keyword.split()).casefold()
        if keyword and normalized not in seen:
            seen.add(normalized)
            values.append((keyword, "root"))

    for row in conn.execute(
        """
        SELECT keyword, MAX(id) AS latest_id
        FROM search_tasks
        WHERE source=?
        GROUP BY keyword
        ORDER BY latest_id
        """,
        (APPROVED_KEYWORD_SOURCE,),
    ):
        keyword = str(row["keyword"]).strip()
        normalized = "".join(keyword.split()).casefold()
        if keyword and normalized not in seen:
            seen.add(normalized)
            values.append((keyword, "approved"))
    return values


def _next_card_rank(conn, keyword: str, card_slots: int) -> int:
    evidence_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM search_result_evidence AS evidence
        WHERE evidence.source_keyword=?
          AND evidence.valid=1
          AND EXISTS (
              SELECT 1
              FROM task_results AS result
              WHERE result.task_id=evidence.task_id
                AND result.product_id=evidence.product_id
                AND result.observation_id=evidence.observation_id
                AND result.valid=1
          )
        """,
        (keyword,),
    ).fetchone()[0]
    return int(evidence_count) % card_slots + 1
