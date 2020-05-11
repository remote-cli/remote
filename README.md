Remote
======

[![Code Quality](https://github.com/remote-cli/remote/workflows/Python%20Code%20Quality/badge.svg)](https://github.com/remote-cli/remote/actions?query=branch%3Amaster+workflow%3A%22Python+Code+Quality%22)
[![pypi](https://img.shields.io/pypi/v/remote-exec.svg)](https://pypi.org/project/remote-exec)
[![versions](https://img.shields.io/pypi/pyversions/remote-exec.svg)](https://github.com/remote-cli/remote)
[![license](https://img.shields.io/github/license/remote-cli/remote.svg)](https://github.com/remote-cli/remote/blob/master/LICENSE)

Work with remote hosts seamlessly
Remote uses rsync and ssh to create a seamless working environment from a local directory to remote directories.
Most used features are:
* Remotely execute commands from any sub-directory.
* Drop into remote interactive sessions.
* Fire off parallel remote commands on multiple hosts.

Executables and purpose
* remote-init: set up a local directory to point to a remote directory
* remote-ignore: set up directories / files to ignore while pushing
* remote-push: explicitly push local changes remote
* remote-pull: pull a directory from remote to local
* remote: execute a command remotely, after first syncing the local tree with the remote tree
* remote-explain: explain your remote setup, explain what command actually will get run
* remote-quick: execute a command remotely, without syncing the trees
* remote-add: add another remote host to the mirror list
* mremote: execute a remote command on all the hosts, after first syncing the local tree with the remote trees
