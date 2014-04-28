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

import base64
from bcoding import bencode, bdecode
from collections import deque
from docopt import docopt
from io import StringIO
import hashlib
import logging
import logging.handlers
import os
import praw
import re
import subprocess
import sys
import time
import urllib.parse


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


class Domain(object):
    """
    Defines the basic Domain code
    """
    #If this is not true, don't worry about the 'doi' or
    #'file_basename_from_doi' methods
    oaepub_support = False

    def __init__(self):
        pass

    @staticmethod
    def predicate(post):
        """
        Returns True if the post's URL corresponds to an article, otherwise it
        will return False.

        Should distinguish between domain non-article URLs such as
        http://www.plosbiology.org/static/contact (return False) and article
        URLs such as http://www.plosbiology.org/article/info%3Adoi%2F10.1371%2Fjournal.pbio.1001812
        (return True).
        """
        raise NotImplementedError

    @staticmethod
    def pdf_url(post):
        """
        Returns a URL to the PDF of the article.
        """
        raise NotImplementedError

    @staticmethod
    def doi(post):
        """
        Returns the article DOI from the post's URL.
        """
        raise NotImplementedError

    @staticmethod
    def file_basename_from_doi(doi):
        """
        Based on the doi, return the basename of the XML file that will be
        downloaded for EPUB production.
        """
        raise NotImplementedError


class PLoSDomain(Domain):
    """
    Code for handling PLoS domains.
    """

    oaepub_support = True

    def __init__(self):
        super(PLoSDomain, self).__init__()

    def predicate(post):
        if '/article/info%3Adoi%2F10.1371%2Fjournal.' in post.url:
            return True
        else:
            return False

    def pdf_url(post):
        """
        Returns a URL to the PDF of the article.
        """
        parsed = urllib.parse.urlparse(post.url)
        pdf_url = '{0}://{1}'.format(parsed.scheme, parsed.netloc)
        pdf_url += '/article/fetchObjectAttachment.action?uri='
        pdf_path = parsed.path.replace(':', '%3A').replace('/', '%2F')
        pdf_path = pdf_path.split('article%2F')[1]
        pdf_url += '{0}{1}'.format(pdf_path, '&representation=PDF')
        return pdf_url

    def doi(post):
        """
        Returns the article DOI from the post's URL.
        """
        return '/'.join(post.url.split('%2F')[1:])

    def file_basename_from_doi(doi):
        return doi.split('/')[1]


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
                  'plosmedicine.org': PLoSDomain}
    already_seen = deque(maxlen=20000)  # Am I being too conservative here?

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
        #log.debug('Accessing wikipage {0} for recognized OA domains'.format(self.oa_domains_wikipage))
        #domain_page = self.reddit.get_wiki_page(self.username,
                                                #self.oa_domains_wikipage)
        #for domain in domain_page.content_md.split('\n'):
            #self.oa_domains.add(domain.strip())

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

    def domain_predicate(self, post):
        if post.domain.startswith('plos'):  # Handle all PLoS domains
            if 'info%3Adoi%2F10.1371%2F' in post.url:
                return True
            else:
                return False

    def run(self):
        log.info('Running!')
        self.alive = True
        self.latest_review_time = time.time()
        while self.alive:
            try:
                self._run()
            except KeyboardInterrupt as e:
                log.exception(e)
                self.alive = False
            except Exception as e:
                log.exception(e)
                time.sleep(30)
        self.close_nicely()

    def _run(self):
        for post in praw.helpers.submission_stream(self.reddit,
                                                   '+'.join(self.watched_subreddits),
                                                   limit=200,
                                                   verbosity=0):
            now = time.time()
            #Wait at least 10 minutes between reviewing posts
            if now - self.latest_review_time > 600:
                self.latest_review_time = now
                self.review_posts()
            if not self.core_predicate(post):
                continue
            if not self.oa_domains[post.domain].predicate(post):
                continue
            #TODO: make the already_seen data persistent between runs
            self.already_seen.append(post)
            self.reply_to_post(post)

    def reply_to_post(self, post):
        reply = post.add_comment('Initiating reply')
        text = '''\
This article is freely available online to everyone as \
**[OpenAccess](http://en.wikipedia.org/wiki/Open_access)**.

___

>Link to the article's **[Online Format]({online})**

___

>Link to the article's **[PDF]({pdf})**{epub}

^[ ^Original ^poster, ^/u/{op}, ^can [^delete]\
(http://www.reddit.com/message/compose?to=OA_source_bot&amp;subject=OA_source_bot Deletion&amp;message=delete+{comment-id})\
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
        article_doi = domain_obj.doi(post)
        pdf_url = domain_obj.pdf_url(post)

        if not domain_obj.oaepub_support:
            reply.edit(text.format(**{'online': post.url,
                                      'op': post.author,
                                      'pdf': pdf_url,
                                      'epub': '',
                                      'comment-id': reply.id}))
            return

        basename = domain_obj.file_basename_from_doi(article_doi)
        epubname2 = 'epubs/epub2/{0}.epub'.format(basename)
        epubname3 = 'epubs/epub3/{0}.epub'.format(basename)
        torrname2 = 'epubs/torrents/{0}.2.torrent'.format(basename)
        torrname3 = 'epubs/torrents/{0}.3.torrent'.format(basename)
        try:
            epub2 = subprocess.check_call(['oaepub', 'convert',
                                           '-2',
                                           '-o', 'epubs/epub2/',
                                           'doi:' + article_doi])
        except subprocess.CalledProcessError as e:
            log.exception(e)
            log.error('Unable to produce EPUB for doi:{0}'.format(post))
            epub2 = False
        else:
            epub2 = True
            subprocess.call(['mktorrent',
                             '-a', 'udp://tracker.publicbt.com:80',
                             '-o', torrname2, epubname2])
            magnet2 = self.make_magnetlink(torrname2)

        try:
            epub3 = subprocess.check_call(['oaepub', 'convert',
                                           '-3',
                                           '-o', 'epubs/epub3/',
                                           'doi:' + article_doi])
        except subprocess.CalledProcessError as e:
            log.exception(e)
            epub3 = False
        else:
            epub3 = True
            subprocess.call(['mktorrent',
                             '-a', 'udp://tracker.publicbt.com:80',
                             '-o', torrname3, epubname3])
            magnet3 = self.make_magnetlink(torrname3)

        if not any([epub2, epub3]):  # Neither were successful, ignore EPUB
            reply.edit(text.format(**{'online': post.url,
                                      'op': post.author,
                                      'pdf': pdf_url,
                                      'epub': '',
                                      'comment-id': reply.id}))
            return
        elif all([epub2, epub3]):  # Both successful
            formats = '[EPUB2]({mag2}) | [EPUB3]({mag3}'.format(**{'mag2': magnet2,
                                                                   'mag3': magnet3})
            epub_text = epub_text.format(formats)
        elif epub2:
            epub_text = epub_text.format('[EPUB2]({0})'.format(magnet2))
        elif epub3:
            epub_text = epub_text.format('[EPUB2]({0})'.format(magnet3))
        reply.edit(text.format(**{'online': post.url,
                                  'op': post.author,
                                  'pdf': pdf_url,
                                  'epub': epub_text,
                                  'comment-id': reply.id}))

    def make_magnetlink(self, torrent_filename):
        #http://stackoverflow.com/questions/12479570/given-a-torrent-file-how-do-i-generate-a-magnet-link-in-python
        with open(torrent_filename, 'rb') as torrent:
            metadata = bdecode(torrent)
        hashcontents = bencode(metadata['info'])
        digest = hashlib.sha1(hashcontents).digest()
        b32hash = base64.b32encode(digest)
        params = {'xt': 'urn:btih:%s' % b32hash,
                  'dn': metadata['info']['name'],
                  'tr': metadata['announce'],
                  'xl': metadata['info']['length']}
        paramstr = urllib.parse.urlencode(params)
        print(paramstr)
        return 'magnet:?' + paramstr

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

    def check_mail(self):
        pass

    def close_nicely(self):
        log.info('closing nicely')

if __name__ == '__main__':
    args = docopt(__doc__, version=__version__)
    logging_config(args['--log'], args['--console-level'])
    bot = OASourceBot(args['--conf-file'])
    bot.run()
