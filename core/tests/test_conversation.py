"""Tests for the reply pipeline, text splitting, memory, characters and the settings store."""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import conversation, package, speech_text  # noqa: E402
from companion.audio import Detector, Speaker, loudness  # noqa: E402
from companion.characters import Characters, split_persona  # noqa: E402
from companion.memory import Memory  # noqa: E402
from companion.store import Store, redact  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

PERSONA = "# Aria\n\nYou are Aria, cheerful and brief.\n\n## Greeting\n\nHi! I'm Aria.\n"


def run(coro):
    return asyncio.run(coro)


class SplitterTest(unittest.TestCase):
    def pieces(self, text, size=5):
        s = speech_text.Splitter()
        out = []
        for i in range(0, len(text), size):
            out += s.feed(text[i:i + size])
        return out + s.flush()

    def test_sentences_come_out_as_they_complete(self):
        s = speech_text.Splitter()
        self.assertEqual(s.feed("Hello there, my friend"), [])
        out = s.feed(". How are")
        self.assertEqual([t for t, _, _ in out], ["Hello there, my friend."])
        self.assertEqual([t for t, _, _ in s.feed(" you? ")], ["How are you?"])

    def test_emotion_and_action_tags_are_taken_out_even_when_split_across_pieces(self):
        out = self.pieces("[happy] That's great news! [timer 5m tea] I set a tea timer for five minutes.", 3)
        self.assertEqual(out[0][1], "happy")
        self.assertNotIn("[", " ".join(t for t, _, _ in out))
        actions = [a for _, _, acts in out for a in acts]
        self.assertEqual(actions, [{"kind": "timer", "seconds": 300, "label": "tea"}])

    def test_short_bits_are_joined_and_markdown_is_dropped(self):
        out = self.pieces("Oh. **Really** nice to meet you. 😀 Bye now.", 4)
        texts = [t for t, _, _ in out]
        self.assertEqual(texts[0], "Oh. Really nice to meet you.")
        self.assertEqual(texts[-1], "Bye now.")

    def test_a_long_first_sentence_is_broken_at_a_comma_to_start_speaking_sooner(self):
        text = "Well, let me think about that for a moment, because it is a rather interesting question, and then I will answer."
        first = self.pieces(text, 200)[0][0]
        self.assertLess(len(first), len(text))
        self.assertTrue(first.endswith(","))

    def test_each_tag_goes_with_the_sentence_it_comes_before_however_the_text_arrives(self):
        text = ("[happy] [wave] Hello! It is lovely to meet you today. [thinking] Let me think about that. "
                "[surprised] Oh, I know! [happy] [nod] Tell me about your day. That is correct. [nod] I agree with you.")
        expected = [("Hello! It is lovely to meet you today.", "happy", ["wave"]),
                    ("Let me think about that.", "thinking", []),
                    ("Oh, I know!", "surprised", []),
                    ("Tell me about your day.", "happy", ["nod"]),
                    ("That is correct.", None, []),
                    ("I agree with you.", None, ["nod"])]
        for size in (1, 3, 7, 40, len(text)):
            got = [(t, e, [a["name"] for a in acts]) for t, e, acts in self.pieces(text, size)]
            self.assertEqual(got, expected, "pieces of %d characters" % size)

    def test_stage_directions_the_model_invents_become_feelings_or_gestures_or_go_unsaid(self):
        text = ("*giggles softly* You're silly, you know. That was *really* good. [smile] I mean it! *waves* "
                "[pause] Okay then. [citation needed] Saturn has rings [1]. *puts hands on hips* Fine, fine!")
        expected = [("You're silly, you know.", None, ["laugh"]),
                    ("That was really good.", None, []),
                    ("I mean it! Okay then.", "happy", ["wave"]),
                    ("Saturn has rings.", None, []),
                    ("Fine, fine!", None, ["hands_on_hips"])]
        for size in (1, 4, len(text)):
            got = [(t, e, [a["name"] for a in acts]) for t, e, acts in self.pieces(text, size)]
            self.assertEqual(got, expected, "pieces of %d characters" % size)
        self.assertEqual(self.pieces("That is **very** important.", 3), [("That is very important.", None, [])])

    def test_tags_written_other_ways_and_emoji_still_count(self):
        text = ("[Emotion: Happy!] Hello there! (smiles) Nice to see you. <sad> I missed you (a lot, honestly). "
                "[mood: thinking] Let me see what we can do... (waves) Bye for now! That is great 🎉")
        out = [(t, e, [a["name"] for a in acts]) for t, e, acts in self.pieces(text, 4)]
        self.assertEqual(out, [("Hello there!", "happy", []), ("Nice to see you.", "happy", []),
                               ("I missed you (a lot, honestly).", "sad", []),
                               ("Let me see what we can do...", "thinking", []),
                               ("Bye for now!", None, ["wave"]),
                               ("That is great", "happy", [])])

    def test_other_words_for_feelings_count_and_stressed_words_are_still_said(self):
        text = ("[joyful] What a day! *nervously* Um, hi there. <Angrily> Stop that right now! "
                "I'm *glad* you came, honestly. Let's *pause* here. *sighs* Okay, fine. (thoughtfully) I wonder.")
        out = [(t, e, [a["name"] for a in acts]) for t, e, acts in self.pieces(text, 5)]
        self.assertEqual(out, [("What a day!", "happy", []), ("Um, hi there.", "embarrassed", []),
                               ("Stop that right now!", "angry", []),
                               ("I'm glad you came, honestly.", None, []), ("Let's pause here.", None, []),
                               ("Okay, fine.", None, ["sigh"]), ("I wonder.", "thinking", [])])

    def test_tags_at_the_very_end_are_kept(self):
        out = self.pieces("All done now, thank you. [happy] [bow]", 6)
        self.assertEqual(out[-1], ("", "happy", [{"kind": "gesture", "name": "bow"}]))

    def test_tags(self):
        self.assertEqual(speech_text.parse_tag("alarm 7:05 wake up"), ("action", {"kind": "alarm", "time": "07:05", "label": "wake up"}))
        self.assertEqual(speech_text.parse_tag("timer 1h30m bread"), ("action", {"kind": "timer", "seconds": 5400, "label": "bread"}))
        self.assertIsNone(speech_text.parse_tag("alarm 25:00"))
        self.assertIsNone(speech_text.parse_tag("not a tag"))
        self.assertEqual(speech_text.parse_tag("sad"), ("emotion", "sad"))


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.memory = Memory(os.path.join(self.dir.name, "memory"))
        self.stage = FakeStage()
        self.events, self.actions = [], []

    def tearDown(self):
        self.dir.cleanup()

    def make(self, llm=None, tts=None):
        return conversation.Conversation(
            llm=llm or FakeLLM("[happy] Hello there. How are you today? [timer 2m eggs] Your egg timer is set."),
            tts=tts or FakeTTS(), speaker=Speaker(command=None, realtime=False), stage=self.stage,
            memory=self.memory, persona=PERSONA,
            on_event=lambda k, d: self.events.append((k, d)), on_action=self.actions.append)

    def test_a_streamed_voices_later_sentences_are_held_back_to_place_their_syllables(self):
        placed = []
        original = conversation.syllable_offsets
        conversation.syllable_offsets = lambda pcm, rate, timing: placed.append(len(pcm)) or original(pcm, rate, timing)
        try:
            tts = FakeTTS(seconds_per_char=0.03)
            conv = conversation.Conversation(
                llm=FakeLLM("This first sentence plays while the next one comes. And this second one is held back."),
                tts=tts, speaker=Speaker(command=None, realtime=True, latency=0.0), stage=self.stage,
                memory=self.memory, persona=PERSONA)
            reply = run(conv.respond("hi"))
        finally:
            conversation.syllable_offsets = original
        self.assertIsNone(reply.error)
        self.assertEqual(len(placed), 1, "the first sentence streams; the second was all there in time, so placed whole")
        second = int(tts.rate * tts.seconds_per_char * len("And this second one is held back.")) * 2
        self.assertEqual(placed[0], second)
        marks = [c["syllable"] for c in self.stage.commands if "syllable" in c]
        self.assertGreater(len(marks), 10, "both sentences' syllables were marked")

    def test_a_voice_too_slow_to_wait_for_streams_on_and_nothing_is_lost(self):
        class SlowSecondTTS(FakeTTS):
            async def stream(self, text):
                slow = bool(self.texts)              # the first sentence comes at once, the second slowly
                async for chunk in super().stream(text):
                    if slow:
                        await asyncio.sleep(0.15)
                    yield chunk

        heard, placed = [], []
        original = conversation.syllable_offsets
        conversation.syllable_offsets = lambda pcm, rate, timing: placed.append(len(pcm)) or original(pcm, rate, timing)
        tts = SlowSecondTTS(seconds_per_char=0.01)
        conv = conversation.Conversation(
            llm=FakeLLM("A first sentence that is long enough to keep the voice busy for a while. "
                        "Then a much longer second sentence that the voice is very slow to make, chunk by chunk."),
            tts=tts, speaker=Speaker(command=None, realtime=True, latency=0.0), stage=self.stage,
            memory=self.memory, persona=PERSONA, on_audio=heard.append)
        try:
            reply = run(conv.respond("hi"))
        finally:
            conversation.syllable_offsets = original
        self.assertIsNone(reply.error)
        self.assertEqual(placed, [], "it waited, the sound was not all there in time, so it streamed on")
        expected = sum(int(tts.rate * tts.seconds_per_char * len(t)) * 2 for t in tts.texts)
        played = sum(len(f) for f in heard)
        self.assertLess(abs(played - expected), 2 * int(tts.rate * 0.02) * 2, "every bit of sound was played")

    def test_a_reply_is_spoken_sentence_by_sentence_with_mouth_movement(self):
        conv = self.make()
        reply = run(conv.respond("hi"))
        self.assertIsNone(reply.error)
        self.assertEqual(reply.spoken, ["Hello there.", "How are you today?", "Your egg timer is set."])
        self.assertEqual(self.stage.states()[0], "thinking")
        self.assertIn("speaking", self.stage.states())
        self.assertEqual(self.stage.states()[-1], "idle")
        levels = [c["mouth"] for c in self.stage.commands if "mouth" in c]
        self.assertGreater(max(levels), 0.3, "the mouth opens with the voice")
        self.assertEqual(levels[-1], 0.0, "and closes at the end")
        self.assertIn({"express": "happy"}, self.stage.commands)
        self.assertEqual(self.actions, [{"kind": "timer", "seconds": 120, "label": "eggs"}])
        self.assertEqual(self.memory.history()[-1]["reply"], "Hello there. How are you today? Your egg timer is set.")

    def test_the_model_gets_the_persona_rules_memory_and_history(self):
        self.memory.set_notes("- Likes tea\n")
        self.memory.add_turn("earlier question", "earlier answer")
        llm = FakeLLM("Sure.")
        run(self.make(llm=llm).respond("and now?"))
        system, messages = llm.calls[0]
        self.assertIn("You are Aria", system)
        self.assertNotIn("Hi! I'm Aria", system, "the greeting is not part of the instructions")
        self.assertIn("Likes tea", system)
        self.assertIn("[timer", system)
        self.assertEqual(messages[-3:], [{"role": "user", "content": "earlier question"},
                                         {"role": "assistant", "content": "earlier answer"},
                                         {"role": "user", "content": "and now?"}])

    def test_the_model_is_reminded_of_earlier_conversations_that_match(self):
        day = 86400
        now = 1_800_000_000
        self.memory.add_episode(1, now - 90 * day, "They told me about their sourdough starter, Bubbles, and how it keeps dying.")
        self.memory.add_episode(2, now - 30 * day, "We talked about Saturn's rings; they want a telescope for their birthday.")
        self.memory.add_episode(3, now - 1 * day, "They had a rough day at work and wanted to vent about their boss.")
        llm = FakeLLM("Sure.")
        run(self.make(llm=llm).respond("I finally baked bread with my starter!"))
        system = llm.calls[0][0]
        self.assertIn("From earlier conversations", system)
        self.assertIn("sourdough starter", system, "the matching conversation is recalled")
        self.assertIn("rough day at work", system, "and the most recent one")
        self.assertNotIn("Saturn", system, "but not the others")
        self.assertLess(system.index("sourdough"), system.index("rough day"), "oldest first")

    def certain_planner(self, conv):
        import random as rnd
        from companion.performance import Planner
        conv.planner = Planner(rnd.Random(2), expressiveness=10.0)      # every rule that applies fires
        return conv

    def test_a_reply_without_tags_still_shows_a_feeling_and_moves_with_its_words(self):
        conv = self.certain_planner(self.make(llm=FakeLLM("That's wonderful news, congratulations! Do you want to celebrate?")))
        reply = run(conv.respond("I got the job!"))
        self.assertIsNone(reply.error)
        self.assertIn({"express": "happy"}, self.stage.commands, "the feeling is guessed from the words")
        performs = [c["perform"] for c in self.stage.commands if "perform" in c]
        self.assertEqual(len(performs), len(reply.spoken), "every sentence gets mouth shapes")
        self.assertTrue(all(set(p["syllables"]) <= set("aeiou") and p["syllables"] for p in performs))
        self.assertIn("tilt", [e[1] for p in performs for e in p["events"]], "a question tilts the head")
        marks = [c["syllable"] for c in self.stage.commands if "syllable" in c]
        self.assertTrue(marks, "syllables are marked in the sound")

    def test_a_feeling_the_model_tagged_is_not_second_guessed(self):
        conv = self.make(llm=FakeLLM("[sad] I lost my keys today. Congratulations, wonderful, amazing!"))
        run(conv.respond("hi"))
        feelings = [c["express"] for c in self.stage.commands if "express" in c and c["express"] != "neutral"]
        self.assertEqual(feelings, ["sad"])

    def test_if_planning_fails_the_character_still_talks(self):
        conv = self.make(llm=FakeLLM("Hello there. How are you today?"))

        def broken(*args, **kwargs):
            raise RuntimeError("planner bug")
        conv.planner.plan = broken
        reply = run(conv.respond("hi"))
        self.assertIsNone(reply.error)
        self.assertEqual(reply.spoken, ["Hello there.", "How are you today?"])
        self.assertFalse(any("perform" in c for c in self.stage.commands))
        self.assertGreater(max(c["mouth"] for c in self.stage.commands if "mouth" in c), 0.3, "the mouth still moves")

    def test_an_interruption_stops_speech_and_remembers_what_was_said(self):
        async def scenario():
            conv = self.make(llm=FakeLLM("One two three four five. Six seven eight nine ten. Eleven twelve.", delay=0.01),
                             tts=FakeTTS(seconds_per_char=0.02))
            conv.speaker.realtime = True
            task = conv.start("count")
            while not any(k == "saying" for k, _ in self.events):
                await asyncio.sleep(0.01)
            conv.interrupt()
            return await task
        reply = run(scenario())
        self.assertTrue(reply.interrupted)
        turn = self.memory.history()[-1]
        self.assertTrue(turn["interrupted"])
        self.assertTrue(turn["reply"].startswith("One two"))
        self.assertNotIn("Eleven", turn["reply"])
        self.assertEqual(self.stage.states()[-1], "idle")

    def test_a_model_failure_is_reported_and_the_character_returns_to_rest(self):
        reply = run(self.make(llm=FakeLLM(fail="start")).respond("hi"))
        self.assertIn("fake model failed", reply.error)
        self.assertTrue(any(k == "error" for k, _ in self.events))
        self.assertEqual(self.stage.states()[-1], "idle")
        self.assertEqual(self.memory.history(), [], "nothing was said, so nothing is remembered")

    def test_a_voice_failure_part_way_keeps_what_was_said(self):
        reply = run(self.make(tts=FakeTTS(fail_on="today")).respond("hi"))
        self.assertIn("fake voice failed", reply.error)
        self.assertEqual(reply.spoken, ["Hello there."])

    def test_a_silent_model_times_out(self):
        old = conversation.FIRST_WORDS_TIMEOUT
        conversation.FIRST_WORDS_TIMEOUT = 0.2
        try:
            reply = run(self.make(llm=FakeLLM(hang=True)).respond("hi"))
        finally:
            conversation.FIRST_WORDS_TIMEOUT = old
        self.assertIn("did not answer", reply.error)

    def test_a_search_request_is_answered_from_the_results(self):
        llm = FakeLLM(["[thinking] Let me check that for you. [search weather in Brisbane]",
                       "It is sunny and twenty five degrees in Brisbane."])
        searched = []

        async def search(query):
            searched.append(query)
            return [{"title": "Brisbane weather", "url": "https://example.com", "content": "Sunny, 25 C."}]

        conv = self.make(llm=llm)
        conv.search = search
        reply = run(conv.respond("what's the weather?"))
        self.assertIsNone(reply.error)
        self.assertEqual(searched, ["weather in Brisbane"])
        self.assertEqual(reply.spoken, ["Let me check that for you.", "It is sunny and twenty five degrees in Brisbane."])
        system, messages = llm.calls[1]
        self.assertIn("Sunny, 25 C.", messages[-1]["content"])
        self.assertIn("[search", llm.calls[0][0], "the model is told how to search")
        self.assertTrue(any(k == "searching" for k, _ in self.events))
        self.assertIn("Brisbane", self.memory.history()[-1]["reply"])

    def test_without_search_the_tag_is_dropped_and_not_mentioned(self):
        llm = FakeLLM("I can't look that up right now. [search something]")
        reply = run(self.make(llm=llm).respond("look it up"))
        self.assertEqual(reply.spoken, ["I can't look that up right now."])
        self.assertEqual(len(llm.calls), 1)
        self.assertNotIn("[search", llm.calls[0][0])

    def test_claude_gets_its_own_web_search_tool_when_enabled(self):
        from companion.anthropic_llm import AnthropicLLM, WEB_SEARCH_TOOL
        on = AnthropicLLM("test-key", web_search=True)._request("sys", [{"role": "user", "content": "hi"}])
        off = AnthropicLLM("test-key", web_search=False)._request("sys", [{"role": "user", "content": "hi"}])
        self.assertEqual(on["tools"], [WEB_SEARCH_TOOL])
        self.assertNotIn("tools", off)
        self.assertEqual(on["model"], "claude-opus-5-5")
        self.assertEqual(on["fallbacks"], "default")
        self.assertNotIn("temperature", on)
        greeting_first = AnthropicLLM("test-key")._request("sys", [{"role": "assistant", "content": "Hi!"},
                                                                   {"role": "user", "content": "hello"}])
        self.assertEqual(greeting_first["messages"][0]["role"], "user", "a conversation must start with the person")

    def test_gestures_play_with_the_sentence_they_belong_to(self):
        llm = FakeLLM("[nod] Yes, that's right. [embarrassed] [tilt] Oh, you noticed?")
        run(self.make(llm=llm).respond("is it?"))
        cmds = self.stage.commands
        self.assertIn({"gesture": "nod"}, cmds)
        self.assertIn({"gesture": "tilt"}, cmds)
        self.assertIn({"express": "embarrassed"}, cmds)
        self.assertEqual(self.actions, [], "gestures are not timers or alarms")

    def test_the_stage_link_names_moods_and_only_gestures_the_character_has(self):
        from companion.stage_link import StageLink

        class Capture(StageLink):
            def __init__(self):
                super().__init__("/nonexistent")
                self.sent = []

            def send(self, command):
                self.sent.append(command)
                return True

        link = Capture()
        link.gestures = ["nod", "tilt"]          # as a head-only character's stage reports
        link.express("happy", 0.8)
        link.express("happy", 0.8)               # no change, nothing sent
        self.assertTrue(link.gesture("nod"))
        self.assertFalse(link.gesture("wave"), "a gesture this character cannot make is not sent")
        link.random_gestures(False)
        self.assertEqual(link.sent, [{"emotion": "happy", "intensity": 0.8}, {"gesture": "nod", "intensity": 1.0},
                                     {"random_gestures": False}])
        link.sent.clear()
        link.clock(23.5)
        link.poke()
        link.heard(1.7)
        self.assertEqual(link.sent, [{"clock": 23.5}, {"poke": True}, {"heard": 1.0}])
        # A character with its own expressions shows the mapped one with the emotion, and none otherwise.
        link.sent.clear()
        link.emotion_map = {"sad": "F03"}
        link.express("sad")
        link.express("angry")
        self.assertEqual(link.sent, [{"emotion": "sad", "intensity": 1.0, "expression": "F03"},
                                     {"emotion": "angry", "intensity": 1.0, "expression": None}])

    def test_the_model_is_told_only_the_gestures_its_character_can_make(self):
        from companion.conversation import system_prompt
        prompt = system_prompt("You are Aria.", "", gestures=["nod", "wave"])
        self.assertIn("[nod]", prompt)
        self.assertIn("[wave] wave", prompt)
        self.assertNotIn("[hands_on_hips]", prompt)
        self.assertNotIn("move with these tags", system_prompt("You are Aria.", "", gestures=[]))

    def test_every_library_gesture_can_be_asked_for(self):
        import json
        from companion.speech_text import GESTURES, parse_tag
        path = os.path.join(os.path.dirname(__file__), "..", "..", "stage", "motions", "library.json")
        with open(path, encoding="utf-8") as f:
            library = json.load(f)
        self.assertEqual(sorted(GESTURES), sorted(library["gestures"]), "the core and the stage name the same gestures")
        self.assertEqual(parse_tag("hands_on_hips"), ("action", {"kind": "gesture", "name": "hands_on_hips"}))
        for emotion in ("happy", "sad", "angry", "surprised", "embarrassed", "thinking", "neutral"):
            self.assertIn(emotion, library["moods"])

    def test_a_feeling_stays_a_little_after_the_reply_then_calms(self):
        async def go():
            conv = self.make(llm=FakeLLM("[happy] That is wonderful news, well done!"))
            conv.mood_linger = 0.1
            await conv.respond("I passed my exam")
            right_after = list(self.stage.commands)
            await asyncio.sleep(0.2)
            return right_after, list(self.stage.commands)
        right_after, later = run(go())
        self.assertIn({"express": "happy"}, right_after)
        self.assertNotIn({"express": "neutral"}, right_after, "the feeling does not snap away when speech ends")
        self.assertEqual(later[-1], {"express": "neutral"})

    def test_the_greeting_is_spoken(self):
        tts = FakeTTS()
        run(self.make(tts=tts).greet())
        self.assertEqual(tts.texts, ["Hi! I'm Aria."])


class PersonaFormTest(unittest.TestCase):
    def test_answers_become_a_persona_with_a_greeting(self):
        from companion import persona
        from companion.characters import split_persona
        text = persona.build({"name": "Mika", "personality": "Cheerful.", "story": "Grew up near an observatory.",
                              "relationship": "Your old friend.", "likes": "stars", "dislikes": "spiders",
                              "speaking": "Warm and playful.", "never": "Never gives medical advice.",
                              "greeting": "Hi there!"})
        body, greeting = split_persona(text)
        self.assertEqual(greeting, "Hi there!")
        self.assertTrue(body.startswith("# Mika"))
        for words in ("You are Mika", "Cheerful.", "## Your story", "You like: stars", "You dislike: spiders",
                      "Warm and playful.", "spoken aloud", "## Never"):
            self.assertIn(words, body)

    def test_empty_answers_are_left_out(self):
        from companion import persona
        text = persona.build({"name": "Mika"})
        self.assertNotIn("## Your story", text)
        self.assertNotIn("## Greeting", text)
        self.assertIn("## How you speak", text, "the spoken-reply rule is always there")


class AudioTest(unittest.TestCase):
    def test_loudness(self):
        import array
        self.assertEqual(loudness(b"\0\0" * 320), 0.0)
        loud = array.array("h", [20000, -20000] * 160).tobytes()
        self.assertEqual(loudness(loud), 1.0)

    def test_the_detector_finds_one_utterance_in_noise(self):
        import array
        import random
        rng = random.Random(1)
        quiet = lambda: array.array("h", (rng.randint(-60, 60) for _ in range(320))).tobytes()
        voice = lambda: array.array("h", (rng.randint(-6000, 6000) for _ in range(320))).tobytes()
        d = Detector(end_silence=0.4)
        frames = [quiet() for _ in range(50)] + [voice() for _ in range(40)] + [quiet() for _ in range(40)]
        found = [pcm for pcm in (d.feed(f) for f in frames) if pcm]
        self.assertEqual(len(found), 1)
        seconds = len(found[0]) / 2 / 16000
        self.assertTrue(0.8 <= seconds <= 1.4, seconds)


class MemoryTest(unittest.TestCase):
    def test_notes_are_updated_by_the_model_and_editable(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_turn("My cat is called Miso.", "What a lovely name!")
            llm = FakeLLM("- Has a cat called Miso\n- Likes mornings\nnot a note\nEPISODE: They told me about their cat, Miso.")
            count = run(m.update_notes(llm))
            self.assertEqual(count, 2)
            self.assertEqual(m.notes(), "- Has a cat called Miso\n- Likes mornings\n")
            self.assertEqual([e["summary"] for e in m.episodes()], ["They told me about their cat, Miso."])
            self.assertIn("Person: My cat is called Miso.", llm.calls[0][1][0]["content"])
            m.set_notes("- Edited by the owner\n")
            self.assertIn("Edited by the owner", m.update_prompt())
            m.clear()
            self.assertEqual((m.notes(), m.history(), m.episodes(), m.turns_since_update), ("", [], [], 0))

    def test_each_turn_is_summed_up_once_even_after_a_restart_or_a_clock_change(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            for i in range(3):
                m.add_turn("question %d" % i, "answer %d" % i)
            self.assertEqual(Memory(d).turns_since_update, 3, "kept on disk")
            run(m.update_notes(FakeLLM("- A note\nEPISODE: The first three questions.")))
            self.assertEqual(Memory(d).turns_since_update, 0)
            from unittest import mock
            with mock.patch("companion.memory.time.time", return_value=1_000_000):   # the clock is wrong
                m.add_turn("question 3", "answer 3")
            self.assertEqual(m.turns_since_update, 1, "turns are numbered, not only timed")
            llm = FakeLLM("- A note\nEPISODE: The fourth question.")
            run(m.update_notes(llm))
            self.assertIn("question 3", llm.calls[0][1][0]["content"])
            self.assertEqual([e["id"] for e in m.episodes()], [3, 4])
            self.assertEqual(run(m.update_notes(llm)), 0, "nothing new, nothing asked")
            self.assertEqual(len(llm.calls), 1)

    def test_one_summary_per_conversation_extended_as_it_goes_on(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)

            def talk(at, *words):
                with mock.patch("companion.memory.time.time", return_value=at):
                    for w in words:
                        m.add_turn(w, "ok")
            start = 1_800_000_000
            talk(start, "my cat Miso is ill", "she sees the vet tomorrow")
            run(m.update_notes(FakeLLM("- Cat Miso is ill\nEPISODE: Their cat Miso is ill.")))
            talk(start + 600, "the vet called back")
            llm = FakeLLM("- Cat Miso is ill\nEPISODE: Their cat Miso is ill; the vet called back with good news.")
            run(m.update_notes(llm))
            prompt = llm.calls[0][1][0]["content"]
            self.assertIn("Earlier in this same conversation (already summed up): Their cat Miso is ill.", prompt)
            self.assertNotIn("she sees the vet tomorrow", prompt, "turns already summed up are not sent again")
            self.assertEqual([(e["id"], e["summary"]) for e in m.episodes()],
                             [(3, "Their cat Miso is ill; the vet called back with good news.")])
            talk(start + 4 * 3600, "guess what, I got the job")
            llm = FakeLLM("- Got a new job\nEPISODE: They got the job they wanted.")
            run(m.update_notes(llm))
            self.assertNotIn("Earlier in this same conversation", llm.calls[0][1][0]["content"])
            self.assertNotIn("Miso", llm.calls[0][1][0]["content"].split("Recent conversation:")[1],
                             "only the new conversation is summed up")
            self.assertEqual([e["id"] for e in m.episodes()], [3, 4], "a later conversation gets its own summary")

    def test_the_summary_line_is_found_however_the_model_dresses_it(self):
        from companion.memory import parse_update
        for line in ("EPISODE: We met.", "**EPISODE:** We met.", "Episode: We met.", "- EPISODE: We met.",
                     "## Episode: We met.", "*Episode*: *We met.*", "  episode : We met."):
            self.assertEqual(parse_update("- A note\n" + line), (["- A note"], "We met."), line)
        self.assertEqual(parse_update("- Episodes of their favourite show are long"),
                         (["- Episodes of their favourite show are long"], ""))

    def test_forgetting_during_an_update_is_not_undone_by_it(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_turn("My secret is X.", "I'll keep it.")

            class ForgetMidway(FakeLLM):
                async def stream(self, system, messages):
                    m.clear()
                    yield "- Their secret is X\nEPISODE: They told me a secret."
            self.assertEqual(run(m.update_notes(ForgetMidway())), 0)
            self.assertEqual((m.notes(), m.episodes()), ("", []))

    def test_summaries_can_be_changed_and_forgotten(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_episode(5, 1_800_000_000, "We talked about   the weather.")
            m.add_episode(9, 1_800_000_100, "We planned a picnic.")
            self.assertEqual(m.episodes()[0]["summary"], "We talked about the weather.")
            self.assertTrue(m.edit_episode(5, "We talked about the storm coming on Friday."))
            self.assertIn("storm", m.recall("Is the storm still coming?")[0]["summary"])
            self.assertTrue(m.delete_episode(5))
            self.assertFalse(m.delete_episode(5))
            self.assertEqual([e["id"] for e in m.episodes()], [9])
            self.assertEqual(m.recall("anything at all"), m.episodes(), "the latest is always recalled")

    def test_recall_prefers_rare_words_and_matches_word_forms(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_episode(1, 1_800_000_000, "They baked cookies for their mum's birthday party.")
            for i in range(2, 8):
                m.add_episode(i, 1_800_000_000 + i, "They talked about work and their weekend plans (%d)." % i)
            m.add_episode(8, 1_800_000_100, "They are learning to play the guitar.")
            m.add_episode(9, 1_800_000_200, "Last chat: a film night.")
            got = [e["id"] for e in m.recall("Do you remember the cookie I baked? Work was busy.", limit=1)]
            self.assertEqual(got, [1, 9], "'cookie' and 'baked' are rarer than 'work'")
            self.assertEqual([e["id"] for e in m.recall("Birthdays and parties!", limit=3)], [1, 9])
            self.assertEqual(len(m.recall("work weekend plans", limit=3)), 4)

    def test_recall_is_quick_with_years_of_summaries(self):
        import random
        import time as clock
        rng = random.Random(3)
        vocabulary = ["word%d" % i for i in range(5000)]
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m._write_episodes([{"id": i, "t": 1_800_000_000 + i, "summary": " ".join(rng.choice(vocabulary) for _ in range(45))}
                               for i in range(1, 3001)])
            m.recall("warm up the index")
            start = clock.perf_counter()
            for _ in range(10):
                m.recall("word12 word345 and word4000 again")
            self.assertLess((clock.perf_counter() - start) / 10, 0.05, "per reply, once the summaries are read")

    def test_dates_in_words(self):
        from companion.memory import when
        import datetime
        now = datetime.datetime(2026, 11, 18, 15, 0).timestamp()
        self.assertEqual(when(now - 3600, now), "today")
        self.assertEqual(when(now - 86400, now), "yesterday")
        self.assertEqual(when(now - 3 * 86400, now), "3 days ago")
        self.assertEqual(when(datetime.datetime(2026, 3, 2, 9, 0).timestamp(), now), "2 March 2026")
        prompt = conversation.system_prompt("You are Aria.", "", now=datetime.datetime(2026, 11, 18, 15, 0),
                                            recalled=[{"t": now - 86400, "summary": "We met."}])
        self.assertIn("- yesterday: We met.", prompt)


class CharactersTest(unittest.TestCase):
    def test_install_list_edit_export_delete(self):
        with tempfile.TemporaryDirectory() as d:
            chars = Characters(d)
            data = package.build(good_files(), manifest())
            cid = chars.install(data)
            self.assertEqual(cid, "aria")
            self.assertEqual(chars.list()[0]["name"], "Aria")
            with self.assertRaises(package.PackageError):
                chars.install(data)
            chars.set_device_settings(cid, {"voice": "voice-123"})
            chars.install(data, replace=True)
            self.assertEqual(chars.device_settings(cid)["voice"], "voice-123", "device choices survive an update")
            chars.set_persona(cid, PERSONA)
            with self.assertRaises(ValueError):
                chars.set_persona(cid, "key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            exported = package.open_package(io.BytesIO(chars.export(cid)))
            self.assertEqual(exported.persona, PERSONA)
            self.assertNotIn("device.json", exported.files)
            chars.delete(cid)
            self.assertEqual(chars.list(), [])

    def test_ids_from_outside_cannot_reach_other_folders(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(KeyError):
                Characters(d).persona("../../etc")

    def test_persona_greeting(self):
        self.assertEqual(split_persona(PERSONA), ("# Aria\n\nYou are Aria, cheerful and brief.", "Hi! I'm Aria."))


class StoreTest(unittest.TestCase):
    def test_keys_are_kept_apart_and_never_returned(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            s.set_secret("openai", "sk-test-1234567890")
            self.assertEqual(s.secret_status()["openai"], True)
            self.assertNotIn("sk-test", json.dumps(s.secret_status()))
            self.assertNotIn("sk-test", json.dumps(s.settings()))
            self.assertEqual(os.stat(s.secrets_path).st_mode & 0o777, 0o600)
            self.assertEqual(redact("failed with sk-test-1234567890 oops", s), "failed with [openai key] oops")
            with self.assertRaises(ValueError):
                s.set_secret("nonsense", "x")
            s.set_secret("openai", "")
            self.assertFalse(s.secret_status()["openai"])

    def test_settings_merge_and_reject_unknown_names(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            s.update_settings({"llm": {"provider": "groq", "model": "m"}})
            self.assertEqual(s.settings()["llm"]["max_tokens"], 400, "defaults kept")
            with self.assertRaises(ValueError):
                s.update_settings({"bogus": 1})

    def test_password(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            self.assertFalse(s.has_password())
            with self.assertRaises(ValueError):
                s.set_password("short")
            s.set_password("correct horse")
            self.assertTrue(s.check_password("correct horse"))
            self.assertFalse(s.check_password("wrong horse"))


if __name__ == "__main__":
    unittest.main()
