# -*- coding: utf-8 -*-

"""
OA_source_bot

A reddit bot for the automatic provision of OpenAccess content files

Usage:
  oa_source_bot.py [--conf-file=FILENAME] [--log=FILENAME]
                   [--console-level=LEVEL]
  oa_source_bot.py [--help | --version]

Options:
  -c --conf-file=FILENAME   Specify a configuration file for the process
                            [default: conf]
  -l --log=FILENAME         Specify the log file name scheme
                            [default: logs/OA_source_bot]
  -C --console-level=LEVEL  Set how much information is output to the console
                            (one of: "CRITICAL", "ERROR", "WARNING", "INFO",
                            "DEBUG", "SILENT") [default: INFO]
  -h --help                 Print this help message and exit
  -v --version              Print the version and exit
"""

import logging
import logging.handlers
import os
import praw
import sys
import time
from docopt import docopt

__version__ = '0.0.1'
LOGNAME = 'OA_source_bot'


def logging_config(filename, console_level, smtp=None):
    log = logging.getLogger(LOGNAME)
    log.setLevel(logging.DEBUG)
    if not os.path.isdir(os.path.dirname(filename)):
        os.makedirs(os.path.dirname(filename))
    trfh = logging.handlers.TimedRotatingFileHandler(filename,
                                                     when='midnight',
                                                     utc=True)
    trfh.setLevel(logging.DEBUG)
    trfh.setFormatter(logging.Formatter('%(name)s [%(levelname)s] %(message)s'))
    log.addHandler(trfh)
    if console_level.upper() != 'SILENT':
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(sh)

log = logging.getLogger(LOGNAME)


class OASourceBot(object):
    user_agent = 'OA_source_bot v. {0} by /u/SavinaRoja, at /r/OA_source_bot'.format(__version__)
    ignored_users = set()
    watched_subreddits = set()

    def __init__(self, config_filename):
        log.info('Starting OA_source_bot')
        self.load_config_and_login(config_filename)
        self.parse_wikipages()
        self.latest_time = None

    def load_config_and_login(self, config_filename):
        with open(config_filename, 'r') as inf:
            self.username = inf.readline().strip()
            password = inf.readline().strip()
            self.ignored_users_wikipage = inf.readline().strip()
            self.watched_subreddits_wikipage = inf.readline().strip()
        self.reddit = praw.Reddit(self.user_agent)
        login_attempt = True
        while login_attempt:
            try:
                self.reddit.login(self.username, password)
            except praw.errors.InvalidUserPass as e:  # Quit if bad password
                log.exception(e)
                sys.exit(str(e))
            except Exception as e:  # Connection trouble? Wait
                log.exception(e)
                log.info('Login unsuccessful, waiting 10 seconds before trying again.')
                time.sleep(10)
            else:
                login_attempt = False
                log.info('Login successful!')

    def parse_wikipages(self):
        ignored_page = self.reddit.get_wiki_page(self.username,
                                                 self.ignored_users_wikipage)
        for ignored in ignored_page.content_md.split('\n'):
            self.ignored_users.add(ignored.strip())
        watched_page = self.reddit.get_wiki_page(self.username,
                                                 self.watched_subreddits_wikipage)
        for watched in watched_page.content_md.split('\n'):
            self.watched_subreddits.add(watched.strip())

    def write_new_item_to_wikipage(self, wikipagename, item):
        wikipage = self.reddit.get_wiki_page(self.username, wikipagename)
        new_content_md = wikipage.content_md + '\n    ' + item
        wikipage.edit(new_content_md)

    def run(self):
        while True:
            if self.latest_time is None:
                self.latest_time = time.time()
            if (time.time() - self.latest_time()) < 30:
                continue


if __name__ == '__main__':
    args = docopt(__doc__, version=__version__)
    logging_config(args['--log'], args['--console-level'])
    bot = OASourceBot(args['--conf-file'])
    print(bot.ignored_users)
    print(bot.watched_subreddits)
