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

from jarvis_agent.agent_runtime import CerebrasResponsesAgent, _is_explicit_memory_write_request
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


def write_call(provider, content=FACT, tags="projet fictif"):
    arguments = {"content": content, "tags": tags}
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


class FakeCerebrasAgent(CerebrasResponsesAgent):
    """Use the real Cerebras runtime; replace only its network transport."""

    def __init__(self, tools, responses):
        super().__init__(tools)
        self.responses = list(responses)
        self.payloads = []
        self.api_key = "test"

    _response_from_dict = staticmethod(FakeGroqAgent._response_from_dict)
    _chat = FakeGroqAgent._chat


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
            """import json
from jarvis_agent.memory import LOCAL_MEMORY
from tests.test_persistent_memory_runtime import CountingTools, FakeCerebrasAgent, message
exact = [m.content for m in LOCAL_MEMORY.search("Comment s'appelle mon projet fictif ?")]
tools = CountingTools(LOCAL_MEMORY)
agent = FakeCerebrasAgent(tools, [message("Atlas Bleu.", "cerebras")])
result = agent.run("C'est quoi mon projet fictif test ?")
print(json.dumps({"exact": exact, "calls": tools.calls,
    "recalled": json.loads(result.actions[0].detail)}))
""",
        ], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["exact"], [FACT])
        self.assertEqual(payload["calls"], [["recall_information", {"query": "projet fictif"}]])
        self.assertEqual(payload["recalled"][0]["content"], FACT)

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

    def test_spoken_write_variants_authorize_persistence(self):
        for request in (
            "S'il te plaît, garde dans mémoire que je veux regarder des films. Le premier film, c'est « Inception ».",
            "Garde ça dans ta mémoire : je veux regarder Inception.",
            "Enregistre dans la mémoire que mon film préféré est Inception.",
            "Mets en mémoire que mon film préféré est Inception.",
            "Conservez dans votre mémoire que mon film préféré est Inception.",
        ):
            with self.subTest(request=request):
                self.assertTrue(_is_explicit_memory_write_request(request))

    def test_spoken_write_negation_and_ordinary_film_request_do_not_authorize(self):
        for request in (
            "Ne garde pas dans mémoire que je veux regarder Inception.",
            "Ne mets pas en mémoire que je veux regarder Inception.",
            "N'enregistre pas dans ta mémoire que je veux regarder Inception.",
            "Garde pas ça dans ta mémoire.",
            "Ne garde jamais dans ta mémoire que je veux regarder Inception.",
            "Je veux regarder Inception.",
            "Rappelle-moi quel film je veux regarder.",
            "C'est quoi mon projet fictif test ?",
        ):
            with self.subTest(request=request):
                self.assertFalse(_is_explicit_memory_write_request(request))

    def test_live_log_wording_exposes_real_write_tool_and_saves_film(self):
        request = "S'il te plaît, garde dans mémoire que je veux regarder des films. Le premier film, c'est « Inception »."
        film = "Le premier film que je veux regarder est Inception."
        for provider, agent_type in (
            ("cerebras", FakeCerebrasAgent), ("groq", FakeGroqAgent),
            ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                tools = CountingTools(LocalMemory(Path(self.tmp.name) / (provider + "-film.sqlite3")))
                agent = agent_type(tools, [write_call(provider, film, "films"), message("Film enregistré.", provider)])
                result = agent.run(request)
                self.assertTrue(result.actions[-1].success)
                fresh = LocalMemory(tools.memory.db_path)
                self.assertEqual(fresh.search("Inception")[0].content, film)
                definitions = agent.payloads[0]["tools"]
                names = {item.get("name") or item.get("function", {}).get("name") for item in definitions}
                self.assertIn("remember_information", names)

    def test_live_log_colloquial_question_loads_atlas_in_fresh_provider_sessions(self):
        atlas = "Mon projet fictif s'appelle Atlas"
        self.memory.remember(atlas, tags="projet")
        for provider, agent_type in (
            ("cerebras", FakeCerebrasAgent), ("groq", FakeGroqAgent),
            ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                tools = CountingTools(LocalMemory(self.path))
                agent = agent_type(tools, [message("Ton projet fictif s'appelle Atlas.", provider)])
                logs = []
                result = agent.run("C'est quoi mon projet fictif test ?", log=logs.append)
                self.assertEqual(tools.calls, [("recall_information", {"query": "projet fictif"})])
                self.assertEqual(json.loads(result.actions[0].detail)[0]["content"], atlas)
                payload = json.dumps(agent.payloads[0], ensure_ascii=False, default=list)
                self.assertIn(atlas, payload)
                self.assertIn('"omitted_terms": ["test"]', payload.replace('\\"', '"'))
                self.assertTrue(any("match=partial" in line for line in logs))

    def test_colloquial_questions_without_punctuation_also_recall(self):
        self.memory.remember(FACT)
        for question in (
            "C'est quoi mon projet fictif",
            "C’est quoi mon projet fictif",
            "Tu te souviens de mon projet fictif",
            "S'il te plaît, quel est mon projet fictif ?",
        ):
            with self.subTest(question=question):
                tools = CountingTools(LocalMemory(self.path))
                agent = FakeCerebrasAgent(tools, [message("Atlas Bleu.", "cerebras")])
                result = agent.run(question)
                self.assertEqual(result.actions[0].name, "recall_information")
                self.assertIn(FACT, json.dumps(agent.payloads[0], ensure_ascii=False, default=list))

    def test_partial_question_requires_two_remaining_significant_terms(self):
        self.memory.remember(FACT)
        agent = FakeCerebrasAgent(self.tools, [message("Peux-tu préciser ?", "cerebras")])
        agent.run("C'est quoi mon projet inconnu ?")
        self.assertEqual(self.tools.calls, [])

    def test_partial_question_does_not_drop_a_capitalized_entity(self):
        self.memory.remember(FACT)
        agent = FakeCerebrasAgent(self.tools, [message("Je ne trouve pas Atlas Nova.", "cerebras")])
        agent.run("C'est quoi mon projet Atlas Nova ?")
        self.assertEqual(self.tools.calls, [])

    def test_partial_question_does_not_drop_a_quoted_entity(self):
        self.memory.remember(FACT)
        agent = FakeCerebrasAgent(self.tools, [message("Je ne trouve pas ce projet.", "cerebras")])
        agent.run("C'est quoi mon projet fictif 'nova' ?")
        self.assertEqual(self.tools.calls, [])

    def test_partial_question_keeps_ambiguity_and_original_terms_in_context(self):
        self.memory.remember(FACT)
        self.memory.remember("Mon projet fictif s'appelle Orion.")
        agent = FakeCerebrasAgent(self.tools, [message("Quel projet veux-tu retrouver ?", "cerebras")])
        result = agent.run("C'est quoi mon projet fictif test ?")
        rows = json.loads(result.actions[0].detail)
        self.assertEqual(len(rows), 2)
        context = next(item["content"] for item in agent.payloads[0]["messages"]
            if item.get("role") == "system" and item["content"].startswith("PERSISTENT_MEMORY_CONTEXT"))
        self.assertIn("correspondance partielle", context)
        self.assertIn('"omitted_terms": ["test"]', context)
        self.assertIn("Atlas Bleu", context)
        self.assertIn("Orion", context)

    def test_new_recall_turn_hides_write_tool_after_explicit_spoken_save(self):
        request = "Garde dans mémoire que mon projet fictif s'appelle Atlas Bleu."
        agent = FakeCerebrasAgent(self.tools, [write_call("cerebras"),
            message("Enregistré.", "cerebras"), message("Atlas Bleu.", "cerebras")])
        agent.run(request)
        agent.reset()
        result = agent.run("C'est quoi mon projet fictif test ?")
        self.assertEqual(result.actions[0].name, "recall_information")
        names = {item.get("function", {}).get("name") for item in agent.payloads[-1]["tools"]}
        self.assertNotIn("remember_information", names)


if __name__ == "__main__":
    unittest.main()
