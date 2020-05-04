import sys
from pathlib import Path
import pkg_resources

TEMPLATE = """\
#!/bin/bash
[ -z "$BASEDIR" ] && export BASEDIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )
REMOTE_ENTRYPOINT="%s" exec -a %s $BASEDIR/bin/remote-exec "$@"
"""


def main():
    """Create shell wrappers for every entry point pointing to main executable"""
    output_dir = Path(sys.argv[1])
    resources = pkg_resources.get_entry_map("remote-exec", "console_scripts")
    for name, entry in resources.items():
        file = output_dir / name
        if entry.module_name != "remote.entrypoints":
            raise RuntimeError(f"Unexpected entry point: {entry}")
        file.write_text(TEMPLATE % (entry.attrs[0], name))
        file.chmod(0o755)
        print(f"Processed {entry}")


if __name__ == "__main__":
    main()
