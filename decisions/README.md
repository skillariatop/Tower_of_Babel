# decisions/

This directory is the **source of truth for the AI Orchestrator**.

Every accepted community decision lives here as a YAML file. The Orchestrator reads these files to decompose decisions into GitHub Issues, assign tasks, and track progress. It does not act on verbal requests in Discord — only on files in this directory.

## File naming

```
NNNN-short-slug.yaml
```

`NNNN` — zero-padded sequential number (0001, 0002, …).  
`short-slug` — kebab-case summary of the decision.

## Template

```yaml
id: 1
title: "Short human-readable title"
level: routine          # routine | significant | critical | by-authority | emergency
status: accepted        # accepted | rejected | superseded
supersedes: ~           # id of the decision this replaces, or ~ for none
votes:
  for: 0
  against: 0
  abstain: 0
discord_thread: ""      # URL to the Discord thread where this was discussed
decided_at: "YYYY-MM-DD"
decided_by: ""          # username(s) or "vote"
decision: |
  Full text of the decision.
tasks_hint: |
  Optional: hints for the Orchestrator on how to break this into tasks.
```

## Status lifecycle

```
pending → accepted
         ↓
      superseded  (a newer decision replaces it)
         or
      rejected
```

Once a file is merged to `main`, its `status` field must not be changed manually — open a new decision that supersedes it instead.
