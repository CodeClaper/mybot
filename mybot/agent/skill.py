
import json
import os
import re
import shutil
from pathlib import Path

## Default builtin skills direcotry.
BUILTIN_SKILL_DIR = Path(__file__).parent.parent / "skills"
STRIP_SKILL_FRONTMATTER = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)

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
            return [s for s in skills if self._check_avaliable(self._get_skill_meta(s["name"]))]           

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

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_name: list of skill name to load.
        Returns:
            Fromatted skills content.
        """
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]

        return "\n\n---\n\n".join(parts)

    def build_skills_summary(self) -> str:
        """
        Build a summary of a all skills (include name, description, path, availablity).

        This is used for progressive loading - the agent can read the full skill content
        using read_file when needed.

        Returns:
            XML-frommatted skills summary.
        """
        all_skills = self.list_skills(filter_unavaliable=False)
        if not all_skills:
            return ""

        lines: list[str] = ["<skills>"]
        for entry in all_skills:
            name = entry["name"]
            meta = self._get_skill_meta(name)
            description = self._get_skill_description(name)
            available = self._check_avaliable(meta)
            lines.extend(
                [
                    f' <skill available="{str(available).lower()}">',
                    f"      <name>{self._escape_xml(name)}</name>",
                    f"      <description>{self._escape_xml(description)}</description>",
                    f"      <location>{entry['path']}</location>",
                ]
            )
            if not available:
                missing = self._get_missing_requirements(meta)
                if missing:
                    lines.append(f"     <requires>{self._escape_xml(missing)}</requires>")
            lines.append(" </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=True that meet requirements."""
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavaliable=True)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_metadata(meta.get("metadata", "")).get("always") or meta.get("always")
            )
        ]


    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.
        
        Args:
            name: Skill name.
        Return:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None
        
        if content.startswith("---"):
            match = STRIP_SKILL_FRONTMATTER.match(content)
            if match:
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata
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

    def _get_skill_meta(self, name: str) -> dict:
        """Get a skill metadata. """
        meta = self.get_skill_metadata(name) or {}
        return self._parse_metadata(meta.get("metadata", ""))

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name) or {}
        if meta.get("description"):
            return meta["description"]
        return name ## Fallback to name.

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return ", ".join(
            [f"CLI: {cmd_name}" for cmd_name in required_bins if not shutil.which(cmd_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )


    def _parse_metadata(self, raw: str) ->dict:
        try:
            data = json.loads(raw)
            return data.get("mybot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError): 
            return {}


    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _escape_xml(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")



