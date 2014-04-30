# -*- coding: utf-8 -*-
"""
This module defines the Domain class along with inheriting classes to provide
support for domain-specific methods of providing source materials.
"""

import logging
import lxml.html
import re
import urllib.error
from urllib.parse import urlparse, urlunparse
import urllib.request


__all__ = ['NatureDomain', 'PLoSDomain']

log = logging.getLogger('OA_source_bot.domains')


class Domain(object):
    """
    Defines the basic Domain code contract, really this is little more than a
    useful collection of methods and static values... Inherit from this when
    adding support for a new domain.
    """
    #If this is not true, don't worry about the 'doi' or
    #'file_basename_from_doi' methods
    oaepub_support = False

    def __init__(self):
        pass

    @classmethod
    def predicate(self, post):
        """
        Returns True if the post's URL corresponds to an article, otherwise it
        will return False.

        Should distinguish between domain non-article URLs such as
        http://www.plosbiology.org/static/contact (return False) and article
        URLs such as http://www.plosbiology.org/article/info%3Adoi%2F10.1371%2Fjournal.pbio.1001812
        (return True).
        """
        raise NotImplementedError

    @classmethod
    def pdf_url(self, post):
        """
        Returns a URL to the PDF of the article.
        """
        raise NotImplementedError

    @classmethod
    def doi(self, post):
        """
        Returns the article DOI from the post's URL.
        """
        raise NotImplementedError

    @classmethod
    def file_basename_from_doi(self, doi):
        """
        Based on the doi, return the basename of the XML file that will be
        downloaded for EPUB production.
        """
        raise NotImplementedError


class PLoSDomain(Domain):
    oaepub_support = True  # At this time, only valid publisher

    def __init__(self):
        super(PLoSDomain, self).__init__()

    @classmethod
    def predicate(self, post):
        log.info('testing {0} against PLoS predicate'.format(post.id))
        if '/article/info%3Adoi%2F10.1371%2Fjournal.' in post.url:
            return True
        else:
            return False

http://www.ploscompbiol.org/article/info%3Adoi%2F10.1371%2Fjournal.pcbi.1003572
                           /article/info%3Adoi%2F10.1371%2Fjournal.
    @classmethod
    def pdf_url(self, post):
        """
        Returns a URL to the PDF of the article.
        """
        parsed = urlparse(post.url)
        pdf_url = '{0}://{1}'.format(parsed.scheme, parsed.netloc)
        pdf_url += '/article/fetchObjectAttachment.action?uri='
        pdf_path = parsed.path.replace(':', '%3A').replace('/', '%2F')
        pdf_path = pdf_path.split('article%2F')[1]
        pdf_url += '{0}{1}'.format(pdf_path, '&representation=PDF')
        return pdf_url

    @classmethod
    def doi(self, post):
        """
        Returns the article DOI from the post's URL.
        """
        return '/'.join(post.url.split('%2F')[1:]).split(';')[0]

    @classmethod
    def file_basename_from_doi(self, doi):
        return doi.split('/')[1]


class NatureDomain(Domain):
    """
    Handles nature.com
    """
    oaepub_support = False
    #Last updated on 29-4-2014 from information located here:
    #http://www.nature.com/libraries/open_access/oa_pub_models.html
    full_oa_subjournals = set(['bcj', 'cddis', 'ctg', 'cti', 'psp', 'emi',
                               'emm', 'hortres', 'hgv', 'ijos', 'lsa', 'mtm',
                               'mtna', 'am', 'nutd', 'oncsis', 'srep', 'tp'])
    opt_oa_subjournals = set(['ajg', 'aps' 'bdj', 'bdc', 'bmt', 'cgt', 'cdd',
                              'cr', 'cmi', 'clpt', 'ejcn', 'ejhg', 'eye',
                              'gene', 'gt', 'gim', 'hdy', 'hr', 'icb', 'ijir',
                              'ijo', 'ismej', 'ja', 'jcbfm', 'jes', 'jhg',
                              'jhh', 'jid', 'jp', 'ki', 'labinvest', 'leu',
                              'modpathol', 'mp', 'mt', 'mi', 'ncomms', 'npp',
                              'onc', 'pr', 'tpj', 'pj', 'pcan', 'sc'])

    def __init__(self):
        super(NatureDomain, self).__init__()

    @classmethod
    def predicate(self, post):
        log.info('testing {0} against NAture predicate'.format(post.id))
        #matches full article link or abstract
        full_regex = 'www.nature.com/\S+/journal/v\S+/n\S+/full/\S+.html'
        abst_regex = 'www.nature.com/\S+/journal/v\S+/n\S+/abs/\S+.html'
        full = re.search(full_regex, post.url)
        abst = re.search(abst_regex, post.url)
        if full is None and abst is None:  # Not an article
            return False
        if full is not None:
            full_url = post.url
        else:
            full_url = post.url.replace('/full/', '/abs/')
        parsed_url = urlparse(full_url)
        subjournal = parsed_url.path.split('/')[1]
        if subjournal in self.full_oa_subjournals:
            return True
        if subjournal not in self.opt_oa_subjournals:
            return False

        #We try to inspect the article's html to detect if access is limited
        try:
            page_html = urllib.request.urlopen(full_url)
        except urllib.error.HTTPError as e:
            log.exception(e)
            return False
        doc = lxml.html.fromstring(page_html.read())
        if doc.find(".//h1[@class='heading access-title entry-title']") is not None:
            return False
        else:
            return True

    @classmethod
    def pdf_url(self, post):
        parsed_url = urlparse(post.url)
        paths = parsed_url.path.split('/')
        paths[-2] = 'pdf'
        paths[-1] = paths[-1].rsplit('.')[0] + '.pdf'
        modified_path = '/'.join(paths)
        return urlunparse([parsed_url.scheme, parsed_url.netloc,
                           modified_path, parsed_url.params,
                           parsed_url.query, parsed_url.fragment])