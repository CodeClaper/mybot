import re
from pathlib import Path

from mybot.agent.skill import SkillLoader

_SKILL_FONTMATTER = re.compile(r"<skills>\n(.*?)\n</skills>")

def _workspace_path() -> Path:
    return Path("~/.mybot").expanduser()

def test_skill_summary():
    loader = SkillLoader(_workspace_path())
    summary = loader.build_skills_summary()
    print(summary)


