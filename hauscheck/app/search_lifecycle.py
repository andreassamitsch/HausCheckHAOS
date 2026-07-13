from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

import app.analysis_package as analysis_package
import app.search_automation as search_automation
from app.storage import (
    connect,
    ensure_columns,
    list_search_candidates,
    now_iso,
    source_url_exists,
)
from app.ui_helpers import score_property


_patched = False


def ensure_search_lifecycle_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "search_candidates",
            {
                "lifecycle_hash": "TEXT",
                "previous_price_eur": "INTEGER",
                "price_changed_at": "TEXT",
                "price_change_percent": "REAL",
                "change_summary": "TEXT",
                "material_change_count": "INTEGER NOT NULL DEFAULT 0",
                "miss_count": "INTEGER NOT NULL DEFAULT 0",
                "reactivated_at": "TEXT",
                "needs_reanalysis": "INTEGER NOT NULL DEFAULT 0",
                "analysis_refreshed_at": "TEXT",
            },
        )
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidate_price_history (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                price_eur INTEGER,
                observed_at TEXT NOT NULL,
                change_type TEXT NOT NULL DEFAULT 'observed',
                FOREIGN KEY(candidate_id) REFERENCES search_candidates(id)
            );

            CREATE TABLE IF NOT EXISTS candidate_change_events (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT,
                old_data_json TEXT,
                new_data_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES search_candidates(id)
            );

            CREATE INDEX IF NOT EXISTS idx_candidate_price_history_candidate
                ON candidate_price_history(candidate_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_candidate_change_events_candidate
                ON candidate_change_events(candidate_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_candidates_lifecycle
                ON search_candidates(profile_id, status, last_seen_at);
            """
        )
        con.commit()


def _snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": candidate.get("title"),
        "price_eur": candidate.get("price_eur"),
        "living_area_m2": candidate.get("living_area_m2"),
        "plot_area_m2": candidate.get("plot_area_m2"),
        "energy_hwb": candidate.get("energy_hwb"),
        "preview_image_url": candidate.get("preview_image_url"),
    }


def _lifecycle_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _same_value(old: object, new: object) -> bool:
    old_number = _number(old)
    new_number = _number(new)
    if old_number is not None or new_number is not None:
        if old_number is None or new_number is None:
            return False
        return abs(old_number - new_number) < 0.001
    return str(old or "").strip() == str(new or "").strip()


def _change_descriptions(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    labels = {
        "title": "Titel geändert",
        "price_eur": "Preis geändert",
        "living_area_m2": "Wohnfläche geändert",
        "plot_area_m2": "Grundstücksfläche geändert",
        "energy_hwb": "HWB geändert",
        "preview_image_url": "Vorschaubild geändert",
    }
    return [label for key, label in labels.items() if not _same_value(old.get(key), new.get(key))]


def _insert_price_history(con: Any, candidate_id: str, price: object, change_type: str, timestamp: str) -> None:
    if price in (None, ""):
        return
    try:
        price_int = int(round(float(price)))
    except Exception:
        return
    latest = con.execute(
        "SELECT price_eur FROM candidate_price_history WHERE candidate_id = ? ORDER BY observed_at DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    if latest and latest[0] == price_int:
        return
    con.execute(
        "INSERT INTO candidate_price_history (id, candidate_id, price_eur, observed_at, change_type) VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex[:12], candidate_id, price_int, timestamp, change_type),
    )


def _insert_event(
    con: Any,
    candidate_id: str,
    event_type: str,
    summary: str,
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any] | None,
    timestamp: str,
) -> None:
    con.execute(
        """
        INSERT INTO candidate_change_events (
            id, candidate_id, event_type, summary, old_data_json, new_data_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex[:12],
            candidate_id,
            event_type,
            summary,
            json.dumps(old_data, ensure_ascii=False, default=str) if old_data is not None else None,
            json.dumps(new_data, ensure_ascii=False, default=str) if new_data is not None else None,
            timestamp,
        ),
    )


def apply_lifecycle_after_search(
    profile_id: str,
    before: dict[str, dict[str, Any]],
    found_count: int,
) -> dict[str, Any]:
    ensure_search_lifecycle_schema()
    timestamp = now_iso()
    after = list_search_candidates(profile_id)
    changed_ids: list[str] = []
    offline_ids: list[str] = []
    reactivated_ids: list[str] = []
    reanalysis_house_ids: list[str] = []

    with connect() as con:
        for candidate in after:
            candidate_id = str(candidate.get("id") or "")
            old = before.get(candidate_id)
            current_snapshot = _snapshot(candidate)
            current_hash = _lifecycle_hash(current_snapshot)
            decision = str(candidate.get("decision") or "")

            if old is None:
                _insert_price_history(con, candidate_id, candidate.get("price_eur"), "initial", timestamp)
                con.execute(
                    "UPDATE search_candidates SET lifecycle_hash = ?, miss_count = 0 WHERE id = ?",
                    (current_hash, candidate_id),
                )
                continue

            seen_now = str(candidate.get("last_seen_at") or "") != str(old.get("last_seen_at") or "")
            old_snapshot = _snapshot(old)
            old_hash = str(old.get("lifecycle_hash") or "")
            old_status = str(old.get("status") or "new")

            if decision == "rejected" or old_status == "rejected":
                con.execute(
                    "UPDATE search_candidates SET status = 'rejected', decision = 'rejected', lifecycle_hash = ? WHERE id = ?",
                    (current_hash, candidate_id),
                )
                continue

            if seen_now:
                changes = _change_descriptions(old_snapshot, current_snapshot) if old_hash else []
                reactivated = old_status == "offline" or bool(old.get("offline_at"))
                previous_price = old.get("price_eur")
                current_price = candidate.get("price_eur")
                price_changed = old_hash != "" and not _same_value(previous_price, current_price)
                price_percent: float | None = None
                if price_changed:
                    old_price_number = _number(previous_price)
                    new_price_number = _number(current_price)
                    if old_price_number and new_price_number is not None:
                        price_percent = round((new_price_number - old_price_number) / old_price_number * 100.0, 2)
                    _insert_price_history(con, candidate_id, current_price, "changed", timestamp)
                    _insert_event(
                        con,
                        candidate_id,
                        "price_changed",
                        f"Preis von {previous_price} auf {current_price} geändert",
                        old_snapshot,
                        current_snapshot,
                        timestamp,
                    )

                if changes:
                    changed_ids.append(candidate_id)
                    _insert_event(
                        con,
                        candidate_id,
                        "content_changed",
                        " · ".join(changes),
                        old_snapshot,
                        current_snapshot,
                        timestamp,
                    )

                if reactivated:
                    reactivated_ids.append(candidate_id)
                    _insert_event(
                        con,
                        candidate_id,
                        "reactivated",
                        "Inserat ist wieder online",
                        old_snapshot,
                        current_snapshot,
                        timestamp,
                    )

                imported_house_id = str(candidate.get("imported_house_id") or "")
                if imported_house_id:
                    new_status = "imported"
                elif reactivated:
                    new_status = "reactivated"
                elif changes:
                    new_status = "changed"
                else:
                    new_status = str(candidate.get("status") or "new")

                needs_reanalysis = 1 if imported_house_id and bool(changes) else int(candidate.get("needs_reanalysis") or 0)
                if needs_reanalysis and imported_house_id:
                    reanalysis_house_ids.append(imported_house_id)

                con.execute(
                    """
                    UPDATE search_candidates
                    SET status = ?, decision = CASE WHEN decision IN ('rejected', 'auto_imported') THEN decision ELSE ? END,
                        lifecycle_hash = ?, previous_price_eur = CASE WHEN ? = 1 THEN ? ELSE previous_price_eur END,
                        price_changed_at = CASE WHEN ? = 1 THEN ? ELSE price_changed_at END,
                        price_change_percent = CASE WHEN ? = 1 THEN ? ELSE price_change_percent END,
                        change_summary = ?, material_change_count = material_change_count + ?,
                        miss_count = 0, offline_at = NULL,
                        reactivated_at = CASE WHEN ? = 1 THEN ? ELSE reactivated_at END,
                        needs_reanalysis = ?
                    WHERE id = ?
                    """,
                    (
                        new_status,
                        new_status,
                        current_hash,
                        1 if price_changed else 0,
                        previous_price,
                        1 if price_changed else 0,
                        timestamp,
                        1 if price_changed else 0,
                        price_percent,
                        json.dumps(changes, ensure_ascii=False),
                        1 if changes else 0,
                        1 if reactivated else 0,
                        timestamp,
                        needs_reanalysis,
                        candidate_id,
                    ),
                )
                continue

            # Null Treffer können auf eine vorübergehende Portalstörung hindeuten.
            # In diesem Fall werden keine Objekte vorschnell offline gesetzt.
            if found_count <= 0 or candidate.get("imported_house_id") or old_status in {"imported", "rejected"}:
                con.execute(
                    "UPDATE search_candidates SET lifecycle_hash = COALESCE(lifecycle_hash, ?) WHERE id = ?",
                    (current_hash, candidate_id),
                )
                continue

            miss_count = int(old.get("miss_count") or 0) + 1
            goes_offline = miss_count >= 2
            if goes_offline and old_status != "offline":
                offline_ids.append(candidate_id)
                _insert_event(
                    con,
                    candidate_id,
                    "offline",
                    "Inserat wurde in zwei erfolgreichen Suchläufen nicht mehr gefunden",
                    old_snapshot,
                    old_snapshot,
                    timestamp,
                )
            con.execute(
                """
                UPDATE search_candidates
                SET miss_count = ?, status = CASE WHEN ? = 1 THEN 'offline' ELSE status END,
                    decision = CASE WHEN ? = 1 THEN 'offline' ELSE decision END,
                    offline_at = CASE WHEN ? = 1 THEN COALESCE(offline_at, ?) ELSE offline_at END,
                    lifecycle_hash = COALESCE(lifecycle_hash, ?)
                WHERE id = ?
                """,
                (
                    miss_count,
                    1 if goes_offline else 0,
                    1 if goes_offline else 0,
                    1 if goes_offline else 0,
                    timestamp,
                    current_hash,
                    candidate_id,
                ),
            )
        con.commit()

    return {
        "changed_ids": changed_ids,
        "offline_ids": offline_ids,
        "reactivated_ids": reactivated_ids,
        "reanalysis_house_ids": sorted(set(reanalysis_house_ids)),
    }


def list_candidate_price_history(candidate_id: str, limit: int = 10) -> list[dict[str, Any]]:
    ensure_search_lifecycle_schema()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM candidate_price_history WHERE candidate_id = ? ORDER BY observed_at DESC LIMIT ?",
            (candidate_id, max(1, min(int(limit), 50))),
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def list_candidate_events(candidate_id: str, limit: int = 10) -> list[dict[str, Any]]:
    ensure_search_lifecycle_schema()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM candidate_change_events WHERE candidate_id = ? ORDER BY created_at DESC LIMIT ?",
            (candidate_id, max(1, min(int(limit), 50))),
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def delete_search_profile_full(profile_id: str) -> None:
    ensure_search_lifecycle_schema()
    with connect() as con:
        exists = con.execute("SELECT 1 FROM search_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not exists:
            raise ValueError("Suchprofil nicht gefunden")
        candidate_ids = [
            row[0]
            for row in con.execute("SELECT id FROM search_candidates WHERE profile_id = ?", (profile_id,)).fetchall()
        ]
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            con.execute(f"DELETE FROM candidate_price_history WHERE candidate_id IN ({placeholders})", candidate_ids)
            con.execute(f"DELETE FROM candidate_change_events WHERE candidate_id IN ({placeholders})", candidate_ids)
        con.execute("DELETE FROM search_candidates WHERE profile_id = ?", (profile_id,))
        con.execute("DELETE FROM search_profiles WHERE id = ?", (profile_id,))
        con.commit()


def _eligible_candidates_lifecycle(profile: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    try:
        threshold = max(0, min(int(profile.get("auto_import_min_score") or 68), 100))
    except Exception:
        threshold = 68
    result: list[tuple[int, dict[str, Any]]] = []
    for candidate in list_search_candidates(str(profile["id"])):
        status = str(candidate.get("status") or "new")
        if status not in {"new", "changed", "reactivated"}:
            continue
        if candidate.get("imported_house_id"):
            continue
        source_url = str(candidate.get("source_url") or "")
        if not source_url or source_url_exists(source_url):
            continue
        score = int(score_property(candidate, status).get("score") or 0)
        if score >= threshold:
            result.append((score, candidate))
    result.sort(key=lambda pair: (pair[0], str(pair[1].get("first_seen_at") or "")), reverse=True)
    return result


def _wrap_save_analysis(original: Callable[[str, dict[str, Any]], Any]) -> Callable[[str, dict[str, Any]], Any]:
    def wrapped(house_id: str, data: dict[str, Any]) -> Any:
        target = original(house_id, data)
        timestamp = now_iso()
        with connect() as con:
            con.execute(
                """
                UPDATE search_candidates
                SET needs_reanalysis = 0, analysis_refreshed_at = ?
                WHERE imported_house_id = ?
                """,
                (timestamp, house_id),
            )
            con.commit()
        return target

    return wrapped


def register_search_lifecycle() -> None:
    global _patched
    if _patched:
        return
    ensure_search_lifecycle_schema()

    original_run = search_automation.run_search_profile

    async def run_with_lifecycle(profile_id: str, max_results: int = 80) -> int:
        before = {str(item.get("id")): dict(item) for item in list_search_candidates(profile_id)}
        found = await original_run(profile_id, max_results)
        lifecycle = apply_lifecycle_after_search(profile_id, before, found)
        if lifecycle["changed_ids"] or lifecycle["offline_ids"] or lifecycle["reactivated_ids"]:
            print(f"HausCheck Inserat-Lifecycle {profile_id}: {lifecycle}", flush=True)
        return found

    search_automation.run_search_profile = run_with_lifecycle
    search_automation._eligible_candidates = _eligible_candidates_lifecycle

    original_save = analysis_package.save_analysis
    wrapped_save = _wrap_save_analysis(original_save)
    analysis_package.save_analysis = wrapped_save
    try:
        import app.github_exchange as github_exchange

        github_exchange.save_analysis = wrapped_save
    except Exception:
        pass

    _patched = True
