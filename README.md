# Remote

[![Code Quality](https://github.com/remote-cli/remote/workflows/Python%20Code%20Quality/badge.svg)](https://github.com/remote-cli/remote/actions?query=branch%3Amaster+workflow%3A%22Python+Code+Quality%22)
[![pypi](https://img.shields.io/pypi/v/remote-exec.svg)](https://pypi.org/project/remote-exec)
[![versions](https://img.shields.io/pypi/pyversions/remote-exec.svg)](https://github.com/remote-cli/remote)
[![license](https://img.shields.io/github/license/remote-cli/remote.svg)](https://github.com/remote-cli/remote/blob/master/LICENSE)

The `remote` CLI lets you execute long or computation-heavy tasks (e.g. compilation, integration tests etc.)
on a powerful remote host while you work on the source code locally.
This process is known as remote execution and can be used to enable remote build capabilities among other things.

When you execute `remote <cmd>`, it will first sync your local workspace to the remote host you selected using `rsync`.
It will then execute the command `<cmd>` on this host using `ssh` and finally, bring all the created/modified files back to your local workspace.
`remote` supports a host of configuration options to allow for complete customization of patterns for files and folders to include during the synchronization process in both directions.

## System Requirements

The CLI supports **Linux** and **Mac OS X** operating systems
with **Python 3.6 or higher** installed. You can also use it on **Windows**
if you have [WSL](https://docs.microsoft.com/en-us/windows/wsl/about) configured.

The remote host must also be running on **Linux** or **Mac OS X**. The local and remote hosts can be running different operating systems. The only requirement is that the remote host must be accessible using `ssh` from the local host.

## Getting Started

### Installing on Mac OS X

If you use Mac OS X, you can install `remote` using [Homebrew](https://brew.sh/)
from our [custom tap](https://github.com/remote-cli/homebrew-remote):

```bash
brew install remote-cli/remote/remote
```

Then, you will always be able to update it to the latest version:

```bash
brew upgrade remote
```

### Installing on other systems

`remote` doesn't support any package managers other than `brew` yet. However, it can be manually downloaded
and installed. To do it, visit https://github.com/remote-cli/remote/releases and download the latest released `-shiv` archive, unpack it to some local directory (e.g., `~/.bin`) and add it to PATH:

```bash
mkdir -p ~/.bin
tar -C ~/.bin -xzf ~/Downloads/remote-1.4.5-shiv.tgz
echo 'export PATH=$PATH:/home/username/.bin/remote/bin' >> ~/.bash_profile
source ~/.bash_profile
```

Don't forget to replace the `/home/username` above with the actual path to your home directory.

### Configuring the remote host

`remote` CLI needs to be able to establish a passwordless SSH connection to the remote host.
Please run `ssh -o BatchMode yes <your-host> echo OK` to confirm that everything is ready for you.
If this command fails, please go through [SSH guide](https://www.ssh.com/ssh/keygen/) to set up
SSH keys locally and remotely.

### First run

After you are done with the configuration, switch the working directory to the root of your workspace in
terminal and run `remote-init` to create a configuration file:

```bash
cd ~/path/to/workspace
remote-init remote-host.example.com
```

This will create a config file named `.remote.toml` in the workspace root
(`~/path/to/workspace/.remote.toml`). This file controls the remote connection and synchronization options.
You can read more about this file in the Configuration section of this doc.

After it, you can start using remote:

```bash
# This will sync workspace and run './gradlew build' remotely
remote ./gradlew build

# This will forcefully push all local files to the remote machine
remote-push

# This will bring in ./build directory from the remote machine to local even if
# the CLI is configured to ignore it
remote-pull build
```

## Distribution

`remote`'s distribution comes with a set of executables:

* `remote-init`: set up a local directory to point to a remote directory on a target host
* `remote-ignore`: set up directories/files to ignore while pushing
* `remote-push`: explicitly push local changes remote
* `remote-pull`: pull a directory from remote to local
* `remote`: execute a command remotely, after first syncing the local tree with the remote tree
* `remote-explain`: explain your remote setup, explain what command actually will get run
* `remote-quick`: execute a command remotely without syncing the trees
* `remote-add`: add another remote host to the mirror list
* `mremote`: execute a remote command on all the hosts, after first syncing the local tree with the remote trees

You can run each of these commands with `--help` flag to get a list of options and arguments they accept.

## Configuration

Three configuration files control the behavior of `remote`:

* `~/.config/remote/defaults.toml` is a global config file. It sets options that affect all the workspaces
  unless they are overwritten by `.remote.toml` file.
* `.remote.toml` is a workspace config that is expected to be placed in the root of every workspace.
  The `remote` CLI cannot execute any commands remotely until this file is present, or the global config
  overwrites this with `allow_uninitiated_workspaces` option.
* `.remoteignore.toml` is a workspace config that controls only sync exlude and include patterns
  and has the highest priority. While the same settings can be specified in the `.remote.toml` file,
  you can use this file to check in project-specific ignore settings in the VCS because it doesn't contain
  host-specific information in it.

Both configs use [TOML](https://github.com/toml-lang/toml) format.

**Workspace root** is a root directory of the project you're working on.
It is identified by the `.remote.toml` file. Each time you execute `remote` from workspace root or any of its
subdirectories, `remote` syncs everything under workspace root with the destination host before running the command.

### Global Configuration File

Global configuration file should be placed in `~/.config/remote/defaults.toml`. This config file is optional
and the `remote` CLI will work with the default values if it is absent. This is the example of how it looks like:

```toml
[general]
allow_uninitiated_workspaces = false
use_relative_remote_paths = false
remote_root = ".remotes"

[[hosts]]
host = "linux-host.example.com"
label = "linux"

[[hosts]]
host = "macos-host.example.com"
port = 2022
supports_gssapi_auth = false
default = true
label = "mac"

[push]
exclude = [".git"]

[pull]
exclude = ["src/generated"]
include = ["build/reports"]

[both]
include_vcs_ignore_patterns = true
```

1. `[general]` block controls system-wide behavior for the `remote` CLI.

   Reference:

   * `allow_uninitiated_workspaces` (optional, defaults to `false`) - if this flag is set to `true` and
     the global config contains at least one remote host, `remote` will treat its current working directory
     as a workspace root even if it doesn't have `.remote.toml` file in it.

     **Warning:** if this option is on and you run `remote` in the subdirectory of already configured workspace,
     `remote` will ignore workspaces configuration and treat subdirectory as a separate workspace root.

   * `remote_root` (optional, defaults to `".remotes"`) - a default directory on the remote machine that
     will be used to store synced workspaces. The path is expected to be relative to the remote user's home
     directory, so `.remotes` will resolve in `/home/username/.remotes`.
     If the workspace-level configuration sets the `directory` for a host, this setting will be ignored.

   * `use_relative_remote_paths` (optional, defaults to `false`)
     * if set to `false` all the workspaces will be stored in the `remote_root` of the target host in a flat
       structure. Each directory will have a name like `<workspace_name>_<workspace_path_hash>`.
     * if set to `false`, the remote path will be placed in `remote_root` tree like it was placed in the users
       home directory tree locally. Some examples:
       * If local path is `/home/username/projects/work/project_name`, the remote path will be
         `/home/username/.remotes/projects/work/project_name`
       * If local path is `/tmp/project_name`, the remote path will be
         `/home/username/.remotes/tmp/project_name`

2. `[[hosts]]` block lists all the remote hosts available for the workspaces. Used when the workspace
   configuration doesn't overwrite it.

   You can provide multiple hosts in this block, but only one will be selected when you execute `remote`.
   It will be either the host that is marked by `default = true` or the first one in the list if no
   default was set explicitly.

   You can run most of the commands with `--label label|number` or `-l label|number` option to run a
   command on non-default host. `label` here is the text label you put in the config file, `number` is
   a number of required host in the hosts list, starting from 1.

   Reference:

   * `host` - a hostname, IP address, or ssh alias of a remote machine that you want to use for remote execution.
   * `port` (optional, defaults to `22`) - a port used by the ssh daemon on the host.
   * `supports_gssapi_auth` (optional, defaults to `true`) - `true` if the remote host supports `gssapi-*` auth
     methods. We recommend disabling it if the ssh connection to the host hangs for some time during establishing.
   * `default` (optional, defaults to `false`) - `true` if this host should be used by default
   * `label` (optional) - a text label that later can be used to identify the host when running the `remote` CLI.

3. `[push]`, `[pull]`, and `[both]` blocks control what files are synced from local to a remote machine and back
   before and after the execution. These blocks are used when the workspace configuration doesn't overwrite them.

   `push` block controls the files that are uploaded from local machine to the remote one. `pull` block controls files that are downloaded from remote machine to local one. `both` block extends previous two.

   Each one of these blocks supports the following options:

   * `exclude` (optional, defaults to empty list) - a list of rsync-style patterns. Every file in the workspace
     that matches these patterns won't be synced unless it is explicitly specified in `include`.
   * `include` (optional, defaults to empty list) - a list of rsync-style patterns. Every file in the workspace
     that matches these patterns will be synced even if it matches the `exclude`.
   * `include_vcs_ignore_patterns` (optional, defaults to `false`) - if `true` and `.gitignore` is present,
     all its patterns will be included in the `exclude` list.

### Workspace Configuration File

This is the example of how standalone workspace-level `.remote.toml` configuration file looks like:

```toml
[[hosts]]
host = "linux-host.example.com"
directory = ".remotes/workspace"
label = "linux"
supports_gssapi_auth = true

[[hosts]]
host = "macos-host.example.com"
port = 2022
directory = ".remotes/other-workspace"
supports_gssapi_auth = false
default = true
label = "mac"

[push]
exclude = [".git"]

[pull]
exclude = ["src/generated"]
include = ["build/reports"]

[both]
include_vcs_ignore_patterns = true
```

All the used blocks here are similar to the ones in the global config file. However, you cannot put
`[general]` block in this file. Also, you can provide one more option in `[[hosts]]` block:

* `directory` (optional) - a path relative to remote user's home. It will be used to store the workspace's
  file on the remote machine.

Also, if you set at least one value for any of the blocks in the workspace-level config,
all the values from this block in the global config will be ignored.
There is a way to change this behavior. You can use `[extends.*]` blocks to do it.

Here is an example. Imagine, you have a following global config:

```toml
[[hosts]]
host = "linux-host.example.com"
label = "linux"
default = true

[push]
exclude = [".git"]

[both]
include_vcs_ignore_patterns = true
```

If you want to be able to use the same Linux host in the workspace but you want to add one more and modify some exclude patterns, you can create the following workspace config:

```toml
[[extends.hosts]]
host = "mac-host.example.com"
directory = ".remotes/mac-workspace"
label = "mac"
default = true

[extends.push]
exclude = ["workspace-specific-dir"]
include = [".git/hooks"]

[both]
include_vcs_ignore_patterns = false
```

As you can see, some block names start with `extends.`. This name tells remote to merge the
workspace and global settings.

There are a few things to note:

* If both workspace-level and global configs define a default host, the workspace-level config wins
* Hosts ordering is preserver, globally configured hosts always go first.
* If an option value is a list (e.g. `exclude`), it is extended. Otherwise, the value is overwritten.

### Workspace Files Sync Configuration File

`.remoteignore.toml` files is similar to `.remote.toml`, but only supports `push`, `pull`, `both`,
`extends.push`, `extends.pull` and `extends.both` blocks. It also cannot be used to identify
the workspace root.

### .remoteenv file

Sometimes you will need to do some action each time before you execute some remote command.
A common example will be to execute `pytest` in the virtual environment: you need to activate it
first, but the activation state won't be preserved between the `remote` runs.

There are two ways of solving this problem:

1. Running both initiation logic and the command together:

   ```bash
   remote 'source env/bin/activate && pytest'
   ```

2. Creating a file called `.remoteenv` in the workspace root. If this file is present, `remote` will
   always run `source .remoteenv` on the destination host before running the actual command. For example,
   here is how you can run `remote`'s tests on the other hosts:

   ```bash
   git clone git@github.com:remote-cli/remote.git
   cd remote
   remote-init <remote-host-name>
   remote python3 -m venv env
   echo '. env/bin/activate' >> .remoteenv

   # starting from this point all python commands will be executed in virtualenv remotely
   # This should print virtualenv's python path
   remote which python
   remote pip install -e .
   remote pip install -r test_requirements.txt
   remote pytest
   ```

   The `.remoteenv` file is guaranteed to sync to remote machine even if it is excluded by the workspace's
   `.gitignore` file or other rules.

## Development & Contribution

To bootstrap the development run:

```bash
git clone git@github.com:remote-cli/remote.git
cd remote
python3 -m venv env
source env/bin/activate
pip install -e .
pip install -r test_requirements.txt
```

After it, you can open the code in any editor or IDE you like. If you prefer VSCode, the project contains the configuration file for it.

Before submitting your pull request, please check it by running:

```bash
flake8 src test && mypy -p remote && black --check -l 120 src test && isort --check-only src test && pytest
```

If `black` or `isort` fails, you can fix it using the following command:

```bash
black -l 120 src test && isort src test
```

Don't forget to add changed files to your commit after you do it.
