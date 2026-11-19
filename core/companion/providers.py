"""Provider adapters: language models, speech recognition and voices.

Every adapter takes its key from the device's secret store at the moment it
is built and never logs it. Each has `test()` for the console's test button.

Language models stream text: `async for piece in llm.stream(system, messages)`.
Speech recognition takes 16-bit mono PCM and returns text.
Voices stream 16-bit mono PCM at `tts.rate` samples per second.
"""
import asyncio
import io
import ipaddress
import json
import re
import socket
import urllib.parse
import wave

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)


class ProviderError(Exception):
    """A provider failed. `retry` says whether trying again might help."""

    def __init__(self, message, retry=False):
        super().__init__(message)
        self.retry = retry


# Known OpenAI-compatible services, so the owner only has to pick a name and paste a key.
OPENAI_COMPATIBLE = {
    "openai": {"base_url": "https://api.openai.com/v1", "secret": "openai"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "secret": "groq"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "secret": "openrouter"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "secret": "openai_compatible"},
    "custom": {"base_url": "", "secret": "openai_compatible"},
}


# Language-model servers people run on their own computers: the port each listens on unless told
# otherwise, and the path of its OpenAI-compatible API (Ollama is spoken to in its own API, which lets
# the device set the model's context size and keep it loaded between replies).
LOCAL_SERVERS = {
    "ollama": {"label": "Ollama", "port": 11434, "path": ""},
    "lmstudio": {"label": "LM Studio", "port": 1234, "path": "/v1"},
    "llamacpp": {"label": "llama.cpp server", "port": 8080, "path": "/v1"},
    "vllm": {"label": "vLLM", "port": 8000, "path": "/v1"},
    "koboldcpp": {"label": "KoboldCpp", "port": 5001, "path": "/v1"},
    "textgen": {"label": "text-generation-webui", "port": 5000, "path": "/v1"},
    "jan": {"label": "Jan", "port": 1337, "path": "/v1"},
    "gpt4all": {"label": "GPT4All", "port": 4891, "path": "/v1"},
    "openai": {"label": "Other (OpenAI-compatible)", "port": None, "path": "/v1"},
}
# A model on a home computer can take a while to start answering (it may first be loaded from disk).
LOCAL_PATIENCE = 120.0
# How much text (in tokens) the model is given at most, unless the owner says otherwise.
LOCAL_CONTEXT = 8192
CLOUD_CONTEXT = 32000


def local_address(address, kind):
    """A server's base address from what the owner typed ("192.168.1.20", "laptop.local:1234",
    "http://host:8080/v1" all do), with the kind's usual port and path where none is given."""
    info = LOCAL_SERVERS.get(kind) or LOCAL_SERVERS["openai"]
    text = (address or "").strip()
    if not text:
        raise ProviderError("type the address of the computer the model runs on")
    if not re.match(r"(?i)^https?://", text):
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ProviderError("that does not look like a computer's address: %s" % address)
    if not host:
        raise ProviderError("that does not look like a computer's address: %s" % address)
    port = port or info["port"] or (443 if parts.scheme.lower() == "https" else 80)
    path = parts.path.rstrip("/")
    if kind == "ollama":
        path = re.sub(r"/(v1|api)$", "", path)
    elif not path:
        path = info["path"]
    shown = "[%s]" % host if ":" in host else host
    return "%s://%s:%d%s" % (parts.scheme.lower(), shown, port, path)


class ThinkFilter:
    """Leaves a reasoning model's thinking (between <think> and </think>) out of what is said, even
    when the tags arrive split across pieces, or the opening one is missing."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buffer = ""
        self.inside = False
        self.said = False

    def feed(self, piece):
        self.buffer += piece
        out = ""
        while True:
            if self.inside:
                end = self.buffer.find(self.CLOSE)
                if end < 0:
                    self.buffer = self.buffer[-(len(self.CLOSE) - 1):]
                    return out
                self.buffer = self.buffer[end + len(self.CLOSE):].lstrip()
                self.inside = False
                continue
            start = self.buffer.find(self.OPEN)
            close = self.buffer.find(self.CLOSE)
            if close >= 0 and (start < 0 or close < start):
                # Thinking that began without its opening tag: before anything was said, it all goes.
                if not self.said and not out:
                    self.buffer = self.buffer[close + len(self.CLOSE):].lstrip()
                else:
                    out += self.buffer[:close]
                    self.buffer = self.buffer[close + len(self.CLOSE):]
                continue
            if start >= 0:
                out += self.buffer[:start]
                self.buffer = self.buffer[start + len(self.OPEN):]
                self.inside = True
                continue
            # Keep back what could be the start of a tag.
            keep = 0
            for k in range(1, min(len(self.CLOSE) - 1, len(self.buffer)) + 1):
                tail = self.buffer[-k:]
                if self.OPEN.startswith(tail) or self.CLOSE.startswith(tail):
                    keep = k
            out += self.buffer[:len(self.buffer) - keep]
            self.buffer = self.buffer[len(self.buffer) - keep:]
            if out.strip():
                self.said = True
            return out

    def flush(self):
        rest, self.buffer = ("" if self.inside else self.buffer), ""
        return rest


def _status_error(service, status, body):
    detail = ""
    try:
        data = json.loads(body)
        err = data.get("error", data)
        detail = err.get("message", "") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        detail = body[:200] if isinstance(body, str) else ""
    if status in (401, 403):
        return ProviderError("%s refused the key (%d). Check the key in Settings." % (service, status))
    if status == 404:
        return ProviderError("%s does not know that model or address (404). %s" % (service, detail))
    if status == 429:
        return ProviderError("%s is rate-limiting or out of credit (429). %s" % (service, detail), retry=True)
    if status >= 500:
        # The server's own words matter most from a model on the owner's computer ("model requires more
        # system memory than is available").
        return ProviderError(("%s had a server error (%d). %s" % (service, status, detail[:200])).strip(), retry=True)
    return ProviderError("%s refused the request (%d). %s" % (service, status, detail))


async def iter_sse(response):
    """Yield the data of each server-sent event."""
    buffer = b""
    async for chunk in response.content.iter_any():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if line.startswith(b"data:"):
                yield line[5:].strip().decode("utf-8", "replace")


class OpenAICompatibleLLM:
    """Chat completions on any OpenAI-compatible service."""

    def __init__(self, base_url, key, model, temperature=0.8, max_tokens=400, service="The language model"):
        if not base_url:
            raise ProviderError("no address is set for this language model")
        if not model:
            raise ProviderError("no model is chosen for the language model")
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.service = service
        # Seconds to wait for the first words, and how much text the model takes (tokens).
        self.patience = None
        self.context = CLOUD_CONTEXT

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        return headers

    async def stream(self, system, messages):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "stream": True,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.post(self.base_url + "/chat/completions", json=body, headers=self._headers()) as r:
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    thinking = ThinkFilter()
                    async for data in iter_sse(r):
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except ValueError:
                            continue
                        if "error" in event:
                            raise ProviderError("%s: %s" % (self.service, event["error"]), retry=True)
                        for choice in event.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                piece = thinking.feed(piece)
                                if piece:
                                    yield piece
                    rest = thinking.flush()
                    if rest:
                        yield rest
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached (%s)" % (self.service, type(error).__name__), retry=True)

    async def models(self):
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.get(self.base_url + "/models", headers=self._headers()) as r:
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    data = await r.json(content_type=None)
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached (%s)" % (self.service, type(error).__name__), retry=True)
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    async def test(self):
        reply = ""
        async for piece in self.stream("Reply with the single word: ready", [{"role": "user", "content": "Are you there?"}]):
            reply += piece
        return "replied: %s" % reply.strip()[:60]


class OllamaLLM:
    """A model on the owner's own computer through Ollama's own API: the device sets how much text the
    model takes (Ollama's default is small, and it cuts longer prompts from the start, persona first)
    and keeps the model loaded between replies."""

    def __init__(self, base_url, model, temperature=0.8, max_tokens=400, context=LOCAL_CONTEXT,
                 service="The model on your computer"):
        if not model:
            raise ProviderError("no model is chosen: press List models, or on that computer run: ollama pull <model>")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context = int(context or LOCAL_CONTEXT)
        self.service = service
        self.patience = LOCAL_PATIENCE

    async def stream(self, system, messages):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "stream": True,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens, "num_ctx": self.context},
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=self.patience)) as session:
            try:
                async with session.post(self.base_url + "/api/chat", json=body) as r:
                    if r.status == 404:
                        raise ProviderError("Ollama has no model called %s. On that computer, run: ollama pull %s"
                                            % (self.model, self.model))
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    thinking = ThinkFilter()
                    async for line in r.content:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("error"):
                            raise ProviderError("%s: %s" % (self.service, event["error"]), retry=True)
                        piece = (event.get("message") or {}).get("content") or ""
                        piece = thinking.feed(piece) if piece else ""
                        if piece:
                            yield piece
                        if event.get("done"):
                            break
                    rest = thinking.flush()
                    if rest:
                        yield rest
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached at %s (%s). Is the computer on, and Ollama "
                                    "open to the network (OLLAMA_HOST=0.0.0.0)?" % (self.service, self.base_url,
                                                                                     type(error).__name__), retry=True)

    async def models(self):
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.get(self.base_url + "/api/tags") as r:
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    data = await r.json(content_type=None)
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached (%s)" % (self.service, type(error).__name__), retry=True)
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))

    async def test(self):
        reply = ""
        async for piece in self.stream("Reply with the single word: ready", [{"role": "user", "content": "Are you there?"}]):
            reply += piece
        return "replied: %s" % reply.strip()[:60]


def _own_addresses():
    """This device's addresses on its home network (IPv4), found without sending anything."""
    found = set()
    for probe in ("10.255.255.255", "172.31.255.255", "192.168.255.255", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                found.add(s.getsockname()[0])
        except OSError:
            continue
    return sorted(a for a in found if ipaddress.ip_address(a).is_private and not ipaddress.ip_address(a).is_loopback)


def neighbours():
    """The addresses to look at for servers: this computer, and the others on the same home network
    (the 254 addresses around each of this device's own; private networks only)."""
    hosts = ["127.0.0.1"]
    for own in _own_addresses():
        net = ipaddress.ip_network(own + "/24", strict=False)
        hosts += [str(h) for h in net.hosts() if str(h) != own]
    return hosts


async def _port_open(host, port, timeout):
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True


async def _identify(session, host, port):
    """What answers on a host's port: an Ollama server, or another OpenAI-compatible one, with its models."""
    base = "http://%s:%d" % (host, port)
    try:
        async with session.get(base + "/api/tags") as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                models = sorted(m.get("name", "") for m in (data or {}).get("models", []) if m.get("name"))
                return {"kind": "ollama", "label": "Ollama", "address": base, "models": models}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
        pass
    try:
        async with session.get(base + "/v1/models") as r:
            if r.status in (200, 401):
                data = await r.json(content_type=None) if r.status == 200 else {}
                models = sorted(m.get("id", "") for m in (data or {}).get("data", []) if m.get("id"))
                kind = next((k for k, v in LOCAL_SERVERS.items() if v["port"] == port and k != "ollama"), "openai")
                return {"kind": kind, "label": LOCAL_SERVERS[kind]["label"], "address": base + "/v1", "models": models,
                        "needs_key": r.status == 401}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
        pass
    return None


async def find_servers(hosts=None, ports=None, timeout=0.6, limit=128):
    """Language-model servers on the home network (or on the given hosts): each one's kind, address and
    models. Only private addresses are looked at."""
    ports = ports or sorted({v["port"] for v in LOCAL_SERVERS.values() if v["port"]})
    if hosts is None:
        hosts = neighbours()
    allowed = []
    for h in hosts:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(h, None, family=socket.AF_INET)
            address = infos[0][4][0]
        except (OSError, IndexError):
            continue
        if ipaddress.ip_address(address).is_private:
            allowed.append(address)
    gate = asyncio.Semaphore(limit)

    async def check(host, port):
        async with gate:
            return (host, port) if await _port_open(host, port, timeout) else None

    open_ports = [hp for hp in await asyncio.gather(*(check(h, p) for h in dict.fromkeys(allowed) for p in ports)) if hp]
    found = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
        for result in await asyncio.gather(*(_identify(session, h, p) for h, p in open_ports)):
            if result:
                found.append(result)
    return found


def pcm_to_wav(pcm, rate):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


class OpenAICompatibleSTT:
    """Transcription on an OpenAI-compatible service (OpenAI, Groq and others)."""

    def __init__(self, base_url, key, model, language="en", service="Speech recognition"):
        if not base_url or not model:
            raise ProviderError("speech recognition needs an address and a model")
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.model = model
        self.language = language
        self.service = service

    async def transcribe(self, pcm, rate=16000):
        form = aiohttp.FormData()
        form.add_field("file", pcm_to_wav(pcm, rate), filename="speech.wav", content_type="audio/wav")
        form.add_field("model", self.model)
        if self.language:
            form.add_field("language", self.language)
        form.add_field("response_format", "json")
        headers = {"Authorization": "Bearer " + self.key} if self.key else {}
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.post(self.base_url + "/audio/transcriptions", data=form, headers=headers) as r:
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    data = await r.json(content_type=None)
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached (%s)" % (self.service, type(error).__name__), retry=True)
        return (data.get("text") or "").strip()

    async def test(self):
        silence = b"\0\0" * 16000
        await self.transcribe(silence)
        return "accepted a test recording"


class LocalSTT:
    """Speech recognition on the device with sherpa-onnx. Free; no network.

    `model_dir` holds a sherpa-onnx offline model: Moonshine (preprocess,
    encode, uncached_decode, cached_decode, tokens) or Whisper (encoder,
    decoder, tokens).
    """

    def __init__(self, model_dir, threads=2):
        import glob
        import os
        try:
            import sherpa_onnx
        except ImportError:
            raise ProviderError("on-device speech recognition is not installed (sherpa-onnx)")
        if not os.path.isdir(model_dir):
            raise ProviderError("no on-device speech model is installed at %s" % model_dir)

        def find(pattern):
            found = sorted(glob.glob(os.path.join(model_dir, pattern)))
            return found[0] if found else ""

        tokens = find("*tokens.txt")
        if find("preprocess*.onnx"):
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine(
                preprocessor=find("preprocess*.onnx"), encoder=find("encode*.onnx"),
                uncached_decoder=find("uncached_decode*.onnx"), cached_decoder=find("cached_decode*.onnx"),
                tokens=tokens, num_threads=threads)
        elif find("*encoder*.onnx"):
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=find("*encoder*.onnx"), decoder=find("*decoder*.onnx"), tokens=tokens,
                language="en", task="transcribe", num_threads=threads)
        else:
            raise ProviderError("the on-device speech model at %s is not one this device knows" % model_dir)

    async def transcribe(self, pcm, rate=16000):
        import asyncio
        import numpy as np

        def run():
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            stream = self.recognizer.create_stream()
            stream.accept_waveform(rate, samples)
            self.recognizer.decode_stream(stream)
            return stream.result.text.strip()

        return await asyncio.get_running_loop().run_in_executor(None, run)

    async def test(self):
        await self.transcribe(b"\0\0" * 16000)
        return "the on-device model loaded and ran"


class OpenAICompatibleTTS:
    """Speech on an OpenAI-compatible service, streamed as raw 24 kHz PCM."""

    rate = 24000

    def __init__(self, base_url, key, model, voice, service="The voice service"):
        if not base_url or not model or not voice:
            raise ProviderError("the voice needs an address, a model and a voice name")
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.model = model
        self.voice = voice
        self.service = service

    async def stream(self, text):
        body = {"model": self.model, "voice": self.voice, "input": text, "response_format": "pcm"}
        headers = {"Authorization": "Bearer " + self.key} if self.key else {}
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.post(self.base_url + "/audio/speech", json=body, headers=headers) as r:
                    if r.status != 200:
                        raise _status_error(self.service, r.status, await r.text())
                    async for chunk in r.content.iter_chunked(4800):
                        yield chunk
            except aiohttp.ClientError as error:
                raise ProviderError("%s could not be reached (%s)" % (self.service, type(error).__name__), retry=True)

    async def test(self):
        size = 0
        async for chunk in self.stream("Testing."):
            size += len(chunk)
        return "spoke %.1f seconds of audio" % (size / 2 / self.rate)


class LocalTTS:
    """A voice on the device: a Piper voice played by sherpa-onnx, with phonemes from espeak-ng.
    Free; no network. `model_dir` holds the voice (`*.onnx`, its `.onnx.json`, `tokens.txt`);
    `voice` picks a speaker by number in voices with several (LibriTTS-R has 904)."""

    CHUNK = 0.2      # seconds of sound per piece handed to the speaker

    def __init__(self, model_dir, voice="", speed=1.0, threads=2):
        import glob
        import os
        from . import phonemes
        try:
            import sherpa_onnx
        except ImportError:
            raise ProviderError("the on-device voice is not installed (sherpa-onnx)")
        if not phonemes.espeak_path():
            raise ProviderError("the on-device voice needs espeak-ng, which is not installed")
        models = sorted(glob.glob(os.path.join(model_dir, "*.onnx")))
        if not models or not os.path.exists(os.path.join(model_dir, "tokens.txt")):
            raise ProviderError("no on-device voice is installed at %s" % model_dir)
        self.espeak_voice = "en-us"
        try:
            with open(models[0] + ".json", encoding="utf-8") as f:
                self.espeak_voice = json.load(f).get("espeak", {}).get("voice") or "en-us"
        except (OSError, ValueError):
            pass
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=models[0], tokens=os.path.join(model_dir, "tokens.txt"),
            data_dir=os.path.join(model_dir, "espeak-ng-data") if os.path.isdir(os.path.join(model_dir, "espeak-ng-data")) else "")
        self.tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=threads), max_num_sentences=1))
        self.rate = self.tts.sample_rate
        self.speakers = self.tts.num_speakers
        self.speed = float(speed) if speed else 1.0
        self.catalogue = {}
        try:
            with open(os.path.join(os.path.dirname(__file__), "voices.json"), encoding="utf-8") as f:
                loaded = json.load(f)
            if os.path.basename(models[0]).startswith(loaded.get("model", "?")):
                self.catalogue = loaded
        except (OSError, ValueError):
            pass
        self.sid = 0
        self.set_voice(voice)
        self._sherpa = sherpa_onnx
        self._phonemize = phonemes.phonemize

    def set_voice(self, voice):
        """Choose a speaker by number; anything else takes the default (the surveyed clear voice, or the first)."""
        text = str(voice or "").strip()
        default = int(self.catalogue.get("default", 0)) if self.catalogue else 0
        self.sid = int(text) if text.isdigit() and int(text) < max(self.speakers, 1) else default

    async def voices(self):
        """The surveyed clear voices, for the settings page's list."""
        return [{"id": str(v["id"]), "name": "%s (%d Hz)" % (v["label"], round(v["pitch_hz"]))}
                for v in self.catalogue.get("voices", [])]

    def _speak(self, text):
        import numpy as np
        from .phonemes import PhonemeError
        try:
            phonemes = self._phonemize(text, self.espeak_voice)
        except PhonemeError as error:
            raise ProviderError("the on-device voice could not read the text (%s)" % error)
        if not phonemes:
            return b""
        config = self._sherpa.GenerationConfig()
        config.phoneme_codepoints = [[ord(c) for c in phonemes]]
        config.sid = self.sid
        config.speed = self.speed
        audio = self.tts.generate(text, config)
        samples = np.clip(np.asarray(audio.samples, dtype=np.float32), -1.0, 1.0)
        return (samples * 32767).astype(np.int16).tobytes()

    async def full(self, text):
        """A whole sentence's sound at once (it is made whole anyway), so its syllables can be placed."""
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, self._speak, text)

    async def stream(self, text):
        import asyncio
        pcm = await asyncio.get_running_loop().run_in_executor(None, self._speak, text)
        step = int(self.rate * self.CHUNK) * 2
        for start in range(0, len(pcm), step):
            yield pcm[start:start + step]

    async def test(self):
        size = 0
        async for chunk in self.stream("Testing, one two three."):
            size += len(chunk)
        return "spoke %.1f seconds of audio on the device" % (size / 2 / self.rate)


class ElevenLabsTTS:
    """ElevenLabs voices, including cloned ones, streamed as raw 24 kHz PCM."""

    rate = 24000
    base_url = "https://api.elevenlabs.io/v1"

    def __init__(self, key, voice, model="eleven_flash_v2_5"):
        if not key:
            raise ProviderError("no ElevenLabs key is set")
        if not voice:
            raise ProviderError("no ElevenLabs voice is chosen")
        self.key = key
        self.voice = voice
        self.model = model or "eleven_flash_v2_5"

    async def stream(self, text):
        url = "%s/text-to-speech/%s/stream?output_format=pcm_%d" % (self.base_url, self.voice, self.rate)
        body = {"text": text, "model_id": self.model}
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            try:
                async with session.post(url, json=body, headers={"xi-api-key": self.key}) as r:
                    if r.status != 200:
                        raise _status_error("ElevenLabs", r.status, await r.text())
                    async for chunk in r.content.iter_chunked(4800):
                        yield chunk
            except aiohttp.ClientError as error:
                raise ProviderError("ElevenLabs could not be reached (%s)" % type(error).__name__, retry=True)

    async def voices(self):
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(self.base_url + "/voices", headers={"xi-api-key": self.key}) as r:
                if r.status != 200:
                    raise _status_error("ElevenLabs", r.status, await r.text())
                data = await r.json(content_type=None)
        return [{"id": v.get("voice_id"), "name": v.get("name")} for v in data.get("voices", [])]

    async def test(self):
        size = 0
        async for chunk in self.stream("Testing."):
            size += len(chunk)
        return "spoke %.1f seconds of audio" % (size / 2 / self.rate)


async def clone_voice_elevenlabs(key, name, sample_wav):
    """Make a cloned voice from a sample; returns its voice id. The voice lives in the owner's account."""
    form = aiohttp.FormData()
    form.add_field("name", name[:100])
    form.add_field("files", sample_wav, filename="sample.wav", content_type="audio/wav")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.post(ElevenLabsTTS.base_url + "/voices/add", data=form, headers={"xi-api-key": key}) as r:
            if r.status != 200:
                raise _status_error("ElevenLabs", r.status, await r.text())
            data = await r.json(content_type=None)
    return data["voice_id"]


def build_llm(settings, store):
    """The language model the settings describe."""
    llm = settings["llm"]
    provider = llm.get("provider", "")
    if provider == "anthropic":
        from .anthropic_llm import AnthropicLLM
        return AnthropicLLM(store.secret("anthropic"), llm.get("model", ""), llm.get("max_tokens", 400),
                            llm.get("effort", "low"),
                            web_search=bool(settings.get("conversation", {}).get("web_search", True)))
    if provider == "selfhosted":
        kind = llm.get("server") or "ollama"
        if kind not in LOCAL_SERVERS:
            raise ProviderError("unknown kind of server: %s" % kind)
        base = local_address(llm.get("base_url", ""), kind)
        context = int(llm.get("context") or LOCAL_CONTEXT)
        if kind == "ollama":
            return OllamaLLM(base, llm.get("model", ""), llm.get("temperature", 0.8), llm.get("max_tokens", 400), context)
        adapter = OpenAICompatibleLLM(base, store.secret("local_llm"), llm.get("model", ""), llm.get("temperature", 0.8),
                                      llm.get("max_tokens", 400), service="The model on your computer")
        adapter.patience = LOCAL_PATIENCE
        adapter.context = context
        return adapter
    if provider in OPENAI_COMPATIBLE:
        known = OPENAI_COMPATIBLE[provider]
        adapter = OpenAICompatibleLLM(llm.get("base_url") or known["base_url"], store.secret(known["secret"]),
                                      llm.get("model", ""), llm.get("temperature", 0.8), llm.get("max_tokens", 400))
        if llm.get("context"):
            adapter.context = int(llm["context"])
        return adapter
    raise ProviderError("no language model is chosen yet")


def build_stt(settings, store, model_dir):
    stt = settings["stt"]
    provider = stt.get("provider", "local")
    if provider == "local":
        return LocalSTT(model_dir)
    if provider in OPENAI_COMPATIBLE:
        known = OPENAI_COMPATIBLE[provider]
        return OpenAICompatibleSTT(stt.get("base_url") or known["base_url"], store.secret(known["secret"]),
                                   stt.get("model", ""), stt.get("language", "en"))
    raise ProviderError("no speech recognition is chosen yet")


def build_tts(settings, store, voice=None, model_dir=None):
    tts = settings["tts"]
    provider = tts.get("provider", "")
    chosen = voice or tts.get("voice", "")
    if provider == "local":
        return LocalTTS(model_dir or "", chosen, tts.get("speed", 1.0))
    if provider == "elevenlabs":
        return ElevenLabsTTS(store.secret("elevenlabs"), chosen, tts.get("model", ""))
    if provider in OPENAI_COMPATIBLE:
        known = OPENAI_COMPATIBLE[provider]
        return OpenAICompatibleTTS(tts.get("base_url") or known["base_url"], store.secret(known["secret"]),
                                   tts.get("model", ""), chosen)
    raise ProviderError("no voice service is chosen yet")
