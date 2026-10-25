#!/usr/bin/env python3
"""Eclipse Muster v0.1 (C0) tests.
Run: python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server as S  # noqa: E402

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "records.json")
    .read_text())["records"]


def fresh_state():
    return S.empty_state()


def ingest_all(state):
    for rec in FIXTURES:
        S.t_record_ingest(state, rec)
    return state


class TestIngest(unittest.TestCase):
    def test_ingest_and_provenance_required(self):
        state = ingest_all(fresh_state())
        self.assertEqual(len(state["records"]), 5)
        bad = {"kind": "person", "record_id": "x",
               "fields": {"name": "No Prov"},
               "field_provenance": {},
               "data_rights": {"source_account": "a",
                               "legal_basis": "b"}}
        with self.assertRaises(S.ToolError) as ctx:
            S.t_record_ingest(state, bad)
        self.assertIn("PROVENANCE_MISSING", str(ctx.exception))

    def test_data_rights_required(self):
        state = fresh_state()
        bad = {"kind": "person", "fields": {"name": "X"},
               "field_provenance": {"name": {
                   "platform": "hubspot", "platform_object_id": "1",
                   "source": "import", "observed_at": "2026-10-24T00:00:00Z"}}}
        with self.assertRaises(S.ToolError) as ctx:
            S.t_record_ingest(state, bad)
        self.assertIn("DATA_RIGHTS_MISSING", str(ctx.exception))


class TestMasking(unittest.TestCase):
    def test_egress_masking(self):
        state = ingest_all(fresh_state())
        owner = S.t_record_read(
            state, {"record_id": "person-hubspot-1001",
                    "surface": "owner"})
        analytic = S.t_record_read(
            state, {"record_id": "person-hubspot-1001",
                    "surface": "analytic"})
        self.assertEqual(owner["fields"]["emails"],
                         ["maya.chen@acme.example"])
        self.assertEqual(analytic["fields"]["emails"],
                         ["***@acme.example"])
        # phone partial on BOTH surfaces; gov-id field nulled on both.
        self.assertTrue(str(owner["fields"]["phone"]).endswith("34"))
        self.assertNotIn("415", str(owner["fields"]["phone"]))
        self.assertIsNone(owner["fields"]["ssn_last4_note"])
        self.assertIsNone(analytic["fields"]["ssn_last4_note"])

    def test_receipts_carry_no_content(self):
        """Spec 5.5: receipts carry hashes/IDs, NEVER content — scan
        the whole ledger for ticket-body and email strings."""
        state = ingest_all(fresh_state())
        S.t_record_read(state, {"record_id": "ticket-zd-9001"})
        S.t_reply_draft(state, {"ticket_id": "ticket-zd-9001"})
        ledger = json.dumps(state["receipts"])
        self.assertNotIn("Invoice export fails", ledger)
        self.assertNotIn("maya.chen@acme.example", ledger)
        self.assertNotIn("refund my card", ledger.lower())
        self.assertNotIn("415-555-0134", ledger)


class TestMerge(unittest.TestCase):
    def test_propose_only_until_confirmed(self):
        state = ingest_all(fresh_state())
        out = S.t_merge_propose(state, {
            "record_a": "person-hubspot-1001",
            "record_b": "person-zendesk-2002"})
        proposal = out["proposal"]
        # Proposing changed NOTHING in the graph.
        self.assertEqual(
            state["records"]["person-hubspot-1001"]["status"], "active")
        self.assertEqual(proposal["evidence"]["confidence"], 0.9)
        self.assertTrue(proposal["evidence"]["matched_keys"])
        # Wrong token = DENY + receipt, still nothing merged.
        with self.assertRaises(S.ToolError):
            S.t_merge_execute(state, {
                "proposal_id": proposal["proposal_id"],
                "confirm_token": "confirm-merge-wrong"})
        self.assertEqual(
            state["records"]["person-hubspot-1001"]["status"], "active")
        self.assertEqual(state["receipts"][-1]["type"],
                         "merge_execute_denied")
        # Correct token (bound to proposal hash) executes.
        token = S.expected_merge_token(proposal)
        res = S.t_merge_execute(state, {
            "proposal_id": proposal["proposal_id"],
            "confirm_token": token})
        merged = state["records"][res["merged_record_id"]]
        # Per-platform values retained; name conflict kept both ways.
        self.assertIn("name", merged["fields"])
        self.assertIn("name@zendesk", merged["fields"])
        self.assertEqual(
            state["records"]["person-hubspot-1001"]["status"],
            "merged_into")
        return state, res

    def test_unmerge_restores_prior_state(self):
        state, res = self.test_propose_only_until_confirmed()
        merge_id = res["merge_id"]
        before_a = json.dumps(
            state["merges"][merge_id]["snapshot"]["record_a"],
            sort_keys=True)
        out = S.t_merge_unmerge(state, {
            "merge_id": merge_id,
            "confirm_token": f"confirm-unmerge-{merge_id}"})
        self.assertEqual(sorted(out["restored_record_ids"]),
                         ["person-hubspot-1001", "person-zendesk-2002"])
        restored = state["records"]["person-hubspot-1001"]
        self.assertEqual(restored["status"], "active")
        self.assertEqual(
            json.dumps({k: v for k, v in restored.items()
                        if k != "status"}, sort_keys=True),
            json.dumps({k: v for k, v in
                        json.loads(before_a).items() if k != "status"},
                       sort_keys=True))
        self.assertNotIn(res["merged_record_id"], state["records"])


class TestDrafting(unittest.TestCase):
    def test_draft_only_from_record_facts(self):
        """The fixture ticket has NO resolution field: the draft must
        carry a MISSING_FACT marker and zero resolution claims."""
        state = ingest_all(fresh_state())
        out = S.t_reply_draft(state, {"ticket_id": "ticket-zd-9001"})
        draft = out["draft"]
        self.assertIn("MISSING_FACT", draft["body"])
        self.assertIn("resolution", draft["missing_facts"])
        self.assertIn("Invoice export fails with error 41",
                      draft["body"])
        self.assertTrue(draft["citations"])
        low = draft["body"].lower()
        self.assertNotIn("resolved", low.replace("resolution", ""))
        self.assertNotIn("fixed", low)
        self.assertNotIn("refund", low)

    def test_injection_quarantined_never_obeyed(self):
        """Herald Law #1: the instruction-shaped customer message is
        ingested as DATA — flagged quarantined, excluded from the
        draft's facts, and no action follows from it."""
        state = ingest_all(fresh_state())
        conv = state["records"]["conv-zd-9001"]
        msgs = {m["message_id"]: m
                for m in conv["fields"]["messages"]["value"]}
        self.assertTrue(msgs["m2"]["quarantined"])
        self.assertEqual(msgs["m2"]["trust"], "untrusted_data")
        self.assertFalse(msgs["m1"]["quarantined"])
        out = S.t_reply_draft(state, {"ticket_id": "ticket-zd-9001"})
        self.assertIn("m2", out["draft"]["quarantined_message_ids"])
        self.assertNotIn("billing@outside.example",
                         out["draft"]["body"])
        # No state anywhere records a refund/forward action.
        blob = json.dumps(state["records"]) + \
            json.dumps(state["drafts"])
        self.assertNotIn("refund_issued", blob)
        self.assertNotIn("forwarded", blob)


class TestPolicy(unittest.TestCase):
    def test_tier_floor_lowering_rejected_at_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "policy.json"
            bad.write_text(json.dumps(
                {"tier_overrides": {"customer_visible_send": 1}}))
            old = S.POLICY_PATH
            S.POLICY_PATH = bad
            try:
                with self.assertRaises(S.ToolError) as ctx:
                    S.load_policy()
                self.assertIn("TIER_FLOOR_VIOLATION", str(ctx.exception))
            finally:
                S.POLICY_PATH = old

    def test_tier_raise_allowed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / "policy.json"
            ok.write_text(json.dumps(
                {"tier_overrides": {"customer_visible_send": 3}}))
            old = S.POLICY_PATH
            S.POLICY_PATH = ok
            try:
                policy = S.load_policy()
                self.assertEqual(
                    S.effective_tier(policy, "customer_visible_send"), 3)
            finally:
                S.POLICY_PATH = old


class TestChain(unittest.TestCase):
    def test_chain_valid_and_tamper_detected(self):
        state = ingest_all(fresh_state())
        S.t_record_search(state, {"kind": "person", "query": "maya"})
        out = S.t_receipt_list(state, {})
        self.assertTrue(out["chain_valid"])
        state["receipts"][1]["detail"]["verdict"] = "FORGED"
        self.assertFalse(S.verify_receipt_chain(state["receipts"]))

    def test_denylist_surface(self):
        names = {t["name"] for t in S.tool_list()}
        self.assertEqual(len(names), 9)
        for forbidden in S.FORBIDDEN_TOOL_NAMES:
            self.assertNotIn(forbidden, names)


if __name__ == "__main__":
    unittest.main()
