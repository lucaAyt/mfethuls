"""Bring what was ingested back in line with the registry.

The registry is the source of truth. Ingest derives everything else from it: the
manifest (experiment IDs), the DuckDB catalog, the stored Parquet files and any
metadata sink of the stores (see :mod:`mfethuls.stores`). When rows are removed or changed in
the registry, those derived records drift. :func:`plan` compares them with the
registry and lists what to do; :func:`apply` does it.

- **relink**: a registry row whose raw data has no manifest entry, while a forgotten
  entry of the same instrument has exactly the same content hash. The raw file was
  renamed: the entry is pointed at the new name and keeps its experiment ID and data.
- **forget**: a manifest entry, catalog row or stored dataset that no registry row
  produces any more. Its catalog rows, stored files, metadata sink records and
  manifest entry are removed. Raw data is never touched.
- **refresh**: an experiment whose catalog row disagrees with the registry (renamed,
  sample or run corrected) or is missing. It is ingested again, from the stored
  dataset when possible.
- **reparse**: an experiment whose reader changed since it was ingested: its
  instrument definition was edited, it is now read by a definition, or mfethuls'
  code parser for it was improved (each has a version). Its raw data is read again.
- **remove_files**: stored files no experiment uses any more (older versions left
  behind after a sample or run change, or files of unknown experiments).

Plans also list registry rows that were never ingested (``pending``) and experiments
whose raw data is identical (``duplicates``); neither needs action.

Rows that are in the registry but invalid still protect their data: nothing is
forgotten because of a typo. A plan that would forget more than ``max_forget``
experiments (by default 10% of them, at least 3) is blocked unless ``force`` is
given, because a half-synced registry file looks just like deleted rows.

From the command line: ``mfethuls cleanup`` shows the plan, ``mfethuls cleanup --apply``
carries it out (on the local stores).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from .experiments import Experiment, Registry, _normalize_optional_str
from .manifest import content_hash
from .naming import stem_key
from .parsers.registry import reads
from .storage.config import _dataset_basename
from .stores import Stores

logger = logging.getLogger(__name__)

# Order in which apply carries out actions.
_ORDER = {"relink": 0, "forget": 1, "refresh": 2, "reparse": 3, "remove_files": 4}
LABELS = {"relink": "Relink", "forget": "Forget", "refresh": "Refresh", "reparse": "Read again",
          "remove_files": "Remove files"}
# Fields a catalog row must share with the registry row to be up to date.
_CATALOG_FIELDS = ("experiment_name", "raw_data_filename", "instrument_name", "sample_id", "run_id")


class ReconcileBlocked(RuntimeError):
    """The plan would forget more experiments than allowed; pass ``force`` to apply it anyway."""


@dataclass
class Action:
    kind: str  # "relink", "forget", "refresh", "reparse" or "remove_files"
    reason: str
    name: Optional[str] = None  # registry name, or the last known name of a forgotten experiment
    experiment_id: Optional[str] = None
    instrument_name: Optional[str] = None
    raw_data_filename: Optional[str] = None  # relink: the new raw data name
    table_names: List[str] = field(default_factory=list)  # catalog rows to remove
    paths: List[str] = field(default_factory=list)  # stored files to remove


@dataclass
class Plan:
    actions: List[Action]
    pending: List[str]  # registry names never ingested
    duplicates: List[List[str]]  # names of experiments with identical raw data
    known: int  # experiments in the manifest
    max_forget: int

    @property
    def forgets(self) -> int:
        return sum(1 for action in self.actions if action.kind == "forget")

    @property
    def blocked(self) -> bool:
        return self.forgets > self.max_forget

    @property
    def blocked_reason(self) -> Optional[str]:
        if not self.blocked:
            return None
        return (
            f"This would forget {self.forgets} of {self.known} experiments (more than {self.max_forget}). "
            "If the registry was only partly synced, sync it first. If the rows really were removed, "
            "apply with force."
        )

    def counts(self) -> Dict[str, int]:
        counts = {kind: 0 for kind in _ORDER}
        for action in self.actions:
            counts[action.kind] += 1
        return counts

    def fingerprint(self) -> str:
        """Identifies the actions, so a plan shown to someone can be checked before it is applied."""
        payload = json.dumps([asdict(action) for action in self.actions], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint(),
            "actions": [asdict(action) for action in self.actions],
            "pending": self.pending,
            "duplicates": self.duplicates,
            "known": self.known,
            "max_forget": self.max_forget,
            "forgets": self.forgets,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "counts": self.counts(),
        }


def _key(instrument_name: Any, raw_data_filename: Any) -> Tuple[Optional[str], Optional[str]]:
    # Instrument names are case-insensitive ("SEC" in the registry is the instrument "sec"), as at ingest.
    # Raw data names too: "lub446" in the registry is the experiment of LUB446.txt (manifest.stem_key).
    instrument = _normalize_optional_str(instrument_name)
    raw = _normalize_optional_str(raw_data_filename)
    return (instrument.casefold() if instrument else instrument), (stem_key(raw) if raw else raw)


def _registry_keys(registry: Registry) -> set:
    """(instrument, raw data) of every registry row, including rows skipped as invalid."""

    keys = set()
    for rec in registry.frame.to_dict(orient="records"):
        # A row's raw data is its raw_data_filename, else its name; both go through _key (case-folded).
        raw = _normalize_optional_str(rec.get("raw_data_filename")) or _normalize_optional_str(rec.get("name"))
        instrument, raw = _key(rec.get("instrument_name"), raw)
        if instrument and raw:
            keys.add((instrument, raw))
    return keys


def _experiment_key(exp: Experiment) -> Tuple[Optional[str], Optional[str]]:
    return _key(exp.instrument_name, exp.raw_data_filename or exp.name)


def raw_data_hash(exp: Experiment) -> Optional[str]:
    """The content hash of the raw data files an experiment would ingest; ``None`` if not found."""

    from .config.loader import prepare_instruments

    raw = exp.raw_data_filename or exp.name
    try:
        bundle = prepare_instruments(filters={"name": [exp.instrument_name]}, experiments=[raw])
        instrument = bundle.instruments[exp.instrument_name]
        files = [f for f in bundle.data_paths[exp.instrument_name].get(raw, []) if reads(instrument.parser, f)]
    except Exception:  # missing or ambiguous raw data: no match possible
        return None
    return content_hash(files) if files else None


def renamed_entry(exp: Experiment, registry: Registry, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The manifest entry ``exp``'s raw data was renamed from, or None.

    The rule of the relink action, for one registry row whose raw data has no entry:
    exactly one entry of the same instrument that no registry row produces any more has
    the same content hash. The raw files are only hashed when such entries exist.
    """
    if not exp.instrument_name:
        return None
    registry_keys = _registry_keys(registry)
    candidates = [e for e in entries if e.get("content_hash")
                  and _key(e["instrument_name"], e["raw_data_filename"])[0] == exp.instrument_name
                  and _key(e["instrument_name"], e["raw_data_filename"]) not in registry_keys]
    if not candidates:
        return None
    raw_hash = raw_data_hash(exp)
    matches = [e for e in candidates if e["content_hash"] == raw_hash] if raw_hash else []
    return matches[0] if len(matches) == 1 else None


def _stored_files(stores: Stores) -> Dict[Tuple[str, str], List[str]]:
    if stores.storage is None:
        return {}
    try:
        return stores.storage.stored_files()
    except NotImplementedError:
        logger.warning("%s cannot list stored files; stored files are left alone.", type(stores.storage).__name__)
        return {}


def _stale_catalog_fields(row: Dict[str, Any], exp: Experiment) -> List[str]:
    wanted = {
        "experiment_name": exp.name,
        "raw_data_filename": exp.raw_data_filename or exp.name,
        "instrument_name": exp.instrument_name,
        "sample_id": exp.sample_id,
        "run_id": exp.run_id,
    }
    return [name for name in _CATALOG_FIELDS if _normalize_optional_str(row.get(name)) != _normalize_optional_str(wanted[name])]


def _reader_change(rows: List[Dict[str, Any]], exp: Experiment) -> Optional[str]:
    """Why the experiment's raw data must be read again: its reader changed since it was read."""
    from .instruments.configured import definition_for, instrument_entries
    from .parsers.registry import get_parser, reader_fingerprint

    entry = next((e for e in instrument_entries() if e["name"] == str(exp.instrument_name or "").casefold()), None)
    if entry is None:
        return None
    try:
        current = reader_fingerprint(get_parser(entry["type"], entry["model"]))
    except ValueError:
        return None
    stored = {_normalize_optional_str(row.get("reader_fingerprint")) for row in rows}
    if stored == {current}:
        return None
    definition = definition_for(exp.instrument_name)
    if definition is None:
        before = ", ".join(sorted(value for value in stored if value)) or "an older reader"
        return f"read by another version of mfethuls' {exp.instrument_name} reader ({before} -> {current})"
    if stored <= {None} or any(value and "-v" in value for value in stored):
        return f"{exp.instrument_name} is now read by an instrument definition"
    definition_part, _, engine = current.partition("@")
    if any(value and value.partition("@")[0] == definition_part for value in stored):
        before = ", ".join(sorted(value.partition("@")[2] or "an older reader" for value in stored if value))
        return f"read by another version of mfethuls' definition reader ({before} -> {engine})"
    return f"the instrument definition of {exp.instrument_name} has changed"


def plan(registry: Registry, stores: Stores, *, max_forget: Optional[int] = None) -> Plan:
    """Compare the registry with the stores and list what :func:`apply` would do. Changes nothing."""

    entries = stores.manifest.all_mappings()
    by_key = {_key(e["instrument_name"], e["raw_data_filename"]): e for e in entries}
    by_id = {e["experiment_id"]: e for e in entries}
    catalog: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for row in stores.catalog.list_registered():
        catalog[row.get("experiment_id")].append(row)
    stored = _stored_files(stores)
    stored_ids = {key[1]: key for key in stored}  # experiment_id -> (instrument, experiment_id)

    registry_keys = _registry_keys(registry)
    orphans = {e["experiment_id"]: e for key, e in by_key.items() if key not in registry_keys}
    experiments = list(registry)
    unmatched = [exp for exp in experiments if _experiment_key(exp) not in by_key]
    actions: List[Action] = []

    # Renamed raw data: an unmatched row with the same content as exactly one forgotten entry.
    forgotten_by_hash: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for entry in orphans.values():
        if entry.get("content_hash"):
            forgotten_by_hash[(entry["instrument_name"], entry["content_hash"])].append(entry)
    relinked: Dict[str, Dict[str, Any]] = {}
    instruments_with_candidates = {instrument for instrument, _ in forgotten_by_hash}
    for exp in unmatched:
        if exp.instrument_name not in instruments_with_candidates:
            continue
        matches = forgotten_by_hash.get((exp.instrument_name, raw_data_hash(exp)), [])
        if len(matches) != 1 or matches[0]["experiment_id"] not in orphans:
            continue
        entry = orphans.pop(matches[0]["experiment_id"])
        relinked[exp.name] = entry
        new_raw = exp.raw_data_filename or exp.name
        actions.append(Action(
            "relink",
            f"raw data renamed from {entry['raw_data_filename']!r} to {new_raw!r} (same content)",
            name=exp.name, experiment_id=entry["experiment_id"], instrument_name=exp.instrument_name,
            raw_data_filename=new_raw,
        ))
    pending = [exp.name for exp in unmatched if exp.name not in relinked]

    def forget(experiment_id, instrument, name, reason):
        rows = catalog.get(experiment_id, [])
        key = stored_ids.get(experiment_id) if experiment_id else None
        actions.append(Action(
            "forget", reason, name=name, experiment_id=experiment_id, instrument_name=instrument,
            table_names=[row["table_name"] for row in rows],
            paths=list(stored.get(key, [])) if key else [row["storage_path"] for row in rows],
        ))

    for entry in orphans.values():
        forget(entry["experiment_id"], entry["instrument_name"], entry.get("experiment_name"),
               f"{entry['instrument_name']}/{entry['raw_data_filename']} is no longer in the registry")
    for experiment_id, rows in catalog.items():
        if experiment_id not in by_id:
            forget(experiment_id, rows[0].get("instrument_name"), rows[0].get("experiment_name"),
                   "in the catalog but not in the manifest")
    for (instrument, experiment_id), paths in stored.items():
        if experiment_id not in by_id and experiment_id not in catalog:
            actions.append(Action("remove_files", "stored data of an unknown experiment",
                                  experiment_id=experiment_id, instrument_name=instrument, paths=list(paths)))

    for exp in experiments:
        entry = by_key.get(_experiment_key(exp)) or relinked.get(exp.name)
        if entry is None:
            continue
        experiment_id = entry["experiment_id"]
        rows = catalog.get(experiment_id, [])
        if exp.name in relinked:
            reason = "raw data renamed"
        elif not rows:
            reason = "not in the catalog"
        else:
            changed = sorted({f for row in rows for f in _stale_catalog_fields(row, exp)})
            reason = f"changed in the registry: {', '.join(changed)}" if changed else None
        reread = _reader_change(rows, exp) if rows else None
        if reread:
            actions.append(Action("reparse", reread, name=exp.name, experiment_id=experiment_id,
                                  instrument_name=exp.instrument_name))
        elif reason:
            actions.append(Action("refresh", reason, name=exp.name, experiment_id=experiment_id,
                                  instrument_name=exp.instrument_name))

        base = _dataset_basename(replace(exp, experiment_id=experiment_id))
        keep = {f"{base}.parquet", f"{base}.metadata.json"}
        stale = [p for p in stored.get((exp.instrument_name, experiment_id), []) if os.path.basename(p) not in keep]
        if stale:
            actions.append(Action("remove_files", "older versions left after a sample or run change",
                                  name=exp.name, experiment_id=experiment_id, instrument_name=exp.instrument_name,
                                  paths=stale))

    kept = [e for e in entries if e["experiment_id"] not in orphans]
    groups: Dict[str, List[str]] = defaultdict(list)
    for entry in kept:
        if entry.get("content_hash"):
            groups[entry["content_hash"]].append(entry.get("experiment_name") or entry["raw_data_filename"])
    duplicates = sorted(sorted(names) for names in groups.values() if len(names) > 1)

    if max_forget is None:
        max_forget = max(3, math.ceil(0.1 * len(entries)))
    actions.sort(key=lambda action: (_ORDER[action.kind], action.name or "", action.experiment_id or ""))
    return Plan(actions, pending, duplicates, known=len(entries), max_forget=max_forget)


def _remove_files(paths: List[str], stores: Stores) -> None:
    if not paths or stores.storage is None:
        return
    try:
        stores.storage.remove_files(paths)
    except NotImplementedError:
        logger.warning("%s cannot remove files; left in place: %s", type(stores.storage).__name__, ", ".join(paths))


def _forget(action: Action, stores: Stores) -> None:
    for table_name in action.table_names:
        stores.catalog.remove_dataset(table_name)
    _remove_files(action.paths, stores)
    if action.experiment_id:
        if stores.metadata is not None:
            stores.metadata.remove_experiment(action.experiment_id)
        stores.manifest.forget(experiment_id=action.experiment_id)


def _refresh(action: Action, registry: Registry, stores: Stores) -> None:
    from .config.loader import ingest_experiment_dataset

    result = ingest_experiment_dataset(action.name, registry=registry, stores=stores,
                                       refresh=action.kind == "reparse")
    status = (result or {}).get("status")
    if status not in {"registered", "persisted"}:
        raise RuntimeError(f"ingest returned status {status!r}")


class PlanChanged(RuntimeError):
    """The plan differs from the one that was reviewed; check again before applying."""


def apply_reviewed(
    registry: Registry, stores: Stores, *, fingerprint: str, force: bool = False
) -> List[Dict[str, Any]]:
    """Plan again and apply, but only if the plan is the one reviewed (same :meth:`Plan.fingerprint`)."""

    current = plan(registry, stores)
    if current.fingerprint() != fingerprint:
        raise PlanChanged("The registry or the stored data changed since the check. Check again before applying.")
    return apply(current, registry, stores, force=force)


def apply(plan: Plan, registry: Registry, stores: Stores, *, force: bool = False) -> List[Dict[str, Any]]:
    """Carry out ``plan``; returns one result per action (``status`` "done", "skipped" or "error").

    Actions run in the order relink, forget, refresh, remove_files. A failed action
    does not stop the others; running reconcile again picks up what is left. Old
    versions of an experiment's files are only removed once its refresh succeeded.
    """

    if plan.blocked and not force:
        raise ReconcileBlocked(plan.blocked_reason)

    failed_refresh: set = set()
    results = []
    for action in plan.actions:
        result = {"kind": action.kind, "name": action.name, "experiment_id": action.experiment_id, "status": "done"}
        try:
            if action.kind == "relink":
                stores.manifest.relink(experiment_id=action.experiment_id, raw_data_filename=action.raw_data_filename)
            elif action.kind == "forget":
                _forget(action, stores)
            elif action.kind in ("refresh", "reparse"):
                try:
                    _refresh(action, registry, stores)
                except Exception:
                    failed_refresh.add(action.experiment_id)
                    raise
            elif action.kind == "remove_files":
                if action.experiment_id in failed_refresh:
                    result["status"] = "skipped"
                    result["error"] = "kept because the refresh of this experiment failed"
                else:
                    _remove_files(action.paths, stores)
        except Exception as exc:  # noqa: BLE001 - reported per action
            logger.warning("Reconcile %s of %r failed: %s", action.kind, action.name or action.experiment_id, exc)
            result["status"] = "error"
            result["error"] = str(exc)
        results.append(result)
    return results


def format_plan(plan: Plan) -> str:
    """The plan as plain text, for ``mfethuls cleanup``."""

    lines = []
    labels = LABELS
    for action in plan.actions:
        who = action.name or action.experiment_id
        extra = f" ({len(action.paths)} files)" if action.paths else ""
        lines.append(f"  {labels[action.kind]:<13} {who}: {action.reason}{extra}")
    if not lines:
        lines.append("  Nothing to do: everything ingested matches the registry.")
    if plan.pending:
        lines.append(f"Never ingested ({len(plan.pending)}): {', '.join(plan.pending)}")
    for names in plan.duplicates:
        lines.append(f"Identical raw data: {', '.join(names)}")
    if plan.blocked:
        lines.append(f"BLOCKED: {plan.blocked_reason}")
    return "\n".join(lines)
