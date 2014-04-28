OA_source_bot
=============

A reddit bot for the automatic provision of OpenAccess content files

Things needed for the running environment
-----------------------------------------

* Linux
* python3
* python3 packages: docopt, lxml, openaccess_epub, praw
* mktorrent
* transmission-daemon
* Dropbox
* pyndexer (I have a custom patched one, I should see about sharing it)

General setup
-------------

Make a virtualenv, something like:

`virtualenv -p python3 oa_bot`

Source the 'bin/activate' in the virtualenv, then pip the dependencies like:

`pip install docopt, lxml, praw, openaccess_epub`

You can of course install dependencies off of github if you like. Get the other tools:

`sudo apt-get install mktorrent transmission-daemon`

"mktorrent" is used to make torrent files for ebooks, "transmission-daemon" will be configured to
watch a directory in your Dropbox Public folder to automatically share the torrent files as they
are created.

Create a configuration file (the script will look for "conf" by default) that has the following
information on separate lines:
<reddit-bot-username>
<reddit-bot-password>
<wikipage-for-ignored-users>
<wikipage-for-watched-subreddits>




