import os
import sys
from lxml import etree
from paste.fixture import TestApp
from paste.urlparser import StaticURLParser
from paste.response import header_value
from transcluder.middleware import TranscluderMiddleware
from formencode.doctest_xml_compare import xml_compare

"""
this runs tests in the test-data directory. 
for each subdir, these expect: 

index.html - the document to fetch through the transcluder
expected.html - the document which should be produced 
"""


def html_string_compare(astr, bstr):
    """
    compare to strings containing html based on html
    equivalence. Raises ValueError if the strings are
    not equivalent.
    """
    def reporter(x):
        print x
    a = None
    b = None
    try:
        a = etree.HTML(astr)
    except:
        print a
        raise
    try:
        b = etree.HTML(bstr)
    except:
        print b
        raise
    reporter = []
    result = xml_compare(a, b, reporter.append)
    if not result:
        raise ValueError("Comparison failed between actual:\n==================\n%s\n\nexpected:\n==================\n%s\n\nReport:\n%s"
            % (astr, bstr, '\n'.join(reporter)))


def run_dir(dir):
    static_app = StaticURLParser(dir)
    trans_app = TranscluderMiddleware(static_app)
    app = TestApp(trans_app)

    result = app.get('/index.html')
    expected = app.get('/expected.html')
    html_string_compare(result.body, expected.body)

def test_all():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data')
    for dir in os.listdir(test_dir):
        yield run_dir, os.path.join(test_dir, dir)

if __name__ == '__main__':
    pass
