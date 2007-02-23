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
from transcluder.transclude import transclude 

from wsgifilter.resource_fetcher import *

from paste import httpheaders
from cookielib import split_header_words

import base64
import time

def get_set_cookies_from_headers(headers, url):
    """Gets the Set-Cookie headers (rather than getting and/or setting Cookie headers).
    """
    cookie_headers = [x[1] for x in headers if x[0].lower() == 'set-cookie']
    cookies = split_header_words(cookie_headers)
    
    cookies_by_key = {}
    for c in cookies: 
        cookie_dict = {}
        for k, v in c[1:]:
            cookie_dict[k.lower()] = v
        cookie_dict['name'], cookie_dict['value'] = c[0]
        if cookie_dict.has_key('max-ages'):
            cookie_dict['max-age'] = httpheaders.EXPIRES.parse(cookie_dict['max-age'])

        #fixme: check that domain is valid using crazy rfc2109 moon logic
        if not cookie_dict.has_key('domain'):
            cookie_dict['domain'] = urlparse(url)[1]

        key = (cookie_dict['domain'], cookie_dict['name'])
        cookies_by_key [key] = cookie_dict

    return cookies_by_key

cookie_attributes = ['name', 'value', 'domain', 'path', 'max-age', 'secure', 'version']
def wrap_cookies(cookies, extra_attrs=None):
    """
    """
    output_list = []
    for cookie in cookies.values():
        cookie_list = []
        for attr in cookie_attributes:
            cookie_list.append(cookie.get(attr, ''))
        output_list.append("\1".join(cookie_list))
    value = base64.encodestring("\0".join(output_list)).replace('=','-')[:-1]

    wrapped_cookie = "m=%s" % value 
    if not extra_attrs: 
        extra_attrs = {}
    
    if not extra_attrs.has_key('max-age'):
        extra_attrs['max-age'] = 2147368447
    
    tmp = []
    httpheaders.LAST_MODIFIED.update(tmp, time=extra_attrs['max-age'])
    extra_attrs['max-age']= tmp[0][1]

    for key, val in extra_attrs.items(): 
        wrapped_cookie += ";%s = %s" % (key,val)

    return wrapped_cookie 

def unwrap_cookies(wrapped_cookie): 
    cookie_parts = split_header_words([wrapped_cookie])
    if not cookie_parts:
        return []
    cookie = cookie_parts[0][0][1]
    if not cookie:
        return []
    cookie = cookie.replace('-', '=')
    cookie += '\n'
    cookies = base64.decodestring(cookie).split("\0")

    unwrapped = []
    for encoded_cookie in cookies:
        split_cookie = encoded_cookie.split("\1")
        cookie_dict = {}
        for i in range(len(cookie_attributes)):
            cookie_dict[cookie_attributes[i]] = split_cookie[i]
        cookie_dict['max-age'] = httpheaders.EXPIRES.parse(cookie_dict['max-age'])
        unwrapped.append(cookie_dict)
    return unwrapped

def expire_cookies(cookies):
    out = []
    now = time.time()
    for cookie in cookies:
        if cookie['max-age'] < now:
            out.append(cookie)
    return out

def is_fqdn(domain):
    """Or something.  Should really try to avoid .co.uk etc"""
    return "." in domain[1:]

def get_relevant_cookies(env, url):
    domain = urlparse(url)[1]
    cookies = []
    for cookie in env['transcluder.incookies']:
        if cookie['domain'] == domain:
            cookies.append(cookie)
        if (cookie['domain'].startswith('.') and 
            is_fqdn(cookie['domain']) and 
            domain.endswith(cookie['domain'])):
            cookies.append(cookie)
    #fixme: check paths
    return cookies

def make_cookie_string(cookies):
    cookie_strings = []
    for cookie in cookies:
        #fixme: append domain, path
        cookie_strings.append("%s=%s" % (cookie['name'], cookie['value']))
    return ",".join(cookie_strings)


class TranscluderMiddleware:
    def __init__(self, app, 
                 recursion_predicate=helpers.always_recurse): 

        self.app = app
        self.recursion_predicate = recursion_predicate

    def __call__(self, environ, start_response):

        environ = environ.copy()

        environ['transcluder.outcookies'] = {}
        if environ.has_key('HTTP_COOKIE'):
            environ['transcluder.incookies'] = expire_cookies(unwrap_cookies(environ['HTTP_COOKIE']))
        else:
            environ['transcluder.incookies'] = {}
        request_url = construct_url(environ)
        environ['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(environ, request_url))

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
        fetch = lambda url: self.etree_subrequest(url, environ)
        
        transclude(doc, request_url, variables, fetch, 
                   should_recurse=self.recursion_predicate)

        body = lxmlutils.tostring(doc)

        newcookie = wrap_cookies(environ['transcluder.outcookies'])
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
        env['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(env, url))

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
        environ['transcluder.outcookies'].update(get_set_cookies_from_headers(headers, effective_url))
        if status.startswith('200'):
            return etree.HTML(body)
        else:
            raise Exception, status


