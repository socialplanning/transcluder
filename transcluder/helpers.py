"""
helper functions for configuration 
"""
from copy import copy 
from lxml import etree
import re
import urlparse





####################################################
# some predicates for recursion/inclusion decisions 
####################################################

def all_urls(url): 
    return True 

def no_urls(url): 
    return False

def localhost_only(url): 
    """
    a recursion predicate that only allows recursive
    transclusion from localhost only 
    """
    host = urlparse.urlparse(url)[1].split(':')[0]
    return host == 'localhost'

def make_regex_predicate(regex_pat):
    pat = re.compile(regex_pat)
    def predicate(url):
        host = urlparse.urlparse(url)[1].split(':')[0]
        return re.search(pat, host, re.I) is not None
    return predicate

def make_whitelist_predicate(whitelisted_prefixes): 
    """
    prepare a predicate for determining where 
    whis is true for urls starting with any prefix
    given in whitelisted_prefixes
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
            host, port = loc.split(':')
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

