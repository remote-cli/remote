import os
import setuptools


def get_version():
    root = os.path.dirname(__file__)
    changelog = os.path.join(root, "CHANGELOG")
    with open(changelog) as f:
        return f.readline().strip()


def get_long_description():
    root = os.path.dirname(__file__)
    with open(os.path.join(root, "README.md")) as f:
        description = f.read()

    description += "\n\nChangelog\n=========\n\n"

    with open(os.path.join(root, "CHANGELOG")) as f:
        description += f.read()

    return description


setuptools.setup(
    name="remote-exec",
    version=get_version(),
    url="https://github.com/shirshanka/remote",
    author="Shirshanka Das",
    license="BSD-2-CLAUSE",
    description="A CLI to sync codebases and execute commands remotely",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved",
        "License :: OSI Approved :: BSD License",
        "Operating System :: Unix",
        "Operating System :: POSIX :: Linux",
        "Environment :: Console",
        "Environment :: MacOS X",
        "Topic :: Software Development",
    ],
    python_requires=">=3.6",
    package_dir={"": "src"},
    packages=["remote", "remote.configuration"],
    include_package_data=True,
    package_data={"remote": ["py.typed"]},
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
    install_requires=[
        'dataclasses; python_version<="3.6"',
        "click>=7.1.1",
        "toml>=0.10.0",
        "pydantic>=1.5.1",
        "watchdog>=0.10.3",
    ],
)
