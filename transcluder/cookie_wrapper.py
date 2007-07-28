from cookielib import parse_ns_headers 
from cookielib import domain_match, IPV4_RE, http2time
from Cookie import SimpleCookie
import base64
import time
import re
from urlparse import urlparse 
from paste import httpheaders
import traceback

"""
utilities for merging cookies from various sources 

this does not handle merging cookies whose size totals
more than the single cookie limit of 4k
"""

__all__ = ['parse_setcookie_headers',
           'parse_cookie_header',
           'get_set_cookies_from_headers', 
           'wrap_cookies', 
           'unwrap_cookies', 
           'expire_cookies',
           'cookie_key',
           'get_relevant_cookies', 
           'make_cookie_string' ]

def parse_setcookie_headers(setcookie_headers): 
    if len(setcookie_headers):
        cookies = parse_ns_headers(setcookie_headers)
        return [make_cookie_dict(x) for x in cookies]
    return []
    
    
def parse_cookie_header(cookie_header_val):
    """
    similar to parse_setcookie_header, but
    using the syntax of the cookie header.
    returns a list of cookies each represented
    as a list containing name value pairs.
    the first element is the name/value of
    the cookie. 
    """
    if not cookie_header_val:
        return []
    parser = SimpleCookie()
    parser.load(cookie_header_val)
    outcookies = []
    for unused,cookie in parser.items():
        cookie_tups = []
        cookie_tups.append((cookie.key, cookie.coded_value))
        # may also contain a path and domain attribute
        for key, val in cookie.items():
            if key.lower() in ['domain', 'path'] and val:
                cookie_tups.append((key,val))
        outcookies.append(cookie_tups)
    return [make_cookie_dict(x) for x in outcookies] 


def make_cookie_dict(c):
    cookie_dict = {}
    for k, v in c[1:]:
        cookie_dict[k.lower()] = v
    cookie_dict['name'], cookie_dict['value'] = c[0]

    #if cookie_dict.has_key('expires'):
    #    import pdb; pdb.set_trace()
    #    cookie_dict['expires'] = http2time(cookie_dict['expires'])

    if cookie_dict.has_key('max-age'):            
        cookie_dict['expires'] = str(int(time.time()) + int(cookie_dict['max-age']))
        del cookie_dict['max-age']

    return cookie_dict

def cookie_key(cookie_map):
    return (cookie_map['domain'],
            cookie_map.get('path',''),
            cookie_map['name'])
    
def get_set_cookies_from_headers(headers, url):
    """Parses Set-Cookie headers which are legitimate for the
    URL given. (rather than getting and/or setting Cookie headers).

    returns a map from 
    (domain, path, name) -> cookie_map 
    where domain is the origin domain specified by the cookie, path
    is the path restriction set by the cookie, and 
    name is the application set name associated with the value of 
    the cookie. Other cookie information such as version etc 
    are contained in the associated map. To obtain a list of 
    cookie_maps, just take values() of the result. 

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/morx')]
    >>> url = 'http://www.example.com/morx/fleem'
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name') : {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}}
    True

    Check domain restrictions:
    >>> headers.append(('Set-Cookie', 'name=value;domain=.badsite.com;path=/morx'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}}
    True

    Check domain restrictions:
    >>> headers.append(('Set-Cookie', 'name=value;domain=foo.bar.example.com'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}}
    True

    Check path restrictions:
    >>> headers.append(('Set-Cookie', 'name=value;domain=.example.com;path=/fleem'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}}
    True

    Check default domain
    >>> headers.append(('Set-Cookie', 'name=value;path=/morx'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}, ('www.example.com', '/morx', 'name'): {'path': '/morx', 'domain': 'www.example.com', 'name': 'name', 'value': 'value', 'version': '0'}}
    True

    >>> headers.append(('Set-Cookie', 'name=value;path=/morx; Max-Age=1134771719'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', '/morx', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value', 'version': '0'}, ('www.example.com', '/morx', 'name'): {'path': '/morx', 'domain': 'www.example.com', 'name': 'name', 'version': '0', 'value': 'value', 'expires': str(int(time.time() + 1134771719))}}
    True


    >>> headers = [('Set-Cookie', 'BMLschemepref=; expires=Thursday, 01-Jan-1970 00:00:00 GMT; path=/; domain=.example.com')]
    >>> get_set_cookies_from_headers(headers, url) ==  {('.example.com', '/', 'BMLschemepref'): {'path': '/', 'domain': '.example.com', 'expires': 0, 'name': 'BMLschemepref', 'version': '0', 'value': ''}}
    True
    
    """
    cookie_headers = [x[1] for x in headers if x[0].lower() == 'set-cookie']
    cookies = parse_setcookie_headers(cookie_headers)

    #print "GSCFH(%s) in: %s / (%s)" % (url, cookies, cookie_headers)
    
    cookies_by_key = {}
    for cookie_dict in cookies: 

        #rfc2109 section 4.3.2 "moon logic"
        urlparts = urlparse(url)
        request_host = urlparts[1]
        if cookie_dict.has_key('domain'):
            if not IPV4_RE.search(request_host):
                if (not request_host.endswith(cookie_dict['domain']) or 
                    '.' in request_host[:len(request_host) - len(cookie_dict['domain'])]):
                    continue
        else:
            # default the domain to the exact request_host
            cookie_dict['domain'] = request_host

        if cookie_dict.has_key('path'):
            if not urlparts[2].startswith(cookie_dict['path']):
                continue
        #end moon logic

        domain = cookie_dict.get('domain', '')
        if ':' in domain:
            cookie_dict['domain'] = domain[:domain.index(":")]

        key = cookie_key(cookie_dict)
        cookies_by_key[key] = cookie_dict

    return cookies_by_key


SESSION_COOKIE_NAME = '__cw_wrapped_session__'
DURABLE_COOKIE_NAME = '__cw_wrapped__'
def wrap_cookies(cookies, oldcookies=''):
    """
    returns a list of set-cookie header values created
    by wrapping the cookies in the list of cookie maps
    given

    oldcookies is an optional Cookie header value. If
    specified, cookies which should no longer appear
    in the output will be issued as a cookie expiring
    in the past.


    the cookies are separated into a session long cookie
    and a more persistent cookie which contains longer
    lived cookies. 
    >>> url = 'http://www.example.com/morx/fleem'
    >>> headers = [('Set-Cookie', 'abc=123'), ('Set-Cookie', 'def=123; max-age=1000')]
    >>> x = get_set_cookies_from_headers(headers, url).values()
    >>> wcs = wrap_cookies(x)
    >>> wcs[0].startswith(SESSION_COOKIE_NAME)
    True
    >>> wcs[1].startswith(DURABLE_COOKIE_NAME)
    True
    >>> _unwrap_cookies(wcs[0], [SESSION_COOKIE_NAME])[0]['name'] == 'abc'
    True
    >>> _unwrap_cookies(wcs[1], [DURABLE_COOKIE_NAME])[0]['name'] == 'def'
    True

    if there is no cookie, but there was an old cookie,
    a delete is issued
    >>> wrap_cookies([], oldcookies='__cw_wrapped_session__=whatever')
    ['__cw_wrapped_session__=deleted; expires=Monday, 01-Jan-90 00:00:01 GMT; path=/']
    """
    out_cookies = []

    session = _wrap_cookies(session_cookies(cookies), SESSION_COOKIE_NAME)
    durable = _wrap_cookies(durable_cookies(cookies), DURABLE_COOKIE_NAME, 
                            extra_attrs={'max-age': 2147368447})
    if session:
        out_cookies.append(session)
    elif has_cookie(oldcookies, SESSION_COOKIE_NAME):
        out_cookies.append(make_expire_cookie(SESSION_COOKIE_NAME))
        
    if durable:
        out_cookies.append(durable)
    elif has_cookie(oldcookies, DURABLE_COOKIE_NAME):
        out_cookies.append(make_expire_cookie(DURABLE_COOKIE_NAME))

    return out_cookies
    
def session_cookies(cookies):
    return [x for x in cookies if not x.has_key('expires')]

def durable_cookies(cookies):
    return [x for x in cookies if x.has_key('expires')]

def has_cookie(cookie_header, cookie_name):
    """
    returns True if a Cookie: header value
    has a cookie with the name given
    """
    for cookie in parse_cookie_header(cookie_header):
        if cookie.get('name','') == cookie_name:
            return True
    return False

def make_expire_cookie(cookie_name):
    return "%s=deleted; expires=Monday, 01-Jan-90 00:00:01 GMT; path=/" % cookie_name


cookie_attributes = ['name', 'value', 'domain', 'path',
                     'expires', 'secure', 'version']
def _wrap_cookies(cookies, cookie_name, extra_attrs=None):
    """Converts a set of cookies into a single cookie

    accepts a list of 'cookie-maps' associating the name and value of 
    the cookie as well as other cookie attributes and attribute values  

    returns a value suitable for use as the value of the http Cookie 
    header. by default the cookie never expires, has a path of / and
    no domain. These may be overridden by specifying values in the
    extra_attrs dictionary. 

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/morx')]
    >>> url = 'http://www.example.com/morx/fleem'
    >>> x = get_set_cookies_from_headers(headers, url).values()
    >>> x == _unwrap_cookies(_wrap_cookies(x, 'foo'), ['foo'])
    True

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/zoo, foo=bar; domain=.example.com')]
    >>> url = 'http://www.example.com/zoo/bar'
    >>> x = get_set_cookies_from_headers(headers, url).values()
    >>> x == _unwrap_cookies(_wrap_cookies(x, 'foo'), ['foo'])
    True


    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/zoo'), ('Set-Cookie', 'foo=bar; domain=.example.com')]
    >>> url = 'http://www.example.com/zoo/bar'
    >>> x = get_set_cookies_from_headers(headers, url).values()
    >>> y = _unwrap_cookies(_wrap_cookies(x, 'foo'), ['foo'])
    >>> x == y 
    True

    """
    #print "wrapping %s" % cookies
    
    if len(cookies) == 0:
        return None
    
    output_list = []
    for cookie in cookies:
        cookie_list = []
        for attr in cookie_attributes:
            cookie_list.append(cookie.get(attr, ''))
        output_list.append("\1".join(cookie_list))


    merged = '\2'.join(output_list)
    b64enc = base64.b64encode(merged)
    cookie_val = b64enc.replace('=','@')

    wrapped_cookie = "%s=%s" % (cookie_name, cookie_val) 
    if not extra_attrs: 
        extra_attrs = {}

    if extra_attrs.has_key('expires') and isinstance(extra_attrs['expires'], str):
        tmp = []
        httpheaders.LAST_MODIFIED.update(tmp, time=extra_attrs['expires'])
        extra_attrs['expires']= tmp[0][1]

    if not extra_attrs.has_key('path'):
        extra_attrs['path'] = '/'
        
    for key, val in extra_attrs.items(): 
        wrapped_cookie += ";%s = %s" % (key,val)

    return wrapped_cookie 

def unwrap_cookies(cookie_header):
    """
    """

    return _unwrap_cookies(cookie_header, [SESSION_COOKIE_NAME,
                                           DURABLE_COOKIE_NAME])

def _unwrap_cookies(cookie_header, cookie_names): 
    """
    Unwraps any wrapped cookies in the cookie header value
    given, returns list of cookie-maps. 

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/zoo, foo=bar; domain=.example.com')]
    >>> url = 'http://www.example.com/zoo/bar'
    >>> cookies = get_set_cookies_from_headers(headers, url).values()
    >>> x = _wrap_cookies(cookies, 'foo')
    >>> unwrapped = _unwrap_cookies('quux=zoo; %s; blurn=blarg' % x, ['foo'])
    >>> cookies == unwrapped
    True

    >>> _unwrap_cookies('foo=bar; domain=.example.com', ['missing_cookie'])
    []
    >>> _unwrap_cookies('%s=somegarbage' % '__wf_wrapped__', ['__wf_wrapped__'])
    []
    >>> _unwrap_cookies('foo=bar; domain=.example.com, name=value; domain=.baz.org', ['__wf_wrapped__'])
    []
    """
    cookies = parse_cookie_header(cookie_header)
    if not cookies:
        return []

    unwrapped = {}
    for cookie in cookies:
        if cookie['name'] in cookie_names: 
            try:
                cms = unwrap_cookie_val(cookie['value'])
                for cm in cms:
                    unwrapped[cookie_key(cm)] = cm
            except Exception:
                # XXX log
                pass
    return unwrapped.values()

def unwrap_cookie_val(cookie): 
    """
    splits a wrapped cookie value created with wrap_cookies
    into component cookie-maps 
    """
    
    if not cookie:
        return []

    cookie = cookie.replace('@', '=')

    unwrapped = []

    cookies = base64.b64decode(cookie).split("\2")
    for encoded_cookie in cookies:
        split_cookie = encoded_cookie.split("\1")
        cookie_dict = {}
        for i in range(len(cookie_attributes)):
            if split_cookie[i]: 
                cookie_dict[cookie_attributes[i]] = split_cookie[i]
            #if cookie_dict.has_key('expires'): 
            #    cookie_dict['expires'] = http2time(cookie_dict['expires'])
        unwrapped.append(cookie_dict)
     
    return unwrapped

def expire_cookies(cookies):
    """
    accepts a list of cookie-maps and returns a list of those 
    cookie maps whose expires date has not yet arrived. 
    """
    out = []
    now = time.time()
    
    for cookie in cookies:
        if not cookie.has_key('expires'):
            out.append(cookie)
        else:
            expire_time = int(cookie['expires'])
            if expire_time > now:
                out.append(cookie)
    return out


def get_relevant_cookies(jar, url):
    """
    accepts a list of cookie maps and returns those 
    cookie maps which should be sent to the url 
    specified according to the domain and path 
    specifications in the cookies. 
    """
    urlparts = urlparse(url)
    domain = urlparts[1]
    path = urlparts[2]

    if ':' in domain:
        domain = domain[:domain.index(':')]

    cks = [x for x in jar if domain_match(domain, x['domain'])
            and path.startswith(x.get('path',''))]

    #print "get_relevant_cookies(%s,%s) => %s" % (jar, url, cks)

    return cks

def make_cookie_string(cookies):
    """
    flattens a cookie map into a string suitable 
    for use as the value of the http Cookie header. 
    """

    return "; ".join(["%s=%s" % (cookie['name'], cookie['value']) for cookie in cookies])
