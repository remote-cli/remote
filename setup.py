import os
import setuptools


def get_version():
    root = os.path.dirname(__file__)
    changelog = os.path.join(root, "CHANGELOG")
    with open(changelog) as f:
        return f.readline().strip()


setuptools.setup(
    name="remote-exec",
    version=get_version(),
    url="https://github.com/shirshanka/remote",
    author="Shirshanka Das",
    license="BSD-2-CLAUSE",
    description="A CLI to sync codebases and execute commands remotely",
    package_dir={"": "src"},
    packages=setuptools.find_namespace_packages(where="src"),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "remote = remote.entrypoints:remote",
            "remote-add = remote.entrypoints:remote_add",
            "remote-delete = remote.entrypoints:remote_delete",
            "remote-explain = remote.entrypoints:remote_explain",
            "remote-host = remote.entrypoints:remote_host",
            "remote-ignore = remote.entrypoints:remote_ignore",
            "remote-init = remote.entrypoints:remote_init",
            "remote-pull = remote.entrypoints:remote_pull",
            "remote-push = remote.entrypoints:remote_push",
            "remote-quick = remote.entrypoints:remote_quick",
            "remote-set = remote.entrypoints:remote_set",
            "mremote = remote.entrypoints:mremote",
            "mremote-push = remote.entrypoints:mremote_push",
        ],
    },
)
