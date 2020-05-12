import sys
from pathlib import Path
import pkg_resources

PYOXIDIZER_ENTRYPOINT = "REMOTE_ENTRYPOINT"
SHIV_ENTRYPOINT = "SHIV_ENTRY_POINT"
TEMPLATE = """\
#!/bin/bash
[ -z "$BASEDIR" ] && export BASEDIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )
%s="%s" exec -a %s $BASEDIR/bin/remote-exec "$@"
"""


def main():
    """Create shell wrappers for every entry point pointing to main executable"""
    output_dir = Path(sys.argv[1])
    entry_point_env = PYOXIDIZER_ENTRYPOINT
    if len(sys.argv) > 2 and sys.argv[2] == "--shiv":
        entry_point_env = SHIV_ENTRYPOINT
    resources = pkg_resources.get_entry_map("remote-exec", "console_scripts")
    for name, entry in resources.items():
        file = output_dir / name
        if entry.module_name != "remote.entrypoints":
            raise RuntimeError(f"Unexpected entry point: {entry}")
        entry_point_str = (
            f"{entry.module_name}:{entry.attrs[0]}" if entry_point_env == SHIV_ENTRYPOINT else entry.attrs[0]
        )
        file.write_text(TEMPLATE % (entry_point_env, entry_point_str, name))
        file.chmod(0o755)
        print(f"Processed {entry}")


if __name__ == "__main__":
    main()
