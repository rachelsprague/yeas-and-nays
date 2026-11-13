"""The Claude Code push hook: which commands count as a push, and what it decides."""

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

HOOK = pathlib.Path(__file__).parents[1] / ".claude" / "hooks" / "confirm-push.py"
spec = importlib.util.spec_from_file_location("confirm_push", HOOK)
confirm_push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(confirm_push)


@pytest.mark.parametrize("command", [
    "git push",
    "git push origin main",
    "\\git push",
    '"git" push',
    "/usr/bin/git push",
    "sh -c 'git push'",
    'eval "git push"',
    "make test && git push",
    "git \\\n  push",
    'git -C "path with space" push',
    "echo $(git push)",
])
def test_finds_push(command):
    assert confirm_push.find_pushes(command)


@pytest.mark.parametrize("command", [
    "git status",
    "git stash push -m wip",
    "git commit -m 'push the fix'",
    "git commit -m \"don't push yet\"",
    "echo push",
    "git log --oneline origin/main..HEAD",
])
def test_ignores_non_push(command):
    assert not confirm_push.find_pushes(command)


@pytest.fixture
def repo(tmp_path):
    def run(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    run("init", "-q", "-b", "main")
    (tmp_path / ".githooks").mkdir()
    (tmp_path / ".githooks" / "pre-push").write_text("#!/bin/sh\n")
    (tmp_path / ".githooks" / "pre-push").chmod(0o755)
    run("add", ".githooks")
    run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x")
    run("config", "core.hooksPath", ".githooks")
    run("checkout", "-q", "-b", "feature")  # pushes go from a branch; main lands through PRs
    return tmp_path, run("rev-parse", "HEAD")


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def record(repo_path, sha):
    d = repo_path / ".git" / "pre-push-reviewed"
    d.mkdir(exist_ok=True)
    (d / sha).touch()


def test_unreviewed_push_is_denied(repo):
    path, _ = repo
    decision, reason = confirm_push.decide("git push", str(path))
    assert decision == "deny" and "/pre-push" in reason


def test_reviewed_push_asks(repo):
    path, head = repo
    record(path, head)
    assert confirm_push.decide("git push -u origin feature", str(path))[0] == "ask"
    assert confirm_push.decide("git push --set-upstream origin feature", str(path))[0] == "ask"
    assert confirm_push.decide("git push origin feature", str(path))[0] == "ask"
    assert confirm_push.decide("git push 2>&1", str(path))[0] == "ask"
    assert confirm_push.decide("git push origin feature > /dev/null", str(path))[0] == "ask"
    assert confirm_push.decide("git push>/dev/null", str(path))[0] == "ask"


@pytest.mark.parametrize("command", ["git push", "git push origin", "git push origin main", "git push -u origin main"])
def test_push_from_main_is_denied_even_when_reviewed(repo, command):
    path, head = repo
    git(path, "checkout", "-q", "main")
    record(path, head)
    decision, reason = confirm_push.decide(command, str(path))
    assert decision == "deny" and "pull request" in reason


def test_push_from_detached_head_is_denied(repo):
    path, head = repo
    record(path, head)
    git(path, "checkout", "-q", "--detach")
    assert confirm_push.decide("git push", str(path))[0] == "deny"


@pytest.mark.parametrize("command", [
    "gh pr merge 12 --squash",
    "gh pr merge --auto",
    "cd /tmp && gh pr merge",
    "gh pr \\\n  merge 12",
    "gh pr -R owner/repo merge 12",
    "gh -R owner/repo pr merge 12",
    "gh --repo owner/repo pr merge 12 --squash --delete-branch",
    "gh -R owner/repo api repos/o/r/pulls/3/merge -X PUT",
    "gh alias set m 'pr merge'",
    "gh api -X PUT repos/o/r/pulls/12/merge",
    "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
    "sh -c 'gh pr merge 12'",
])
def test_gh_pr_merge_is_denied(repo, command):
    path, _ = repo
    decision, reason = confirm_push.decide(command, str(path))
    assert decision == "deny" and "maintainer" in reason


@pytest.mark.parametrize("command", [
    "gh pr view 12 && git merge origin/main",
    "gh pr view 12 --json state",
    "gh pr list",
    "gh api repos/o/r/pulls/2/comments",
    "gh api repos/o/r/issues/2/comments --paginate",
    "gh api -X GET repos/o/r/pulls/2/comments -f per_page=100",
    "gh api repos/o/r/actions/runs -f status=failure",
    "git merge origin/main",
])
def test_pr_commands_that_dont_merge_or_post_are_left_to_normal_permissions(repo, command):
    path, _ = repo
    assert confirm_push.decide(command, str(path)) is None


@pytest.mark.parametrize("command", [
    "gh pr create --base main --head feature --title 'Add X' --body-file body.md",
    "gh pr edit 12 --body-file body.md",
    "gh pr edit 12 --body-file=body.md",
    "gh pr comment 12 --body-file body.md",
    "gh pr comment 12 -F body.md",
    "gh -R owner/repo pr comment 12 --body-file body.md",
    "gh pr review 12 --comment --body-file body.md",
    "gh issue comment 3 --body-file body.md",
    "gh api repos/o/r/issues/12/comments -F body=@body.md",
    "gh api repos/o/r/pulls/12/comments/99/replies -F body=@body.md",
    "gh api -X PATCH repos/o/r/issues/comments/5 -F body=@body.md",
])
def test_posting_text_from_a_file_asks_and_shows_it(repo, command):
    path, _ = repo
    (path / "body.md").write_text("Adds the floor schedule.\n")
    decision, reason = confirm_push.decide(command, str(path))
    assert decision == "ask" and "PUBLIC" in reason and "Adds the floor schedule." in reason


def test_the_title_is_shown_and_a_long_body_is_cut(repo):
    path, _ = repo
    (path / "body.md").write_text("x" * (confirm_push.SHOWN_CHARS + 50))
    decision, reason = confirm_push.decide("gh pr create --title 'Add X' --body-file body.md", str(path))
    assert decision == "ask" and "Title: Add X" in reason and "truncated" in reason


@pytest.mark.parametrize("command", [
    "gh pr comment 12 --body 'looks good'",
    "gh pr comment 12 -b 'looks good'",
    "gh pr edit 12 --body='new text'",
    "gh pr create --fill",
    "gh pr create --fill-first",
    "gh pr comment 12 --body-file -",
    "gh issue comment 3 --body hi",
    "gh api repos/o/r/issues/12/comments -f body='looks good'",
    "gh api repos/o/r/issues/12/comments --input -",
    "gh api graphql -f query='mutation { addComment(input: {subjectId: \"x\", body: \"hi\"}) { clientMutationId } }'",
    "gh pr comment 12 --body-file missing.md",
    "gh pr comment 12 --body-file body.md && gh pr comment 13 --body-file body.md",
    "sh -c \"gh pr comment 12 --body hi\"",
])
def test_posting_inline_or_unseen_text_is_denied(repo, command):
    path, _ = repo
    (path / "body.md").write_text("text\n")
    assert confirm_push.decide(command, str(path))[0] == "deny"


def test_a_heredoc_script_that_posts_is_denied(repo):
    path, _ = repo
    command = "python3 - <<'EOF'\nimport os\nos.system('gh pr comment 12 --body hi')\nEOF"
    assert confirm_push.decide(command, str(path))[0] == "deny"


@pytest.mark.parametrize("command", [
    "git push origin main",
    "git push origin other",
    "git push -u origin other",
    "git push origin feature:other",
    "git push origin HEAD",
    "git push -f origin feature",
    "git push --force-with-lease origin feature",
    "git push --no-verify",
    "git push origin feature:main",
    "git push --all",
    "git push --tags",
    "git push --mirror",
    "git -C ../other push",
    "git -c core.hooksPath=/dev/null push",
    "GIT_DIR=../other/.git git push",
    "cd ../other && git push",
    "sh -c 'cd ../other && git push'",
    "env -C ../other git push",
    "env --chdir=../other git push",
    "export GIT_DIR=../other/.git; git push",
    "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null; git push",
    "git push origin main && git push",
    "python3 -c \"import subprocess; subprocess.run(['git', 'push', '--no-verify'])\"",
    "git $'pu\\x73h'",
    "git push --no-v''erify",
    "git config core.hooks''Path /dev/null && git push",
    "printf x > .githooks/pre-push; git push",
    "make test && git push",
    "git push | cat",
    "echo 'git push'",
    "git status  # check first\ngit push --force origin main",
    "open http://localhost:4000/#x; git push --all",
    "git push origin main#x; git push origin feature",
    "git push origin feature && git push origin feature",
    "git push  # ship it",
])
def test_uncovered_push_forms_are_denied_even_when_reviewed(repo, command):
    path, head = repo
    record(path, head)
    assert confirm_push.decide(command, str(path))[0] == "deny"


def test_push_denied_without_git_hook_installed(repo):
    path, head = repo
    record(path, head)
    subprocess.run(["git", "-C", str(path), "config", "--unset", "core.hooksPath"], check=True)
    decision, reason = confirm_push.decide("git push", str(path))
    assert decision == "deny" and "make hooks" in reason


def test_push_allowed_with_absolute_hooks_path_to_this_checkout(repo):
    path, head = repo
    record(path, head)
    git(path, "config", "core.hooksPath", str(path / ".githooks"))  # as the worktree tool writes it
    assert confirm_push.decide("git push", str(path))[0] == "ask"


def test_push_denied_with_hooks_path_elsewhere(repo, tmp_path_factory):
    path, head = repo
    record(path, head)
    other = tmp_path_factory.mktemp("other")
    (other / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    (other / "pre-push").chmod(0o755)
    git(path, "config", "core.hooksPath", str(other))
    decision, reason = confirm_push.decide("git push", str(path))
    assert decision == "deny" and "make hooks" in reason


# Paths that collapse to .githooks as text but that git resolves elsewhere
# (a missing directory before `..`; `~` expanded to $HOME).
@pytest.mark.parametrize("value", ["nope/../.githooks", "~/../.githooks", "./.githooks", ".githooks/"])
def test_push_denied_for_any_other_spelling_of_hooks_path(repo, value):
    path, head = repo
    record(path, head)
    git(path, "config", "core.hooksPath", value)
    assert confirm_push.decide("git push", str(path))[0] == "deny"


def test_push_denied_when_git_hook_file_missing(repo):
    path, head = repo
    record(path, head)
    (path / ".githooks" / "pre-push").unlink()
    assert confirm_push.decide("git push", str(path))[0] == "deny"


def test_push_denied_when_git_hook_edited(repo):
    path, head = repo
    record(path, head)
    (path / ".githooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    assert "differs" in confirm_push.decide("git push", str(path))[1]


@pytest.mark.parametrize("config", [
    ["alias.ship", "!git push"],
    ["remote.origin.push", "+refs/heads/*:refs/heads/*"],
    ["remote.origin.pushurl", "https://example.com/other.git"],
    ["push.default", "matching"],
    ["push.default", "upstream"],
    ["branch.feature.remote", "other"],
    ["branch.feature.merge", "refs/heads/main"],
    ["url.https://example.com/.pushInsteadOf", "https://github.com/"],
])
def test_push_denied_when_config_changes_what_is_pushed(repo, config):
    path, head = repo
    record(path, head)
    git(path, "config", *config)
    assert confirm_push.decide("git push", str(path))[0] == "deny"


@pytest.mark.parametrize("config", [
    ["alias.ship", "!git push"],
    ["remote.origin.push", "+refs/heads/*:refs/heads/*"],
    ["remote.origin.pushurl", "https://example.com/other.git"],
    ["push.default", "matching"],
    ["url.https://example.com/.pushInsteadOf", "https://github.com/"],
])
def test_explicit_push_still_denied_when_config_changes_what_is_pushed(repo, config):
    path, head = repo
    record(path, head)
    git(path, "config", *config)
    assert confirm_push.decide("git push -u origin feature", str(path))[0] == "deny"


def test_branch_with_a_name_outside_the_plain_set_is_denied(repo):
    path, head = repo
    git(path, "checkout", "-q", "-b", "a+b")
    record(path, head)
    assert confirm_push.decide("git push -u origin a+b", str(path))[0] == "deny"


def test_branch_named_like_a_tag_uses_its_own_config(repo):
    path, head = repo
    git(path, "tag", "feature")  # `symbolic-ref --short` would now say heads/feature
    record(path, head)
    git(path, "config", "branch.feature.merge", "refs/heads/main")
    assert confirm_push.decide("git push", str(path))[0] == "deny"


def test_explicit_push_allowed_when_a_new_branch_tracks_origin_main(repo):
    path, head = repo
    record(path, head)
    git(path, "config", "branch.feature.remote", "origin")
    git(path, "config", "branch.feature.merge", "refs/heads/main")  # `worktree add -b x origin/main` does this
    assert confirm_push.decide("git push -u origin feature", str(path))[0] == "ask"
    assert confirm_push.decide("git push", str(path))[0] == "deny"  # would go to main


def test_push_allowed_when_branch_tracks_its_origin_branch(repo):
    path, head = repo
    record(path, head)
    git(path, "config", "branch.feature.remote", "origin")
    git(path, "config", "branch.feature.merge", "refs/heads/feature")
    git(path, "config", "push.default", "simple")
    assert confirm_push.decide("git push", str(path))[0] == "ask"


@pytest.fixture
def worktree(repo, tmp_path_factory):
    """A linked worktree of `repo` on branch `wt`, as the worktree tool makes them."""
    path, head = repo
    wt = tmp_path_factory.mktemp("wt") / "checkout"
    git(path, "worktree", "add", "-q", "-b", "wt", str(wt))
    return path, wt, head


def test_push_from_a_worktree_with_relative_hooks_path(worktree):
    path, wt, head = worktree
    record(path, head)
    assert confirm_push.decide("git push -u origin wt", str(wt))[0] == "ask"


def test_push_from_a_worktree_with_hooks_path_to_the_main_checkout(worktree):
    path, wt, head = worktree
    record(path, head)
    git(path, "config", "core.hooksPath", str(path / ".githooks"))  # as the worktree tool writes it
    assert confirm_push.decide("git push -u origin wt", str(wt))[0] == "ask"


def test_push_from_a_worktree_denied_when_its_own_hook_edited(worktree):
    path, wt, head = worktree
    record(path, head)
    (wt / ".githooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")  # relative hooks path: git runs this one
    assert "differs" in confirm_push.decide("git push -u origin wt", str(wt))[1]


def test_push_from_a_worktree_with_hooks_path_to_itself(worktree):
    path, wt, head = worktree
    record(path, head)
    git(path, "config", "core.hooksPath", str(wt / ".githooks"))
    assert confirm_push.decide("git push -u origin wt", str(wt))[0] == "ask"


def test_push_denied_with_hooks_path_to_another_worktree(worktree, tmp_path_factory):
    path, wt, head = worktree
    other = tmp_path_factory.mktemp("wt2") / "checkout"
    git(path, "worktree", "add", "-q", "-b", "wt2", str(other))
    record(path, head)
    git(path, "config", "core.hooksPath", str(other / ".githooks"))
    assert confirm_push.decide("git push -u origin wt", str(wt))[0] == "deny"


def test_push_from_a_worktree_denied_when_main_checkout_hook_edited(worktree):
    path, wt, head = worktree
    record(path, head)
    git(path, "config", "core.hooksPath", str(path / ".githooks"))
    (path / ".githooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    assert "differs" in confirm_push.decide("git push -u origin wt", str(wt))[1]


NOTES = "Set up finch's notes: install via /install-github-app, then run /pre-push."


@pytest.mark.parametrize("command", [
    f"cat > backlog/notes.md <<'EOF'\n{NOTES}\nEOF",
    f"tee -a BOARD.md <<EOF >/dev/null\n{NOTES}\nEOF\necho done",
    f"cat <<-EOF > x.md\n\t{NOTES}\n\tEOF",
    # A python script that only edits text: prose with an apostrophe, "github", "/pre-push".
    f"python3 - <<'PY'\nprint(\"{NOTES}\")\nPY",
    # Unparseable (unbalanced quote), but nothing pushes: "github" and "pre-push" aren't git push.
    f"echo {NOTES}",
])
def test_prose_about_github_and_pre_push_is_not_a_push(repo, command):
    path, _ = repo
    assert confirm_push.decide(command, str(path)) is None


@pytest.mark.parametrize("command", [
    "bash <<'EOF'\ngit push origin main\nEOF",
    "cat <<'EOF' | sh\ngit push origin main\nEOF",
    "tee /dev/null <<EOF | bash\ngit push --all\nEOF",
    # A body written with cat or tee, then run.
    "cat > x.sh <<'EOF'\ngit push origin main\nEOF\nsh x.sh",
    "cat <<EOF > f.sh && bash f.sh\ngit push origin main\nEOF",
    "tee x.sh <<'EOF' >/dev/null\ngh pr merge 5\nEOF\nbash x.sh",
    "x=$(cat <<EOF\ngit push origin main\nEOF\n)\neval \"$x\"",
    "bash <(cat <<EOF\ngit push origin main\nEOF\n)",
    "cat <<EOF >> ~/.zshrc\nalias gp='git push origin HEAD:main'\nEOF",
    "source /dev/stdin <<'EOF'\ngit $'\\x70ush' origin main\nEOF",
    # `<<EOF` inside a quoted message, with no delimiter line: the next line is still a command.
    "git commit -m \"fix; cat <<EOF\"\ngit push origin HEAD:main",
    "sh <<EOF\necho finch's\ngit push --no-verify\nEOF",
    "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'push', '--force'])\nPY",
    "python3 - <<'PY'\nimport os; os.system('gh pr merge 12')\nPY",
    "echo finch's && git push --force origin main",
    "echo don't; gh pr merge 3",
])
def test_pushes_inside_heredocs_or_unparseable_commands_are_still_denied(repo, command):
    path, head = repo
    record(path, head)
    assert confirm_push.decide(command, str(path))[0] == "deny"


def test_non_push_command_gets_no_decision(repo):
    path, _ = repo
    assert confirm_push.decide("git status", str(path)) is None


def run_hook(stdin):
    out = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)
    return out.returncode, out.stdout


def test_hook_fails_closed_on_error():
    code, out = run_hook("not json, but mentions push")
    assert code == 0 and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_error_on_other_command_does_not_block():
    assert run_hook("not json") == (0, "")


# The git pre-push hook (.githooks/pre-push), fed the ref lines git sends it.
GIT_HOOK = pathlib.Path(__file__).parents[1] / ".githooks" / "pre-push"
ZERO = "0" * 40


def git_hook(path, lines):
    return subprocess.run([str(GIT_HOOK), "origin", "url"], cwd=path, input="".join(f"{l}\n" for l in lines),
                          capture_output=True, text=True).returncode


def test_git_hook_allows_reviewed_commit(repo):
    path, head = repo
    record(path, head)
    assert git_hook(path, [f"refs/heads/main {head} refs/heads/main {ZERO}"]) == 0


def test_git_hook_refuses_unreviewed_commit(repo):
    path, head = repo
    assert git_hook(path, [f"refs/heads/main {head} refs/heads/main {ZERO}"]) == 1


def test_git_hook_refuses_non_fast_forward(repo):
    path, head = repo
    git(path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "y")
    remote = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    record(path, head)
    assert git_hook(path, [f"refs/heads/main {head} refs/heads/main {remote}"]) == 1
    record(path, remote)
    assert git_hook(path, [f"refs/heads/main {remote} refs/heads/main {head}"]) == 0


def test_git_hook_refuses_deletion_and_any_unreviewed_ref(repo):
    path, head = repo
    record(path, head)
    assert git_hook(path, [f"(delete) {ZERO} refs/heads/old {head}"]) == 1
    assert git_hook(path, [f"refs/heads/main {head} refs/heads/main {ZERO}",
                           f"refs/tags/v1 {'1' * 40} refs/tags/v1 {ZERO}"]) == 1
