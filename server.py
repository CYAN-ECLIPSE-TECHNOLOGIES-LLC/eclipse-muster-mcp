#!/usr/bin/env python3
"""Eclipse Muster MCP — v0.1.0, phase C0 (Customer Graph core).

Powered by Cyan Eclipse Technologies (cetech.ai).

Descriptor (family spec, eclipse-customer-family-spec-20261025): the
Eclipse customer adapter family — one canonical Customer Graph becomes
governed reads, internal writes, and owner-approved drafts and sends
across the popular CRM and customer-service platforms, according to
what each platform actually sanctions. Where a vendor already ships
an MCP server, Eclipse wraps it in policy, approval, masking, and
receipts — it never rebuilds it. Where no sanctioned server exists,
Eclipse builds one over the platform's public API — never over a
scraped session. Customer-visible sends are drafts until the owner
approves them, and ticket content never becomes a data product.

This server is the SHARED CORE (spec sections 5-7). It owns:
  * the canonical Customer Graph — Person / Company / Deal / Ticket /
    Conversation / Activity records where EVERY field carries
    provenance {platform, platform_object_id, source, observed_at,
    adapter_version} and every record carries a Data Rights Ledger
    block. A field without provenance does not enter the graph;
  * identity resolution — PROPOSE-ONLY merges (Beacon doctrine). The
    engine proposes candidate merges with evidence; a merge executes
    only on an owner-confirm token bound to the proposal hash, and a
    confirmed merge can be UNMERGED from the merge receipt, restoring
    the pre-merge nodes exactly;
  * the masking engine (Deep Field pattern) — field-level rules
    applied at egress: phone -> partial, email -> full on the owner
    surface / domain-only on analytic surfaces, government IDs /
    payment data / health-adjacent fields -> null in v1;
  * the drafting service — reply drafts generated ONLY from record
    facts, each with a citation list. A fact not traceable to a
    record field cannot appear; gaps surface as MISSING_FACT markers
    instead of being filled;
  * Herald Security Law #1 — customer-authored text is untrusted
    DATA. Instruction-shaped customer content is quarantined at
    ingest and never obeyed, never used as a drafting fact source;
  * the action-tier floors (Environment ladder transposed) — a
    policy that tries to LOWER a floor is rejected at load with a
    named error;
  * the append-only, hash-chained receipt ledger. Receipts carry
    IDs + hashes + tier + verdict — NEVER content (spec 5.5).

C0 SCOPE: local core over owner-fed records; fixtures are synthetic.
No platform is contacted, no credential exists, no send happens here
(sends are adapter tools gated by section 6.3 approval tokens).

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0), stdlib only.
State: $ECLIPSE_MUSTER_STATE or ./data/state.json beside this file.
Policy: ./policy.json beside this file (floors + kill switches).
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
STATE_PATH = Path(os.environ.get(
    "ECLIPSE_MUSTER_STATE", HERE / "data" / "state.json"))
POLICY_PATH = Path(os.environ.get(
    "ECLIPSE_MUSTER_POLICY", HERE / "policy.json"))

KINDS = {"person", "company", "deal", "ticket", "conversation",
         "activity"}

SOURCES = {"api", "mcp_wrap", "import", "owner_entry"}

# Action-class tier floors (spec 6.1). Nothing may lower a floor;
# a policy/config that tries is rejected at load (named error).
TIER_FLOORS = {
    "read": 0,
    "internal_write": 1,
    "draft_create": 1,
    "graph_merge_execute": 2,
    "customer_visible_send": 2,
    "destructive": 3,
    "platform_merge": 3,
    "automation_edit": 3,
}

# Field classes whose values are nulled at egress in v1 (spec 5.5:
# government IDs, payment data, health-adjacent free text).
NULL_FIELD_MARKERS = ("ssn", "gov_id", "tax_id", "passport",
                      "card_number", "payment", "iban", "health",
                      "diagnosis")

# Instruction-shaped customer content (Herald Law #1 fixtures). A
# customer message matching any marker is quarantined at ingest:
# kept as data, flagged, never a fact source, never obeyed.
INJECTION_MARKERS = (
    "ignore your instructions", "ignore previous instructions",
    "ignore all instructions", "disregard your instructions",
    "you must refund", "refund my", "refund me", "forward this",
    "send this thread", "reveal your system", "system prompt",
)


class ToolError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ------------------------------------------------------------------ policy
def load_policy() -> dict:
    """Load + validate policy. Tier floors may only be RAISED."""
    policy = {"tier_overrides": {}, "kill_writes": False,
              "kill_reads": False}
    if POLICY_PATH.exists():
        policy.update(json.loads(POLICY_PATH.read_text()))
    for action_class, tier in (policy.get("tier_overrides") or {}).items():
        if action_class not in TIER_FLOORS:
            raise ToolError(
                f"UNKNOWN_ACTION_CLASS: {action_class} is not a "
                f"classified action class")
        if int(tier) < TIER_FLOORS[action_class]:
            raise ToolError(
                f"TIER_FLOOR_VIOLATION: override for {action_class} "
                f"is T{tier}, below the core floor "
                f"T{TIER_FLOORS[action_class]}; tiers may only be "
                f"raised (spec 6.1)")
    return policy


def effective_tier(policy: dict, action_class: str) -> int:
    return max(TIER_FLOORS[action_class],
               int((policy.get("tier_overrides") or {}).get(
                   action_class, 0)))


try:
    POLICY = load_policy()
except ToolError:
    # main() re-validates strictly and exits 2; direct-import (tests)
    # falls back to bare floors so validators stay testable.
    POLICY = {"tier_overrides": {}, "kill_writes": False,
              "kill_reads": False}


def check_kill(policy: dict, action_class: str) -> None:
    tier = effective_tier(policy, action_class)
    if tier == 0 and policy.get("kill_reads"):
        raise ToolError("KILL_SWITCH: reads are halted by policy")
    if tier >= 1 and policy.get("kill_writes"):
        raise ToolError("KILL_SWITCH: writes are halted by policy")


# ------------------------------------------------------------------- state
def empty_state() -> dict:
    return {"records": {}, "proposals": {}, "merges": {},
            "drafts": {}, "receipts": []}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return empty_state()


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


# ---------------------------------------------------------------- receipts
def emit_receipt(state: dict, rtype: str, detail: dict) -> dict:
    """Append-only, hash-chained. Content-free by construction:
    callers pass IDs, hashes, tiers, verdicts — never field values
    or body text (spec 5.5)."""
    prev = state["receipts"][-1]["hash"] if state["receipts"] else "GENESIS"
    entry = {"seq": len(state["receipts"]) + 1, "ts": int(time.time()),
             "type": rtype, "prev_hash": prev, "detail": detail}
    entry["hash"] = sha(prev + canon(
        {k: v for k, v in entry.items() if k != "hash"}))
    state["receipts"].append(entry)
    return entry


def verify_receipt_chain(receipts) -> bool:
    prev = "GENESIS"
    for entry in receipts:
        if entry.get("prev_hash") != prev:
            return False
        expected = sha(prev + canon(
            {k: v for k, v in entry.items() if k != "hash"}))
        if entry.get("hash") != expected:
            return False
        prev = entry["hash"]
    return True


# ----------------------------------------------------------------- masking
def mask_value(field: str, value, surface: str):
    """Deep Field-style egress masking (spec 5.5)."""
    if isinstance(value, list):
        return [mask_value(field, item, surface) for item in value]
    name = field.lower()
    if any(marker in name for marker in NULL_FIELD_MARKERS):
        return None
    if isinstance(value, str) and "email" in name:
        if surface == "owner":
            return value
        local, _, domain = value.partition("@")
        return f"***@{domain}" if domain else "***"
    if "phone" in name or "mobile" in name or "tel" in name:
        text = str(value)
        digits = "".join(ch for ch in text if ch.isdigit())
        return f"***{digits[-2:]}" if len(digits) >= 2 else "***"
    if surface == "analytic" and name in ("name", "full_name"):
        parts = str(value).split()
        return " ".join(p[0] + "." for p in parts if p)
    return value


def masked_fields(record: dict, surface: str) -> dict:
    return {field: mask_value(field, fv["value"], surface)
            for field, fv in record["fields"].items()}


# ------------------------------------------------------------- record core
def validate_provenance(field: str, prov) -> None:
    if not isinstance(prov, dict):
        raise ToolError(
            f"PROVENANCE_MISSING: field '{field}' has no provenance; "
            f"a field without provenance does not enter the graph "
            f"(spec 5.3)")
    for key in ("platform", "platform_object_id", "source",
                "observed_at"):
        if not prov.get(key):
            raise ToolError(
                f"PROVENANCE_MISSING: field '{field}' provenance "
                f"lacks '{key}' (spec 5.3)")
    if prov["source"] not in SOURCES:
        raise ToolError(
            f"PROVENANCE_SOURCE: field '{field}' source "
            f"'{prov['source']}' is not one of {sorted(SOURCES)}")


def is_instruction_shaped(text) -> bool:
    if not isinstance(text, str):
        return False
    low = text.lower()
    return any(marker in low for marker in INJECTION_MARKERS)


def t_record_ingest(state, args):
    check_kill(POLICY, "internal_write")
    kind = str(args.get("kind") or "").lower()
    if kind not in KINDS:
        raise ToolError(f"unknown record kind '{kind}' "
                        f"(one of {sorted(KINDS)})")
    fields = args.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ToolError("record_ingest requires a non-empty fields map")
    provenance = args.get("field_provenance") or {}
    drl = args.get("data_rights")
    if not isinstance(drl, dict) or not drl.get("source_account") \
            or not drl.get("legal_basis"):
        raise ToolError(
            "DATA_RIGHTS_MISSING: every record carries a Data Rights "
            "Ledger block with source_account + legal_basis (spec 5.3)")
    stored_fields = {}
    quarantined = []
    for field, value in fields.items():
        validate_provenance(field, provenance.get(field))
        entry = {"value": value, "provenance": provenance[field]}
        if kind == "conversation" and field == "messages" \
                and isinstance(value, list):
            msgs = []
            for msg in value:
                msg = dict(msg)
                if msg.get("author") == "customer":
                    msg["trust"] = "untrusted_data"
                    if is_instruction_shaped(msg.get("body")):
                        msg["quarantined"] = True
                        quarantined.append(msg.get("message_id"))
                    else:
                        msg["quarantined"] = False
                else:
                    msg["trust"] = "trusted"
                    msg["quarantined"] = False
                msgs.append(msg)
            entry["value"] = msgs
        stored_fields[field] = entry
    record_id = str(args.get("record_id") or
                    f"{kind}-{sha(canon(fields))[:10]}")
    record = {
        "record_id": record_id, "kind": kind,
        "external_ids": args.get("external_ids") or {},
        "fields": stored_fields,
        "data_rights": {
            "source_account": drl["source_account"],
            "legal_basis": drl["legal_basis"],
            "method": drl.get("method", "adapter_ingest"),
            "retention": drl.get("retention", "graph-cache-30d"),
            "pii_class": drl.get("pii_class", "strictest"),
        },
        "ingested_at": now_iso(),
        "status": "active",
    }
    state["records"][record_id] = record
    receipt = emit_receipt(state, "record_ingested", {
        "record_id": record_id, "kind": kind, "tier": 1,
        "field_count": len(stored_fields),
        "fields_hash": sha(canon(
            {f: fv["value"] for f, fv in stored_fields.items()})),
        "quarantined_message_ids": quarantined,
        "verdict": "ALLOW"})
    return {"record_id": record_id, "kind": kind,
            "quarantined_message_ids": quarantined,
            "receipt_seq": receipt["seq"]}


def get_record(state, record_id):
    record = state["records"].get(str(record_id))
    if not record or record.get("status") == "merged_into":
        raise ToolError(f"unknown or merged record: {record_id}")
    return record


def t_record_read(state, args):
    check_kill(POLICY, "read")
    record = get_record(state, args.get("record_id"))
    surface = str(args.get("surface") or "analytic").lower()
    if surface not in ("owner", "analytic"):
        raise ToolError("surface must be 'owner' or 'analytic'")
    receipt = emit_receipt(state, "record_read", {
        "record_id": record["record_id"], "kind": record["kind"],
        "tier": 0, "surface": surface, "verdict": "ALLOW"})
    return {"record_id": record["record_id"], "kind": record["kind"],
            "external_ids": record["external_ids"],
            "fields": masked_fields(record, surface),
            "provenance": {f: fv["provenance"]
                           for f, fv in record["fields"].items()},
            "data_rights": record["data_rights"],
            "receipt_seq": receipt["seq"]}


def t_record_search(state, args):
    check_kill(POLICY, "read")
    kind = str(args.get("kind") or "").lower()
    query = str(args.get("query") or "").lower()
    surface = str(args.get("surface") or "analytic").lower()
    hits = []
    for record in state["records"].values():
        if record.get("status") == "merged_into":
            continue
        if kind and record["kind"] != kind:
            continue
        hay = canon({f: fv["value"]
                     for f, fv in record["fields"].items()}).lower()
        if query and query not in hay and query not in \
                record["record_id"].lower():
            continue
        hits.append({"record_id": record["record_id"],
                     "kind": record["kind"],
                     "fields": masked_fields(record, surface)})
    emit_receipt(state, "record_search", {
        "kind": kind or None, "tier": 0,
        "query_hash": sha(query) if query else None,
        "hit_count": len(hits), "verdict": "ALLOW"})
    return {"hits": hits, "count": len(hits), "surface": surface}


# ------------------------------------------------------------ merge engine
def field_values(record, field):
    fv = record["fields"].get(field)
    return fv["value"] if fv else None


def merge_evidence(a: dict, b: dict) -> dict:
    """Evidence for a candidate merge: matching keys + conflicts.
    Email/phone equality is evidence, not proof (spec 5.2)."""
    matched, conflicts = [], []
    for field in ("emails", "email", "phones", "phone"):
        va, vb = field_values(a, field), field_values(b, field)
        if va and vb:
            sa = {str(x).lower() for x in
                  (va if isinstance(va, list) else [va])}
            sb = {str(x).lower() for x in
                  (vb if isinstance(vb, list) else [vb])}
            if sa & sb:
                matched.append({"field": field,
                                "match_hash": sha(canon(sorted(sa & sb)))})
    for field in ("name", "full_name"):
        va, vb = field_values(a, field), field_values(b, field)
        if va and vb and str(va).lower() != str(vb).lower():
            conflicts.append({"field": field,
                              "values_kept": "both (per-platform)"})
    confidence = 0.0
    if matched:
        confidence = 0.9
    elif not conflicts:
        confidence = 0.3
    else:
        confidence = 0.15
    return {"matched_keys": matched, "conflicts": conflicts,
            "confidence": confidence,
            "warning": "shared inboxes, recycled numbers, and "
                       "family-shared emails are known false-merge "
                       "classes; matching is evidence, not proof"}


def t_merge_propose(state, args):
    check_kill(POLICY, "internal_write")
    a = get_record(state, args.get("record_a"))
    b = get_record(state, args.get("record_b"))
    if a["kind"] != b["kind"]:
        raise ToolError("merge candidates must be the same kind")
    if a["record_id"] == b["record_id"]:
        raise ToolError("cannot merge a record with itself")
    evidence = merge_evidence(a, b)
    proposal_id = str(args.get("proposal_id") or
                      f"prop-{sha(a['record_id'] + b['record_id'])[:10]}")
    proposal = {"proposal_id": proposal_id,
                "kind": a["kind"],
                "record_a": a["record_id"], "record_b": b["record_id"],
                "evidence": evidence, "status": "proposed",
                "proposed_at": now_iso()}
    proposal["proposal_hash"] = sha(canon(
        {k: proposal[k] for k in ("proposal_id", "kind", "record_a",
                                  "record_b", "evidence")}))
    state["proposals"][proposal_id] = proposal
    receipt = emit_receipt(state, "merge_proposed", {
        "proposal_id": proposal_id,
        "proposal_hash": proposal["proposal_hash"],
        "record_ids": [a["record_id"], b["record_id"]],
        "tier": 1, "verdict": "PROPOSED"})
    return {"proposal": proposal, "receipt_seq": receipt["seq"]}


def expected_merge_token(proposal):
    return f"confirm-merge-{proposal['proposal_id']}-" \
           f"{proposal['proposal_hash'][:12]}"


def t_merge_execute(state, args):
    check_kill(POLICY, "graph_merge_execute")
    proposal = state["proposals"].get(str(args.get("proposal_id")))
    if not proposal:
        raise ToolError(f"unknown proposal: {args.get('proposal_id')}")
    if proposal["status"] != "proposed":
        raise ToolError(
            f"proposal is {proposal['status']}, not proposed")
    if str(args.get("confirm_token") or "") != \
            expected_merge_token(proposal):
        emit_receipt(state, "merge_execute_denied", {
            "proposal_id": proposal["proposal_id"], "tier": 2,
            "reason": "CONFIRM_TOKEN_INVALID", "verdict": "DENY"})
        raise ToolError(
            "CONFIRM_TOKEN_INVALID: a graph merge executes only on "
            "an owner-confirm token bound to the proposal hash "
            "(spec 5.2)")
    a = get_record(state, proposal["record_a"])
    b = get_record(state, proposal["record_b"])
    # Snapshot pre-merge nodes: the unmerge restores from THIS record.
    snapshot = {"record_a": json.loads(json.dumps(a)),
                "record_b": json.loads(json.dumps(b))}
    merged_id = f"{proposal['kind']}-merged-" \
                f"{proposal['proposal_hash'][:8]}"
    merged_fields = {}
    for source in (a, b):
        for field, fv in source["fields"].items():
            if field not in merged_fields:
                merged_fields[field] = fv
            # per-platform values are never destroyed: a conflicting
            # second value is retained under a platform-suffixed key.
            elif canon(merged_fields[field]["value"]) != canon(fv["value"]):
                plat = fv["provenance"]["platform"]
                merged_fields[f"{field}@{plat}"] = fv
    merged = {
        "record_id": merged_id, "kind": proposal["kind"],
        "external_ids": {**a["external_ids"], **b["external_ids"]},
        "fields": merged_fields,
        "data_rights": a["data_rights"],
        "ingested_at": now_iso(), "status": "active",
        "merged_from": [a["record_id"], b["record_id"]],
    }
    state["records"][merged_id] = merged
    a["status"] = "merged_into"
    b["status"] = "merged_into"
    proposal["status"] = "executed"
    merge_record = {"merge_id": f"merge-{proposal['proposal_hash'][:10]}",
                    "proposal_id": proposal["proposal_id"],
                    "merged_record_id": merged_id,
                    "snapshot": snapshot, "status": "active"}
    state["merges"][merge_record["merge_id"]] = merge_record
    receipt = emit_receipt(state, "merge_executed", {
        "merge_id": merge_record["merge_id"],
        "proposal_id": proposal["proposal_id"],
        "proposal_hash": proposal["proposal_hash"],
        "merged_record_id": merged_id,
        "source_record_ids": [a["record_id"], b["record_id"]],
        "snapshot_hash": sha(canon(snapshot)),
        "tier": 2, "verdict": "ALLOW"})
    return {"merge_id": merge_record["merge_id"],
            "merged_record_id": merged_id,
            "receipt_seq": receipt["seq"]}


def t_merge_unmerge(state, args):
    check_kill(POLICY, "graph_merge_execute")
    merge = state["merges"].get(str(args.get("merge_id")))
    if not merge:
        raise ToolError(f"unknown merge: {args.get('merge_id')}")
    if merge["status"] != "active":
        raise ToolError(f"merge is {merge['status']}, not active")
    expected = f"confirm-unmerge-{merge['merge_id']}"
    if str(args.get("confirm_token") or "") != expected:
        emit_receipt(state, "merge_unmerge_denied", {
            "merge_id": merge["merge_id"], "tier": 2,
            "reason": "CONFIRM_TOKEN_INVALID", "verdict": "DENY"})
        raise ToolError(
            "CONFIRM_TOKEN_INVALID: unmerge requires its confirm "
            "token (spec 5.2)")
    snap = merge["snapshot"]
    for key in ("record_a", "record_b"):
        restored = json.loads(json.dumps(snap[key]))
        restored["status"] = "active"
        state["records"][restored["record_id"]] = restored
    merged = state["records"].get(merge["merged_record_id"])
    if merged:
        merged["status"] = "split"
        state["records"].pop(merge["merged_record_id"], None)
    merge["status"] = "unmerged"
    receipt = emit_receipt(state, "merge_unmerged", {
        "merge_id": merge["merge_id"],
        "restored_record_ids": [snap["record_a"]["record_id"],
                                snap["record_b"]["record_id"]],
        "snapshot_hash": sha(canon(snap)),
        "tier": 2, "verdict": "ALLOW"})
    return {"restored_record_ids": [snap["record_a"]["record_id"],
                                     snap["record_b"]["record_id"]],
            "receipt_seq": receipt["seq"]}


# --------------------------------------------------------- drafting service
def t_reply_draft(state, args):
    """Draft a reply ONLY from record facts (spec 6.4). The ticket is
    the fact source; linked Person/Company give the greeting + org.
    Customer-authored text is never a fact source (Law #1) — its
    quarantined items are reported, never quoted or obeyed."""
    check_kill(POLICY, "draft_create")
    ticket = get_record(state, args.get("ticket_id"))
    if ticket["kind"] != "ticket":
        raise ToolError("reply_draft requires a ticket record")
    citations = []
    quarantined_seen = []

    def fact(record, field):
        fv = record["fields"].get(field)
        if fv is None:
            return None
        citations.append({"record_id": record["record_id"],
                          "field": field})
        return fv["value"]

    subject = fact(ticket, "subject")
    status = fact(ticket, "status")
    requester_name = None
    requester_id = (ticket.get("external_ids") or {}).get("requester")
    person = None
    for rec in state["records"].values():
        if rec["kind"] == "person" and rec.get("status") == "active" \
                and (rec["record_id"] == args.get("person_id")
                     or requester_id in (rec.get("external_ids")
                                          or {}).values()):
            person = rec
            break
    if person:
        requester_name = fact(person, "name")
    # Scan the linked conversation for quarantined customer content:
    # reported to the reviewer, excluded from facts.
    for rec in state["records"].values():
        if rec["kind"] != "conversation":
            continue
        msgs = (rec["fields"].get("messages") or {}).get("value") or []
        for msg in msgs:
            if msg.get("quarantined"):
                quarantined_seen.append(msg.get("message_id"))
    resolution = fact(ticket, "resolution")
    lines = []
    if requester_name:
        lines.append(f"Hello {str(requester_name).split()[0]},")
    else:
        lines.append("Hello,")
    if subject:
        lines.append(
            f"Thank you for contacting us about: {subject}.")
    if status:
        lines.append(f"Your ticket is currently recorded as: {status}.")
    missing = []
    if resolution:
        lines.append(f"Recorded resolution: {resolution}")
    else:
        missing.append("resolution")
        lines.append(
            "[MISSING_FACT: resolution — no resolution is recorded "
            "on this ticket; no outcome is asserted]")
    lines.append("We will follow up from this record.")
    body = "\n".join(lines)
    draft_id = str(args.get("draft_id") or
                   f"draft-{sha(body)[:10]}")
    draft = {"draft_id": draft_id, "ticket_id": ticket["record_id"],
             "body": body, "citations": citations,
             "missing_facts": missing,
             "quarantined_message_ids": quarantined_seen,
             "content_hash": sha(body), "created_at": now_iso(),
             "status": "draft"}
    state["drafts"][draft_id] = draft
    receipt = emit_receipt(state, "draft_created", {
        "draft_id": draft_id, "ticket_id": ticket["record_id"],
        "content_hash": draft["content_hash"],
        "citation_count": len(citations),
        "missing_facts": missing,
        "quarantined_message_ids": quarantined_seen,
        "tier": 1, "verdict": "ALLOW"})
    return {"draft": draft, "receipt_seq": receipt["seq"]}


# -------------------------------------------------------------------- misc
def t_policy_show(state, args):
    return {"tier_floors": TIER_FLOORS,
            "effective_tiers": {k: effective_tier(POLICY, k)
                                for k in TIER_FLOORS},
            "kill_reads": bool(POLICY.get("kill_reads")),
            "kill_writes": bool(POLICY.get("kill_writes")),
            "masking": {"email": "owner: full; analytic: domain-only",
                        "phone": "partial (last 2)",
                        "gov_id/payment/health fields": "null (v1)"}}


def t_receipt_list(state, args):
    limit = args.get("limit")
    receipts = state["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(state["receipts"]),
            "chain_valid": verify_receipt_chain(state["receipts"])}


TOOLS = {
    "record_ingest": (
        t_record_ingest,
        "Ingest a canonical Customer Graph record (person / company / "
        "deal / ticket / conversation / activity). Every field must "
        "carry provenance; a Data Rights Ledger block is required. "
        "Customer-authored conversation text is tagged untrusted and "
        "instruction-shaped content is quarantined at ingest.",
        {"kind": {"type": "string"}, "record_id": {"type": "string"},
         "external_ids": {"type": "object"},
         "fields": {"type": "object"},
         "field_provenance": {"type": "object"},
         "data_rights": {"type": "object"}}, ["kind", "fields"]),
    "record_read": (
        t_record_read,
        "Read one graph record with egress masking applied (surface: "
        "owner = full email, analytic = domain-only email; phone "
        "always partial; gov/payment/health fields null). Receipted.",
        {"record_id": {"type": "string"},
         "surface": {"type": "string"}}, ["record_id"]),
    "record_search": (
        t_record_search,
        "Search graph records by kind + substring; returns masked "
        "summaries. The query itself is receipted by hash only.",
        {"kind": {"type": "string"}, "query": {"type": "string"},
         "surface": {"type": "string"}}, []),
    "merge_propose": (
        t_merge_propose,
        "PROPOSE an identity merge between two same-kind records. "
        "Returns evidence (matching keys by hash, conflicts) + a "
        "proposal hash. Executes nothing (Beacon propose-only "
        "doctrine).",
        {"record_a": {"type": "string"}, "record_b": {"type": "string"},
         "proposal_id": {"type": "string"}},
        ["record_a", "record_b"]),
    "merge_execute": (
        t_merge_execute,
        "Execute a proposed graph merge. Requires the owner-confirm "
        "token bound to the proposal hash "
        "(confirm-merge-<proposal_id>-<hash12>). Graph nodes only — "
        "never merges records inside a platform. The pre-merge "
        "snapshot is stored on the merge record for unmerge.",
        {"proposal_id": {"type": "string"},
         "confirm_token": {"type": "string"}},
        ["proposal_id", "confirm_token"]),
    "merge_unmerge": (
        t_merge_unmerge,
        "Undo a confirmed merge from its receipt snapshot, restoring "
        "the pre-merge nodes exactly. Requires "
        "confirm-unmerge-<merge_id>.",
        {"merge_id": {"type": "string"},
         "confirm_token": {"type": "string"}},
        ["merge_id", "confirm_token"]),
    "reply_draft": (
        t_reply_draft,
        "Draft a ticket reply ONLY from record facts, with a "
        "citation list. Untraceable facts become MISSING_FACT "
        "markers. Customer text is never a fact source; quarantined "
        "(instruction-shaped) messages are reported, never obeyed.",
        {"ticket_id": {"type": "string"},
         "person_id": {"type": "string"},
         "draft_id": {"type": "string"}}, ["ticket_id"]),
    "policy_show": (
        t_policy_show,
        "Show the tier floors, effective tiers, kill switches, and "
        "masking rules in force.",
        {}, []),
    "receipt_list": (
        t_receipt_list,
        "List the append-only, hash-chained receipts and verify the "
        "chain. Receipts carry IDs + hashes only — never content.",
        {"limit": {"type": "integer"}}, []),
}

# Capability denylist, stated in code: the core sends nothing,
# deletes nothing, and never merges records inside a platform.
FORBIDDEN_TOOL_NAMES = {
    "record_delete", "platform_merge", "reply_send", "email_send",
    "bulk_update", "macro_edit", "trigger_edit", "session_login",
    "cookie_reuse", "scrape_records",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-muster", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"unknown or C0-forbidden tool {name}"}}
        state = load_state()
        try:
            out = TOOLS[name][0](state, args)
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            # Denials are receipts too (spec 7.4): persist the state
            # so the DENY entry survives. Denied tools raise before
            # any platform/graph mutation by construction.
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    global POLICY
    try:
        POLICY = load_policy()
    except ToolError as exc:
        sys.stderr.write(f"eclipse-muster: policy rejected: {exc}\n")
        sys.exit(2)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
