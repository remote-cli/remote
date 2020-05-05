def make_dist():
    return default_python_distribution()

def make_exe(dist):
    python_config = PythonInterpreterConfig(
        run_eval="import os; from remote import entrypoints; getattr(entrypoints, os.getenv('REMOTE_ENTRYPOINT', 'remote'))()",
    )

    exe = dist.to_python_executable(
        name="remote-exec",
        config=python_config,
        extension_module_filter='no-libraries',
        include_sources=False,
        include_resources=False,
        include_test=False,
    )

    exe.add_in_memory_python_resources(dist.pip_install(["."]))

    return exe

def make_embedded_resources(exe):
    return exe.to_embedded_resources()

def make_install(exe):
    return FileManifest()

# Tell PyOxidizer about the build targets defined above.
register_target("dist", make_dist)
register_target("exe", make_exe, depends=["dist"], default=True)
register_target("resources", make_embedded_resources, depends=["exe"], default_build_script=True)
register_target("install", make_install, depends=["exe"])

# Resolve whatever targets the invoker of this configuration file is requesting
# be resolved.
resolve_targets()

# END OF COMMON USER-ADJUSTED SETTINGS.
#
# Everything below this is typically managed by PyOxidizer and doesn't need
# to be updated by people.

PYOXIDIZER_VERSION = "0.7.0"
PYOXIDIZER_COMMIT = "UNKNOWN"
