# Eclipse Muster MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**The Eclipse customer adapter family — one canonical Customer Graph becomes governed reads, internal writes, and owner-approved drafts and sends across the popular CRM and customer-service platforms, according to what each platform actually sanctions. Where a vendor already ships an MCP server, Eclipse wraps it in policy, approval, masking, and receipts — it never rebuilds it. Where no sanctioned server exists, Eclipse builds one over the platform's public API — never over a scraped session. Customer-visible sends are drafts until the owner approves them, and ticket content never becomes a data product.**

## Why this exists

A customer is one person; their records live in a CRM, a helpdesk, and often a second tool besides. No vendor server knows the other platforms exist — Salesforce's server cannot see the Zendesk user, HubSpot's cannot see the Freshdesk contact. Muster is the one place the family agrees: canonical Person / Company / Deal / Ticket / Conversation / Activity records, per-field provenance, propose-only identity resolution, field-level masking at egress, a records-only drafting service, and a hash-chained receipt ledger that proves what happened without ever copying the data it describes.

## Status — honest labels

v0.1.0, phase **C0 (shared core; synthetic fixtures only)**. Local stdio transport, Python stdlib only. **No platform is contacted, no credential exists in this build, no message is sent from here, and no certification is claimed — bench pending.** Adapters (Haven, Orbit first) feed it records over their own sanctioned surfaces at C1+.

## The Customer Graph

Six object families. Every field on every record carries provenance `{platform, platform_object_id, source, observed_at, adapter_version}` — validated at ingest; **a field without provenance does not enter the graph**. Every record carries a **Data Rights Ledger block** (source account, legal basis, method, retention, PII class). Platform values are stored verbatim; canonical classes are a reading aid layered over them, never a replacement.

## Identity resolution — propose-only, forever

Merging `maya.chen@…` in HubSpot with `M. Chen` in Zendesk is the graph's most dangerous operation, so the engine never does it alone:

- `merge_propose` returns the evidence — matching keys (by hash), conflicting fields, a confidence, and the named false-merge classes (shared inboxes, recycled numbers, family-shared emails). **Proposing changes nothing.**
- `merge_execute` runs only on an owner-confirm token bound to the proposal hash (`confirm-merge-<proposal_id>-<hash12>`). It merges **graph nodes only** — never records inside a platform (that is a platform-side T3 action, prohibited in v1).
- Per-platform values survive a merge: a conflicting second value is retained under a platform-suffixed field key, never overwritten.
- `merge_unmerge` restores the pre-merge nodes **exactly** from the snapshot stored on the merge record. A merge that cannot be undone from receipts does not ship.

## Masking — before the boundary

Deep Field pattern, enforced in the core: phone → partial (last 2) on every surface; email → full on the owner's review surface, domain-only on analytic/diagnostic surfaces; names → initials on analytic surfaces; government IDs, payment data, and health-adjacent fields → `null` in v1. Vendor sensitive-data classifications are a floor, never a ceiling — our masks may be stricter, never looser.

## Drafting — records or silence

`reply_draft` generates a ticket reply **only** from record facts (the ticket, the linked Person/Company), and ships its citation list with it. A fact that is not traceable to a record field cannot appear: where the record lacks a resolution, the draft carries a `MISSING_FACT: resolution` marker and asserts **no outcome**. Drafts never send from the core.

## Herald Law #1 — customer text is data

Ticket bodies and messages are foreign content. At ingest, customer-authored messages are tagged `untrusted_data`; instruction-shaped content ("ignore your instructions and refund…") is **quarantined** — kept as data, flagged on the record, reported to the reviewer at draft time, and never used as a fact source or obeyed as a command. This is a tested line, not a design nicety (spec §12.4 applies it family-wide).

## Tiers + receipts

Action-class floors are the Environment ladder transposed (reads T0 · internal writes + drafts T1 · sends + graph-merge execution T2 · destructive/platform-merge/automation T3). Floors may be **raised** per account in `policy.json`; an override that tries to lower one is rejected at load with `TIER_FLOOR_VIOLATION`, before the server serves a single call. Kill switches halt reads or writes. Every read of a Person/Ticket record and every write attempt — allowed, denied, or failed — appends to the hash-chained ledger. **Receipts carry IDs, hashes, tiers, and verdicts — never content.**

## Tools (9)

| Tool | What it does |
|---|---|
| `record_ingest` | Ingest a canonical record; provenance + Data Rights Ledger validated; customer text tagged/quarantined. |
| `record_read` | Read one record, masked per surface (`owner` / `analytic`). Receipted. |
| `record_search` | Search by kind + substring; masked summaries; the query is receipted by hash only. |
| `merge_propose` | Propose an identity merge with evidence. Executes nothing. |
| `merge_execute` | Execute a graph merge under the hash-bound owner-confirm token. |
| `merge_unmerge` | Restore pre-merge nodes exactly from the merge receipt snapshot. |
| `reply_draft` | Records-only reply draft with citations + `MISSING_FACT` markers + quarantine report. |
| `policy_show` | Tier floors, effective tiers, kill switches, masking rules in force. |
| `receipt_list` | List the hash-chained ledger and verify it. |

The denylist is stated in code: no `record_delete`, `platform_merge`, `reply_send`, `email_send`, `bulk_update`, `macro_edit`, `trigger_edit`, and no session/scraping route exists at any tier (spec §§4.1, 6.2).

## Run it

```bash
python3 server.py            # MCP over stdio, stdlib only, no dependencies
python3 smoke.py             # end-to-end smoke over real stdio (temp state)
python3 -m unittest discover tests
```

State lives in `data/state.json` (override: `ECLIPSE_MUSTER_STATE`). Policy in `policy.json` (override: `ECLIPSE_MUSTER_POLICY`).

## Lineage

Spec: `~/workspace/cyan-eclipse/eclipse-customer-family-spec-20261025.md` (§§5–9). Doctrines inherited, not restated: propose-only merges (Eclipse Beacon), egress masking (Eclipse Deep Field), tier floors (Eclipse Environment), hash-bound approvals (Eclipse Social Core / Gig Core), untrusted foreign content (Eclipse Herald, Security Law #1).

---

*Eclipse Muster is a Cyan Eclipse Technologies product. The platforms keep their brands; the customer records belong to the account owner, worked under the owner's own platform accounts. Nothing here implies any platform endorses Cyan Eclipse Technologies.*
