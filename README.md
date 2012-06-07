remote
======

Work with remote hosts seamlessly
Remote uses rsync and ssh to create a seamless working environment from a local directory to a remote directory. 
Most used features are:
* Remotely execute commands from any sub-directory. 
* Drop into remote interactive sessions.

Executables and purpose
* remote-init: set up a local directory to point to a remote directory
* remote-ignore: set up directories / files to ignore while pushing
* remote-push: explicitly push local changes remote
* remote-pull: pull a directory from remote to local
* remote: execute a command remotely, after first syncing the local tree with the remote tree
* remote-quick: execute a command remotely, without syncing the trees

Wish-List
--------
* Support for setting up multiple remote directories to mirror a local directory

Build a package
---------------
./build

