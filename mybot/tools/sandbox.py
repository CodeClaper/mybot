import shlex
import sys
import tempfile
from pathlib import Path
from loguru import logger

from mybot.config.path import get_media_dir

_IS_LINUX = sys.platform.startswith("linux")
_IS_DARWIN = sys.platform == "darwin"

def _bwrap(command: str, workspace: str, cwd: str) -> str:
    """Wrap command in a bubblewrap sandbox (requires bwrap in container).

    Only the workspace is bind-mounted read-write; its parent dir (which holds
    config.json) is hidden behind a fresh tmpfs.  The media directory is
    bind-mounted read-only so exec commands can read uploaded attachments.
    """
    if not _IS_LINUX:
        raise RuntimeError(
            f"bwrap sandbox is only supported on Linux (current platform: {sys.platform})"
        )

    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    required  = ["/usr"]
    optional  = ["/bin", "/lib", "/lib64", "/etc/alternatives",
                 "/etc/ssl/certs", "/etc/resolv.conf", "/etc/ld.so.cache"]

    args = ["bwrap", "--new-session", "--die-with-parent"]
    for p in required: args += ["--ro-bind",     p, p]
    for p in optional: args += ["--ro-bind-try", p, p]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", str(ws.parent),        # mask config dir
        "--dir", str(ws),                 # recreate workspace mount point
        "--bind", str(ws), str(ws),
        "--ro-bind-try", str(media), str(media),  # read-only access to media
        "--chdir", sandbox_cwd,
        "--", "sh", "-c", command,
    ]
    return shlex.join(args)

def _build_sandbox_profile(workspace: str, media: str) -> str:
    """Build a macOS sandbox-exec profile (Apple Sandbox Profile Language).

    Default-deny with explicit allowances:
    - Read-write: workspace, /tmp, /var/tmp
    - Read-only: media, system paths (/usr, /bin, /etc, /dev, ...)
    - Process execution from standard binary paths
    - Outbound network (matching bwrap behaviour which doesn't restrict it)
    """
    return f"""(version 1)
(deny default)
(allow signal (target self))
(allow sysctl-read)
(allow process-exec
    (subpath "/usr/bin")
    (subpath "/usr/sbin")
    (subpath "/usr/libexec")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/opt/homebrew/bin")
    (subpath "/usr/local/bin")
)
(allow file-read*
    (subpath "/usr")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/etc")
    (subpath "/private/etc")
    (subpath "/var")
    (subpath "/dev")
    (subpath "/System/Library")
    (subpath "/Library/Apple")
    (subpath "/Library/Frameworks")
    (subpath "/opt/homebrew")
    (subpath "/usr/local")
    (literal "{media}")
)
(allow file-read* file-write*
    (subpath "{workspace}")
    (subpath "/private/tmp")
    (subpath "/tmp")
    (subpath "/private/var/tmp")
)
(allow network-outbound)
"""


def _sandbox_exec(command: str, workspace: str, cwd: str) -> str:
    """Wrap command using macOS sandbox-exec for sandboxed execution.

    The workspace parent directory (where config.json lives) is inaccessible
    by default — the profile only allows access to the workspace itself.
    The media directory is mounted read-only via the profile.
    """
    if not _IS_DARWIN:
        raise RuntimeError(
            f"sandbox-exec sandbox is only supported on macOS (current platform: {sys.platform})"
        )

    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    profile = _build_sandbox_profile(str(ws), str(media))
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sb", delete=False, prefix="mybot_sandbox_"
    ) as f:
        f.write(profile)
        profile_path = f.name

    # sandbox-exec has no --chdir, so prepend cd to set the working directory
    wrapped = f"cd {shlex.quote(sandbox_cwd)} && {command}"
    args = [
        "sandbox-exec", "-f", profile_path,
        "--", "sh", "-c", wrapped,
    ]
    return shlex.join(args)

_BACKENDS = {"bwrap": _bwrap, "sand_exec": _sandbox_exec}


def wrap_command(sandbox: str, command: str, workspace: str, cwd: str) -> str:
    """Wrap *command* using the named sandbox backend."""
    logger.debug(f"workspace: {workspace}, cwd: {cwd}")
    if backend := _BACKENDS.get(sandbox):
        logger.debug(f"Using sandbox type: {sandbox}")
        return backend(command, workspace, cwd)
    raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
