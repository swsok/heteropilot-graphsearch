"""The submodule pointer this repository records is the one checked out.

`git -C vendor/heteropilot status --porcelain` is the gate CLAUDE.md names, and
it answers a narrower question than it looks: whether the submodule's own
working tree is clean. It says nothing about whether the commit this repository
*records* is the commit that is *checked out*.

Those came apart once. A bump to the hook H4 merge was committed on one branch
while a later `git push` named another, so `main` recorded the old commit while
every local run used the new one -- and the gate passed throughout, because the
submodule's working tree was clean at both. Every result produced in that state
was produced against code the repository did not claim to be using.
"""

from __future__ import annotations

import subprocess

from graphsearch import paths_root

ROOT = paths_root.GRAPHSEARCH_ROOT
SUBMODULE = "vendor/heteropilot"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def test_the_recorded_pointer_is_the_checked_out_commit() -> None:
    recorded = _git("ls-tree", "HEAD", SUBMODULE).split()
    assert recorded, f"{SUBMODULE} is not recorded in HEAD"
    checked_out = _git("-C", SUBMODULE, "rev-parse", "HEAD")
    assert recorded[2] == checked_out, (
        f"{SUBMODULE}: HEAD records {recorded[2][:12]} but the working tree is "
        f"at {checked_out[:12]}. Every result produced now is produced against "
        f"code this repository does not claim to be using. Either commit the "
        f"bump or check the recorded commit back out."
    )


def test_the_submodule_working_tree_is_clean() -> None:
    """The gate CLAUDE.md names, asserted here so a run says which one failed."""
    dirt = _git("-C", SUBMODULE, "status", "--porcelain")
    assert not dirt, (
        f"{SUBMODULE} has local modifications:\n{dirt}\nIt is read-only: a "
        f"change there is a pull request in that repository followed by a "
        f"submodule bump here."
    )
