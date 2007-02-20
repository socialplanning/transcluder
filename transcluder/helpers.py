"""
helper functions for configuration 
"""

from lxml import etree
import urlparse
from copy import copy 



###########################################
# some predicates for recursion decisions 
###########################################

def always_recurse(url): 
    return True 

def never_recurse(url): 
    return False

def recurse_for_localhost_only(url): 
    """
    a recursion predicate that only allows recursive
    transclusion from localhost only 
    """
    host = urlparse.urlparse(url)[1].split(':')[0]
    return host == 'localhost'

def make_recursion_predicate(whitelisted_prefixes): 
    """
    prepare a predicate for determining where 
    recursive transclusion is allowed from a 
    list of allowable prefixes. 
    eg: ['http://www.example.org/', 'https://www.example.org/']
    """
    prefixes = copy(whitelisted_prefixes)
    def predicate(url): 
        for prefix in prefixes: 
            if url.startswith(prefix): 
                return True
        return False 

    return predicate

###########################################
# helpers for uri templates 
###########################################

def make_uri_template_dict(request_url): 
    """
    makes a dict for use with uri template 
    substitution with standard entries based on the url 
    given, eg request.host, etc. 
    """

    scope = {}
    parts = urlparse.urlparse(request_url)
    scope['request.url'] = request_url
    if len(parts[0]):
        scope['request.scheme'] = parts[0]
    else:
        scope['request.scheme'] = 'http'
    if len(parts[1]):
        loc = parts[1]
        if loc.find(':') != -1:
            host, port = loc.spit(':')
            scope['request.host'] = host
            scope['request.port'] = port
        else:
            scope['request.host'] = loc
            scope['request.port'] = '80'
    else:
        scope['request.host'] = 'localhost'
        scope['request.port'] = '80'
    scope['request.path'] = parts[2]
    scope['request.params'] = parts[3]
    scope['request.query'] = parts[4]
    scope['request.fragment'] = parts[5]

    return scope

