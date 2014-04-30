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
#TODO: Think about other options that might be useful, perhaps a --test flag

from collections import deque
from docopt import docopt
from domains import *
import logging
import logging.handlers
import os
import praw
import re
import shutil
import subprocess
import sys
import time

__version__ = '0.0.2'
LOGNAME = 'OA_source_bot'


def timer(interval):
    """
    This function can work as a decorator to prevent functions from being called
    until a specified interval has passed since their last call.
    """
    def wrap(func):
        def wrapped_func(self):
            now = time.time()
            if now - wrapped_func.latest > interval:
                func(self)
                wrapped_func.latest = now
        wrapped_func.latest = time.time()
        return wrapped_func
    return wrap


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
        sh.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        log.addHandler(sh)

log = logging.getLogger(LOGNAME)


class OASourceBot(object):
    user_agent = 'OA_source_bot v. {0} by /u/SavinaRoja, at /r/OA_source_bot'.format(__version__)
    ignored_users = set()
    watched_subreddits = set()
    oa_domains = {'plosone.org': PLoSDomain,
                  'plosbiology.org': PLoSDomain,
                  'ploscompbiol.org': PLoSDomain,
                  'ploscollections.org': PLoSDomain,
                  'plosgenetics.org': PLoSDomain,
                  'plospathogens.org': PLoSDomain,
                  'plosntds.org': PLoSDomain,
                  'plosmedicine.org': PLoSDomain,
                  'nature.com': NatureDomain}
    already_seen = deque(maxlen=2000)  # Am I being too conservative here?
    temp_message = 'Initiating reply, refresh in a few seconds.'

    def __init__(self, config_filename):
        #TODO: Do some checking for locally written wikipage data dumps
        log.info('Starting OA_source_bot')
        self.load_already_seen()
        self.load_config_and_login(config_filename)
        self.myself = self.reddit.get_redditor(self.username)
        self.parse_wikipages()
        self.latest_time = None
        self.alive = False

    def load_already_seen(self):
        if os.path.isfile('already_seen'):
            with open('already_seen') as inf:
                for line in inf:
                    self.already_seen.append(line.rstrip())

    def load_config_and_login(self, config_filename):
        with open(config_filename, 'r') as inf:
            self.username = inf.readline().strip()
            log.debug('Username: ' + self.username)
            password = inf.readline().strip()
            self.ignored_users_wikipage = inf.readline().strip()
            self.watched_subreddits_wikipage = inf.readline().strip()
            self.dropbox_dir = inf.readline().strip()
            log.debug('Dropbox folder: ' + self.dropbox_dir)
            self.dropbox_url = inf.readline().strip()
            log.debug('Dropbox URL: ' + self.dropbox_url)
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

    def write_new_item_to_wikipage(self, wikipagename, item):
        log.debug('Adding {0} to wikipage {1}'.format(item, wikipagename))
        wikipage = self.reddit.get_wiki_page(self.username, wikipagename)
        new_content_md = wikipage.content_md + '\n    ' + item
        wikipage.edit(new_content_md)

    def core_predicate(self, post):
            """
            The predicate defines what posts will be recognized and replied to.
            This will return True only for posts to which OA_source_bot will
            try to reply to.
            """
            if post.subreddit.display_name not in self.watched_subreddits:
                return False
            if post.author is None:  # Deleted? Removed? Skip it.
                return False
            if post.author.name in self.ignored_users:
                return False
            if post.id in self.already_seen:
                return False
            if post.domain not in self.oa_domains:
                return False
            return True

    def run(self):
        log.info('Initiating Run')
        self.alive = True
        self.review_posts()
        self.check_mail()
        while self.alive:
            try:
                log.info('Running')
                self._run()
            except KeyboardInterrupt:
                self.alive = False
            except Exception as e:
                log.exception(e)
                try:
                    time.sleep(30)
                except KeyboardInterrupt:
                    self.alive = False
        log.info('Writing data before shutting down!')
        self.write_all_data()
        log.info('Shutting down!')

    def _run(self):
        #A multireddit could be employed as shown in the commented line below,
        #however comment lags (as is common when just developing on /r/test)
        #sometimes require the use of 'all' and core_predicate filtering
        #If you want to run a test, switch the 'all' to 'test' and make your
        #test posts in /r/test
        for post in praw.helpers.submission_stream(self.reddit,
                                                   #'all',
                                                   'test',
                                                   #'+'.join(self.watched_subreddits),
                                                   limit=100,
                                                   verbosity=0):
            #The intervals for these is implemented by their timers
            self.review_posts()
            self.check_mail()
            self.backup_data()

            #Apply the core predicate to the post
            if not self.core_predicate(post):
                continue
            #Apply the domain-specific predicate to the post
            if not self.oa_domains[post.domain].predicate(post):
                continue

            #Add the post id to the record of already seen, then reply
            self.already_seen.append(post.id)
            self.reply_to_post(post)

    def reply_to_post(self, post):
        log.info('Replying to post {0}'.format(post.id))
        reply = post.add_comment(self.temp_message)
        text = '''\
This article is freely available online to everyone as \
**[OpenAccess](http://en.wikipedia.org/wiki/Open_access)**.

___

>Link to the article's **[Online Format]({online})**

___

>Link to the article's **[PDF]({pdf})**{epub}

^[ ^Original ^poster, ^/u/{op}, ^can [^delete]\
(http://www.reddit.com/message/compose?to=OA_source_bot&amp;subject=Delete&amp;message={comment-id})\
^. ^Will ^also ^delete ^on ^score ^less ^than ^0. ^| [^About ^Me]\
(http://www.np.reddit.com/r/OA_source_bot/wiki/index) ^]
'''

        epub_text = '''

___

>You can also read this article as an Ebook in the following formats: \
**{0}**

>*The EPUB format is provided by [OpenAcess_EPUB]\
(https://github.com/SavinaRoja/OpenAccess_EPUB), a project currently under \
development by /u/SavinaRoja; please contact if you spot any problems, have \
feedback/suggestions, or would like to contribute.*
'''

        domain_obj = self.oa_domains[post.domain]
        pdf_url = domain_obj.pdf_url(post)

        if not domain_obj.oaepub_support:
            reply.edit(text.format(**{'online': post.url,
                                      'op': post.author,
                                      'pdf': pdf_url,
                                      'epub': '',
                                      'comment-id': reply.id}))
            return

        article_doi = domain_obj.doi(post)

        #Torrents are on the backburner for now. Connectivity issues are being a
        #massive pain... Bandwidth issue aside, I will eventually hit a storage
        #cap, so getting this worked out is crucial.
        basename = domain_obj.file_basename_from_doi(article_doi)
        epubname = basename + '.epub'
        epub2name = os.path.join('epub2', '{0}-2.epub'.format(basename))
        epub3name = os.path.join('epub3', '{0}-3.epub'.format(basename))
        try:
            epub2 = subprocess.check_call(['oaepub', 'convert',
                                           '-2',
                                           'doi:' + article_doi])
        except subprocess.CalledProcessError as e:
            log.exception(e)
            log.error('Unable to produce EPUB for doi:{0}'.format(post))
            epub2 = False
        else:
            epub2 = True
            shutil.move(epubname, os.path.join(self.dropbox_dir, epub2name))
            epub2_url = self.dropbox_url + epub2name

        try:
            epub3 = subprocess.check_call(['oaepub', 'convert',
                                           '-3',
                                           'doi:' + article_doi])
        except subprocess.CalledProcessError as e:
            log.exception(e)
            epub3 = False
        else:
            epub3 = True
            shutil.move(epubname, os.path.join(self.dropbox_dir, epub3name))
            epub3_url = self.dropbox_url + epub3name

        log.info('Calling pyndexer')
        subprocess.call(['python', './patched_pyndexer/pyndexer.py'])

        if not any([epub2, epub3]):  # Neither were successful, ignore EPUB
            reply.edit(text.format(**{'online': post.url,
                                      'op': post.author,
                                      'pdf': pdf_url,
                                      'epub': '',
                                      'comment-id': reply.id}))
            return
        elif all([epub2, epub3]):  # Both successful
            formats = '[EPUB2]({0}) | [EPUB3]({1})'.format(epub2_url, epub3_url)
            epub_text = epub_text.format(formats)
        elif epub2:
            epub_text = epub_text.format('[EPUB2]({0})'.format(epub2_url))
        elif epub3:
            epub_text = epub_text.format('[EPUB2]({0})'.format(epub3_url))
        reply.edit(text.format(**{'online': post.url,
                                  'op': post.author,
                                  'pdf': pdf_url,
                                  'epub': epub_text,
                                  'comment-id': reply.id}))

    @timer(300)  # 5 minute interval
    def review_posts(self):
        log.debug('Reviewing posts')
        user = self.myself
        for comment in user.get_comments('all', limit=None):
            if comment.score < 0:
                comment.delete()
                log.info('Deleting comment {0} for having a low score'.format(comment.id))
                continue
            elif comment.body == self.temp_message:
                comment.delete()
                log.info('Deleting comment {0} for being incomplete'.format(comment.id))
                continue

    @timer(15)  # 5 minute interval
    def check_mail(self):
        """
        Here is a proposed map of mail triggers and actions
        message body "delete <comment-id>"
        """
        #These are a map of message.subject to action
        action_map = {'delete': self.delete_mail_request,
                      'ignore': self.ignore_user_request,
                      'unignore': self.unignore_user_request,
                      'watch subreddit': self.watch_subreddit_request,
                      'drop subreddit': self.drop_subreddit_request,
                      'remote kill': self.remote_kill_request,
                      'check submission': self.check_submission_request}
        log.debug('Checking mail')
        for message in self.reddit.get_unread(limit=None):
            action = action_map.get(message.subject.lower())
            if action is None:
                log.info('Unrecognized subject: {0}'.format(action.subject))
            else:
                action(message)

    def delete_mail_request(self, message):
        sender = message.author.name
        comment_id = message.body
        log.info('/u/{0} requested deletion of comment {1}'.format(sender,
                                                                   comment_id))
        self.myself.mark_as_read(message)
        comment = self.reddit.get_info(thing_id='t1_{0}'.format(comment_id))
        if not comment:
            log.info('Invalid. Could not retrieve comment')
            return
        if sender == comment.submission.author.name:
            log.info('Valid request from OP, deleting {0}'.format(comment_id))
            comment.delete()
        elif sender == 'SavinaRoja':
            log.info('Valid request from /u/SavinaRoja, deleting {0}'.format(comment_id))
            comment.delete()
        else:
            log.info('Invalid. Not OP or mod')

    def ignore_user_request(self, message):
        sender = message.author.name
        log.info('/u/{0} requested ignore, adding them to ignored users set'.format(sender))
        self.myself.mark_as_read(message)
        self.ignored_users.add(sender)
        self.write_ignored_users_to_wikipage()

    def unignore_user_request(self, message):
        sender = message.author.name
        log.info('/u/{0} requested unignore, removing them from ignored users set'.format(sender))
        self.myself.mark_as_read(message)
        try:
            self.ignored_users.remove(sender)
        except KeyError:
            log.info('Invalid. /u/{0} was not in the ignored users set'.format(sender))
        else:
            log.info('Valid request. /u/{0} was successfully removed from unignored set'.format(sender))
            self.write_ignored_users_to_wikipage()

    def watch_subreddit_request(self, message):
        sender = message.author
        subname = message.body
        subreddit = self.reddit.get_subreddit(subname)
        log.info('/u/{0} requested addition of /r/{1} to watched subreddits set'.format(sender.name, subname))
        self.myself.mark_as_read(message)
        try:
            moderators = list(subreddit.get_moderators())
        except Exception as e:
            log.exception(e)
            log.info('Invalid request, probably does not exist')
        else:
            if sender in moderators or sender.name in ['SavinaRoja', 'OA_source_bot']:
                log.info('Valid request, adding /r/{0} to watched subreddit set'.format(subname))
                self.watched_subreddits.add(subname)
                self.write_watched_subreddits_to_wikipage()

            else:
                log.info('Invalid. Not a mod of /r/{0}'.format(subname))

    def drop_subreddit_request(self, message):
        sender = message.author
        subname = message.body
        subreddit = self.reddit.get_subreddit(subname)
        log.info('/u/{0} requested dropping /r/{1} from watched subreddits set'.format(sender.name, subname))
        self.myself.mark_as_read(message)
        try:
            moderators = list(subreddit.get_moderators())
        except Exception as e:
            log.exception(e)
            log.info('Invalid request, probably does not exist')
        else:
            if sender in moderators or sender.name in ['SavinaRoja', 'OA_source_bot']:
                try:
                    self.watched_subreddits.remove(subname)
                except KeyError:
                    log.info('Invalid. /r/{0} was not in watched_subreddits'.format(subname))
                else:
                    log.info('Valid request, removed /r/{0} from watched_subreddit set'.format(subname))
                    self.write_watched_subreddits_to_wikipage()

            else:
                log.info('Invalid. Not a mod of /r/{0}'.format(subname))

    def remote_kill_request(self, message):
        sender = message.author.name
        self.myself.mark_as_read(message)
        log.info('Received remove kill request from /u/{0}'.format(sender))
        if sender in ['SavinaRoja', 'OA_source_bot']:
            log.info('Valid remote kill request by mod')
            raise KeyboardInterrupt  # Mimics shutdown by CTRL-C
        else:
            log.info('Invalid remote kill request by non-mod')

    def check_submission_request(self, message):
        def submission_check(post):
            #Apply the core predicate to the post
            if not self.core_predicate(post):
                return
            #Apply the domain-specific predicate to the post
            if not self.oa_domains[post.domain].predicate(post):
                return

            #Add the post id to the record of already seen, then reply
            self.already_seen.append(post.id)
            self.reply_to_post(post)

        sender = message.author.name
        submission_id = message.body
        self.myself.mark_as_read(message)
        log.info('Request to check submission {0} by /u/{1}'.format(submission_id, sender))
        submission = self.reddit.get_info(thing_id='t3_{0}'.format(submission_id))
        if not submission:
            log.info('Invalid. Could not retrieve submission')
            return
        if sender not in ['SavinaRoja', 'OA_source_bot']:
            log.info('Invalid request from non-mod')
        else:
            log.info('Valid request, checking the submission')
            submission_check(submission)

    @timer(1800)  # 30 minute interval
    def backup_data(self):
        log.info('Writing data')
        self.write_all_data()

    def write_already_seen_local(self):
        log.info('Writing the record of posts that have already been seen to local file.')
        with open('already_seen', 'w') as out:
            for item in self.already_seen:
                out.write(item + '\n')

    def write_ignored_users_to_wikipage(self):
        log.info('Writing the list of ignored users to the wikipage')
        ignored_md = '\n'.join(['    ' + item for item in self.ignored_users])
        try:
            ign = self.reddit.get_wiki_page(self.username,
                                            self.ignored_users_wikipage)
            ign.edit(ignored_md)
        except Exception as e:
            log.exception(e)
            log.info('An error occurred while writing wikipage! Writing to file instead.')
            with open('ignored_users', 'w') as out:
                out.write(ignored_md)

    def write_watched_subreddits_to_wikipage(self):
        log.info('Writing the list of watched_subreddits to the wikipage')
        watched_md = '\n'.join(['    ' + item for item in self.watched_subreddits])
        try:
            wat = self.reddit.get_wiki_page(self.username,
                                            self.watched_subreddits_wikipage)
            wat.edit(watched_md)
        except Exception as e:
            log.exception(e)
            log.info('An error occurred while writing wikipage! Writing to file instead.')
            with open('watched_subreddits', 'w') as out:
                out.write(watched_md)

    def write_all_data(self):
        self.write_already_seen_local()
        self.write_ignored_users_to_wikipage()
        self.write_watched_subreddits_to_wikipage()


if __name__ == '__main__':
    args = docopt(__doc__, version=__version__)
    logging_config(args['--log'], args['--console-level'])
    bot = OASourceBot(args['--conf-file'])
    bot.run()
