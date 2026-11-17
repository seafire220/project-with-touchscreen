"""Claude models through the official Anthropic SDK.

Imported only when the owner chooses Anthropic, because the SDK adds about
50 MB of memory, which matters on a 1 GB device.

Defaults: Claude Opus 5.5 at low effort (a spoken chat wants quick, short
replies; effort is the setting that trades depth for speed). The model and
effort are chosen in the console. Server-side fallback is on for the models
that support it, so a request a model declines is answered by another model
instead of failing.
"""
import anthropic

from .providers import ProviderError

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept server-side fallbacks ("default" lets the API choose the fallback).
FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class AnthropicLLM:
    def __init__(self, key, model="", max_tokens=400, effort="low"):
        if not key:
            raise ProviderError("no Anthropic key is set")
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max(64, int(max_tokens or 400))
        self.effort = effort if effort in EFFORTS else "low"
        self.client = anthropic.AsyncAnthropic(api_key=key, timeout=60.0, max_retries=1)

    def _request(self, system, messages):
        # The conversation must start with the user; a greeting the character
        # spoke first is left out of what is sent.
        messages = list(messages)
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": self.effort},
        }
        if self.model in FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    async def stream(self, system, messages):
        request = self._request(system, messages)
        try:
            if "betas" in request:
                manager = self.client.beta.messages.stream(**request)
            else:
                manager = self.client.messages.stream(**request)
            async with manager as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "refusal":
                raise ProviderError("the model declined to answer that")
        except anthropic.AuthenticationError:
            raise ProviderError("Anthropic refused the key. Check the key in Settings.")
        except anthropic.PermissionDeniedError:
            raise ProviderError("this Anthropic key may not use %s" % self.model)
        except anthropic.NotFoundError:
            raise ProviderError("Anthropic does not know the model %s" % self.model)
        except anthropic.RateLimitError:
            raise ProviderError("Anthropic is rate-limiting this key; try again shortly", retry=True)
        except anthropic.BadRequestError as error:
            raise ProviderError("Anthropic refused the request: %s" % getattr(error, "message", "bad request"))
        except anthropic.APIStatusError as error:
            raise ProviderError("Anthropic had a server error (%s)" % error.status_code,
                                retry=error.status_code >= 500)
        except anthropic.APIConnectionError:
            raise ProviderError("Anthropic could not be reached", retry=True)

    async def models(self):
        try:
            page = await self.client.models.list(limit=100)
        except anthropic.AuthenticationError:
            raise ProviderError("Anthropic refused the key. Check the key in Settings.")
        except anthropic.APIConnectionError:
            raise ProviderError("Anthropic could not be reached", retry=True)
        return [m.id for m in page.data]

    async def test(self):
        reply = ""
        async for piece in self.stream("Reply with the single word: ready", [{"role": "user", "content": "Are you there?"}]):
            reply += piece
        return "%s replied: %s" % (self.model, reply.strip()[:60])
