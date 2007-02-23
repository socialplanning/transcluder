from cookielib import split_header_words as broken_split_header_words, domain_match, IPV4_RE, http2time
import base64
import time
import re
from urlparse import urlparse 
from paste import httpheaders


__all__ = ['split_header_words', 
           'get_set_cookies_from_headers', 
           'wrap_cookies', 
           'unwrap_cookies', 
           'expire_cookies', 
           'get_relevant_cookies', 
           'make_cookie_string' ]



def split_header_words(cookies):
    """One day, I got a cookie like this from livejournal.  No, really!  Note the comma after thursday:
    Set-Cookie: langpref=; expires=Thursday, 01-Jan-1970 00:00:00 GMT; path=/; domain=.livejournal.com
    At that point, I decided to become a farmer.  Farmers don't parse.
    """

    pat = re.compile("expires=((?:\w+)day,.*?)([;,]|$)")
    return broken_split_header_words(map(lambda c : pat.sub(r'expires="\1"\2', c), cookies))


def get_set_cookies_from_headers(headers, url):
    """Gets the Set-Cookie headers (rather than getting and/or setting Cookie headers).

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/morx')]
    >>> url = 'http://www.example.com/morx/fleem'
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name') : {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}}
    True

    Check domain restrictions:
    >>> headers.append(('Set-Cookie', 'name=value;domain=.badsite.com;path=/morx'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}}
    True

    Check path restrictions:
    >>> headers.append(('Set-Cookie', 'name=value;domain=.example.com;path=/fleem'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}}
    True

    Check default domain
    >>> headers.append(('Set-Cookie', 'name=value;path=/morx'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}, ('www.example.com', 'name'): {'path': '/morx', 'domain': 'www.example.com', 'name': 'name', 'value': 'value'}}
    True

    >>> headers.append(('Set-Cookie', 'name=value;path=/morx; Max-Age=1134771719'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}, ('www.example.com', 'name'): {'path': '/morx', 'domain': 'www.example.com', 'name': 'name', 'value': 'value', 'expires': str(int(time.time() + 1134771719))}}
    True

    >>> headers.append(('Set-Cookie', 'BMLschemepref=; expires=Thursday, 01-Jan-1970 00:00:00 GMT; path=/; domain=.livejournal.com'))
    >>> get_set_cookies_from_headers(headers, url) == {('.example.com', 'name'): {'path': '/morx', 'domain': '.example.com', 'name': 'name', 'value': 'value'}, ('www.example.com', 'name'): {'path': '/morx', 'domain': 'www.example.com', 'name': 'name', 'value': 'value', 'expires': str(int(time.time() + 1134771719))}}
    True


    """
    cookie_headers = [x[1] for x in headers if x[0].lower() == 'set-cookie']
    cookies = split_header_words(cookie_headers)
    
    cookies_by_key = {}
    for c in cookies: 
        cookie_dict = {}
        for k, v in c[1:]:
            cookie_dict[k.lower()] = v
        cookie_dict['name'], cookie_dict['value'] = c[0]
        if cookie_dict.has_key('expires'):
            cookie_dict['expires'] = http2time(cookie_dict['expires'])
        if cookie_dict.has_key('max-age'):            
            cookie_dict['expires'] = str(int(time.time()) + int(cookie_dict['max-age']))
            del cookie_dict['max-age']

        #rfc2109 section 4.3.2 "moon logic"
        urlparts = urlparse(url)
        request_host = urlparts[1]
        if cookie_dict.has_key('domain'):
            if not IPV4_RE.search(request_host):
                if (not request_host.endswith(cookie_dict['domain']) or 
                    '.' in request_host[:len(request_host) - len(cookie_dict['domain'])]):
                    continue
        else:
            cookie_dict['domain'] = request_host

        if cookie_dict.has_key('path'):
            if not urlparts[2].startswith(cookie_dict['path']):
                continue
        #end moon logic

        key = (cookie_dict['domain'], cookie_dict['name'])
        cookies_by_key [key] = cookie_dict

    return cookies_by_key

cookie_attributes = ['name', 'value', 'domain', 'path', 'expires', 'secure', 'version']
def wrap_cookies(cookies, extra_attrs=None):
    """Converts a set of cookies into a single cookie

    >>> headers = [('Set-Cookie', 'name=value;domain=.example.com;path=/morx')]
    >>> url = 'http://www.example.com/morx/fleem'
    >>> x = get_set_cookies_from_headers(headers, url).values()
    >>> unwrap_cookies(wrap_cookies(x)) == x
    True

    
    """
    output_list = []
    for cookie in cookies:
        cookie_list = []
        for attr in cookie_attributes:
            cookie_list.append(cookie.get(attr, ''))
        output_list.append("\1".join(cookie_list))
    value = base64.encodestring("\0".join(output_list)).replace('=','-')[:-1]

    wrapped_cookie = "m=%s" % value 
    if not extra_attrs: 
        extra_attrs = {}

    if not extra_attrs.has_key('max-age') and not extra_attrs.has_key('expires'):
        extra_attrs['max-age'] = 2147368447        
    
    if extra_attrs.has_key('expires') and isinstance(extra_attrs['expires'], str):
        tmp = []
        httpheaders.LAST_MODIFIED.update(tmp, time=extra_attrs['expires'])
        extra_attrs['expires']= tmp[0][1]

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
            if split_cookie[i]: 
                cookie_dict[cookie_attributes[i]] = split_cookie[i]
        if cookie_dict.has_key('expires'): 
            cookie_dict['expires'] = http2time(cookie_dict['expires'])
        unwrapped.append(cookie_dict)
    return unwrapped

def expire_cookies(cookies):
    out = []
    now = time.time()
    for cookie in cookies:
        if not cookie.has_key('expires') or cookie['expires'] < now:
            out.append(cookie)
    return out


def get_relevant_cookies(jar, url):
    urlparts = urlparse(url)
    domain = urlparts[1]
    path = urlparts[2]

    filtered = [x for x in jar if domain_match(domain, x['domain'])]
    return [x for x in filtered if path.startswith(x.get('path',''))]


def make_cookie_string(cookies):
    cookie_strings = []
    for cookie in cookies:
        #fixme: append domain, path
        cookie_strings.append("%s=%s" % (cookie['name'], cookie['value']))
    return ",".join(cookie_strings)