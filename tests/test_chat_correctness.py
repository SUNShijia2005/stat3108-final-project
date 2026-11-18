"""Regression cases for actual user interactions, including rejected side effects."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from parcel.assistant import chat, extract_fields, update
from parcel.domain import quote, ValidationError
from parcel.tracking import SAMPLE


def shipment():
    return {"origin_province": "Shanghai", "destination_country": "US", "destination_city": "Los Angeles",
            "destination_state": "CA", "destination_zip": "90001", "goods": "Cotton T-shirts",
            "weight_kg": 10, "length_cm": 30, "width_cm": 20, "height_cm": 10, "budget_cny": 5000}


def task():
    fields = shipment()
    return {"id": "conversation-test", "fields": fields, "quote": quote(fields),
            "checks": {"status": "checked", "issues": []}, "selected_service": {"service": "IE"},
            "tracking": {"data_type": "live_api", "tracking_number": "EXISTING123"}, "messages": []}


class ConversationCorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.task = task()
        self.original = deepcopy(self.task)
        self.no_model = patch("parcel.assistant.model.configured", return_value=False)
        self.no_model.start()

    def tearDown(self):
        self.no_model.stop()

    def assert_saved_state_unchanged(self):
        for key in ["fields", "quote", "checks", "selected_service", "tracking"]:
            self.assertEqual(self.task[key], self.original[key], key)

    def test_hypothetical_and_explicit_do_not_modify(self):
        result = chat(self.task, "如果改成8kg会便宜多少？先不要修改我的10kg需求。")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["intent"], "scenario")
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["scenario"]["quote"]["billable_kg"], 8)
        self.assertEqual({row["service"]: row["delta"] for row in result["scenario"]["differences"]},
                         {"IE": -712, "IP": -724, "IPE": -768})
        self.assertIn("试算", result["text"])

    def test_english_hypothetical(self):
        result = chat(self.task, "What if I change the weight to 8kg? Do not change the saved shipment.")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["scenario"]["quote"]["billable_kg"], 8)
        self.assertIn("Scenario", result["text"])

    def test_negative_change_is_not_executed(self):
        chat(self.task, "先不要把重量改成8kg")
        self.assert_saved_state_unchanged()

    def test_english_negative_change(self):
        chat(self.task, "Don't change the weight to 8kg")
        self.assert_saved_state_unchanged()

    def test_other_negative_phrasings_preserve_saved_fields(self):
        for message in ["别修改重量为8kg", "不需要更新成8kg", "我不想把重量改成8kg", "I want to compare 8kg without updating my shipment"]:
            with self.subTest(message=message):
                self.task = deepcopy(self.original)
                chat(self.task, message)
                self.assert_saved_state_unchanged()

    def test_question_with_weight_does_not_modify(self):
        chat(self.task, "8kg的体积重怎么算？")
        self.assert_saved_state_unchanged()

    def test_origin_comparison_does_not_overwrite_origin(self):
        chat(self.task, "北京和上海寄件有什么区别？")
        self.assert_saved_state_unchanged()

    def test_price_question_does_not_change_weight(self):
        result = chat(self.task, "8kg是多少钱？")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["scenario"]["quote"]["billable_kg"], 8)

    def test_budget_question_without_punctuation_does_not_update(self):
        result = chat(self.task, "预算4000可以吗")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["changes"], [])

    def test_affirmative_update_invalidates_selected_service(self):
        result = chat(self.task, "把重量改成8kg")
        self.assertEqual(self.task["fields"]["weight_kg"], 8)
        self.assertEqual(self.task["quote"]["billable_kg"], 8)
        self.assertIsNone(self.task["selected_service"])
        self.assertIsNone(self.task["checks"])
        self.assertEqual(result["changes"], [{"field": "weight_kg", "label": "实际重量", "before": 10, "after": 8.0}])

    def test_old_and_new_weight_use_new_value(self):
        chat(self.task, "将重量从10kg改成8kg")
        self.assertEqual(self.task["fields"]["weight_kg"], 8)

    def test_budget_old_and_new_use_new_value(self):
        chat(self.task, "把预算从5000改成4000")
        self.assertEqual(self.task["fields"]["budget_cny"], 4000)

    def test_bare_number_is_not_a_new_saved_weight(self):
        chat(self.task, "8kg")
        self.assert_saved_state_unchanged()

    def test_explicit_initial_request_is_recorded(self):
        self.task = {"fields": {}, "messages": [], "quote": None, "checks": None, "tracking": None}
        result = chat(self.task, "我想从上海寄衣物到洛杉矶，10公斤，预算5000元。")
        self.assertEqual(result["intent"], "update")
        self.assertEqual(self.task["fields"]["weight_kg"], 10)
        self.assertEqual(self.task["quote"]["status"], "needs_input")
        self.assertIn("destination_zip", self.task["quote"]["missing"])

    def test_missing_zip_followup_is_supported(self):
        self.task["fields"]["destination_zip"] = None
        self.task["quote"] = quote(self.task["fields"])
        self.task["messages"] = [{"role": "assistant", "text": "请补充美国邮编。"}]
        chat(self.task, "90001")
        self.assertEqual(self.task["fields"]["destination_zip"], "90001")
        self.assertEqual(self.task["quote"]["status"], "estimated")

    def test_missing_dimensions_followup_is_supported(self):
        for name in ["length_cm", "width_cm", "height_cm"]:
            self.task["fields"][name] = None
        self.task["quote"] = quote(self.task["fields"])
        self.task["messages"] = [{"role": "assistant", "text": "请补充长宽高，单位厘米。"}]
        chat(self.task, "30x20x10cm")
        self.assertEqual(self.task["fields"]["length_cm"], 30)
        self.assertEqual(self.task["quote"]["status"], "estimated")

    def test_city_change_clears_stale_zip(self):
        chat(self.task, "把目的地改到纽约")
        self.assertEqual(self.task["fields"]["destination_city"], "New York")
        self.assertEqual(self.task["fields"]["destination_state"], "NY")
        self.assertIsNone(self.task["fields"]["destination_zip"])
        self.assertEqual(self.task["quote"]["status"], "needs_input")

    def test_full_form_patch_with_old_zip_is_cleared(self):
        update(self.task, {**shipment(), "destination_city": "New York", "destination_state": "NY"})
        self.assertIsNone(self.task["fields"]["destination_zip"])
        self.assertIsNone(self.task["quote"])
        self.assertIsNone(self.task["selected_service"])

    def test_explicit_new_zip_is_preserved(self):
        chat(self.task, "把目的地改到纽约，邮编10001")
        self.assertEqual(self.task["fields"]["destination_zip"], "10001")
        self.assertEqual(self.task["quote"]["zone"], "2")

    def test_generic_tracking_never_queries_demo(self):
        with patch("parcel.assistant.track", side_effect=AssertionError("No tracking call expected")):
            result = chat(self.task, "我的物流到哪里了？")
        self.assertEqual(self.task["tracking"], self.original["tracking"])
        self.assertIn("填写运单号", result["text"])
        self.assertEqual(result["trace"], [])

    def test_logistics_cost_question_is_not_tracking(self):
        with patch("parcel.assistant.track", side_effect=AssertionError("No tracking call expected")):
            result = chat(self.task, "物流费用是多少？")
        self.assertNotEqual(result["intent"], "tracking")
        self.assertIn("estimate_rates", [row["tool"] for row in result["trace"]])

    def test_real_tracking_number_does_not_trigger_example(self):
        with patch("parcel.assistant.track", side_effect=AssertionError("No tracking call expected")):
            result = chat(self.task, "查一下运单号TEST987654的物流")
        self.assertEqual(self.task["tracking"], self.original["tracking"])
        self.assertNotIn("已送达", result["text"])

    def test_explicit_demo_request_reads_cached_sample(self):
        result = chat(self.task, "查询官方示例运单")
        self.assertEqual(self.task["tracking"]["tracking_number"], SAMPLE)
        self.assertEqual(self.task["tracking"]["data_type"], "official_synthetic_sample")
        self.assertIn("法国", result["text"])

    def test_negated_demo_request_is_not_executed(self):
        with patch("parcel.assistant.track", side_effect=AssertionError("No tracking call expected")):
            chat(self.task, "不要查询官方示例运单")
        self.assert_saved_state_unchanged()

    def test_unknown_unit_is_not_silently_centimeters(self):
        chat(self.task, "把尺寸改成12x10x8 inches")
        self.assert_saved_state_unchanged()

    def test_negated_document_check_preserves_results(self):
        for message in ["不要检查我的发票", "Please do not check my invoice", "如果检查我的发票会发现什么？", "如何检查发票？", "What fields does the invoice check examine?"]:
            with self.subTest(message=message):
                self.task = deepcopy(self.original)
                with patch("parcel.assistant.document_check", side_effect=AssertionError("No check requested")):
                    result = chat(self.task, message)
                self.assert_saved_state_unchanged()
                self.assertEqual(result["intent"], "consultation")

    def test_explicit_document_check_still_executes(self):
        for message in ["请检查我的发票", "核对单证", "Can you check my invoice?"]:
            with self.subTest(message=message):
                self.task = deepcopy(self.original)
                result = chat(self.task, message)
                self.assertEqual(result["intent"], "documents")
                self.assertIn("check_documents", [row["tool"] for row in result["trace"]])

    def test_please_do_not_modify_is_readonly(self):
        chat(self.task, "Please do not modify the shipment to 8kg")
        self.assert_saved_state_unchanged()

    def test_model_cannot_execute_negated_document_check(self):
        def unwanted_check(message, staged, execute):
            execute("check_documents", {})
            return "Checked."
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=unwanted_check), patch("parcel.assistant.document_check", side_effect=AssertionError("Must not run")):
            result = chat(self.task, "不要检查我的发票")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["mode"], "workflow")

    def test_hypothetical_demo_does_not_replace_tracking(self):
        with patch("parcel.assistant.track", side_effect=AssertionError("No example lookup requested")):
            chat(self.task, "如果查询官方模拟运单，会显示什么？")
        self.assert_saved_state_unchanged()

    def test_invalid_update_has_no_partial_side_effects(self):
        with self.assertRaises(ValidationError):
            chat(self.task, "把重量改成-1kg")
        self.assertEqual(self.task, self.original)

    def test_model_cannot_update_fields_for_a_question(self):
        def malicious_reply(message, staged, execute):
            execute("update_shipment", {"weight_kg": 8})
            return "Changed."
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=malicious_reply):
            result = chat(self.task, "8kg的体积重怎么算？")
        self.assert_saved_state_unchanged()
        self.assertEqual(result["mode"], "workflow")
        self.assertIsNotNone(result["model_error"])

    def test_failed_model_round_is_rolled_back_before_fallback(self):
        def broken_reply(message, staged, execute):
            staged["fields"]["origin_province"] = "Corrupted model staging"
            staged["selected_service"] = {"service": "invented"}
            execute("estimate_rates", {})
            raise RuntimeError("transport interrupted")
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=broken_reply):
            result = chat(self.task, "估算运费")
        self.assertEqual(self.task["fields"], self.original["fields"])
        self.assertEqual(self.task["selected_service"], self.original["selected_service"])
        self.assertEqual(self.task["quote"]["status"], "estimated")
        self.assertEqual([row["tool"] for row in result["trace"]], ["estimate_rates"])
        self.assertEqual(result["model_error"], "transport interrupted")

    def test_model_cannot_add_an_unrequested_update(self):
        def unrequested_reply(message, staged, execute):
            execute("update_shipment", {"budget_cny": 1})
            return "Changed."
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=unrequested_reply):
            result = chat(self.task, "把重量改成8kg")
        self.assertEqual(self.task["fields"]["weight_kg"], 8)
        self.assertEqual(self.task["fields"]["budget_cny"], 5000)
        self.assertEqual(result["mode"], "workflow")


if __name__ == "__main__":
    unittest.main()
