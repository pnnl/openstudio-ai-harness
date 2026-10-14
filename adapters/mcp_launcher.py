"""Start a pinned OpenStudio AI runtime command, preferring uv's cache.

Marketplace `.mcp.json` files inline this file's source:

    uv run --no-project --python <range> python -I -c <source> \
        <uv tool run options> -- <command> [args...]

The options must include `--from <exact spec>`: the cache probe runs `python`
from that environment, so without it the probe would test the wrong thing.

The runtime pins exact releases, so a cached environment can never be out of
date. Try it offline first: that is instant and needs no network. Fall back to
a normal online `uv tool run` only when the cache does not have it yet.

Probe first, then launch once, rather than launching offline and retrying
online on failure: after the server starts, a failure could come from the
server itself, and it may already have read the host's MCP messages.

Standard library only: this runs before the runtime environment exists.

On Windows the host's process tree is host -> python -> uv -> server; if the
host kills only this process, the server may outlive it.
"""

import os
import shutil
import subprocess
import sys


def launch_argv(uv, options, command, cached):
    """Return the `uv tool run` argv, offline when the environment is cached."""
    offline = ["--offline"] if cached else []
    return [uv, "tool", "run", *offline, *options, *command]


def environment_is_cached(uv, options):
    """Whether uv can build the pinned environment without the network.

    A nonzero exit is treated as a cache miss; the online launch that follows
    reports any real problem on stderr.
    """
    probe = subprocess.run(
        [uv, "tool", "run", "--offline", *options, "python", "-c", ""],
        # stdin is the host's MCP channel; the probe must not read from it.
        stdin=subprocess.DEVNULL,
        # stdout is the MCP channel too; any probe output would corrupt it.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def fail(message, code):
    print(f"openstudio-ai launcher: {message}", file=sys.stderr)
    return code


def main(argv):
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        return fail("expected `<uv tool run options> -- <command>`", 2)
    split = argv.index("--")
    options, command = argv[:split], argv[split + 1 :]
    if "--from" not in options:
        return fail("expected `--from <spec>` in the uv tool run options", 2)
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        return fail("`uv` was not found.", 127)
    try:
        cached = environment_is_cached(uv, options)
        if not cached:
            print(
                "openstudio-ai launcher: runtime not in uv's cache; downloading it.",
                file=sys.stderr,
            )
        final = launch_argv(uv, options, command, cached)
        if os.name != "nt":
            os.execv(uv, final)
        # Windows has no real exec; run the server as a child that inherits stdio.
        return subprocess.run(final, check=False).returncode
    except OSError as error:
        return fail(f"could not run uv at {uv!r}: {error}", 127)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
