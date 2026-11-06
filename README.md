# ☤ Psychopomp

**Hermes carries your words across time.**

In Greek myth, Hermes was the messenger of the gods. He was also the *psychopomp*: the one who walked beside souls to the threshold. Psychopomp gives your Hermes Agent that second job.

You write letters to the people you love. You seal them. Then you live your life and talk to Hermes as usual, on the CLI, in Desktop, on Telegram, by email. Every word you say tells Hermes you are still here.

If one day you fall silent, Hermes checks in with you on all your channels. If you never answer, it asks one person you trust for a code. Only when that person confirms does Hermes carry your letters to the people you wrote them for.

> A dead man's switch for Hermes Agent, with the warmth left in.

## How it works

```
you talk to Hermes ──► heartbeat resets (any surface: CLI, Desktop, TUI, Telegram, email…)

30 days of silence ──► check-in 1 ─► check-in 2 ─► check-in 3      (every 3 days, all your channels)
                                                        │
                       no answer ───────────────────────┘
                           │
                           ▼
            your trusted contact gets a one-time code (PSY-123456)
                           │
     they reply with it on ANY channel Hermes listens to ─► letters are emailed
                           │
     you say anything, anywhere ─► everything resets, the code dies, they are told you're fine
```

- **Never early.** Letters leave only after silence, every check-in unanswered, *and* a human confirming. No timer alone can send them.
- **Omni input.** The confirmation code works on any gateway channel (Telegram, WhatsApp, Signal, email, Discord…), even if your trusted contact is not on Hermes' allow-list. It is caught before the gateway's sender check and never reaches the model.
- **Sealed means sealed.** After sealing, a letter's words never appear again: not in Desktop, not in tool results, not to Hermes.
- **Hermes helps you write.** Ask "help me write a letter to my sister" and Hermes drafts it from what it knows of you, in your voice. You edit it, and it is sealed only when you say so.
- **Guessing is pointless.** Codes are 6 digits; five wrong guesses retire the code and send your contact a fresh one.

## Install

```bash
hermes plugins install ponzgpt/psychopomp
hermes plugins enable psychopomp
```

Then, in **Settings › Plugins › Psychopomp** (or `plugins.entries.psychopomp.settings` in `config.yaml`):

| Setting | Example |
|---|---|
| Your name | `Javier` |
| Where Hermes checks in with you | `telegram:123456789, email:me@example.com` |
| Trusted contact's name | `Leo` |
| Where Hermes reaches them | `email:leo@example.com, telegram:987654321` |
| Days of silence / days between check-ins / check-ins | `30 / 3 / 3` |

Letters travel by email using the same settings as Hermes' Email gateway: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_SMTP_HOST` (and optionally `EMAIL_SMTP_PORT`, default 587). Other channels use Hermes' own delivery (`hermes send` targets).

```bash
hermes psychopomp doctor   # what would stop the switch from working
hermes psychopomp test     # send yourself a test check-in on every channel
hermes psychopomp arm      # start watching
```

Open the **Psychopomp** page in the Desktop sidebar to see your heartbeat, write and seal letters, and follow the journey.

**Run it where Hermes is always awake.** A switch on a laptop that sleeps cannot fire. For real use, install Psychopomp on an always-on Hermes (a home server or VPS running the gateway); `doctor` warns you when the host sleeps.

## Surfaces it uses

| Surface | What for |
|---|---|
| `pre_llm_call` hook | Heartbeat: any turn on any surface (Hermes' own cron jobs don't count) |
| `pre_gateway_dispatch` hook | Omni input: the confirmation code on any channel, before auth; consumed and answered there |
| Background ticker (one process at a time, file lock) | Advances the switch every 30 s |
| Tools `psychopomp_status`, `psychopomp_seal_letter` | Hermes sees envelopes, never contents; seals only after your approval |
| `/psychopomp` and `hermes psychopomp` | status, arm, disarm, doctor, test, reset |
| Desktop page (`desktop/plugin.js` + `dashboard/plugin_api.py`) | Heartbeat, envelopes with wax seals, composer, "Write it with Hermes" |
| `config_schema` | Settings form in Desktop |

## Disclosures (risky behaviour)

- **Sends messages on your behalf** to the channels you configure: check-ins to you, a code request to your trusted contact, and your letters by email to their recipients.
- **Reads every inbound gateway message** at ingress to look for a `PSY-######` code. Messages with a code are consumed (not passed to the model); all others pass through untouched.
- **Stores letters in plain text** in `$HERMES_HOME/plugin-data/psychopomp/state.json` on the machine running Hermes. Anyone with access to that machine can read them.
- **Imports `tools.send_message_tool`** (what `hermes send` uses) to reach non-email channels, because Hermes has no public send API for plugins yet.
- Uses your SMTP credentials only to send the letters and email check-ins.

## Try it in two minutes (demo mode)

Turn on **Demo mode** in the settings: a "day" lasts one minute. With silence 2, every 1, check-ins 2, the whole journey (silence, check-ins, trusted contact, code, delivery) plays out in about five minutes.

## Develop

```bash
./scripts/check.sh   # tests + syntax + Hermes' validator when installed
ln -s "$PWD" ~/.hermes/plugins/psychopomp && hermes plugins enable psychopomp
```

The switch itself is a pure state machine in `psychopomp_core.py`, tested without Hermes. `psychopomp_store.py` holds I/O; `__init__.py` wires it into Hermes.

MIT © Javier Ponz. Written with AI agents; specified and tested by a human.
