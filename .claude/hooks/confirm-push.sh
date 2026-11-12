#!/usr/bin/env bash
# PreToolUse hook (Bash): require explicit approval for any `git push`.
# Reads the hook payload on stdin; prints an "ask" decision for pushes and
# nothing otherwise, so all other commands go through the normal permission flow.
set -euo pipefail

command=$(jq -r '.tool_input.command // ""')

# Matches `git push`, `git -C dir push`, `git -c k=v push`, and pushes inside
# compound commands (`cd x && git push`). Only git's global options may sit
# between `git` and `push`, so `git stash push` doesn't match.
if printf '%s' "$command" | grep -Eq '(^|[[:space:];&|(`])([^[:space:];&|]*/)?git([[:space:]]+(-[Cc][[:space:]]+[^[:space:];&|]+|-[^[:space:];&|]+))*[[:space:]]+push([[:space:]]|$|[;&|)])'; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: "git push to a PUBLIC repo. Approve only if Claude has completed the \"Public repo: review before every push\" checklist in CLAUDE.md (every outgoing commit reviewed individually: secrets, personal info, commit identity, neutrality, internal notes, data size, third-party content) and reported the findings."
    }
  }'
fi
