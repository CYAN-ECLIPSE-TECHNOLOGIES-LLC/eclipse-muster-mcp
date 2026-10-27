#!/usr/bin/env python3
# Eclipse Muster MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# End-to-end stdio smoke for Eclipse Muster v0.1 (C0).

"""End-to-end stdio smoke for Eclipse Muster v0.1 (C0).

Temp state. Drives initialize -> ingest fixtures -> masked read ->
merge_propose -> merge_execute (confirm token) -> merge_unmerge ->
reply_draft (injection fixture reported, no resolution invented) ->
receipt_list (chain valid, no content in ledger).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def rpc(proc, rid, method, params=None):
    req = {"jsonrpc": "2.0", "id": rid, "method": method,
           "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def call(proc, rid, name, args):
    response = rpc(proc, rid, "tools/call",
                   {"name": name, "arguments": args})
    return json.loads(response["result"]["content"][0]["text"])


def main():
    fixtures = json.loads(
        (HERE / "fixtures" / "records.json").read_text())["records"]
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["ECLIPSE_MUSTER_STATE"] = str(Path(tmp) / "state.json")
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            cwd=str(HERE), env=env)
        try:
            init = rpc(proc, 1, "initialize",
                       {"protocolVersion": "2025-03-26"})
            assert init["result"]["serverInfo"]["name"] == "eclipse-muster"
            print("initialize OK")
            rid = 10
            for rec in fixtures:
                rid += 1
                out = call(proc, rid, "record_ingest", rec)
                assert "record_id" in out, out
            print("ingest OK:", len(fixtures), "records")
            rid += 1
            read = call(proc, rid, "record_read", {
                "record_id": "person-hubspot-1001",
                "surface": "analytic"})
            assert read["fields"]["emails"] == ["***@acme.example"], read
            assert read["fields"]["ssn_last4_note"] is None
            print("masked read OK (analytic surface)")
            rid += 1
            prop = call(proc, rid, "merge_propose", {
                "record_a": "person-hubspot-1001",
                "record_b": "person-zendesk-2002"})["proposal"]
            print("merge_propose OK; confidence",
                  prop["evidence"]["confidence"])
            rid += 1
            token = f"confirm-merge-{prop['proposal_id']}-" \
                    f"{prop['proposal_hash'][:12]}"
            merged = call(proc, rid, "merge_execute", {
                "proposal_id": prop["proposal_id"],
                "confirm_token": token})
            print("merge_execute OK ->", merged["merged_record_id"])
            rid += 1
            un = call(proc, rid, "merge_unmerge", {
                "merge_id": merged["merge_id"],
                "confirm_token":
                    f"confirm-unmerge-{merged['merge_id']}"})
            assert len(un["restored_record_ids"]) == 2
            print("merge_unmerge OK; pre-merge nodes restored")
            rid += 1
            draft = call(proc, rid, "reply_draft",
                         {"ticket_id": "ticket-zd-9001"})["draft"]
            assert "MISSING_FACT" in draft["body"]
            assert "m2" in draft["quarantined_message_ids"]
            assert "refund" not in draft["body"].lower()
            print("reply_draft OK; injection m2 quarantined, "
                  "no resolution invented")
            rid += 1
            receipts = call(proc, rid, "receipt_list", {})
            assert receipts["chain_valid"], receipts
            blob = json.dumps(receipts)
            assert "maya.chen@acme.example" not in blob
            assert "Invoice export fails" not in blob
            print("receipt_list OK; chain valid;",
                  receipts["count"], "receipts, zero content")
            print("SMOKE PASS")
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()

# Eclipse Muster MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
