"""The character's memory: conversations with clear ends, lasting memories the model keeps up to date,
what the model is given for each reply, the diary, the owner's changes, and memory from the first
version carried over."""
import asyncio
import datetime
import json
import os
import sys
import tempfile
import time as clock
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import memory as mem  # noqa: E402
from companion.memory import Memory, parse_sum_up  # noqa: E402
from fakes import FakeLLM  # noqa: E402


def at(day, hour, minute=0):
    """A local time on a day of November 2026."""
    return datetime.datetime(2026, 11, day, hour, minute).timestamp()


def run(coro):
    return asyncio.run(coro)


SUMMED = """TITLE: Driving nerves
SUMMARY: They were nervous about their driving test on Friday; I told them they would do well.
MOOD: nervous
ADD about them | 5 | Their name is Sam | -
ADD plans and events | 4 | Their driving test is on Friday 20 November | 2026-11-20
FOLLOW UP 2026-11-20 | how the driving test went
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.m = Memory(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def talk(self, when, *pairs):
        for i, (user, reply) in enumerate(pairs):
            self.m.add_turn(user, reply, now=when + 20 * i)


class ConversationsTest(Base):
    def test_a_conversation_ends_after_a_quiet_spell_a_goodbye_a_new_day_or_when_asked(self):
        m = self.m
        first = m.add_turn("hi", "hello", now=at(18, 19, 0))
        self.assertEqual(m.add_turn("still here", "good", now=at(18, 19, 15)), first, "15 minutes on: the same one")
        second = m.add_turn("back again", "welcome back", now=at(18, 19, 50))
        self.assertNotEqual(second, first, "35 quiet minutes ended it")
        self.assertEqual(m.sessions()[-1]["why"], "quiet")
        m.add_turn("ok, bye for now!", "bye!", now=at(18, 20, 0))
        self.assertEqual(m.add_turn("oh, one more thing", "yes?", now=at(18, 20, 2)), second, "words soon after a goodbye carry on")
        m.add_turn("good night", "sleep well", now=at(18, 20, 5))
        third = m.add_turn("can't sleep", "oh no", now=at(18, 20, 10))
        self.assertEqual(m.sessions()[-1]["why"], "goodbye")
        late = m.add_turn("it's late", "it is", now=at(19, 3, 50))
        self.assertNotEqual(late, third)
        self.assertEqual(m.add_turn("still awake", "me too", now=at(19, 3, 58)), late)
        morning = m.add_turn("morning!", "good morning", now=at(19, 4, 5))
        self.assertNotEqual(morning, late, "a pause across 4 am begins a new day's conversation")
        self.assertEqual(m.sessions()[-1]["why"], "new day")
        closed = m.new_conversation()
        self.assertEqual(closed["id"], morning)
        self.assertEqual(m.sessions()[-1]["why"], "started afresh")
        self.assertIsNone(m.open_session())

    def test_a_clock_that_goes_back_neither_ends_the_conversation_nor_muddles_its_turns(self):
        m = self.m
        sid = m.add_turn("hello", "hi", now=at(18, 10))
        self.assertEqual(m.add_turn("the clock jumped back", "oh", now=1_000_000), sid)
        self.assertEqual([t["n"] for t in m.history()], [1, 2], "turns are numbered, not only timed")
        self.assertEqual([t["user"] for t in m.transcript(sid)], ["hello", "the clock jumped back"])

    def test_years_of_conversations_keep_the_latest_summaries_and_every_word(self):
        m = self.m
        with mock.patch.object(mem, "KEEP_SESSIONS", 3):
            ids = [m.add_turn("chat number %d" % day, "ok", now=at(day, 10)) for day in range(1, 7)]
        self.assertEqual([s["id"] for s in m.sessions()], ids[2:5], "the latest summaries (the last one is still going on)")
        self.assertEqual(m.transcript(ids[0])[0]["user"], "chat number 1", "the oldest words stay in the archive")

    def test_every_word_is_kept_and_a_conversation_can_be_forgotten_whole(self):
        m = self.m
        self.talk(at(18, 10), ("my secret is the cake recipe", "I'll keep it"), ("it has cardamom", "lovely"))
        sid = m.history()[-1]["s"]
        self.talk(at(18, 12), ("hello again", "hi"))
        self.assertEqual([t["user"] for t in m.transcript(sid)], ["my secret is the cake recipe", "it has cardamom"])
        self.assertTrue(m.forget_session(sid))
        self.assertEqual(m.transcript(sid), [])
        self.assertNotIn("cardamom", json.dumps(m.history()))
        self.assertFalse(m.forget_session(sid))


class ContextTest(Base):
    def test_within_a_conversation_the_model_gets_it_word_for_word(self):
        self.talk(at(18, 19), ("I adopted a kitten", "How exciting!"), ("her name is Mochi", "What a sweet name"))
        text, messages = self.m.context("she is so tiny", now=at(18, 19, 5))
        self.assertEqual([x["content"] for x in messages],
                         ["I adopted a kitten", "How exciting!", "her name is Mochi", "What a sweet name"])
        self.assertIn("This conversation began 5 minutes ago", text)
        self.assertNotIn("first time you have talked today", text)

    def test_a_new_conversation_begins_with_what_was_said_last_time_not_its_words(self):
        m = self.m
        self.talk(at(16, 20), ("my driving test is on Friday", "You'll be great"))
        diary = "Sam told me about their driving test tonight. I hope they believe in themself as much as I do."
        run(m.process(FakeLLM([SUMMED, diary]), now=at(16, 22)))
        text, messages = m.context("hi!", now=at(18, 9))
        self.assertEqual(messages, [], "last time's words are not passed off as this conversation's")
        self.assertIn("Your last conversation with them was on Monday evening (2 days ago), "
                      "“Driving nerves”: They were nervous about their driving test", text)
        self.assertIn("This is the first time you have talked today", text)
        self.assertIn("From your diary (2026-11-16): Sam told me", text)
        self.assertIn("Their name is Sam", text, "an important memory")
        text, _ = m.context("hi!", now=at(30, 9))
        self.assertIn("on 16 November 2026 (2 weeks ago)", text)
        self.assertNotIn("From your diary", text, "a week-old entry is not news")

    def test_a_conversation_that_ended_minutes_ago_carries_its_last_words_over(self):
        self.talk(at(18, 19), ("let's plan the party", "Yes!"), ("bye for now", "bye"))
        text, messages = self.m.context("I'm back, where were we", now=at(18, 19, 30))
        self.assertEqual(messages, [{"role": "user", "content": "let's plan the party"}, {"role": "assistant", "content": "Yes!"},
                                    {"role": "user", "content": "bye for now"}, {"role": "assistant", "content": "bye"}])
        self.assertIn("Your last conversation with them was 30 minutes ago.\nIts last few words are below", text)
        self.assertNotIn("it ended with", text, "not twice")
        text, messages = self.m.context("hello again", now=at(18, 22, 30))
        self.assertEqual(messages, [])
        self.assertIn("this evening (3 hours ago): it ended with:\nPerson: let's plan the party\nYou: Yes!\n"
                      "Person: bye for now\nYou: bye", text, "not summed up yet: how it ended, at least")

    def test_nothing_falls_between_the_summary_and_the_words(self):
        self.talk(at(18, 19), *[("question %d" % i, "answer %d" % i) for i in range(20)])
        _, messages = self.m.context("next", now=at(18, 19, 8), verbatim=12)
        self.assertEqual(len(messages), 40)
        self.assertEqual(messages[0]["content"], "question 0", "not summed up yet, so still word for word")

    def test_memories_that_matter_come_up_and_retired_ones_never(self):
        m = self.m
        m.add_memory("Their name is Sam", "about them", 5)
        m.add_memory("They are allergic to peanuts", "health and wellbeing", 3)
        m.add_memory("Their favourite band is Arctic Monkeys", "likes and dislikes", 2)
        m.add_memory("They like rainy days", "likes and dislikes", 2, pinned=True)
        old = m.add_memory("They work at the bakery", "work and study", 3)
        m.edit_memory(old["id"], status="retired")
        text, _ = m.context("should I put peanuts in the cookies?", now=at(18, 10))
        self.assertIn("Their name is Sam", text, "important")
        self.assertIn("allergic to peanuts", text, "matches what was said")
        self.assertIn("rainy days", text, "pinned")
        self.assertNotIn("Arctic Monkeys", text, "neither important nor relevant now")
        self.assertNotIn("bakery", text, "retired")

    def test_plans_are_followed_up_once_their_day_has_come(self):
        m = self.m
        m.add_memory("how the driving test went", "plans and events", 3, "2026-11-20", follow_up=True)
        text, _ = m.context("hello", now=at(19, 10))
        self.assertNotIn("Plans whose day has come", text, "not before its day")
        for day in (21, 22):
            text, _ = m.context("hello", now=at(day, 10))
            self.assertIn("Plans whose day has come; ask how they went if it fits (just once):\n- how the driving test went", text)
            self.assertEqual(text.count("how the driving test went"), 1, "a question to ask, not a memory")
        text, _ = m.context("hello", now=at(23, 10))
        self.assertNotIn("Plans whose day has come", text, "asked about twice: enough")

    def test_a_dated_plan_comes_up_by_itself_until_they_say_how_it_went(self):
        m = self.m
        plan = m.add_memory("They have a job interview at the library", "plans and events", 4, "2026-11-20", now=at(16, 10))
        text, _ = m.context("hello", now=at(20, 9))
        self.assertNotIn("Plans whose day has come", text, "not on the day itself: it may not have happened yet")
        self.assertIn("- [plans and events] They have a job interview at the library (Friday 20 November 2026, today)", text)
        text, _ = m.context("hello", now=at(21, 9))
        self.assertIn("Plans whose day has come; ask how they went if it fits (just once):\n"
                      "- They have a job interview at the library \u2014 Friday 20 November 2026, yesterday", text)
        self.assertEqual(text.count("job interview"), 1, "asked about, not listed twice")
        m.edit_memory(plan["id"], text="They got the job at the library", now=at(21, 18))
        text, _ = m.context("hello", now=at(22, 9))
        self.assertNotIn("Plans whose day has come", text, "they said how it went")

    def test_a_small_model_gets_less_but_never_loses_the_latest_words(self):
        m = self.m
        for i in range(60):
            m.add_memory("They collect stamp number %d from a different country of the world" % i, "likes and dislikes", 4)
        self.talk(at(18, 10), *[("question %d about something long " % i + "x" * 200, "answer %d " % i + "y" * 200) for i in range(10)])
        text, messages = m.context("question 11", now=at(18, 10, 5), room=3000)
        self.assertLessEqual(len(text), 1000)
        self.assertGreaterEqual(len(messages), 2)
        self.assertEqual(messages[-1]["content"].split()[:2], ["answer", "9"], "the newest exchange is always there")

    def test_quick_with_years_of_conversations(self):
        m = self.m
        sessions = [{"id": i, "start": at(1, 10) - i * 3600, "end": at(1, 10) - i * 3600 + 600, "first": i, "last": i,
                     "turns": 1, "why": "quiet", "title": "Chat %d" % i, "summary": "We talked about topic%d and topic%d." % (i, i * 7),
                     "mood": "", "done": True} for i in range(3000, 0, -1)]
        mem._write_jsonl(m.sessions_path, sessions)
        for i in range(500):
            m.add_memory("Fact number %d about hobby%d" % (i, i), "other", 3)
        m.context("warm up")
        start = clock.perf_counter()
        for _ in range(5):
            m.context("tell me about topic77 and hobby12")
        self.assertLess((clock.perf_counter() - start) / 5, 0.25)


class ProcessTest(Base):
    def test_a_conversation_that_is_over_is_summed_up_and_its_memories_kept(self):
        m = self.m
        self.talk(at(16, 20), ("I'm Sam, my driving test is on Friday", "You'll be great, Sam"))
        llm = FakeLLM(SUMMED)
        self.assertTrue(m.needs_work(now=at(16, 21)))
        done = run(m.process(llm, now=at(16, 21), name="Aria"))
        self.assertEqual(done["summed"], 1)
        session = m.sessions()[-1]
        self.assertEqual((session["title"], session["mood"], session["done"]), ("Driving nerves", "nervous", True))
        texts = {x["text"]: x for x in m.memories()}
        self.assertEqual(texts["Their name is Sam"]["importance"], 5)
        self.assertEqual(texts["Their driving test is on Friday 20 November"]["when"], "2026-11-20")
        self.assertTrue(texts["how the driving test went"]["follow_up"])
        prompt = llm.calls[0][1][0]["content"]
        self.assertIn("Person: I'm Sam, my driving test is on Friday", prompt)
        self.assertIn("Aria", prompt)
        self.assertFalse(m.needs_work(now=at(16, 21, 5)))

    def test_what_was_said_wins_over_what_was_remembered(self):
        m = self.m
        cats = m.add_memory("They have one cat, Miso", "about them", 3)
        job = m.add_memory("They work at the bakery", "work and study", 3)
        untouched = m.add_memory("They live in Brisbane", "about them", 4)
        self.talk(at(17, 18), ("we adopted a second cat, Tofu! and I quit the bakery", "Congratulations!"))
        run(m.process(FakeLLM("TITLE: News\nSUMMARY: New cat, new job hunt.\nMOOD: happy\n"
                              "UPDATE #%d | They have two cats, Miso and Tofu\nFORGET #%d | they quit\n"
                              "UPDATE #999 | something it was never shown" % (cats["id"], job["id"])), now=at(17, 19)))
        texts = [x["text"] for x in m.memories()]
        self.assertIn("They have two cats, Miso and Tofu", texts)
        self.assertNotIn("They work at the bakery", texts)
        self.assertIn("They live in Brisbane", texts)
        self.assertTrue(any(x["id"] == job["id"] and x["status"] == "retired" for x in m.memories(everything=True)))
        self.assertEqual(untouched["text"], "They live in Brisbane")

    def test_the_model_is_asked_to_update_plans_whose_day_has_come(self):
        m = self.m
        plan = m.add_memory("They have a driving test", "plans and events", 4, "2026-11-13", now=at(9, 19))
        self.talk(at(14, 10), ("I passed my driving test!", "Congratulations!"))
        llm = FakeLLM("TITLE: Passed\nSUMMARY: They passed.\nMOOD: proud\n"
                      "UPDATE #%d plans and events: They passed their driving test | 2026-11-13" % plan["id"])
        run(m.process(llm, now=at(14, 11)))
        prompt = llm.calls[0][1][0]["content"]
        self.assertIn("#%d [plans and events] They have a driving test (2026-11-13)" % plan["id"], prompt)
        self.assertIn("Plans above whose day has come: #%d." % plan["id"], prompt)
        self.assertEqual([(x["text"], x["when"]) for x in m.memories()], [("They passed their driving test", "2026-11-13")])
        self.assertEqual(m.follow_ups(now=at(15, 9)), [], "nothing left to ask")

    def test_the_early_part_of_a_long_conversation_is_summed_up_as_it_goes(self):
        m = self.m
        self.talk(at(18, 19), *[("question %d" % i, "answer %d" % i) for i in range(30)])
        llm = FakeLLM("Summary: They asked thirty questions about the stars.")
        self.assertTrue(m.needs_work(now=at(18, 19, 12)))
        run(m.process(llm, now=at(18, 19, 12)))
        session = m.open_session()
        self.assertEqual(session["rolling"], "They asked thirty questions about the stars.")
        text, messages = m.context("one more", now=at(18, 19, 13))
        self.assertIn("Earlier in it: They asked thirty questions about the stars.", text)
        self.assertEqual(messages[0]["content"], "question 18", "only the latest turns word for word")
        self.assertNotIn("question 3\n", llm.calls[0][1][0]["content"].split("since")[0])

    def test_the_owners_choice_of_how_much_is_word_for_word_is_kept(self):
        m = self.m
        self.talk(at(18, 19), *[("question %d" % i, "answer %d" % i) for i in range(19)])
        self.assertFalse(m.needs_work(now=at(18, 19, 7), keep=12))
        self.assertTrue(m.needs_work(now=at(18, 19, 7), keep=6))
        run(m.process(FakeLLM("They asked questions 0 to 12."), now=at(18, 19, 7), keep=6))
        text, messages = m.context("next", now=at(18, 19, 8), verbatim=6)
        self.assertEqual([x["content"] for x in messages[::2]], ["question %d" % i for i in range(13, 19)])
        self.assertIn("Earlier in it: They asked questions 0 to 12.", text)

    def test_the_diary_is_written_once_a_day_in_the_characters_voice(self):
        m = self.m
        self.talk(at(18, 9), ("good morning!", "Morning!"))
        self.talk(at(18, 19), ("I passed my driving test!", "I'm so proud of you!"))
        summaries = ["TITLE: Morning\nSUMMARY: A quick good morning.\nMOOD: sleepy",
                     "TITLE: Passed!\nSUMMARY: They passed their driving test.\nMOOD: thrilled",
                     "What a day. This morning they were sleepy, and tonight they told me they passed their "
                     "driving test! I felt so proud of them."]
        llm = FakeLLM(summaries)
        run(m.process(llm, now=at(18, 20)))
        self.assertEqual(m.diary(), [], "not before it is late and quiet")
        run(m.process(llm, now=at(18, 22)))
        self.assertEqual([d["day"] for d in m.diary()], ["2026-11-18"])
        self.assertIn("proud of them", m.diary()[0]["text"])
        prompt = llm.calls[-1][1][0]["content"]
        self.assertIn("Passed!", prompt)
        self.assertIn("your own voice", prompt)
        run(m.process(llm, now=at(19, 9)))
        self.assertEqual(len(m.diary()), 1, "once a day")
        text, _ = m.context("good morning", now=at(19, 9, 30))
        self.assertIn("From your diary (2026-11-18)", text)

    def test_a_model_that_ignores_the_form_still_leaves_a_summary(self):
        m = self.m
        self.talk(at(18, 10), ("I planted tomatoes and basil today", "Lovely! A summer garden."))
        self.talk(at(18, 12), ("the basil is already sprouting", "Fast!"))
        run(m.process(FakeLLM(["They told me about planting tomatoes and basil in their garden.", ""]), now=at(18, 13)))
        self.assertEqual([s["summary"] for s in m.sessions()],
                         ["They told me about planting tomatoes and basil in their garden.",
                          "They said: the basil is already sprouting"], "a plain answer, or their own words")
        self.assertTrue(all(s["done"] for s in m.sessions()))

    def test_an_update_of_a_memory_it_was_never_shown_is_something_new(self):
        m = self.m
        self.talk(at(9, 19), ("my sister Kim is flying in from Perth", "How lovely!"))
        run(m.process(FakeLLM("TITLE: Kim\nSUMMARY: Kim is coming.\nMOOD: happy\n"
                              "UPDATE #1 | Their sister Kim is flying in from Perth for the driving test | 2026-11-13"), now=at(9, 20)))
        self.assertEqual([(x["text"], x["category"], x.get("when")) for x in m.memories()],
                         [("Their sister Kim is flying in from Perth for the driving test", "their people", "2026-11-13")])

    def test_a_model_stuck_in_a_loop_adds_only_so_much(self):
        m = self.m
        self.talk(at(18, 10), ("my sister moved to Darwin", "Oh wow!"))
        lines = "\n".join("ADD their people | 2 | They mentioned fact number %s about Darwin" % w for w in
                          ("one two three four five six seven eight nine ten eleven twelve".split()))
        run(m.process(FakeLLM("TITLE: Darwin\nSUMMARY: Kim moved.\nMOOD: sad\n" + lines), now=at(18, 11)))
        self.assertEqual(len(m.memories()), mem.MAX_CHANGES)

    def test_forgetting_meanwhile_is_not_undone(self):
        m = self.m
        self.talk(at(18, 10), ("my secret is X", "I'll keep it"))

        class ForgetMidway(FakeLLM):
            async def stream(self, system, messages):
                m.clear()
                yield SUMMED
        run(m.process(ForgetMidway(), now=at(18, 11)))
        self.assertEqual((m.sessions(), m.memories(), m.history()), ([], [], []))


class OwnerTest(Base):
    def test_the_owner_can_add_change_pin_and_forget_memories(self):
        m = self.m
        e = m.add_memory("Their sister Kim lives in Perth", "their people")
        self.assertEqual(m.add_memory("Their sister Kim lives in Perth now", "their people")["id"], e["id"], "nearly the same: one memory")
        self.assertTrue(m.edit_memory(e["id"], pinned=True, importance=4))
        self.assertTrue(m.memories()[0]["pinned"])
        self.assertTrue(m.edit_memory(e["id"], text="Their sister Kim moved to Darwin"))
        self.assertEqual(m.memories()[0]["text"], "Their sister Kim moved to Darwin")
        self.assertFalse(m.edit_memory(e["id"], text="x"))
        self.assertTrue(m.forget_memory(e["id"]))
        self.assertEqual(m.memories(), [])
        self.assertIsNone(m.add_memory("  ", "other"))

    def test_the_owners_notes_and_edits_stand(self):
        m = self.m
        m.set_notes("Call me Sam. I'm vegetarian.")
        self.talk(at(18, 10), ("hi", "hello"))
        run(m.process(FakeLLM(SUMMED), now=at(18, 11)))
        self.assertEqual(m.notes(), "Call me Sam. I'm vegetarian.", "the model never changes the owner's notes")
        sid = m.sessions()[-1]["id"]
        self.assertTrue(m.edit_session(sid, summary="We said hello."))
        self.assertEqual(m.sessions()[-1]["summary"], "We said hello.")
        text, _ = m.context("hello", now=at(19, 10))
        self.assertIn("What they asked you always to remember:\nCall me Sam. I'm vegetarian.", text)

    def test_memories_are_kept_within_reason(self):
        m = self.m

        def name(i):
            return "".join("bcdfghjklmnprstvwz"[int(d)] for d in "%03d" % i).capitalize() + "ava"

        with mock.patch.object(mem, "KEEP_MEMORIES", 40):
            m.add_memory("A pinned one about the garden", "other", 1, pinned=True)
            for i in range(60):
                m.add_memory("Their friend %s plays %s" % (name(i), name(i + 500)), "their people", 1 + i % 5)
            active = m.memories()
        self.assertEqual(len(active), 40)
        self.assertTrue(any(x.get("pinned") for x in active), "pinned ones stay")
        kept = [x["importance"] for x in active if not x.get("pinned")]
        self.assertEqual((kept.count(1), kept.count(2), kept.count(3) + kept.count(4) + kept.count(5)), (0, 3, 36),
                         "the least important went first")


class RecallTest(Base):
    def sessions(self, *summaries):
        mem._write_jsonl(self.m.sessions_path, [{"id": i, "start": at(1, 10) + i * 60, "end": at(1, 10) + i * 60 + 30,
                                                 "title": "", "summary": s, "done": True} for i, s in enumerate(summaries, 1)])

    def test_rare_words_count_for_more_and_word_forms_match(self):
        self.sessions("They baked cookies for their mum's birthday party.",
                      *["They talked about work and their weekend plans (%d)." % i for i in range(2, 8)],
                      "They are learning to play the guitar.", "Last chat: a film night.")
        got = [s["id"] for s in self.m.recall("Do you remember the cookie I baked? Work was busy.", limit=1)]
        self.assertEqual(got, [1, 9], "'cookie' and 'baked' are rarer than 'work'; the latest always comes")
        self.assertEqual([s["id"] for s in self.m.recall("Birthdays and parties!", limit=3)], [1, 9])
        self.assertEqual(len(self.m.recall("work weekend plans", limit=3)), 4)

    def test_greetings_and_feelings_do_not_bring_up_old_conversations(self):
        self.sessions("A quick good morning before work.", "They love their new bike.", "We planned a picnic.")
        self.assertEqual([s["id"] for s in self.m.recall("Good morning! I love today", limit=3)], [3])
        self.assertEqual([s["id"] for s in self.m.recall("my bike got a flat tyre", limit=3)], [2, 3])

    def test_an_edited_summary_is_found_by_its_new_words(self):
        self.sessions("We talked about the weather.", "We planned a picnic.")
        self.assertEqual([s["id"] for s in self.m.recall("Is the storm still coming?", limit=1)], [2])
        self.assertTrue(self.m.edit_session(1, summary="We talked about a big storm."))   # the same length
        self.assertEqual([s["id"] for s in self.m.recall("Is the storm still coming?", limit=1)], [1, 2])


class UpgradeTest(unittest.TestCase):
    def test_memory_from_the_first_version_is_carried_over(self):
        with tempfile.TemporaryDirectory() as d:
            t = at(10, 19)
            with open(os.path.join(d, "history.jsonl"), "w") as f:
                for n in range(1, 6):
                    f.write(json.dumps({"n": n, "t": t + n * 60, "user": "q%d" % n, "reply": "a%d" % n}) + "\n")
            with open(os.path.join(d, "episodes.jsonl"), "w") as f:
                f.write(json.dumps({"id": 3, "t": t + 180, "summary": "They told me about their cat, Miso."}) + "\n")
            with open(os.path.join(d, "notes.md"), "w") as f:
                f.write("- Has a cat called Miso\n- Likes mornings\n")
            with open(os.path.join(d, "state.json"), "w") as f:
                json.dump({"summarised": 3}, f)
            m = Memory(d)
            self.assertEqual([s["summary"] for s in m.sessions()], ["They told me about their cat, Miso."])
            self.assertEqual(sorted(x["text"] for x in m.memories()), ["Has a cat called Miso", "Likes mornings"])
            self.assertEqual(m.notes(), "", "the model's old notes became memories; the owner's notes start empty")
            self.assertTrue(os.path.exists(os.path.join(d, "notes.md.v1")))
            self.assertEqual([t["s"] for t in m.history()], [1, 1, 1, 2, 2], "turns since the last summary are an open conversation")
            self.assertEqual(m.open_session()["turns"], 2)
            self.assertEqual(len(m.transcript(1)), 3, "and every word is in the archive")
            Memory(d)
            self.assertEqual(len(m.memories()), 2, "only once")


class ParseTest(unittest.TestCase):
    def test_the_models_answer_is_read_however_it_dresses_it(self):
        r = parse_sum_up("**TITLE:** Big news\n- SUMMARY: They got the job.\n## MOOD: delighted\n"
                         "* ADD [work and study] | 4 | They start at the library on Monday | 2026-11-23\n"
                         "ADD likes | 2 | They like oolong tea | -\n"
                         "UPDATE #3 | Works at the library\nFORGET #7 | no longer true\n"
                         "FOLLOW UP | 2026-11-24 | how their first day went\nsome stray line")
        self.assertEqual((r["title"], r["summary"], r["mood"]), ("Big news", "They got the job.", "delighted"))
        ops = r["ops"]
        self.assertEqual(ops[0], {"op": "add", "category": "work and study", "importance": 4,
                                  "text": "They start at the library on Monday", "when": "2026-11-23"})
        self.assertEqual(ops[1]["category"], "likes and dislikes")
        self.assertEqual(ops[2], {"op": "update", "id": 3, "text": "Works at the library"})
        self.assertEqual(ops[3], {"op": "forget", "id": 7})
        self.assertEqual(ops[4], {"op": "follow", "text": "how their first day went", "when": "2026-11-24"})
        self.assertEqual(len(ops), 5)
        loose = parse_sum_up("ADD likes | They like oolong tea\nUPDATE #3: Works at the library now\nUPDATE 4 — Lives in Darwin")["ops"]
        self.assertEqual(loose, [{"op": "add", "category": "likes and dislikes", "importance": 3, "text": "They like oolong tea"},
                                 {"op": "update", "id": 3, "text": "Works at the library now"},
                                 {"op": "update", "id": 4, "text": "Lives in Darwin"}], "small models' looser forms")
        real = parse_sum_up("FOLLOW UP YYYY-MM-DD 2026-11-13\n"
                            "UPDATE #3 | Their sister Kim lives in Darwin now. -\n"
                            "UPDATE #2 plans and events: They passed their driving test. | 2026-11-13\n"
                            "ADD about them | 5 | Their name is Sam. | YYYY-MM-DD\n"
                            "UPDATE #2 [plans and events] They passed their driving test. (2026-11-13)")["ops"]
        self.assertEqual(real, [{"op": "update", "id": 3, "text": "Their sister Kim lives in Darwin now."},
                                {"op": "update", "id": 2, "text": "They passed their driving test.", "when": "2026-11-13"},
                                {"op": "add", "category": "about them", "importance": 5, "text": "Their name is Sam."},
                                {"op": "update", "id": 2, "text": "They passed their driving test.", "when": "2026-11-13"}],
                         "lines a real small model wrote")
        garbage = parse_sum_up("ADD | their people | Kim\nADD | about them 1 | about them\nADD about them | 1 | 2026-11-13\n"
                               "UPDATE 1 | The memory as it is now\nADD | health and wellbeing 2 | They hoped Kim settles in well\n"
                               "FOLLOW UP: 2026-11-10")["ops"]
        self.assertEqual(garbage, [{"op": "add", "category": "health and wellbeing", "importance": 2,
                                    "text": "They hoped Kim settles in well"}], "what a 3-billion model wrote: only the real one kept")
        labels = parse_sum_up("ADD category | importance 4 | Their driving test is on Friday, 13th November | 2026-11-13\n"
                              "ADD category | importance 4 | Their sister Kim will support them | 2026-11-13\n"
                              "ADD 2 | They like hiking | likes\n"
                              "ADD | Their favourite tea is oolong\n"
                              "ADD category | importance 4 | Their people: Kim is flying in from Perth | 2026-11-13")["ops"]
        self.assertEqual([(x["category"], x["importance"], x.get("when")) for x in labels],
                         [("plans and events", 4, "2026-11-13"), ("their people", 4, "2026-11-13"),
                          ("likes and dislikes", 2, None), ("likes and dislikes", 3, None), ("their people", 4, "2026-11-13")],
                         "what a 7-billion model wrote: the form's labels copied, fields out of order")

    def test_dates_in_words(self):
        now = datetime.datetime(2026, 11, 18, 15, 0).timestamp()
        self.assertEqual(mem.when(now - 3600, now), "today")
        self.assertEqual(mem.when(now - 86400, now), "yesterday")
        self.assertEqual(mem.when(now - 3 * 86400, now), "3 days ago")
        self.assertEqual(mem.when(datetime.datetime(2026, 3, 2, 9, 0).timestamp(), now), "2 March 2026")

    def test_times_in_words_the_way_people_say_them(self):
        now = at(18, 15)                                    # a Wednesday afternoon
        self.assertEqual(mem.said_when(now - 25 * 60, now), "25 minutes ago")
        self.assertEqual(mem.said_when(at(18, 9), now), "this morning (6 hours ago)")
        self.assertEqual(mem.said_when(at(17, 20), now), "yesterday evening")
        self.assertEqual(mem.said_when(at(18, 1), now), "last night", "until 4 am it is still the night before")
        self.assertEqual(mem.said_when(at(16, 19), now), "on Monday evening (2 days ago)")
        self.assertEqual(mem.said_when(datetime.datetime(2026, 10, 2, 12).timestamp(), now), "on 2 October 2026 (7 weeks ago)")
        self.assertEqual(mem.said_when(at(10, 12), now), "on 10 November 2026 (1 week ago)")
        self.assertEqual(mem.date_words("2026-11-21", now), "Saturday 21 November 2026, in 3 days")
        self.assertEqual(mem.date_words("2026-11-17", now), "Tuesday 17 November 2026, yesterday")
        self.assertEqual(mem.date_words("2027-02-01", now), "Monday 1 February 2027")
        self.assertEqual(mem.date_words("soon", now), "")


if __name__ == "__main__":
    unittest.main()
