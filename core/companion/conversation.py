"""One spoken exchange: hear, think, speak, and let it be interrupted.

    words heard ─► language model (streamed) ─► sentences ─► voice (streamed) ─► speaker
                                                  │                                 │
                                                  └─ emotions, timers ─► stage      └─ loudness ─► mouth

The voice starts on the first sentence while the model is still writing the
rest, and the next sentence's audio is fetched while the current one plays.
Pressing the button (or speaking, with echo cancellation) interrupts: the
sound stops at once and what was actually said is remembered.
"""
import asyncio
import datetime
import functools
import logging
import random

from .audio import tone
from .characters import split_persona
from .performance import Planner, SyllableMarks, guess_feeling, syllable_offsets
from .memory import when
from .providers import ProviderError
from .search import results_for_model
from .speech_text import SEARCH_RULE, Splitter, speech_rules

log = logging.getLogger("companion.conversation")

FIRST_WORDS_TIMEOUT = 20.0   # seconds to wait for the model's first sentence
MOOD_LINGER = 6.0            # seconds a feeling stays after a reply ends, before calming to neutral
REPLY_TIMEOUT = 90.0         # longest a whole reply may take


def system_prompt(persona, notes, now=None, search_tag=False, gestures=("nod", "shake", "bow", "tilt"), recalled=()):
    """The model's instructions: the persona, how to speak, the time, and what the character remembers:
    its notes and the summaries of earlier conversations recalled for this reply (oldest first)."""
    body, _ = split_persona(persona)
    now = now or datetime.datetime.now()
    rules = speech_rules(gestures) + ("\n" + SEARCH_RULE if search_tag else "")
    parts = [body, rules, "It is now %s." % now.strftime("%A %d %B %Y, %H:%M")]
    if notes.strip():
        parts.append("What you remember about the person you are talking with:\n" + notes.strip())
    if recalled:
        lines = ["- %s: %s" % (when(e["t"], now.timestamp()), e["summary"]) for e in recalled]
        parts.append("From earlier conversations with them (your own summaries; bring them up only when "
                     "they fit):\n" + "\n".join(lines))
    return "\n\n".join(p for p in parts if p)


class Reply:
    """The state of the reply being spoken; read by the console and by interruptions."""

    def __init__(self, heard):
        self.heard = heard
        self.spoken = []
        self.interrupted = False
        self.error = None


class Conversation:
    def __init__(self, *, llm, tts, speaker, stage, memory, persona, history_turns=12,
                 on_event=None, on_action=None, on_audio=None, search=None, gestures=None):
        self.llm = llm
        self.tts = tts
        self.speaker = speaker
        self.stage = stage
        self.memory = memory
        self.persona = persona
        self.history_turns = history_turns
        self.on_event = on_event or (lambda kind, data: None)
        self.on_action = on_action or (lambda action: None)
        self.on_audio = on_audio
        self.search = search            # async query -> results, for models without their own search
        # Gestures the character can make (told to the model); by default whatever the stage reports.
        self.gestures = gestures
        self.current = None
        self._task = None
        self.mood_linger = MOOD_LINGER
        self._calm = None
        # Mouth shapes and movements that go with each sentence's meaning (performance.py).
        self.planner = Planner(random.Random())

    def _calm_later(self):
        """Let the reply's feeling stay a little, then return to neutral (unless a new reply starts)."""
        async def calm():
            await asyncio.sleep(self.mood_linger)
            self.stage.express("neutral")
        self._calm = asyncio.ensure_future(calm())

    def _stop_calming(self):
        if self._calm is not None and not self._calm.done():
            self._calm.cancel()
        self._calm = None

    @property
    def busy(self):
        return self._task is not None and not self._task.done()

    def interrupt(self):
        """Stop speaking now. Safe to call at any time."""
        if self.current is not None:
            self.current.interrupted = True
        self.speaker.stop()
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def start(self, heard):
        """Begin replying to what was heard, in the background. Returns the task."""
        self.interrupt()
        self._task = asyncio.ensure_future(self.respond(heard))
        return self._task

    async def respond(self, heard):
        self._stop_calming()
        reply = self.current = Reply(heard)
        self.on_event("heard", {"text": heard})
        self.stage.state("thinking")
        messages = self.memory.recent(self.history_turns) + [{"role": "user", "content": heard}]
        gestures = self.gestures if self.gestures is not None else getattr(self.stage, "gestures", ("nod", "shake", "bow", "tilt"))
        system = system_prompt(self.persona, self.memory.notes(), search_tag=self.search is not None, gestures=gestures,
                               recalled=self.memory.recall(heard))
        writer = None
        try:
            queries = []
            for round_ in range(2):          # a reply, and at most one answer from search results
                sentences = asyncio.Queue()
                writer = asyncio.ensure_future(self._write(system, messages, sentences, reply))
                queries = []
                await asyncio.wait_for(self._speak(sentences, reply, queries), REPLY_TIMEOUT)
                if not (queries and self.search) or round_ == 1:
                    break
                self.stage.state("thinking")
                self.on_event("searching", {"query": queries[0]})
                found = await asyncio.wait_for(self.search(queries[0]), 25)
                messages = messages + [{"role": "assistant", "content": " ".join(reply.spoken) or "Let me check."},
                                       {"role": "user", "content": results_for_model(queries[0], found)}]
        except asyncio.TimeoutError:
            reply.error = "the reply took too long"
        except asyncio.CancelledError:
            reply.interrupted = True
        except ProviderError as error:
            reply.error = str(error)
        finally:
            if writer is not None:
                writer.cancel()
            if reply.interrupted:
                self.speaker.stop()
            self.stage.mouth(0.0)
            if reply.interrupted or reply.error:
                self.stage.express("neutral")
            else:
                self._calm_later()
            said = " ".join(reply.spoken).strip()
            if said or reply.interrupted:
                self.memory.add_turn(heard, said, interrupted=reply.interrupted)
            if reply.error:
                log.warning("reply failed: %s", reply.error)
                self.on_event("error", {"message": reply.error})
                await self._notice()
            self.stage.state("idle")
            self.on_event("replied", {"text": said, "interrupted": reply.interrupted, "error": reply.error})
            self.current = None
        return reply

    async def _write(self, system, messages, sentences, reply):
        """Read the model's stream and queue up sentences to speak."""
        splitter = Splitter()
        try:
            async for piece in self.llm.stream(system, messages):
                for item in splitter.feed(piece):
                    await sentences.put(item)
            for item in splitter.flush():
                await sentences.put(item)
            await sentences.put(None)
        except ProviderError as error:
            await sentences.put(error)
        except asyncio.CancelledError:
            raise
        except Exception as error:             # a provider bug must not leave the character stuck
            log.exception("language model stream failed")
            await sentences.put(ProviderError("the language model failed (%s)" % type(error).__name__))

    async def _next(self, sentences, first):
        item = await asyncio.wait_for(sentences.get(), FIRST_WORDS_TIMEOUT if first else REPLY_TIMEOUT)
        if isinstance(item, ProviderError):
            raise item
        return item

    async def _speak(self, sentences, reply, queries=None):
        """Speak sentences as they come, fetching the next one's audio while one plays."""
        try:
            item = await self._next(sentences, True)
        except asyncio.TimeoutError:
            raise ProviderError("the language model did not answer in time", retry=True)
        audio_queue = asyncio.Queue(maxsize=64)

        async def fetch_all(first_item):
            try:
                item, first, tagged, feeling = first_item, True, False, None
                while item is not None:
                    text, emotion, actions = item
                    if emotion:
                        tagged = True
                    elif text and not tagged:
                        # The model tagged no feeling in this reply (yet): guess one from the words.
                        guess = guess_feeling(text)
                        emotion = guess if guess and guess != feeling else None
                    if emotion:                  # the mood first, so a gesture asked for plays on top of it
                        feeling = emotion
                        await audio_queue.put(("emotion", emotion))
                    asked = []
                    for action in actions:
                        if action.get("kind") == "search":
                            if queries is not None:
                                queries.append(action["query"])
                        elif action.get("kind") == "gesture":
                            asked.append(action["name"])
                            await audio_queue.put(("gesture", action["name"]))   # in step with the speech
                        else:
                            self.on_action(action)
                    if text:
                        plan = self._plan(text, asked, first)
                        first = False
                        if plan:
                            await audio_queue.put(("perform", plan))
                        await self._queue_sound(text, plan, audio_queue)
                    item = await self._next(sentences, False)
                await audio_queue.put(None)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                await audio_queue.put(("error", ProviderError("the language model stopped part-way", retry=True)))
            except Exception as error:      # passed to the player, which stops and reports it
                await audio_queue.put(("error", error))

        fetcher = asyncio.ensure_future(fetch_all(item))

        async def audio():
            while True:
                entry = await audio_queue.get()
                if entry is None:
                    return
                kind, value = entry
                if kind == "error":
                    raise value if isinstance(value, ProviderError) else ProviderError(
                        "the voice failed (%s)" % type(value).__name__)
                if kind == "audio":
                    yield value
                elif kind == "emotion":          # markers: each runs as the sound before it is heard
                    yield functools.partial(self.stage.express, value)
                elif kind == "gesture":
                    if hasattr(self.stage, "gesture"):
                        yield functools.partial(self.stage.gesture, value)
                elif kind == "perform":
                    if hasattr(self.stage, "perform"):
                        yield functools.partial(self.stage.perform, value)
                elif kind == "syllable":
                    if hasattr(self.stage, "syllable"):
                        yield functools.partial(self.stage.syllable, value)
                elif kind == "text":
                    reply.spoken.append(value)
                    self.on_event("saying", {"text": value})
                    self.stage.state("speaking")

        try:
            await self.speaker.play(audio(), self.tts.rate, self.stage.mouth, self.on_audio)
        finally:
            fetcher.cancel()

    def _plan(self, text, asked, first):
        """The sentence's performance, or None (the stage then moves the mouth with the loudness alone)."""
        try:
            available = self.gestures if self.gestures is not None else getattr(self.stage, "gestures", ())
            return self.planner.plan(text, available or (), asked=asked, first=first)
        except Exception:
            log.exception("could not plan a sentence's performance")
            return None

    async def _queue_sound(self, text, plan, audio_queue):
        """Queue a sentence's sound, with a mark where each of its syllables is heard."""
        count = len(plan["syllables"]) if plan else 0
        whole = getattr(self.tts, "full", None)
        if whole and count:
            # Made whole anyway (the device's own voice): place each syllable at its loudness peak.
            pcm = await whole(text)
            await audio_queue.put(("text", text))
            try:
                offsets = [o * 2 for o in syllable_offsets(pcm, self.tts.rate, count)]
            except Exception:
                log.exception("could not place a sentence's syllables")
                offsets = []
            step, pos = int(self.tts.rate * 0.2) * 2, 0
            cuts = sorted(set([0] + [o for o in offsets if 0 <= o < len(pcm)]))
            marks = {o: k for k, o in enumerate(offsets)}
            for i, cut in enumerate(cuts):
                end = cuts[i + 1] if i + 1 < len(cuts) else len(pcm)
                if cut in marks:
                    await audio_queue.put(("syllable", marks[cut]))
                for piece in range(cut, end, step):
                    await audio_queue.put(("audio", pcm[piece:min(end, piece + step)]))
            return
        marks = SyllableMarks(self.tts.rate, count, plan["clauses"]) if count else None
        started = False
        async for chunk in self.tts.stream(text):
            if not started:                      # counted as said only once its sound exists
                await audio_queue.put(("text", text))
                started = True
            for out in (marks.feed(chunk) if marks else [chunk]):
                await audio_queue.put(("audio", out) if isinstance(out, bytes) else out)
        for out in (marks.flush() if marks else []):
            await audio_queue.put(("audio", out))

    async def _notice(self):
        """A short tone when something failed, so a silent device is never a mystery."""
        try:
            await self.speaker.play(tone(), 24000, lambda level: None, self.on_audio)
        except Exception:
            pass

    async def greet(self):
        """Say the persona's greeting, if it has one."""
        _, greeting = split_persona(self.persona)
        if not greeting:
            return
        reply = Reply("")
        sentences = asyncio.Queue()
        for item in [(greeting, "happy", []), None]:
            await sentences.put(item)
        try:
            await self._speak(sentences, reply)
        except ProviderError as error:
            self.on_event("error", {"message": str(error)})
        finally:
            self._calm_later()
            self.stage.state("idle")
