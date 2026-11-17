"""Provider adapters: language models, speech recognition and voices.

Every adapter takes its key from the device's secret store at the moment it
is built and never logs it. Each has `test()` for the console's test button.

Language models stream text: `async for piece in llm.stream(system, messages)`.
Speech recognition takes 16-bit mono PCM and returns text.
Voices stream 16-bit mono PCM at `tts.rate` samples per second.
"""
import io
import json
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
        return ProviderError("%s had a server error (%d)." % (service, status), retry=True)
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
                    async for data in iter_sse(r):
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                        except ValueError:
                            continue
                        if "error" in event:
                            raise ProviderError("%s: %s" % (self.service, event["error"]), retry=True)
                        for choice in event.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                yield piece
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
    if provider in OPENAI_COMPATIBLE:
        known = OPENAI_COMPATIBLE[provider]
        return OpenAICompatibleLLM(llm.get("base_url") or known["base_url"], store.secret(known["secret"]),
                                   llm.get("model", ""), llm.get("temperature", 0.8), llm.get("max_tokens", 400))
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


def build_tts(settings, store, voice=None):
    tts = settings["tts"]
    provider = tts.get("provider", "")
    chosen = voice or tts.get("voice", "")
    if provider == "elevenlabs":
        return ElevenLabsTTS(store.secret("elevenlabs"), chosen, tts.get("model", ""))
    if provider in OPENAI_COMPATIBLE:
        known = OPENAI_COMPATIBLE[provider]
        return OpenAICompatibleTTS(tts.get("base_url") or known["base_url"], store.secret(known["secret"]),
                                   tts.get("model", ""), chosen)
    raise ProviderError("no voice service is chosen yet")
