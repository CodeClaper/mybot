
import mimetypes
import os
from pathlib import Path
from typing import Any

from mybot.config.path import get_media_dir
from mybot.tools.base import Tool
from mybot.tools.fielstate import FileStates, current_file_states, _hash_file
from mybot.utils.helper import build_image_content_blocks, detect_image_mime


_FS_WORKSPACE_BOUNDARY_NOTE = (
    " (this is a hard policy boundary, not a transient failure; "
    "do not retry with shell tricks or alternative tools, and ask "
    "the user how to proceed if the resource is genuinely required)"
)

class _FsTool(Tool):
    """Shared base for filesystem tool."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        extra_allowed_dirs: list[Path] | None = None,
        file_states: FileStates | None = None,
    ) -> None:
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._extra_allowed_dirs = extra_allowed_dirs
        # Explicit state is used by isolated runners like Dream/subagents.
        # Main AgentLoop tools leave this unset and resolve state from the
        # current async task, which keeps shared tool instances session-safe.
        self._explicit_file_states = file_states
        self._fallback_file_states = FileStates()

    
    @property
    def _file_states(self) -> FileStates:
        if self._explicit_file_states is not None:
            return self._explicit_file_states
        return current_file_states(self._fallback_file_states)

    def _resolve(self, path: str) -> Path:
        """Resolve path against workspace (if relative) and enforce directory restriction."""
        p = Path(path).expanduser()
        if not p.is_absolute() and self._workspace:
            p = self._workspace / p
        resolved = p.resolve()
        if self._allowed_dir:
            media_path = get_media_dir().resolve()
            all_dirs = [self._allowed_dir] + [media_path] + (self._extra_allowed_dirs or [])
            if not any(self._is_under(resolved, d) for d in all_dirs):
                raise PermissionError(
                    f"Path {path} is outside allowed directory {self._allowed_dir}" 
                    + _FS_WORKSPACE_BOUNDARY_NOTE
                )

        return resolved

    def _is_under(self, path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory.resolve())
            return True
        except ValueError:
            return False



#--------------------------------------------------
# read file.
#--------------------------------------------------

_BLOCKED_DEVICE_PATHS = frozenset({
    "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full",
    "/dev/stdin", "/dev/stdout", "/dev/stderr",
    "/dev/tty", "/dev/console",
    "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
})


def _is_blocked_device(path: str | Path) -> bool:
    """Check if path is a blocked device."""
    import re
    raw = str(path)

    try:
        resolved = str(Path(raw).resolve())
    except (OSError, ValueError):
        resolved = raw

    if raw in _BLOCKED_DEVICE_PATHS or resolved in _BLOCKED_DEVICE_PATHS:
        return True
    if re.match(r"/proc/\d+/fd/[012]$", raw) or re.match(r"/proc/self/fd/[012]$", raw):
        return True
    if re.match(r"/proc/\d+/fd/[012]$", resolved) or re.match(r"/proc/self/fd/[012]$", resolved):
        return True

    # Check if resolved path starts with /dev/ (covers symlinks to devices)
    if resolved.startswith("/dev/"):
        return True
    return False


class ReadFileTool(_FsTool):
    """Read file contents with optional line-based pagination."""

    _MAX_CHARS = 128_000
    _MAX_PDF_PAGES = 20
    _DEFAULT_LIMIT = 2000

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read a file (text, image, or document). "
            "Text output format: LINE_NUM|CONTENT. "
            "Images return visual content for analysis. "
            "Supports PDF, DOCX, XLSX, PPTX documents. "
            "Use offset and limit for large text files. "
            "Reads exceeding ~128K chars are truncated."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed, default 1)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maxinum number of lines to read (default 2000)"
                },
                "pages": {
                    "type": "string",
                    "description": "Page range for PDF files, e.g. '1-5' (default: all, max 20 pages)"
                }
            },
            "required": ["path"]
        }

    
    async def execute(self, path: str | None = None, offset: int = 1, limit: int | None = None, pages: str | None = None, **kwargs: Any) -> Any:
        try:
            if not path:
                return "Error reading file: Unknown path"

            # Device path blacklist
            if _is_blocked_device(path):
                return f"Error: Reading {path} is blocked (device path that could hang or produce infinite output)."

            fp = self._resolve(path)
            if _is_blocked_device(fp):
                return f"Error: Reading {fp} is blocked (device path that could hang or produce infinite output)."
            if not fp.exists():
                return f"Error: File not found: {path}"
            if not fp.is_file():
                return f"Error: Not a file: {path}"

            # PDF support
            if fp.suffix.lower() == ".pdf":
                return self._read_pdf(fp, pages)

            # Office document support
            if fp.suffix.lower() in {".docx", ".xlsx", ".pptx"}:
                return self._read_office_doc(fp)

            raw = fp.read_bytes()
            if not raw:
                return f"(Empty file: {path})"

            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if mime and mime.startswith("image/"):
                return build_image_content_blocks(raw, mime, str(fp), f"(Image file: {path})")

            # Read dedup: same path + offset + limit + unchanged mtime → stub
            # Always check for external modifications before dedup
            entry = self._file_states.get(fp)
            try:
                current_mtime = os.path.getmtime(fp)
            except OSError:
                current_mtime = 0.0
            if entry and entry.can_dedup and entry.offset == offset and entry.limit == limit:
                if current_mtime != entry.mtime:
                    # File was modified externally - force full read and mark as not dedupable
                    entry.can_dedup = False
                    self._file_states.record_read(fp, offset=offset, limit=limit)  # Update state with new mtime
                    # Continue to read full content (don't return dedup message)
                else:
                    # File unchanged - return dedup message
                    # But only if content is actually unchanged (not just mtime)
                    current_hash = _hash_file(str(fp))
                    if current_hash == entry.content_hash:
                        return f"[File unchanged since last read: {path}]"
                    else:
                        # Content changed despite same mtime - force full read
                        entry.can_dedup = False
                        self._file_states.record_read(fp, offset=offset, limit=limit)
            else:
                # No previous state or marked as not dedupable - read full content
                self._file_states.record_read(fp, offset=offset, limit=limit)
                # Force full read by setting can_dedup to False for this read
                if entry:
                    entry.can_dedup = False

            # Read the file content after dedup check
            raw = fp.read_bytes()
            try:
                text_content = raw.decode("utf-8")
            except UnicodeDecodeError:
                # Binary file - return error message
                mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
                if mime and mime.startswith("image/"):
                    return build_image_content_blocks(raw, mime, str(fp), f"(Image file: {path})")
                return f"Error: Cannot read binary file {path} (MIME: {mime or 'unknown'}). Only UTF-8 text and images are supported."

            # Normalize CRLF -> LF before line-splitting. Primarily a Windows
            # concern (git checkouts with autocrlf, editors saving CRLF) but
            # applied on all platforms so downstream StrReplace/Grep behavior
            # is consistent regardless of where the file was written.
            text_content = text_content.replace("\r\n", "\n")

            all_lines = text_content.splitlines()
            total = len(all_lines)

            if offset < 1:
                offset = 1
            if offset > total:
                return f"Error: offset {offset} is beyond end of file ({total} lines)"

            start = offset - 1
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            if len(result) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            if end < total:
                result += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
            else:
                result += f"\n\n(End of file — {total} lines total)"
            self._file_states.record_read(fp, offset=offset, limit=limit)
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {e}"


    def _read_pdf(self, fp: Path, pages: str | None) -> str:
        try:
            import fitz  # pymupdf
        except ImportError:
            return "Error: PDF reading requires pymupdf. Install with: pip install pymupdf"

        try:
            doc = fitz.open(str(fp))
        except Exception as e:
            return f"Error reading PDF: {e}"

        total_pages = len(doc)
        if pages:
            try:
                start, end = self._parse_page_range(pages, total_pages)
            except (ValueError, IndexError):
                doc.close()
                return f"Error: Invalid page range '{pages}'. Use format like '1-5'."
            if start > end or start >= total_pages:
                doc.close()
                return f"Error: Page range '{pages}' is out of bounds (document has {total_pages} pages)."
        else:
            start = 0
            end = min(total_pages - 1, self._MAX_PDF_PAGES - 1)

        if end - start + 1 > self._MAX_PDF_PAGES:
            end = start + self._MAX_PDF_PAGES - 1

        parts: list[str] = []
        for i in range(start, end + 1):
            page = doc[i]
            text = str(page.get_text()).strip()
            if text:
                parts.append(f"--- Page {i + 1} ---\n{text}")
        doc.close()

        if not parts:
            return f"(PDF has no extractable text: {fp})"

        result = "\n\n".join(parts)
        if end < total_pages - 1:
            result += f"\n\n(Showing pages {start + 1}-{end + 1} of {total_pages}. Use pages='{end + 2}-{min(end + 1 + self._MAX_PDF_PAGES, total_pages)}' to continue.)"
        if len(result) > self._MAX_CHARS:
            result = result[:self._MAX_CHARS] + "\n\n(PDF text truncated at ~128K chars)"
        return result

    def _read_office_doc(self, fp: Path) -> str:
        from mybot.utils.document import extract_text

        result = extract_text(fp)

        if result is None:
            return f"Error: Unsupported file format: {fp.suffix}"

        if result.startswith("[error:"):
            return f"Error reading {fp.suffix.upper()} file: {result}"

        if not result:
            return f"({fp.suffix.upper().lstrip('.')} has no extractable text: {fp})"

        if len(result) > self._MAX_CHARS:
            result = result[:self._MAX_CHARS] + "\n\n(Document text truncated at ~128K chars)"

        return result

    def _parse_page_range(self, pages: str, total: int) -> tuple[int, int]:
        """Paarse a page range like '2-5' into 0-based (start, end) inclusive."""
        parts = pages.strip().split("-")
        if len(parts) == 1:
            p = int(parts[0])
            return max(0, p - 1), min(p - 1, total - 1)
        start = int(parts[0])
        end = int(parts[1])
        return max(0, start - 1), min(end - 1, total - 1)
        


class WriteFileTool(_FsTool):
    """Write content to a file."""
    _scopes = {"core", "subagent", "memory"}

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Overwrites if the file already exists; "
            "creates parent directories as needed. "
            "For partial edits, prefer edit_file instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str | None = None, content: str | None = None, **kwargs: Any) -> str:
        try:
            if not path:
                raise ValueError("Unknown path")
            if content is None:
                raise ValueError("Unknown content")
            fp = self._resolve(path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            self._file_states.record_write(fp)
            return f"Successfully wrote {len(content)} characters to {fp}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {e}"

