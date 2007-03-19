# Note: test_parallel_gets has been renamed to teXst_parallel_gets so
# that it does not get run by default, because it is slow.  Also, the __main__ stuff has been
# removed

import re
import os
import sys
import time
from lxml import etree
from paste.fixture import TestApp
from paste.urlparser import StaticURLParser
from paste.response import header_value
from paste.request import construct_url
from paste.wsgilib import intercept_output
from paste import httpheaders
from transcluder.middleware import TranscluderMiddleware
from transcluder.tasklist import TaskList
from formencode.doctest_xml_compare import xml_compare
from wsgifilter.fixtures.cache_fixture import CacheFixtureApp, CacheFixtureResponseInfo
import traceback 

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


def make_http_time(t):
    tmp = []
    httpheaders.LAST_MODIFIED.update(tmp, time=t)
    return tmp[0][1]

def http_time_to_unix(h):
    return time.strptime(h, "%a, %d %b %Y %H:%M:%S GMT")

def test_if_mod_304():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', '304')

    cache_app = CacheFixtureApp()
    index_page = CacheFixtureResponseInfo(open(os.path.join(test_dir,'index.html')).read())
    page1 = CacheFixtureResponseInfo(open(os.path.join(test_dir,'page1.html')).read())
    page2 = CacheFixtureResponseInfo(open(os.path.join(test_dir,'page2.html')).read())
    cache_app.map_url('/index.html',index_page)
    cache_app.map_url('/page1.html',page1)
    cache_app.map_url('/page2.html',page2)
    
    index_page.mod_time = 1000 
    page1.mod_time = 1000 
    page2.mod_time = 1000 

    
    transcluder = TranscluderMiddleware(cache_app)
    test_app = TestApp(transcluder)

    #load up the deptracker
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_MODIFIED_SINCE' : make_http_time(2000)})

    #and test it
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_MODIFIED_SINCE' : make_http_time(2000)})
    assert result.status == 304
    
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_MODIFIED_SINCE' : make_http_time(500)})
    assert result.status == 200

    page1.mod_time = 3000
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_MODIFIED_SINCE' : make_http_time(2000)})
    assert result.status == 200


def test_etag_304():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', '304')

    cache_app = CacheFixtureApp()
    index_page = CacheFixtureResponseInfo(open(os.path.join(test_dir,'index.html')).read())
    page1 = CacheFixtureResponseInfo(open(os.path.join(test_dir,'page1.html')).read())
    page2 = CacheFixtureResponseInfo(open(os.path.join(test_dir,'page2.html')).read())
    cache_app.map_url('/index.html',index_page)
    cache_app.map_url('/page1.html',page1)
    cache_app.map_url('/page2.html',page2)
    
    index_page.etag = 'index'
    page1.etag = 'page1'
    page2.etag = 'page2'

    transcluder = TranscluderMiddleware(cache_app)
    test_app = TestApp(transcluder)

    #load up the deptracker
    result = test_app.get('/index.html')
    
    etag = header_value(result.headers, 'ETAG')
    assert etag is not None

    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})
    assert result.status == 304 

    page1.etag = 'page1.new'
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})
    assert result.status == 200 
    
    new_etag = header_value(result.headers, 'ETAG')
    assert new_etag != etag 

    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : new_etag})
    assert result.status == 304 


class PausingMiddleware: 
    def __init__(self, app, sleep_time): 
        self.app = app 
        self.sleep_time = sleep_time

    def __call__(self, environ, start_response): 
        try:
            time.sleep(self.sleep_time)
        except KeyboardInterrupt:
            return self.app(environ, start_response)
        return self.app(environ, start_response)


the_tasklist = TaskList()
def teXst_parallel_gets(): 
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', '304')

    sleep_time = 1
    cache_app = CacheFixtureApp()
    sleep_app = PausingMiddleware(cache_app, sleep_time)
    transcluder = TranscluderMiddleware(sleep_app, tasklist = the_tasklist)
    static_test_app = TestApp(cache_app)
    test_app = TestApp(transcluder)

    page_list = ['index.html', 'index2.html', 'page1.html', 'page2.html', 'page2_1.html', 'page3.html', 'page4.html', 'expected5.html']
    pages = {}
    for page in page_list:
        pages[page] = CacheFixtureResponseInfo(open(os.path.join(test_dir, page)).read())
        cache_app.map_url('/' + page, pages[page])
        pages[page].etag = page
    
    #load up the deptracker
    start = time.time() 
    result = test_app.get('/index.html')
    end = time.time() 
    #print "took %s sleep_times" % ((end - start) / sleep_time) 
    assert  2*sleep_time <= end - start < 3*sleep_time, the_tasklist.doprint(2, end - start)

    etag = header_value(result.headers, 'ETAG')
    assert etag is not None

    #test parallel fetch from correct tracked deps
    start = time.time() 
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})
    end = time.time() 
    #print "took %s sleep_times" % ((end - start) / sleep_time) 
    assert  sleep_time <= end - start < 2*sleep_time, the_tasklist.doprint(1, end - start)
    assert result.status == 304

    pages['page1.html'].etag = 'page1.new'
    start = time.time() 
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})    
    end = time.time() 
    #print "took %s sleep_times" % ((end - start) / sleep_time) 

    assert  2*sleep_time <= end - start < 3*sleep_time, the_tasklist.doprint(2, end - start)
    etag = header_value(result.headers, 'ETAG')

    assert result.status == 200 

    # change the content of the index page, this will make it depend on page3 
    cache_app.map_url('/index.html',pages['index2.html'])
    start = time.time() 
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})
    end = time.time() 
    #print "took %s sleep_times" % ((end - start) / sleep_time) 
    assert  2*sleep_time <= end - start < 3*sleep_time, the_tasklist.doprint(2, end - start)

    # change dependency to have a dependency 
    cache_app.map_url('/page2.html', pages['page2_1.html'])
    start = time.time() 
    result = test_app.get('/index.html', extra_environ={'HTTP_IF_NONE_MATCH' : etag})
    expected = static_test_app.get('/expected5.html')
    html_string_compare(result.body, expected.body)
    end = time.time() 
    
    #print "took %s sleep_times" % ((end - start) / sleep_time) 
    assert  2*sleep_time <= end - start < 3*sleep_time, the_tasklist.doprint(2, end - start)
    
    

class AnyDomainTranscluderMiddleware(TranscluderMiddleware):
    def premangle_subrequest(self, url, environ):
        pat = re.compile('[a-z]*.example.com')
        return pat.sub("localhost", url)

class CookieMiddlware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        old_cookie = environ.get('HTTP_COOKIE', 'nothing')

        domain = environ['PATH_INFO'].split("/")[1][0]

        if construct_url(environ).endswith('/index.html') :
            return self.app(environ, start_response)

        status, headers, body = intercept_output(environ, self.app)
        headers.append(('Set-Cookie', 'name=%s' % domain))
        
        start_response('200 OK', headers)
        return ["<html><head></head><body>Had %s. Setting cookie from %s</body></html>" % (old_cookie, domain)]

def test_cookie():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', 'cookie')
    static_app = StaticURLParser(test_dir)
    cookie_app = CookieMiddlware(static_app)
    transcluder = AnyDomainTranscluderMiddleware(cookie_app)
    test_app = TestApp(transcluder)
    test_static_app = TestApp(static_app)

    result = test_app.get('/index.html')
    expected = test_static_app.get('/expected1.html')
    html_string_compare(result.body, expected.body)
    result = test_app.get('/index.html')
    expected = test_static_app.get('/expected2.html')
    html_string_compare(result.body, expected.body)

class TimeBomb: 
    def __init__(self, app, calls_until_explosion=1): 
        self.app = app 
        self.calls_left = calls_until_explosion 

    def __call__(self, environ, start_response): 
        if self.calls_left > 0: 
            self.calls_left-=1
            return self.app(environ, start_response) 

        raise Exception("requested resource internally!")

def external(dir):
    static_app = StaticURLParser(dir)
    bomb = TimeBomb(static_app)
    trans_app = TranscluderMiddleware(bomb)
    app = TestApp(trans_app)

    result = app.get('/index.html')
    expected = TestApp(static_app).get('/expected.html')
    html_string_compare(result.body, expected.body)

def test_external():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', 'external')
    for dir in os.listdir(test_dir):
        if dir.startswith('.'):
            continue 
        yield external, os.path.join(test_dir, dir)

def run_dir(dir):
    static_app = StaticURLParser(dir)
    trans_app = TranscluderMiddleware(static_app)
    app = TestApp(trans_app)

    result = app.get('/index.html')
    expected = app.get('/expected.html')
    html_string_compare(result.body, expected.body)

def test_internal():
    base_dir = os.path.dirname(__file__)
    test_dir = os.path.join(base_dir, 'test-data', 'standard')
    for dir in os.listdir(test_dir):
        if dir.startswith('.'):
            continue
        yield run_dir, os.path.join(test_dir, dir)

thread_count = 0
from threading import Thread
def try_teXst_parallel_gets():
    global thread_count
    try:
        test_parallel_gets()
    finally:
        thread_count -= 1

if __name__ == '__main__':
    pass

if 0:
    global thread_count
    count = 0 
    ok = 0 
    while(1): 
        #print "\n\n\n\n******** RUN %s [%s sucesses] *********\n\n\n\n\n" % (count, ok)
        if thread_count < 10:
            try:
                print "RUN %s [%s sucesses] %s threads" % (count, ok, thread_count)
                thread_count += 1
                Thread(target=try_test_parallel_gets).start()
                ok+=1
            except KeyboardInterrupt: 
                the_tasklist.kill()
                break
            except:
                traceback.print_exc() 
            count+=1
