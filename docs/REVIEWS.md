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

### 1. The chat allowlist fails open — **open**

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

### 2. Two documents with the same filename overwrite each other — **open**

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
