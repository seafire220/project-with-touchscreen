"""A language model on the owner's own computer: Ollama and other servers, finding them on the network,
leaving out a reasoning model's thinking, and waiting longer for its first words."""
import asyncio
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import providers  # noqa: E402
from companion.providers import ProviderError, ThinkFilter, local_address  # noqa: E402
from companion.store import Store  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeServers:
    """An Ollama server and an OpenAI-compatible one (as LM Studio or llama.cpp's), on this computer."""

    def __init__(self):
        self.seen = []

    async def start(self):
        self.runners = []
        ollama = web.Application()
        ollama.router.add_get("/api/tags", self.tags)
        ollama.router.add_post("/api/chat", self.ollama_chat)
        other = web.Application()
        other.router.add_get("/v1/models", self.models)
        other.router.add_post("/v1/chat/completions", self.openai_chat)
        self.ollama_port, self.other_port = free_port(), free_port()
        for app, port in ((ollama, self.ollama_port), (other, self.other_port)):
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", port).start()
            self.runners.append(runner)

    async def stop(self):
        for r in self.runners:
            await r.cleanup()

    async def tags(self, request):
        return web.json_response({"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:3b"}]})

    async def ollama_chat(self, request):
        body = await request.json()
        self.seen.append(body)
        if body["model"] not in ("qwen2.5:7b", "llama3.2:3b"):
            return web.json_response({"error": "model '%s' not found" % body["model"]}, status=404)
        response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await response.prepare(request)
        import json
        for piece in ("<thi", "nk>Let me plan this.</th", "ink>", "Hello ", "there!"):
            await response.write((json.dumps({"message": {"role": "assistant", "content": piece}, "done": False}) + "\n").encode())
        await response.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n").encode())
        return response

    async def models(self, request):
        return web.json_response({"data": [{"id": "local-model"}]})

    async def openai_chat(self, request):
        body = await request.json()
        self.seen.append(body)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        import json
        for piece in ("<think>", "hmm", "</think>Hi ", "from LM Studio."):
            await response.write(("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n").encode())
        await response.write(b"data: [DONE]\n\n")
        return response


async def collect(llm):
    out = ""
    async for piece in llm.stream("You are Aria.", [{"role": "user", "content": "Hello"}]):
        out += piece
    return out


class ThinkingTest(unittest.TestCase):
    def run_filter(self, pieces):
        f = ThinkFilter()
        return "".join(f.feed(p) for p in pieces) + f.flush()

    def test_thinking_is_left_out_however_it_arrives(self):
        self.assertEqual(self.run_filter(["<think>plan</think>Hello"]), "Hello")
        self.assertEqual(self.run_filter(["<th", "ink>pl", "an</thi", "nk>  Hello", " there"]), "Hello there")
        self.assertEqual(self.run_filter(["I was thinking</think>Hello"]), "Hello", "no opening tag")
        self.assertEqual(self.run_filter(["Hello <", "b>world</b>"]), "Hello <b>world</b>", "other tags are kept")
        self.assertEqual(self.run_filter(["Plain words", " only."]), "Plain words only.")
        self.assertEqual(self.run_filter(["<think>never closed"]), "")


class AddressTest(unittest.TestCase):
    def test_what_the_owner_types_becomes_the_servers_address(self):
        self.assertEqual(local_address("192.168.1.20", "ollama"), "http://192.168.1.20:11434")
        self.assertEqual(local_address("http://192.168.1.20:11434/v1", "ollama"), "http://192.168.1.20:11434")
        self.assertEqual(local_address("my-laptop.local", "lmstudio"), "http://my-laptop.local:1234/v1")
        self.assertEqual(local_address("10.0.0.5:9000", "llamacpp"), "http://10.0.0.5:9000/v1")
        self.assertEqual(local_address("https://ai.home.example/v1", "openai"), "https://ai.home.example:443/v1")
        with self.assertRaises(ProviderError):
            local_address("", "ollama")


class ServersTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeServers()
        await self.fake.start()
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(self.dir.name)

    async def asyncTearDown(self):
        await self.fake.stop()
        self.dir.cleanup()

    def settings(self, **llm):
        s = self.store.settings()
        s["llm"].update(llm)
        return s

    async def test_ollama_is_asked_for_a_large_enough_context_and_kept_loaded(self):
        llm = providers.build_llm(self.settings(provider="selfhosted", server="ollama", model="qwen2.5:7b",
                                                base_url="127.0.0.1:%d" % self.fake.ollama_port, context=16384), self.store)
        self.assertIsInstance(llm, providers.OllamaLLM)
        self.assertEqual(await collect(llm), "Hello there!", "its thinking is not said")
        body = self.fake.seen[-1]
        self.assertEqual(body["options"]["num_ctx"], 16384)
        self.assertEqual(body["keep_alive"], "30m")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "You are Aria."})
        self.assertEqual(await llm.models(), ["llama3.2:3b", "qwen2.5:7b"])
        self.assertGreaterEqual(llm.patience, 60, "a model on a home computer may take a while to load")

    async def test_a_missing_ollama_model_says_how_to_get_it(self):
        llm = providers.build_llm(self.settings(provider="selfhosted", server="ollama", model="gemma3:4b",
                                                base_url="127.0.0.1:%d" % self.fake.ollama_port), self.store)
        with self.assertRaisesRegex(ProviderError, "ollama pull gemma3:4b"):
            await collect(llm)

    async def test_other_servers_are_spoken_to_as_openai_compatible(self):
        llm = providers.build_llm(self.settings(provider="selfhosted", server="lmstudio", model="local-model",
                                                base_url="http://127.0.0.1:%d" % self.fake.other_port), self.store)
        self.assertIsInstance(llm, providers.OpenAICompatibleLLM)
        self.assertEqual(llm.base_url, "http://127.0.0.1:%d/v1" % self.fake.other_port)
        self.assertEqual(await collect(llm), "Hi from LM Studio.")
        self.assertGreaterEqual(llm.patience, 60)

    async def test_a_computer_that_is_off_says_so(self):
        llm = providers.build_llm(self.settings(provider="selfhosted", server="ollama", model="qwen2.5:7b",
                                                base_url="127.0.0.1:%d" % free_port()), self.store)
        with self.assertRaisesRegex(ProviderError, "could not be reached.*OLLAMA_HOST"):
            await collect(llm)

    async def test_servers_are_found_and_told_apart(self):
        closed = free_port()
        found = await providers.find_servers(hosts=["127.0.0.1"], ports=[self.fake.ollama_port, self.fake.other_port, closed])
        kinds = {f["kind"]: f for f in found}
        self.assertEqual(set(kinds), {"ollama", "openai"})
        self.assertEqual(kinds["ollama"]["models"], ["llama3.2:3b", "qwen2.5:7b"])
        self.assertEqual(kinds["openai"]["address"], "http://127.0.0.1:%d/v1" % self.fake.other_port)
        self.assertEqual(await providers.find_servers(hosts=["8.8.8.8"], ports=[53]), [], "only home-network addresses")

    async def test_the_settings_page_finds_a_server_at_the_address_typed(self):
        from companion.audio import Speaker
        from companion.device import Device
        from companion.web import make_app
        from fakes import FakeStage
        device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=FakeStage())
        client = TestClient(TestServer(make_app(device)))
        await client.start_server()
        try:
            h = {"X-Companion": "1"}
            await client.post("/api/setup", json={"password": "a good password"}, headers=h)
            r = await client.post("/api/llm/find", json={"host": "127.0.0.1:%d" % self.fake.ollama_port}, headers=h)
            servers = (await r.json())["servers"]
            self.assertEqual([s["kind"] for s in servers], ["ollama"])
            r = await client.put("/api/settings", json={"llm": {"provider": "selfhosted", "server": "ollama",
                                                               "base_url": servers[0]["address"], "model": "qwen2.5:7b"}},
                                 headers=h)
            self.assertEqual(r.status, 200)
            r = await client.post("/api/test/llm", headers=h)
            self.assertEqual(await r.json(), {"ok": True, "message": "replied: Hello there!"})
        finally:
            await client.close()


class PatienceTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_conversation_waits_as_long_as_the_model_needs(self):
        from companion.conversation import Conversation, FIRST_WORDS_TIMEOUT

        class Slow:
            patience = 90.0

        conv = Conversation(llm=Slow(), tts=None, speaker=None, stage=None, memory=None, persona="")
        self.assertEqual(conv.patience, 90.0)
        conv.llm = object()
        self.assertEqual(conv.patience, FIRST_WORDS_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
