# eclipse-muster

mcp-name: io.github.CYAN-ECLIPSE-TECHNOLOGIES-LLC/muster

**What this is:** the MCP server for **Eclipse Muster** — the shared
core of Cyan Eclipse Technologies' Eclipse customer adapter family.
One canonical Customer Graph becomes governed reads, internal writes,
and owner-approved drafts across the popular CRM and customer-service
platforms, according to what each platform actually sanctions.

**What this is not:** phase C0 is a local core over owner-fed records
with synthetic fixtures. **No platform is contacted, no credential
exists in this build, and no message is sent from here** — sends are
adapter tools gated by owner approval tokens, elsewhere.

## Run it

```console
$ pip install eclipse-muster
$ eclipse-muster             # MCP over stdio, Python stdlib only
```

MCP client config:

```json
{ "mcpServers": { "eclipse-muster": { "command": "uvx", "args": ["eclipse-muster"] } } }
```

## Tools (9)

`record_ingest` · `record_read` · `record_search` · `merge_propose` ·
`merge_execute` · `merge_unmerge` · `reply_draft` · `policy_show` ·
`receipt_list`

## Honest scope

- Every field on every record carries provenance and every record a
  Data Rights Ledger block; a field without provenance does not enter
  the graph. Identity merges are **propose-only** — a merge executes
  only on an owner-confirm token bound to the proposal hash, and can
  be unmerged exactly from its receipt.
- Field-level masking is enforced at egress; reply drafts are
  generated only from record facts with citations — untraceable facts
  surface as `MISSING_FACT` markers. Instruction-shaped customer text
  is quarantined at ingest (Herald Security Law #1): data, never
  commands. Receipts carry IDs, hashes, tiers, and verdicts — never
  content.
- Policy floors live in `policy.json`, shipped beside the server in
  the wheel (override with `ECLIPSE_MUSTER_POLICY`); state persists in
  `data/state.json` (override with `ECLIPSE_MUSTER_STATE`).
- Certified (local) by the Eclipse Test Bench at v0.1.0; the listing
  status in the Eclipse Bazaar catalog is in-development.

Powered by Cyan Eclipse Technologies LLC (cetech.ai) — a Veteran-Owned
Small Business. MIT licensed.
