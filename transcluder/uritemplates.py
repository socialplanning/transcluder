
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


import re

"""
performs uri template substitution as described in:
http://www.ietf.org/internet-drafts/draft-gregorio-uritemplate-00.txt
"""

SUBST_PAT = re.compile("{(.*?)}")
def expand_uri_template(uri, scope):
    """
    returns the url given with instances
    of {key} replaced with scope[key].

    examples from draft-gregorio-uritemplate-00.txt:
    >>> vars = {'a': 'fred', 'b':'barney', 'c': 'cheeseburger', '20': 'this-is-spinal-tap', 'a~b': 'none%20of%20the%20above', 'scheme': 'https', 'p': 'quote=to+bo+or+not+to+be', 'e': '', 'q': 'hullo#world'}
    >>> expand_uri_template('http://example.org/{a}/{b}/', vars)
    'http://example.org/fred/barney/'
    >>> expand_uri_template('http://example.org/{a}{b}/', vars)
    'http://example.org/fredbarney/'
    >>> expand_uri_template('http://example.org/page1#{a}', vars)
    'http://example.org/page1#fred'
    >>> expand_uri_template('{scheme}://{20}.example.org?date={wilma}&option={a}', vars)
    'https://this-is-spinal-tap.example.org?date=&option=fred'
    >>> expand_uri_template('http://example.org/{a~b}', vars)
    'http://example.org/none%20of%20the%20above'
    >>> expand_uri_template('http://example.org?{p}', vars)
    'http://example.org?quote=to+bo+or+not+to+be'
    >>> expand_uri_template('http://example.com/order/{c}/{c}/{c}/', vars)
    'http://example.com/order/cheeseburger/cheeseburger/cheeseburger/'
    >>> expand_uri_template('http://example.com/{q}', vars)
    'http://example.com/hullo#world'
    >>> expand_uri_template('http://example.com/{e}/', vars)
    'http://example.com//'

    >>> vars = {'a': 'fred barney', 'b': '%'}
    >>> expand_uri_template('http://example.org/{a}', vars)
    'http://example.org/fred barney'
    >>> expand_uri_template('http://example.org/{b}/', vars)
    'http://example.org/%/'
    """

    def lookup(m):
        key = m.group(1)
        if key in scope:
            return scope[key]
        return ""

    return re.sub(SUBST_PAT, lookup, uri)
