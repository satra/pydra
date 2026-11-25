import re
from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).parents[3] / ".pre-commit-config.yaml"


def _pattern() -> "re.Pattern[str]":
    hooks = [h for r in yaml.safe_load(CONFIG.read_text())["repos"] for h in r["hooks"]]
    (hook,) = [h for h in hooks if h["id"] == "no-review-ids"]
    return re.compile(hook["entry"])


# Built by concatenation, so that this file passes the hook it tests
REJECTED = [
    "# the fix" + " round 2 change",
    "(N" + "1, IMP-2)",
    "(N" + "2a)",
    "(B" + "-r3)",
    "(review" + " r1, I2, I3)",
    "I1 probe" + " W2",
    "measured" + " on R1",
    "Inert until" + " R7",
    "a partial node, after" + " E2",
    "(R7" + " follow-on)",
    '"""O' + "2: a docstring",
    '"""NB' + "1: a docstring",
    "the X" + "6b lookup",
    "ruling" + " R4",
    "R-" + "287",
]

ACCEPTED = [
    "f(t1)",
    "(RFC 0002 section 3.2)",
    "The R7 driver model (RFC 0002)",
    "x = (i1, i2)",
    "a review of the inputs",
    "a downstream project name",
    "the image's repository (I6a)",  # an RFC unit name
    "pool facts (W11b)",
]


@pytest.mark.parametrize("text", REJECTED)
def test_the_hook_rejects_review_ids_and_history(text):
    assert _pattern().search(text)


@pytest.mark.parametrize("text", ACCEPTED)
def test_the_hook_accepts_ordinary_code_and_rfc_labels(text):
    assert not _pattern().search(text)
