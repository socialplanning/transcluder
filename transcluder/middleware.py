
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


"""
Transclusion WSGI middleware
"""
import traceback
import httplib
import re

from paste.request import construct_url
from paste.response import header_value, replace_header
from paste.wsgilib import intercept_output
from urlparse import urlparse
from lxml import etree
import lxmlutils

from transcluder import helpers 
from transcluder.transclude import Transcluder

from wsgifilter.resource_fetcher import *
from wsgifilter.cache_utils import parse_merged_etag
from transcluder.cookie_wrapper import * 
from transcluder.tasklist import PageManager, TaskList
from transcluder.deptracker import DependencyTracker


TRANSCLUDED_HTTP_HEADER = 'HTTP_X_TRANSCLUDED'

def is_conditional_get(environ):
    return 'HTTP_IF_MODIFIED_SINCE' in environ or 'HTTP_IF_NONE_MATCH' in environ

class TranscluderMiddleware:
    def __init__(self, app, deptracker = None, tasklist = None,
                 include_predicate=helpers.all_urls,
                 recursion_predicate=helpers.all_urls): 

        self.app = app
        self.include_predicate = include_predicate
        self.recursion_predicate = recursion_predicate
        if deptracker:
            self.deptracker = deptracker
        else:
            self.deptracker = DependencyTracker()
        if tasklist:
            self.tasklist = tasklist
        else:
            self.tasklist = TaskList()

    def __call__(self, environ, start_response):
        environ = environ.copy()
        
        environ['transcluder.outcookies'] = {}
        if environ.has_key('HTTP_COOKIE'):
            environ['transcluder.incookies'] = expire_cookies(unwrap_cookies(environ['HTTP_COOKIE']))
        else:
            environ['transcluder.incookies'] = {}


        if environ.has_key('HTTP_IF_NONE_MATCH'): 
            environ['transcluder.etags'] = parse_merged_etag(environ['HTTP_IF_NONE_MATCH'])
        else: 
            environ['transcluder.etags'] = {}

        request_url = construct_url(environ)
        environ[TRANSCLUDED_HTTP_HEADER] = request_url
        
        variables = self.get_template_vars(request_url)
        
        tc = Transcluder(variables, None,
                         should_include=self.include_predicate,
                         should_recurse=self.recursion_predicate)

        pm = PageManager(request_url, environ, self.deptracker, tc.find_dependencies, self.tasklist, self.etree_subrequest)
        def simple_fetch(url):
            status, headers, body, parsed = pm.fetch(url)
            if status.startswith('200'):
                return parsed
            else:
                raise Exception, 'Status was: %s' % status 
            
        tc.fetch = simple_fetch

        if is_conditional_get(environ) and not pm.is_modified():
            headers = [] 
            pm.merge_headers_into(headers)
            start_response('304 Not Modified', headers)
            return []

        pm.begin_speculative_gets() 

        status, headers, body, parsed = pm.fetch(request_url)

        if parsed: 
            tc.transclude(parsed, request_url)
            # XXX doctype 
            body = lxmlutils.tostring(parsed, doctype_pair=("-//W3C//DTD HTML 4.01 Transitional//EN",
                                                            "http://www.w3.org/TR/html4/loose.dtd"))
            replace_header(headers, 'content-length', str(len(body)))
            replace_header(headers, 'content-type', 'text/html; charset=utf-8')

        pm.merge_headers_into(headers)

        #print "outbound headers: %s" % headers
        
        start_response(status, headers)
        return [body]

    HTML_DOC_PAT = re.compile(r"^.*<\s*html(\s*|>).*$",re.I|re.M)
    def is_html(self, status, headers, body):
        type = header_value(headers, 'content-type')
        if type and (type.startswith('text/html') or type.startswith('application/xhtml+xml')):
            if self.HTML_DOC_PAT.search(body) is not None:
                return True
            
        return False


    def get_template_vars(self, url): 
        return helpers.make_uri_template_dict(url)


    def premangle_subrequest(self, url, environ):
        """
        this function is a hook for subclasses to arbitrarily 
        rewrite subrequests. 
        """
        return url

    def etree_subrequest(self, url, environ):
        try: 
            effective_url = self.premangle_subrequest(url, environ)

            url_parts = urlparse(effective_url)
            env = environ.copy()

            env['PATH_INFO'] = url_parts[2]
            if len(url_parts[4]):
                env['QUERY_STRING'] = url_parts[4]


            request_url = construct_url(environ, with_path_info=False,
                                        with_query_string=False)
            request_url_parts = urlparse(request_url)

            if url == construct_url(environ):
                status, headers, body = intercept_output(environ, self.app)
            elif url_parts[0] == 'file':
                status, headers, body = get_file_resource(file, env)
            elif request_url_parts[0:2] == url_parts[0:2]:
                status, headers, body = get_internal_resource(url, env, self.app)
            else:
                status, headers, body = get_external_resource(url, env)

            if status.startswith('200') and self.is_html(status, headers, body):
                parsed = etree.HTML(body)
            else:
                parsed = None

            return status, headers, body, parsed
        except Exception, message:
            # httplib throws all sorts of fun exceptions to here
            # some from socket and elsewhere when minor normal
            # problems occur. Many of these should be consumed 
            # to allow subpage fetching failures to occur gracefully.
            # the option to freak out is preserved by returning a
            # 500 status code.
            
            # XXX should be logged
            traceback.print_exc()
            err = str(message) # traceback.format_exc()
            headers = [('content-length',len(err)),
                       ('content-type','text/plain')]
            return ('500 Server Error', headers, err, None)
