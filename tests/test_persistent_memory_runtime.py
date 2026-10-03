import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jarvis_agent.agent_runtime import _is_explicit_memory_write_request
from jarvis_agent.config import settings
from jarvis_agent.memory import LocalMemory
from jarvis_agent.native_tools import NativeToolRegistry
from tests.test_agent_runtime import FakeGroqAgent, FakeOllamaAgent, FakeOpenAIAgent


FACT = "Mon projet fictif s'appelle Atlas Bleu."
REQUEST = "Retiens cette information de test : " + FACT
QUESTION = "Comment s’appelle mon projet fictif ?"


def message(text, provider, response_id="response_test"):
    if provider == "ollama":
        return {"message": {"content": text}}
    return {"id": response_id, "output": [{
        "type": "message", "content": [{"type": "output_text", "text": text}],
    }]}


def write_call(provider):
    arguments = {"content": FACT, "tags": "projet fictif"}
    if provider == "ollama":
        return {"message": {"tool_calls": [{
            "function": {"name": "remember_information", "arguments": arguments},
        }]}}
    return {"id": "response_call", "output": [{
        "type": "function_call", "call_id": "call_store",
        "name": "remember_information", "arguments": json.dumps(arguments),
    }]}


class CountingTools(NativeToolRegistry):
    def __init__(self, memory):
        super().__init__(memory=memory)
        self.calls = []

    def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, dict(arguments)))
        return super().execute(name, arguments, approved=approved)


class PersistentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.sqlite3"
        self.memory = LocalMemory(self.path)
        self.tools = CountingTools(self.memory)

    def test_exact_human_question_after_reopening_database(self):
        self.memory.remember(FACT)
        fresh = LocalMemory(self.path)
        self.assertEqual([row.content for row in fresh.search(QUESTION)], [FACT])

    def test_unicode_accents_and_case_are_normalized(self):
        self.memory.remember("Mon ÉQUIPE préférée est l'ÉTOILE.")
        self.assertEqual(len(self.memory.search("equipe preferee etoile")), 1)

    def test_arabic_question_and_content(self):
        self.memory.remember("مشروعي التجريبي اسمه اطلس")
        self.assertEqual(len(self.memory.search("ما هو مشروعي التجريبي")), 1)

    def test_no_results_without_significant_terms(self):
        self.memory.remember(FACT)
        self.assertEqual(self.memory.search("Comment ?"), [])
        self.assertEqual(self.memory.search("% _"), [])

    def test_unrelated_entity_is_not_returned_by_partial_overlap(self):
        self.memory.remember(FACT)
        self.assertEqual(self.memory.search("projet Atlas Nova"), [])

    def test_tool_verifies_durable_readback(self):
        result = self.tools.execute("remember_information", {"content": FACT})
        proof = json.loads(result.detail)
        self.assertTrue(result.success)
        self.assertTrue(proof["verified"])
        fresh = LocalMemory(self.path)
        self.assertEqual(fresh.get(proof["memory_id"]).content, FACT)

    def test_sqlite_failure_is_reported_as_failure(self):
        with patch.object(self.memory, "remember", side_effect=sqlite3.OperationalError("test")):
            result = self.tools.execute("remember_information", {"content": FACT})
        self.assertFalse(result.success)

    def test_failed_readback_does_not_claim_persistence(self):
        with patch.object(self.memory, "get", return_value=None):
            result = self.tools.execute("remember_information", {"content": FACT})
        self.assertFalse(result.success)

    def test_real_second_process_recalls_committed_memory(self):
        self.tools.execute("remember_information", {"content": FACT})
        env = dict(os.environ, JARVIS_MEMORY_DB_PATH=str(self.path), PYTHONIOENCODING="utf-8")
        completed = subprocess.run([
            sys.executable, "-c",
            "import json; from jarvis_agent.memory import LOCAL_MEMORY; "
            "print(json.dumps([m.content for m in LOCAL_MEMORY.search(\"Comment s'appelle mon projet fictif ?\")]))",
        ], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), [FACT])

    def test_retiens_authorizes_and_negation_does_not(self):
        self.assertTrue(_is_explicit_memory_write_request(REQUEST))
        self.assertFalse(_is_explicit_memory_write_request("Ne retiens pas cette information."))
        self.assertFalse(_is_explicit_memory_write_request("Don't remember this information."))
        self.assertFalse(_is_explicit_memory_write_request("Do you remember my project?"))

    def test_database_file_is_released_after_a_read_and_write(self):
        self.memory.remember(FACT)
        self.memory.search(QUESTION)
        renamed = self.path.with_name("released.sqlite3")
        self.path.rename(renamed)
        self.assertEqual(LocalMemory(renamed).search(QUESTION)[0].content, FACT)

    def test_all_model_loops_repair_a_false_memory_confirmation(self):
        for provider, agent_type in (
            ("groq", FakeGroqAgent), ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                tools = CountingTools(LocalMemory(Path(self.tmp.name) / (provider + ".sqlite3")))
                agent = agent_type(tools, [
                    message("C'est mémorisé.", provider), write_call(provider),
                    message("Information enregistrée durablement.", provider, "response_final"),
                ])
                result = agent.run(REQUEST)
                self.assertEqual([name for name, _ in tools.calls], ["remember_information"])
                self.assertTrue(result.actions[-1].success)
                self.assertIn("Atlas Bleu", tools.memory.search(QUESTION)[0].content)

    def test_all_model_loops_reject_success_when_the_model_keeps_ignoring_storage(self):
        for provider, agent_type in (
            ("groq", FakeGroqAgent), ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                agent = agent_type(self.tools, [message("C'est mémorisé.", provider)] * 2)
                result = agent.run(REQUEST)
                self.assertIn("n'ai pas enregistré", result.text)
                self.assertEqual(self.tools.calls, [])

    def test_fresh_model_session_uses_persistent_memory_without_prior_conversation(self):
        self.memory.remember(FACT)
        for provider, agent_type in (
            ("groq", FakeGroqAgent), ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                tools = CountingTools(LocalMemory(self.path))
                agent = agent_type(tools, [message("Votre projet s'appelle Atlas Bleu.", provider)])
                result = agent.run(QUESTION)
                self.assertEqual(tools.calls[0][0], "recall_information")
                self.assertIn("Atlas Bleu", json.dumps(agent.payloads[0], ensure_ascii=False, default=list))
                self.assertEqual(result.actions[0].name, "recall_information")

    def test_memory_context_is_retrieved_again_after_reset(self):
        self.memory.remember(FACT)
        agent = FakeGroqAgent(self.tools, [message("Atlas Bleu.", "groq")] * 2)
        agent.run(QUESTION)
        agent.reset()
        agent.run(QUESTION)
        self.assertEqual([name for name, _ in self.tools.calls], ["recall_information"] * 2)

    def test_ordinary_conversation_does_not_persist_information(self):
        agent = FakeGroqAgent(self.tools, [message("D'accord.", "groq")])
        agent.run(FACT)
        self.assertEqual(self.tools.calls, [])
        self.assertEqual(self.memory.search("Atlas Bleu"), [])

    def test_memory_retry_respects_the_round_budget(self):
        agent = FakeGroqAgent(self.tools, [message("C'est mémorisé.", "groq")])
        with patch("jarvis_agent.agent_runtime.settings", replace(settings, agent_max_tool_rounds=1)):
            result = agent.run(REQUEST)
        self.assertIn("n'ai pas enregistré", result.text)
        self.assertEqual(len(agent.payloads), 1)


if __name__ == "__main__":
    unittest.main()
