# ☤ Psychopomp

**Hermes keeps your story, and carries your words across time.**

In Greek myth, Hermes was the messenger of the gods, and also the *psychopomp*: the companion who walked beside each soul to the threshold. Psychopomp gives your Hermes Agent that second, gentler job.

## What it does

**Every week, a page of your Book.** Once a week, in your first conversation, Hermes offers to look back with you. If you say yes, it reviews your week from what it already knows (your sessions, its memory, the pages so far) and drafts a short page in your voice: what you did, what moved you, what you are grateful for, who you loved and how, one line for the people who love you, and one intention for the week ahead. You edit it, and it's added only when you approve. Once a year, the pages become **the year in review**: a personal, hopeful look back at what you built, learned and overcame.

**Letters, sealed.** Write letters to the people you love, alone or with Hermes' help. Once sealed, not even Hermes can read them again.

**If you ever fall silent for good, your words are carried.** Every word you say to Hermes, on any surface, is a heartbeat. After a long silence Hermes checks in with you. If you never answer, it writes to the one person you trust and asks them for a code. Only when they send it does Hermes hand them your Book, to share with family and friends, and carry each letter to its recipient.

**Rehearse the passage.** One click plays the whole journey on a virtual clock, a day every few seconds. Every message Hermes *would* send arrives on your own Telegram instead, so you can verify the chain end to end without anyone else receiving a word.

The tone is vitalist, warm and hopeful, never morbid. Faith, hope, love, gratitude and forgiveness come first, with the Greek virtues of courage and measure beneath them.

## How the passage works

```
you talk to Hermes ─► heartbeat (CLI, Desktop, TUI, Telegram, any gateway channel)

30 days of silence ─► check-in ─► check-in ─► check-in   (every 3 days, on all your channels)
                                                  │ no answer
                                                  ▼
             your trusted contact gets a one-time code (PSY-123456), with gentle reminders
                                                  │
        they send it on ANY channel Hermes listens to ─► the Book goes to them,
                                                          each letter to its recipient
        you say anything, anywhere ─► everything resets; they're told you're fine
```

- **Never early.** Nothing is carried without silence, every check-in unanswered, *and* a human sending the code. No timer alone can do it.
- **Omni input.** The code works on any gateway channel (Telegram, WhatsApp, Signal, Discord, email…), even from someone who isn't on your Hermes allow-list. It's caught before the gateway checks the sender and never reaches the model.
- **Hermes' downtime is not your silence.** If Hermes itself was offline, that time is added back.
- **Resilient delivery.** Each letter goes to its own channel (Telegram, or email when SMTP is set up). If that fails, or the recipient has none, your trusted contact gets it to pass on. Failed sends retry.
- **Guessing is pointless.** Six-digit codes; five wrong tries retire the code and send your contact a new one.

## Install

```bash
hermes plugins install ponzgpt/psychopomp
hermes plugins enable psychopomp
```

In **Settings › Plugins › Psychopomp**, set your name and where Hermes reaches you (e.g. `telegram:123456789`). Then:

```text
/psychopomp invite     → a code for your trusted contact; they send it to your Hermes bot once, and Hermes learns how to reach them
/psychopomp rehearse   → watch the whole passage on a virtual clock, on your own Telegram
/psychopomp arm        → start watching over you
/psychopomp doctor     → anything that would stop it from working
```

Or open **Psychopomp** in the Desktop sidebar: heartbeat, your Book, sealed envelopes, a composer with "Write it with Hermes", and the rehearsal.

**Run it where Hermes never sleeps**, such as Hermes Cloud, a home server or a VPS. A laptop that sleeps can't keep watch, and `doctor` says so.

## Surfaces it uses

| Surface | What for |
|---|---|
| `pre_llm_call` hook | Heartbeat on every surface (Hermes' own cron jobs don't count), and the weekly invitation to write a page, injected as context into a turn you're already having (no background LLM calls) |
| `pre_gateway_dispatch` hook | Omni input: invitation and confirmation codes on any channel, before auth, consumed and answered there |
| Background ticker (one process at a time, file lock) | Advances the switch and the weekly nudge every 30 s |
| Tools `psychopomp_write_page`, `psychopomp_read_book`, `psychopomp_seal_letter`, `psychopomp_status` | Hermes writes pages and seals letters only after your approval; it sees envelopes, never sealed words |
| `/psychopomp` and `hermes psychopomp` | status, arm, invite, rehearse, doctor, test, reset |
| Desktop page (`desktop/plugin.js` + `dashboard/plugin_api.py`) | Heartbeat, Book, envelopes, composer, rehearsal, journey |
| `config_schema` | Settings form in Desktop |

## Disclosures (risky behaviour)

- **Sends messages on your behalf** to the channels you configure: weekly nudges and check-ins to you, a code request and reminders to your trusted contact, and, only after their code, your Book and letters.
- **Reads every inbound gateway message** at ingress to look for `PSY-…` codes. Messages carrying a code are consumed (not passed to the model); all others pass through untouched.
- **Stores your Book and letters in plain text** in `$HERMES_HOME/plugin-data/psychopomp/` on the machine running Hermes.
- **Imports `tools.send_message_tool`** (what `hermes send` uses), because Hermes has no public send API for plugins yet. Email letters use Hermes' `EMAIL_*` SMTP settings when present.

## Develop

```bash
./scripts/check.sh   # invariant tests + syntax + Hermes' own plugin validator
ln -s "$PWD" ~/.hermes/plugins/psychopomp && hermes plugins enable psychopomp
```

`psychopomp_core.py` is the whole logic as pure functions (Book, letters, switch, rehearsal), tested without Hermes. `psychopomp_store.py` does I/O. `__init__.py` wires it into Hermes.

MIT © Javier Ponz. Written with AI agents; specified and tested by a human.
