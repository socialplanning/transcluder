"""
Transclusion WSGI middleware
"""

from paste.request import construct_url
from paste.response import header_value
from paste.wsgilib import intercept_output
import urlparse
from lxml import etree
import lxmlutils

from transcluder import helpers 
from transcluder.transclude import transclude 

from wsgiutils.resource_fetcher import *

class TranscluderMiddleware:
    def __init__(self, app, 
                 recursion_predicate=helpers.always_recurse): 

        self.app = app
        self.recursion_predicate = recursion_predicate

    def __call__(self, environ, start_response):
        # intercept the call if it is for an html document 
        status, headers, body = intercept_output(environ, self.app,
                                                 self.should_intercept,
                                                 start_response)
        if status is None:
            return body

        # perform transclusion if we intercepted 
        doc = etree.HTML(body)
        request_url = construct_url(environ)
        variables = self.get_template_vars(request_url)
        fetch = lambda url: self.etree_subrequest(url, environ)
        
        transclude(doc, request_url, variables, fetch, 
                   should_recurse=self.recursion_predicate)

        body = lxmlutils.tostring(doc)
        
        start_response(status, headers)
        return [body]

    def should_intercept(self, status, headers):
        type = header_value(headers, 'content-type')
        return type.startswith('text/html') or type.startswith('application/xhtml+xml')


    def get_template_vars(self, url): 
        return helpers.make_uri_template_dict(url)


    def etree_subrequest(self, url, environ):
        # XXX this is essentially a stub, 
        # should handle external requests, 
        # raise specific exceptions etc, etc. 
        # this is in no way robust

        url_parts = urlparse.urlparse(url)
        env = environ.copy()
        env['PATH_INFO'] = url_parts[2]
        if len(url_parts[4]):
            env['QUERY_STRING'] = url_parts[4]

        request_url = construct_url(environ, with_path_info=False, with_query_string=False)
        request_url_parts = urlparse.urlparse(request_url)

        if request_url_parts[0:2] == url_parts[0:2]:
            status, headers, body = get_internal_resource(env, url, self.app)
        else:
            status, headers, body = get_external_resource(url)
        if status.startswith('200'):
            return etree.HTML(body)
        else:
            raise Exception, status


