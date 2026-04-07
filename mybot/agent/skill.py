
import os
import shutil
from pathlib import Path

## Default builtin skills direcotry.
BUILTIN_SKILL_DIR = Path(__file__).parent.parent / "skills"

class SkillLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to 
    use special tools or perfom certain tasks 
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None) -> None:
        self.workspace = workspace
        self.workpace_skills_dir = workspace / "skills"
        self.builtin_skills_dir = builtin_skills_dir or BUILTIN_SKILL_DIR


    def list_skills(self, filter_unavaliable: bool = True) -> list[dict[str, str]]:
        """ 
        List all available skills. 

        Args:
            filter_unavaliable: If True, filter out skills that are unavaliable.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'
        """

        skills: list[dict[str, str]] = []
        
        # Workspace skills (highest priority)
        if self.workpace_skills_dir.exists():
            for skill_dir in self.workpace_skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        ## Builtin skills.
        if self.builtin_skills_dir.exists():
            for skill_dir in self.builtin_skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})
        
        if filter_unavaliable:
            return [s for s in skills if self._check_avaliable(s)]           

        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args: 
            name: Skill name (direcotry name).
        Returns:
            Skill content or None if not found.
        """

        workspace_skill = self.workpace_skills_dir / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        if self.builtin_skills_dir:
            bultin_skill = self.builtin_skills_dir / name / "SKILL.md"
            if bultin_skill.exists():
                return bultin_skill.read_text(encoding="utf-8")
        return None

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        """
        return None

    
    def _check_avaliable(self, skill_meta: dict) -> bool:
        """Check if skill is available. """
        requires = skill_meta.get("requires", {}) or {}
        for bin in requires.get("bins", []):
            if not shutil.which(bin):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True


