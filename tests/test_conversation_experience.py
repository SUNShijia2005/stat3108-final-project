"""Natural conversation routing without sacrificing actual shipment state."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from parcel.assistant import chat
from parcel.domain import quote


def saved_task():
    fields = {"origin_province":"Shanghai", "destination_country":"US", "destination_city":"Los Angeles",
              "destination_state":"CA", "destination_zip":"90001", "goods":"Cotton T-shirts",
              "weight_kg":10, "length_cm":30, "width_cm":20, "height_cm":10, "budget_cny":5000}
    return {"id":"natural-conversation", "fields":fields, "quote":quote(fields), "messages":[],
            "checks":{"status":"checked","issues":[]}, "selected_service":{"service":"IE"}, "tracking":None}


class ConversationExperienceTests(unittest.TestCase):
    def setUp(self):
        self.task = saved_task()
        self.before = deepcopy(self.task)

    def assert_business_preserved(self):
        for field in ["fields", "quote", "checks", "selected_service", "tracking"]:
            self.assertEqual(self.task[field], self.before[field], field)

    def test_offline_greeting_is_a_greeting_without_feature_menu(self):
        with patch("parcel.assistant.model.configured", return_value=False):
            answer = chat(self.task, "你好呀！")
        self.assertEqual(answer["text"], "你好呀！想聊点什么？")
        self.assertEqual(answer["trace"], [])
        self.assert_business_preserved()

    def test_offline_thanks_does_not_redirect_to_parcel_form(self):
        with patch("parcel.assistant.model.configured", return_value=False):
            answer = chat(self.task, "谢谢你")
        self.assertEqual(answer["text"], "不客气！")
        self.assert_business_preserved()

    def test_open_question_reports_missing_model_without_irrelevant_retrieval(self):
        with patch("parcel.assistant.model.configured", return_value=False), patch("parcel.assistant.retrieve", side_effect=AssertionError("not a shipping question")):
            answer = chat(self.task, "帮我写一封给老师的感谢信")
        self.assertTrue(self.task["messages"][-1]["connection_required"])
        self.assertIn("启用 AI 对话", answer["text"])
        self.assertNotIn("本轮", answer["text"])
        self.assertEqual(answer["trace"], [])
        self.assert_business_preserved()

    def test_unrelated_city_and_weight_declarations_never_become_shipping_edits(self):
        for message in ["我想去北京旅游", "我要买10kg大米", "我想减肥8kg", "如果明天纽约下雨怎么办"]:
            with self.subTest(message=message), patch("parcel.assistant.model.configured", return_value=False):
                self.task = deepcopy(self.before)
                answer = chat(self.task, message)
                self.assertEqual(answer["changes"], [])
                self.assert_business_preserved()

    def test_model_handles_open_conversation_directly(self):
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", return_value="先休息十分钟吧，回来再看这道题。") as respond:
            answer = chat(self.task, "我今天学神经网络学得好累啊")
        respond.assert_called_once()
        self.assertEqual(answer["mode"], "model")
        self.assertEqual(answer["text"], "先休息十分钟吧，回来再看这道题。")
        self.assertEqual(answer["trace"], [])
        self.assert_business_preserved()

    def test_nonshipping_price_question_does_not_force_shipping_tool(self):
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", return_value="哪家店、什么规格的牛奶？"):
            answer = chat(self.task, "超市的牛奶多少钱？")
        self.assertEqual(answer["mode"], "model")
        self.assertEqual(answer["trace"], [])
        self.assert_business_preserved()

    def test_scenario_reaches_model_with_grounded_temporary_result(self):
        def reply(message, task, execute):
            scenario = task["_turn_context"]["scenario"]
            self.assertEqual(task["fields"]["weight_kg"], 10)
            self.assertEqual(scenario["quote"]["billable_kg"], 8)
            self.assertEqual(scenario["differences"][0]["delta"], -712)
            return "按8kg试算，IE参考小计少712元。"
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=reply):
            answer = chat(self.task, "如果改成8kg，会便宜多少？")
        self.assertEqual(answer["mode"], "model")
        self.assertEqual(answer["scenario"]["quote"]["billable_kg"], 8)
        self.assertNotIn("_turn_context", self.task)
        self.assert_business_preserved()

    def test_tracking_question_also_reaches_model_without_substituting_demo(self):
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", return_value="可以，把你的运单号填到物流查询页就行。"), patch("parcel.assistant.track", side_effect=AssertionError("no automatic lookup")):
            answer = chat(self.task, "我怎么查包裹到哪了？")
        self.assertEqual(answer["mode"], "model")
        self.assert_business_preserved()

    def test_model_failure_does_not_claim_successful_ai_answer(self):
        with patch("parcel.assistant.model.configured", return_value=True), patch("parcel.assistant.model.respond", side_effect=RuntimeError("API key 验证失败，请检查密钥。")):
            answer = chat(self.task, "帮我写一封感谢信")
        self.assertEqual(answer["mode"], "workflow")
        self.assertIn("AI 暂时没连上", answer["text"])
        self.assertIn("API key", answer["model_error"])
        self.assert_business_preserved()

    def test_saved_task_recall_uses_actual_fields(self):
        with patch("parcel.assistant.model.configured", return_value=False):
            answer = chat(self.task, "我之前说的包裹有多重？")
        self.assertIn("10 kg", answer["text"])
        self.assertEqual(answer["changes"], [])
        self.assert_business_preserved()


if __name__ == "__main__":
    unittest.main()
