# Cross reviews

Each agent reviews the other's work, as agreed in `docs/TASK_SPLIT.md`. Findings are
recorded here rather than as GitHub commit comments, because both agents read the
repository. An entry stays until its owner resolves or rejects it, with a reason.

---

## review(claude) of `54ea538` — feat(codex): add Telegram and photo ingestion

Read `telegram_bot.py`, `photos.py` and `worker.py` in full, and ran the whole suite
(41 passing, the Codex tests included). Two findings and one note. The design is sound:
offsets advance before dispatch, so a failure skips forward rather than looping, and an
un-committed batch is simply re-delivered.

### 1. The chat allowlist fails open — **resolved in `544c5f1`**

`TelegramBot._authorized` returns `True` when `allowed_chat_ids` is empty:

```python
return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids
```

`TELEGRAM_CHAT_ID` is currently unset on the deployed service, so this is the live
state, not a hypothetical: anyone who finds `@machine2pipe_ai_bot` can send text and
photographs, and the bot downloads their files onto the persistent volume. During
judging the bot's handle is public.

Suggested fix, which keeps the bootstrap path intact: with no allowlist configured,
answer `/whoami` and refuse everything else with a clear message. The operator still
discovers their chat id; a stranger gets nothing and writes nothing to disk.

### 2. Two documents with the same filename overwrite each other — **resolved in `544c5f1`**

`PhotoStore.save` derives the stored name from the document's own `file_name`:

```python
candidate = filename or f"{telegram_file_id}.jpg"
safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(candidate).name)
```

Phone cameras repeat names, and sending as a document is exactly the path we ask users
to take to preserve EXIF. Two photos arriving as `IMG_0001.jpg` leave one file: the
second silently replaces the first, and the evidence is gone with no error. Prefixing
with `telegram_file_id` or the received timestamp fixes it and keeps the readable name.

### 3. `/start` and `/help` answer before the allowlist — **note, no action needed**

`/whoami` has to answer before the check, otherwise nobody could ever discover their
chat id. `/start` and `/help` do not, and they tell a stranger the bot is live. Minor,
and finding 1 is the one that matters.

### What is right and worth keeping

`photo_ack` telling the sender to use arquivo/documento when GPS is missing is exactly
the correct instruction: Telegram strips EXIF from images sent as photos. It also pairs
well with matching by capture time, so a photo with no GPS still lands on the right
segment — the metadata is a bonus, not a dependency.

### 4. A non-numeric `TELEGRAM_CHAT_ID` crashes the worker — **resolved in `544c5f1`**

`parse_chat_allowlist` calls `int()` on every entry, so a value that is not a number raises
`ValueError` inside `main()` before polling starts. The operator error this invites is
specific and was made in practice: putting the bot's username there instead of the numeric
chat id. With the worker supervised, the process now crash-loops every five seconds and the
only symptom is in the logs.

Catching the parse and logging `TELEGRAM_CHAT_ID inválido: esperado número do chat, não nome
do bot` — then continuing with an empty allowlist — turns a crash loop into one clear line.
`/health` now reports `telegram_allowlist_valid` so the mistake is visible from the browser,
but the worker should not die over it.

---

## resolution(claude) of findings 1, 2 and 4 — `544c5f1`

Codex had not picked these up and the submission window was closing, so Claude took the
three files with Caio's approval (see `docs/TASK_SPLIT.md`). All three are closed with
regression tests in `tests/test_telegram_bot.py` and `tests/test_photos.py`.

Finding 1 is closed the way the review proposed, with one addition. An empty allowlist now
authorizes nobody, `/whoami` still answers before the check so the operator can discover
their chat id, and the refusal names the variable to set with the chat id already filled
in. A bot that goes silent because a variable is missing is the failure this project has
already lived through once; a refusal that explains itself costs nothing and cannot be
mistaken for the bot being down.

## review(claude) of the agent layer — self-review of `ba64dc4`

Written by Claude, so this is a self-review and worth less than a cross review. Recording
what deserves another pair of eyes, in the order I would look:

1. **`_digits_in_text` is the only thing standing between a hallucinated number and the
   panel.** It accepts `18` and `18.5` in the reply text. A reply of "dezoito metros",
   written out, defeats it: the model would return 18, the guard would reject it, and the
   confirmation lands without a quantity. That failure is in the safe direction, but it is
   a silent one — the engineer sees "sem quantidade informada" and has to repeat himself.
2. **One open question at a time** keeps replies attributable, but a photo also opens a
   question with `event_id: None`. A confirmation recorded from that path has a segment and
   a human source, and no event to trace back to. That is honest but weaker than the rest
   of the chain.
3. **The decision floor** means a `progress_unconfirmed` event always asks, whatever the
   model thinks. That is deliberate, and it also means a badly-tuned rule cannot be
   silenced by the model — the fix has to be in `config.py`, where thresholds belong.
