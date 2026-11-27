import unittest
from main import payload_for, unpack_response, child_env, is_admin_record, VOICES

class Tests(unittest.TestCase):
    def test_sonna_available(self):
        self.assertIn('sonna', VOICES)
        self.assertIn('cove', VOICES)

    def test_agent_and_context(self):
        self.assertEqual(payload_for(" Hallo ", "conversation.openai_conversation", "abc"),
                         {"text":"Hallo","language":"de","agent_id":"conversation.openai_conversation","conversation_id":"abc"})
    def test_reject_empty_and_wrong_agent(self):
        for text, agent in [("", "conversation.foo"), ("hi", "light.foo"), ("x"*4001, "conversation.foo")]:
            with self.assertRaises(ValueError):
                payload_for(text, agent)
    def test_response(self):
        result = unpack_response({"response":{"speech":{"plain":{"speech":"23 Grad"}}},"conversation_id":"abc","continue_conversation":True})
        self.assertEqual(result["text"],"23 Grad")
        self.assertEqual(result["conversation_id"],"abc")
        self.assertTrue(result["continue_conversation"])
    def test_empty_response(self):
        with self.assertRaises(ValueError):
            unpack_response({})
    def test_admin_record(self):
        admin = {"id":"a","is_active":True,"group_ids":["system-admin"]}
        self.assertTrue(is_admin_record(admin,"a"))
        self.assertFalse(is_admin_record(admin,"b"))
        self.assertFalse(is_admin_record(dict(admin,is_active=False),"a"))
        self.assertFalse(is_admin_record(dict(admin,group_ids=["system-users"]),"a"))

    def test_child_env_no_credentials(self):
        for key in ["SUPERVISOR_TOKEN","OPENAI_API_KEY","CODEX_API_KEY"]:
            self.assertNotIn(key,child_env())

if __name__ == "__main__":
    unittest.main()
