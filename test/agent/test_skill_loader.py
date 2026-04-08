from pathlib import Path
from mybot.agent.skill import SkillLoader

def _workspace_path() -> Path:
    return Path("~/.mybot").expanduser()

def test_skill_summary():
    loader = SkillLoader(_workspace_path())
    summary = loader.build_skills_summary()
    assert summary == ""


