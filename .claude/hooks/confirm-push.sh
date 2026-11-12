#!/usr/bin/env bash
# PreToolUse hook (Bash): gate every `git push` on a pre-push review.
#
# - No review recorded for the current HEAD: deny, and tell Claude to run the
#   /pre-push skill (public-repo checklist + fresh-agent code and security
#   reviews), which records the review when it finishes.
# - Review recorded: ask, so the user approves the push against the report.
#
# Reads the hook payload on stdin; prints nothing for other commands, so they
# go through the normal permission flow.
set -euo pipefail

payload=$(cat)
command=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')
cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty')

# Matches `git push`, `git -C dir push`, `git -c k=v push`, and pushes inside
# compound commands (`cd x && git push`). Only git's global options may sit
# between `git` and `push`, so `git stash push` doesn't match.
if ! printf '%s' "$command" | grep -Eq '(^|[[:space:];&|(`])([^[:space:];&|]*/)?git([[:space:]]+(-[Cc][[:space:]]+[^[:space:];&|]+|-[^[:space:];&|]+))*[[:space:]]+push([[:space:]]|$|[;&|)])'; then
  exit 0
fi

repo="${CLAUDE_PROJECT_DIR:-${cwd:-.}}"
head=$(git -C "$repo" rev-parse HEAD 2>/dev/null || true)
git_dir=$(git -C "$repo" rev-parse --absolute-git-dir 2>/dev/null || true)

if [ -n "$head" ] && [ -n "$git_dir" ] && [ -f "$git_dir/pre-push-reviewed/$head" ]; then
  jq -n --arg head "${head:0:7}" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: ("git push to a PUBLIC repo. The /pre-push review (public-repo checklist, code review, security review) is recorded for HEAD " + $head + ". Approve if its report, shown above, is acceptable.")
    }
  }'
else
  jq -n --arg head "${head:0:7}" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("No pre-push review is recorded for HEAD " + $head + ". This repo is public: run the /pre-push skill first (public-repo checklist plus fresh-agent code and security reviews). It records the review for this exact commit; any later commit needs a new review.")
    }
  }'
fi
