# API gotchas

These quirks are baked into the typed verbs so callers do not have to rediscover
them by hitting API errors.

- **`share`** -> `add-users-to-document` wants `names` as an **`{email: name}` object map**,
  not an array. Sending an array can make the server return `500`.
- **`update`** -> `update-document` keys the note as **`id`**, not `document_id`.
  Sending `document_id` returns `400 "Missing document ID"`.
- **`get`** -> the full single-note record comes from `get-documents-batch`
  (`{document_ids: [...]}`), not a singular `get-document`.

Full request/response shapes are documented in `docs/granola-api.md` in the companion
credential-decrypt research repo.
