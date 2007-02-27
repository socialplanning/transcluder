"""
Transclusion WSGI middleware
"""

from paste.request import construct_url
from paste.response import header_value
from paste.wsgilib import intercept_output
from urlparse import urlparse
from lxml import etree
import lxmlutils

from transcluder import helpers 
from transcluder.transclude import Transcluder

from wsgifilter.resource_fetcher import *
from transcluder.cookie_wrapper import * 
from transcluder.tasklist import PageManager, TaskList
from transcluder.deptracker import DependencyTracker

class TranscluderMiddleware:
    def __init__(self, app, deptracker = None, tasklist = None,
                 recursion_predicate=helpers.always_recurse): 

        self.app = app
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
        request_url = construct_url(environ)
        environ['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(environ['transcluder.incookies'], request_url))

        # intercept the call if it is for an html document 
        status, headers, body = intercept_output(environ, self.app,
                                                 self.should_intercept,
                                                 start_response)
        if status is None:
            return body

        environ['transcluder.outcookies'].update(get_set_cookies_from_headers(headers, request_url))

        # perform transclusion if we intercepted 
        doc = etree.HTML(body)
        variables = self.get_template_vars(request_url)
        
        tc = Transcluder(variables, None, should_recurse=self.recursion_predicate)

        pm = PageManager(request_url, environ, self.deptracker, tc.find_dependencies, self.tasklist, self.etree_subrequest)
        def simple_fetch(url):
            status, headers, body, parsed = pm.fetch(url)
            if status.startswith('200'):
                return parsed
            else:
                raise Exception, status
        tc.fetch = simple_fetch
        
        tc.transclude(doc, request_url)

        body = lxmlutils.tostring(doc)

        newcookie = wrap_cookies(environ['transcluder.outcookies'].values())
        headers.append(('Set-Cookie', newcookie))

        start_response(status, headers)
        return [body]

    def should_intercept(self, status, headers):
        type = header_value(headers, 'content-type')
        return type.startswith('text/html') or type.startswith('application/xhtml+xml')


    def get_template_vars(self, url): 
        return helpers.make_uri_template_dict(url)


    def premangle_subrequest(self, url, environ):
        """
        this function is a hook for subclasses to arbitrarily 
        rewrite subrequests. 
        """
        return url

    def etree_subrequest(self, url, environ):

        effective_url = self.premangle_subrequest(url, environ)

        url_parts = urlparse(effective_url)
        env = environ.copy()
        env['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(env['transcluder.incookies'], url))

        env['PATH_INFO'] = url_parts[2]
        if len(url_parts[4]):
            env['QUERY_STRING'] = url_parts[4]

        request_url = construct_url(environ, with_path_info=False, with_query_string=False)
        request_url_parts = urlparse(request_url)

        if request_url_parts[0:2] == url_parts[0:2]:
            status, headers, body = get_internal_resource(url, env, self.app)
        else:
            status, headers, body = get_external_resource(url, env)

        #put cookies into real environ
        environ['transcluder.outcookies'].update(get_set_cookies_from_headers(headers, url))

        if status.startswith('200'):
            parsed = etree.HTML(body)
        else:
            parsed = None
        return status, headers, body, parsed


