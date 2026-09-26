import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import DomainError, PrivacyRequestService  # noqa: E402


class WithdrawalFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = PrivacyRequestService(Path(self.tmp.name) / "test.db")
        self.service.configure_jurisdiction("sup1", "supervisor", "CN", "中国", 30, 30, True, True)
        self.subject = self.service.create_subject("intake1", "intake", "SUB-001", "CN", False, "person@example.test")

    def tearDown(self):
        self.tmp.cleanup()

    def make_request(self, number, kind="access", key=None):
        return self.service.create_request(
            "intake1", "intake", number, self.subject["id"], kind,
            key or "IDEM-" + number,
        )["request"]

    def prepare_request(self, number):
        request = self.make_request(number)
        request = self.service.verify_identity("officer1", "privacy_officer", request["id"], request["version"], "ID-001")
        request = self.service.assign_request("sup1", "supervisor", request["id"], "officer1", request["version"])
        location = self.service.add_data_location("officer1", "privacy_officer", request["id"], "CRM", "profile", "customer")
        self.service.classify_location("officer1", "privacy_officer", location["id"], False, False, False)
        request = self.service.prepare_response("officer1", "privacy_officer", request["id"], request["version"])
        return request

    def test_received_request_withdrawn_directly_and_preserved(self):
        request = self.make_request("PR-W1")
        result = self.service.withdraw_request("intake1", "intake", request["id"], "申请人不再需要查阅", request["version"])
        self.assertEqual("withdrawn", result["status"])
        self.assertIsNone(result["reviewed_by"])
        self.assertTrue(result["reappliable"])
        self.assertEqual("申请人撤回：申请人不再需要查阅", result["closure_reason"])
        self.assertEqual("intake1", result["withdrawn_by"])
        # 原请求编号、创建人仍然保留
        self.assertEqual("PR-W1", result["request_no"])
        self.assertEqual("intake1", result["created_by"])
        detail = self.service.get_request("sup1", "supervisor", request["id"])
        self.assertEqual("withdrawn", detail["request"]["status"])
        actions = {t["action"] for t in detail["timeline"]}
        self.assertIn("request.withdrawn", actions)

    def test_response_ready_requires_supervisor_review(self):
        request = self.prepare_request("PR-W2")
        pending = self.service.withdraw_request("officer1", "privacy_officer", request["id"], "代理说明已自行解决", request["version"], "authorized_agent")
        self.assertEqual("withdrawal_pending", pending["status"])
        self.assertFalse(pending["reappliable"])
        with self.assertRaises(DomainError) as ctx:
            self.service.review_withdrawal("officer1", "privacy_officer", request["id"], True, pending["version"])
        self.assertEqual(403, ctx.exception.status)
        closed = self.service.review_withdrawal("sup1", "supervisor", request["id"], True, pending["version"], "情况属实")
        self.assertEqual("withdrawn", closed["status"])
        self.assertEqual("sup1", closed["reviewed_by"])
        self.assertTrue(closed["reappliable"])
        self.assertIn("自行解决", closed["closure_reason"])
        # 已登记的数据位置仍然保留
        detail = self.service.get_request("sup1", "supervisor", request["id"])
        self.assertEqual(1, len(detail["locations"]))
        self.assertEqual("officer1", detail["request"]["assigned_to"])

    def test_extended_withdrawal_approved_and_rejected_paths(self):
        request = self.prepare_request_extended("PR-W3")
        pending = self.service.withdraw_request("sup1", "supervisor", request["id"], "申请人计划重新整理材料", request["version"])
        self.assertEqual("withdrawal_pending", pending["status"])
        restored = self.service.review_withdrawal("sup1", "supervisor", request["id"], False, pending["version"], "材料缺失，撤回无效")
        self.assertEqual("extended", restored["status"])
        self.assertFalse(restored["reappliable"])
        pending = self.service.withdraw_request("sup1", "supervisor", request["id"], "申请人确认撤回", restored["version"])
        closed = self.service.review_withdrawal("sup1", "supervisor", request["id"], True, pending["version"])
        self.assertEqual("withdrawn", closed["status"])
        self.assertEqual("sup1", closed["reviewed_by"])

    def prepare_request_extended(self, number):
        request = self.make_request(number)
        request = self.service.verify_identity("officer1", "privacy_officer", request["id"], request["version"], "ID-002")
        request = self.service.assign_request("sup1", "supervisor", request["id"], "officer1", request["version"])
        return self.service.extend_request("sup1", "supervisor", request["id"], 10, "等待跨系统取证", request["version"])

    def test_withdraw_requires_reason_and_permission(self):
        request = self.make_request("PR-W4")
        with self.assertRaises(DomainError) as ctx:
            self.service.withdraw_request("intake1", "intake", request["id"], "  ", request["version"])
        self.assertEqual(400, ctx.exception.status)
        other = self.service.create_subject("intake2", "intake", "SUB-002", "CN", False, "other@example.test")
        other_req = self.service.create_request("intake2", "intake", "PR-OTHER", other["id"], "access", "IDEM-OTHER")["request"]
        with self.assertRaises(DomainError) as ctx2:
            self.service.withdraw_request("intake1", "intake", other_req["id"], "无权撤回", other_req["version"])
        self.assertEqual(403, ctx2.exception.status)

    def test_cannot_withdraw_final_or_pending_twice(self):
        request = self.make_request("PR-W5")
        closed = self.service.withdraw_request("intake1", "intake", request["id"], "申请人放弃", request["version"])
        with self.assertRaises(DomainError) as ctx:
            self.service.withdraw_request("intake1", "intake", request["id"], "再次撤回", closed["version"])
        self.assertEqual(409, ctx.exception.status)
        with self.assertRaises(DomainError) as ctx2:
            self.service.review_withdrawal("sup1", "supervisor", request["id"], True, closed["version"])
        self.assertEqual(409, ctx2.exception.status)

    def test_rejected_withdrawal_requires_note(self):
        request = self.prepare_request("PR-W6")
        pending = self.service.withdraw_request("officer1", "privacy_officer", request["id"], "代理要求撤回", request["version"])
        with self.assertRaises(DomainError) as ctx:
            self.service.review_withdrawal("sup1", "supervisor", request["id"], False, pending["version"], "")
        self.assertEqual(400, ctx.exception.status)

    def test_withdrawn_request_not_counted_as_duplicate(self):
        first = self.make_request("PR-W7")
        closed = self.service.withdraw_request("intake1", "intake", first["id"], "申请人暂不申请", first["version"])
        self.assertEqual("withdrawn", closed["status"])
        again = self.service.create_request("intake1", "intake", "PR-W8", self.subject["id"], "access", "IDEM-PR-W8")
        self.assertEqual("received", again["request"]["status"])
        self.assertIsNone(again["request"]["duplicate_of"])

    def test_version_conflict_guards_withdrawal(self):
        request = self.make_request("PR-W9")
        with self.assertRaises(DomainError) as ctx:
            self.service.withdraw_request("intake1", "intake", request["id"], "申请人放弃", request["version"] + 1)
        self.assertEqual(409, ctx.exception.status)


if __name__ == "__main__":
    unittest.main()
