"""The part of the night run that looks at GitHub: whether the rules are still there that the trust of all clouds rests on.

It needs no identity of a cloud. It notices a rule that is gone, and cannot prevent it. night.py calls it.
"""

from check_sign_in import SUBJECTS, Unusable
from github_checks import LimitReached, check_environments

IN_PLACE = "in place"


def night_github(env, fetch):
    """Yields what is looked at, what should come of it, and what did, for every repo. GitHub shows these rules to
    everyone, and to a job's own token more often than 60 times an hour."""
    if not env.get("GITHUB_TOKEN"):
        raise Unusable("Not set: GITHUB_TOKEN.")
    for repo in SUBJECTS:
        try:
            problems = check_environments(repo, fetch)
        except LimitReached:
            raise Unusable(f"GitHub did not show the rules of {repo}: not allowed, or asked too often.") from None
        yield f"find the rules of {repo}", IN_PLACE, "; ".join(problems) or IN_PLACE
