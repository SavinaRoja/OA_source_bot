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

from collections import deque
from docopt import docopt
import logging
import logging.handlers
import os
from pprint import pprint
import praw
import re
import sys
import time


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
    oa_domains = set()
    already_seen = deque(maxlen=2000)  # Am I being too conservative here?

    def __init__(self, config_filename):
        log.info('Starting OA_source_bot')
        self.load_config_and_login(config_filename)
        self.parse_wikipages()
        self.latest_time = None
        self.alive = False

    def load_config_and_login(self, config_filename):
        with open(config_filename, 'r') as inf:
            self.username = inf.readline().strip()
            password = inf.readline().strip()
            self.ignored_users_wikipage = inf.readline().strip()
            self.watched_subreddits_wikipage = inf.readline().strip()
            self.oa_domains_wikipage = inf.readline().strip()
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
        log.info('Attempting to load information from wikipages')
        log.debug('Accessing wikipage {0} for ignored users'.format(self.ignored_users_wikipage))
        ignored_page = self.reddit.get_wiki_page(self.username,
                                                 self.ignored_users_wikipage)
        for ignored in ignored_page.content_md.split('\n'):
            self.ignored_users.add(ignored.strip())
        log.debug('Accessing wikipage {0} for watched subreddits'.format(self.watched_subreddits_wikipage))
        watched_page = self.reddit.get_wiki_page(self.username,
                                                 self.watched_subreddits_wikipage)
        for watched in watched_page.content_md.split('\n'):
            self.watched_subreddits.add(watched.strip())
        log.debug('Accessing wikipage {0} for recognized OA domains'.format(self.oa_domains_wikipage))
        domain_page = self.reddit.get_wiki_page(self.username,
                                                self.oa_domains_wikipage)
        for domain in domain_page.content_md.split('\n'):
            self.oa_domains.add(domain.strip())

    def write_new_item_to_wikipage(self, wikipagename, item):
        log.debug('Adding {0} to wikipage {1}'.format(item, wikipagename))
        wikipage = self.reddit.get_wiki_page(self.username, wikipagename)
        new_content_md = wikipage.content_md + '\n    ' + item
        wikipage.edit(new_content_md)

    def run(self):
        log.info('Running!')
        #self.alive = True
        #self.latest_time = time.time()
        self.latest_review_time = time.time()

        def predicate(post):
            """
            The predicate defines what posts will be recognized and replied to.
            This will return True only for posts to which OA_source_bot will
            try to reply to.
            """
            if post.subreddit.display_name not in self.watched_subreddits:
                return False
            if post.author.name in self.ignored_users:
                return False
            if post.id in self.already_seen:
                return False
            if post.domain not in self.oa_domains:
                return False
            return True

        while True:
            try:
                for post in praw.helpers.submission_stream(self.reddit,
                                                           'all',
                                                           limit=None,
                                                           verbosity=0):
                    now = time.time()
                    #Wait at least 10 minutes between reviewing posts
                    if now - self.latest_review_time > 600:
                        self.latest_review_time = now
                        self.review_posts()
                    if not predicate(post):
                        continue
                    #TODO: make the already_seen data persistent between launches
                    self.already_seen.append(post)

            except Exception as e:
                log.exception(e)
                #self.alive = False
                break

    def review_posts(self):
        user = self.reddit.get_redditor(self.username)
        for comment in user.get_comments(limit=None):
            if comment.score < 0:
                comment.delete()
                log.info('Deleting comment {0} for having a low score'.format(comment.id))
                continue
            for reply in comment.replies:
                r_author = reply.author.name
                if r_author == comment.submission.author:
                    if re.search('delete', reply.body.lower()):
                        log.info('Deleting comment {0} by {1} request'.format(comment.id, r_author))
                        comment.delete()
                        continue
                    elif re.search('ignore', reply.body.lower()):
                        log.info('Deleting comment {0} and adding {1} to ignored users list'.format(comment.id, r_author))
                        if r_author not in self.ignored_users:
                            self.ignored_users.add(r_author)
                            self.write_new_item_to_wikipage(self.ignored_users_wikipage, r_author)

if __name__ == '__main__':
    args = docopt(__doc__, version=__version__)
    logging_config(args['--log'], args['--console-level'])
    bot = OASourceBot(args['--conf-file'])
    bot.run()
