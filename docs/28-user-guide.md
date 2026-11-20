# User guide: your character device

Status: 2026-11-19. Written for buyers, from the software as it is today. It
has not yet been followed on a finished unit (no unit has been built, see
`29-hardware-setup.md`); correct it after the first build. Items marked
*not yet* are planned, not built.

## What it is

A small screen with a character on it that you talk to. It listens when you
press its button, answers out loud in its own voice, and moves while it
talks: its mouth follows the words, its face and body show how it feels, and
it nods, waves, tilts its head and gestures with what it says. Left alone,
it looks around, gazes out of the window, stretches and, late at night,
dozes off. It remembers what you tell it.

You choose the character: make one from a picture, bring a Live2D-format
model or a 3D VRM avatar you already have, or bring a character card's
personality.

## What you need

- The device and its power supply.
- Home Wi-Fi, and a phone or computer on it, to use the settings page.
- **A language model** (the character's mind): a key for a service (several
  have free allowances), or a model running on your own computer, which is
  free and keeps your words at home. See "AI services" below. The device
  comes with no keys: you add your own, and they never leave the device.
- Optional: a key for a voice service (the device has a free voice of its
  own), and a web-search key (only for models that cannot search by
  themselves; Claude can).
- To make characters from pictures: a Linux or Mac computer for Character
  Studio (Windows *not yet*).

## Setting it up

1. **Plug it in.** After about 40 seconds the screen shows *Set up Wi-Fi*:
   the device's own network name, its password and a QR code.
2. **Join the device's network** with your phone (scan the QR code, or
   choose the network and type the password), then open
   `http://10.42.0.1`.
3. **Choose a password for the settings page.** Write it down; it protects
   your keys and your character's memory.
4. **Choose your home Wi-Fi** under **Device → Wi-Fi** and type its
   password. The device joins it and shows *Hello!*, its new address and a
   QR code.
5. **Put your phone back on your home Wi-Fi** and open the address on the
   screen, or `http://companion.local`.
6. **Follow "Getting started"** on the settings page's Home tab: add a
   language-model key, choose a voice, add a character, then press the
   button and say hello. Each step links to where it is done. The page also
   gives the device your phone's time zone.

The settings page only answers on your home network.

## Talking

- **Press the listen button and speak.** In the usual mode it hears when
  you stop speaking and answers. You can change this under **Device →
  Listening** to *press to start, press again to send*, and set how long a
  pause ends your turn.
- **Press the button while it speaks** to stop it. With a sound card that
  cancels the device's own voice (the ReSpeaker Lite does), you can also
  turn on *Let me interrupt it by speaking*.
- **On the settings page**, the Home tab has *Start listening*, *Stop
  speaking*, a box to type a message instead of speaking, and *What is
  happening*: what it heard, what it is doing, and any problem.
- **Volume** is under **Device**.

While you speak it looks at you, nods in your pauses and looks up when you
start. While it thinks it looks away for a moment.

### Things you can ask for

- **Timers and alarms**: "Set a timer for ten minutes for the pasta",
  "Wake me at half past seven", "Cancel the pasta timer". They ring out
  loud, and they survive the device being switched off and on.
- **Things to look up**: turn on **Allow web search** under **Device**.
  Claude models search the web themselves; other models need a "Web
  search" key from tavily.com (free monthly allowance), added under **AI
  services → All saved keys**.
- **Anything you would ask a friend who remembers you**: it keeps notes
  about you and can recall earlier conversations.

## Characters

Your characters are on the **Characters** tab. Choose one to put it on the
screen; the one on the screen is the one you talk to. Each has its own
personality, voice, movement and memory.

### Making one from a picture: Character Studio

Character Studio runs on your computer (not the device) and turns one
picture into a moving character. How to install it is in
`14-making-characters.md`.

1. Drop in a picture and give the character a name.
2. Watch it being made; a preview of it moving appears (about a minute).
3. **Check the arms in the preview.** If an arm moves wrongly (a sleeve
   with no hand, a coat taken for an arm), untick that arm and make it
   again: it then stays still, and the character greets you instead of
   waving.
4. Say who the character is (or do it later on the device).
5. **Send to the device**: its address and the settings-page password
   (used for that one upload, not kept). Or save the `.char` file and add
   it on the **Characters** tab.

Pictures that work best:

- One character, facing you, head to at least the waist (head to toe is
  best), on a plain or transparent background.
- The face clear of hair and hands; the eyes open.
- **For arms that move**: arms hanging at the sides from the shoulder, with
  the hands showing. Hands in pockets, arms folded or raised, hands at the
  face, wide sleeves, capes and long hair over the arms all keep the arms
  still (the rest of the character still moves).

### A Live2D model you rigged, or bought

On **Characters → Add a character**, choose a `.zip` of the model's folder: the folder with its `.model3.json`, as used by VTube Studio.
- The device plays the model itself (with Ayagami), with its physics (hair and clothes swaying) and its expressions.
- If the model shows alternate parts in turn (two sets of arms, say), its pose file is respected. The device
works out which of its settings turn the head, blink, open the mouth and so
on. If something moves wrongly, the **Movement** section under the
character lets you choose the right setting for each movement and test it
on the screen. **Feelings** maps the model's own expressions to the
character's moods.

### An Inochi2D model you rigged

[Inochi Creator](https://inochi2d.com) is a free, open-source rigging program, similar to Live2D Cubism. Export your model as an `.inp` file and choose it on **Characters → Add a character**; Inochi Creator's own `.inx` project files work too.
- The device reads the model's name, artist and licence from the file.
- It works out which parameters turn the head, blink and open the mouth, from Inochi2D's standard names ("Head:: Yaw-Pitch", "Eye:: Left:: Blink", "Mouth:: Open") or Live2D's ("ParamAngleX").
- If a movement is wrong, the **Movement** section under the character lets you choose the right parameter and test it on the screen.

### A 3D avatar (VRM) you already have

On **Characters → Add a character**, choose a `.vrm` file (as made with
VRoid Studio and most VTubing programs). Adding it takes up to a minute
while its pictures are fitted to the device's memory. If an avatar is too
detailed for the device, it says so and what to do (export it again with
fewer polygons and smaller textures). Its maker's terms (who may use it,
whether commercially) are shown under it; follow them. **Feelings** starts
with its own happy, sad, angry and surprised expressions.

It talks like any other character, with the same moods, gestures and lip
sync. Under **3D animation** you choose how it moves:

- **Full body** (the usual): it stands and moves like a person, with a
  different idle pose for each mood and for listening, thinking and
  talking, and gestures with its whole body (waving, bowing, a hand on the
  chin while it thinks, stretching, yawning behind its hand).
- **Light**: it moves the way the 2D characters do, using a little less of
  the device.
- **Show**: head to thighs, head and shoulders, or the whole body.
- **Simplify the drawing**: no outlines and smaller pictures, for a slow
  device. The device does this by itself if the screen gets slow.

**Its own animations**: add VRM Animation files (`.vrma`, from VRoid Hub,
VRM Posing Desktop or Blender) as an idle pose (for a mood, or for
listening, thinking or talking), in place of one of its gestures, or as a
new gesture with a few words saying when to use it ("do a little dance").
**Try** plays one on the screen. Use only animations you have the right to
use.

### Who the character is

Under the character, **Describe the character** asks a few questions (name,
personality, story, how they treat you, likes, dislikes, how they speak,
things they never do, a greeting) and writes the persona from your answers.
You can then edit the persona freely. A **character card** (a PNG or JSON
file from other AI-companion apps) fills it in for you to check and save.

### Its voice

The device's own voice is free and works without the internet. With a voice
service (ElevenLabs, or an OpenAI-style one), each character can have its
own voice: put its voice ID under the character. **Clone a voice** makes a
voice from a recording, with ElevenLabs.

## How it moves

The character moves by itself; you can shape how. Under each character:

- **Temperament**: two sliders, *Calm ↔ Lively* (how much and how soon it
  moves) and *Reserved ↔ Expressive* (how many and how big its gestures
  are). *Suggest from the personality* sets them from the persona.
- **Gestures and idle actions it makes by itself**: switch off any you do
  not want (a character who never waves, say).
- **Movement** (mostly for imported models): which of the model's settings
  each movement uses, with a **Test** button for each.

The **Animation** tab shows what the character is doing right now: its
mood, the time of day it thinks it is, how energetic, attentive, bored or
sleepy it is, which parts of its body are busy, and the last gestures and
why it made them. **Change or add a gesture** lets you edit a gesture's
movement, try it on the screen, and save it as a new gesture with the words
that bring it on. Character Studio can also make a gesture from a video of
you doing it (`14-making-characters.md`).

## Memory

The character remembers each conversation as a whole, the lasting things
it learns about you, and keeps a diary (`31-memory.md`).

- **A conversation ends** after 20 quiet minutes, a few minutes after you
  say goodbye, when a new day starts (4 am), or when you press **Start a
  new conversation**. It is then summed up in the background: a title, a
  summary, how you seemed, and what it learnt.
- **What it learns** is kept as short memories with a category and an
  importance: your name, your people, what you like, plans with their
  dates. When something changes ("Kim moved to Darwin"), the old memory is
  updated, not kept beside the new one. Once a plan's day has passed, it
  asks how it went.
- **Each evening** it writes a diary entry in its own voice, and the next
  day it picks up where you left off.

The **Memory** tab shows all of it:
- **Always remember**: notes it keeps in mind in every conversation, which
  it never changes itself.
- **What it remembers about you**: its memories, which you can add, pin,
  change or forget; ones it found no longer true can be restored.
- **Conversations**: each with its summary; **Show words** shows every word.
- **Diary**: its entries.

**Forget everything** clears that character's memory.

### Speaking first

Turn on **Device → Speak first** and the character greets you when you come back after a while. It asks how your plans went, then listens for half a minute so you can just answer.
- It notices speech-like sound in the room; nothing is recorded or sent.
- Choose how long apart counts (3 hours by default) and the quiet hours when it never speaks first (10 pm to 8 am by default).
- A television left talking can set it off, so it is off unless you turn it on.

## AI services

Under **AI services**, in three parts:

1. **Language model**: Claude (Anthropic), OpenAI, Gemini, Groq, OpenRouter,
   or any service with an OpenAI-style address. Choose the service and model,
   paste the key, then **Save and test**.

   **A model on your own computer** (*My own computer or server*):
   - Supported: Ollama, LM Studio, llama.cpp, vLLM, KoboldCpp,
     text-generation-webui, Jan or GPT4All on a computer in your home. Free,
     and nothing you say leaves your home network. With the device's own voice
     and speech recognition, the character then works without the internet.
   - **Open the model to your network:**
     - Ollama: start it with `OLLAMA_HOST=0.0.0.0`.
     - LM Studio: turn on *Serve on Local Network*.
     - llama.cpp: start its server with `--host 0.0.0.0`.
   - **Connect:** press **Find on my network**, pick your server and a model,
     then **Save and test**. If it isn't found, type the computer's address.
   - **Context** is how much the model reads at once (8,192 if left empty).
     More lets it remember more of a long conversation, but needs more of the
     computer's memory.
   - **Model size matters most for memory.** A model of 7 to 8 billion
     parameters (such as `qwen2.5:7b` or `llama3.1:8b`) chats well on a recent
     laptop and keeps memory mostly right; glance at the Memory tab now and
     then. A 3-billion model can chat, but keeps poor memories. Larger models
     on a computer with a graphics card do better.
   - The first reply after a while is slower, as the model loads.
2. **Voice**: the free on-device voice, or a voice service.
3. **Speech recognition** (hearing you): free and on the device by default,
   or a cloud service.

**All saved keys** lists which keys are saved, without showing them.

## Privacy and your keys

- **Keys** are stored only on the device, in a file only its software can
  read. Once saved, a key is never shown again: not on the page, the screen,
  in logs, or in character files you export or share.
- **What you say** goes to the language-model service you chose, as text
  (with the on-device speech recognition, your voice itself stays on the
  device). With a cloud voice or cloud speech recognition, the text or audio
  goes to that service. Their own privacy terms apply.
- **Memory** (conversations, memories, the diary and your notes) stays on
  the device. What the character reads for a reply goes to the language
  model you chose; with a model on your own computer, it stays in your home.
- **The settings page** only answers on your home network, behind your
  password.

## Software updates

The device keeps itself up to date. It looks for updates from its maker twice a day, and installs them at night (2 to 5 am) when nobody is talking to the character.
- Your characters, memories, keys and settings are kept.
- If an update ever doesn't start properly, the device goes back to the version before by itself. That includes after a power cut in the middle of one.

**Device → Software** shows the version, and lets you:
- check for updates and install one now;
- turn automatic installing off;
- go back to the previous version;
- install an update file you were sent (for a device without internet).

## Backup, and help

**Device → Backup → Download a backup** saves every character, with its memory, choices and animations, and the settings, in one file.
- Keep it somewhere safe, or restore it on a new device or a bigger card: **Restore from a backup**.
- Keys, the password and Wi-Fi are never in a backup, so put your keys in again afterwards.

If something is wrong, **Device → Help → Download a support report** and send it to the device's maker.
- It has versions, settings, recent problems and logs.
- It has no keys, no passwords, and nothing anyone said.

## Rights

Use only pictures, models, character cards and voices you have the right to
use. A character made from a picture of a well-known character is for your
own private use. Clone only your own voice, or a voice whose owner agrees.

## Buttons

| Button | Press | Hold |
|---|---|---|
| Listen | Start listening; press again to stop; press while it speaks to interrupt | 12 seconds: forget the settings-page password and the saved Wi-Fi (characters, memories and keys stay), and show the setup screens again |
| Power | Shut down cleanly; press again to start | — |

## Troubleshooting

| Problem | What to do |
|---|---|
| The screen shows *Set up Wi-Fi* again | The device cannot find your Wi-Fi (new router or password?): join its network and choose your Wi-Fi again |
| The settings page will not open | Is your phone on the same Wi-Fi? Use the address on the screen rather than `companion.local` |
| Forgot the settings-page password | Hold the listen button for 12 seconds, then set up again (characters, memories and keys stay) |
| It does not hear you | Is listening on (press the button)? Look at *What is happening* on the Home tab |
| "refused the key" | The key is wrong, expired, or the account has no credit: paste it again under AI services and **Save and test** |
| It answers slowly | Choose a faster model, or lower *Effort* under the language model. With a model on your own computer, choose a smaller one; the first reply after a pause is slower while it loads |
| **Find on my network** finds nothing | Is the computer on, with the model server running and opened to the network (see AI services)? Type its address instead, such as `192.168.1.20`; a firewall may need to allow the port (Ollama: 11434, LM Studio: 1234) |
| "requires more system memory" | The model is too big for that computer: choose a smaller one, or lower *Context* |
| It forgot something it should know | Look on the **Memory** tab: add or correct the memory, or pin it so it is always in mind |
| The Home tab says the memory was not brought up to date | The language model could not be reached; it tries again in 15 minutes |
| An arm moves wrongly | Make the character again in Character Studio with that arm unticked |
| It moves too much, or too little | Its **Temperament** sliders |
| An imported model moves the wrong part | Its **Movement** section: choose another setting for that movement and test it |
| The screen says a character cannot be shown | Choose another character; the file may be damaged or of an unsupported kind |
| The screen says a 3D avatar is too detailed for this device | Choose another character, or export the avatar again with fewer polygons and smaller textures and add it again |
| A 3D avatar moves stiffly or the screen is slow | Under **3D animation**, tick *Simplify the drawing*, or choose the *Light* style |
| A 3D animation you added will not load | It must be a `.vrma` file of at most 16 MB and 2 minutes; the settings page says what is wrong |
| The screen says *Updating* for more than ten minutes | Unplug it and plug it in again: it starts on the version that works and finishes or undoes the update |
| Giving the device away | **Device → Reset everything** (password, then type RESET): removes characters, memories, keys, settings, timers and saved Wi-Fi |
