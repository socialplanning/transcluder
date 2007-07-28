from sets import Set
from copy import copy 
from threading import Lock, RLock, Condition
from enum import Enum
from avl import new as avl
from transcluder.cookie_wrapper import * 
from wsgifilter.cache_utils import merge_cache_headers, parse_merged_etag
from transcluder.threadpool import WorkRequest, ThreadPool
from transcluder.deptracker import make_resource_key
from locked import locked
import time 
import traceback 
import threading

class trackingSet(Set):
    def __init__(self, *args):
        print "starting with %s" % (args,)
        Set.__init__(self, *args)
    
    def add(self, *args):
        print "adding %s" % args
        return Set.add(self, *args)

    def remove(self, *args):
        print "removing %s" % args
        return Set.remove(self, *args)


# def timeit(func, *args):
#     start = time.time()
#     out = func(*args)
#     end = time.time()
#     if end - start > 2.10:
#         print "too long in %s: %s" % (func, end - start)
#         import traceback
#         print "".join(traceback.format_stack()[-5:-2])
#     return out

# class TracingCondition(object):
#     def __init__(self, lock = None):
#         self.oldThread = None
#         self.currentThread = None
#         if not lock:
#             lock = Lock()
#         self._condition = Condition(lock)
    
#     def acquire(self, blocking = 1):
#         out = timeit(self._condition.acquire, blocking)
#         self.oldThread = self.currentThread
#         self.currentThread = threading.currentThread()
#         return out

#     def release(self):
#         self.currentThread = None
#         return self._condition.release()

#     def wait(self):
#         timeit(self._condition.wait)
    
#     def notify(self):
#         return self._condition.notify()

#     def notifyAll(self):
#         return self._condition.notifyAll()

class TaskList:
    def __init__(self, poolsize=30):
        self._fetchlists = avl()
        self._lock = RLock()
        self.cv = Condition(self._lock)
        self.next_task_list_index = 0
        self.alive = True
        self.threadpool = ThreadPool(poolsize, self)

    def kill(self):
        self.alive = False
        self.notifyAll()

    def get(self):     
        self.cv.acquire()
        while self.alive:
            for list in self._fetchlists:
                task = list.pop()
                if task:
                    self.cv.release()
                    return task
            self.cv.wait()


    @locked
    def put_list(self, list):        
        #assert list not in self._fetchlists
        if not hasattr(list, 'task_list_index'):
            list.task_list_index = self.next_task_list_index
            self.next_task_list_index += 1
        self._fetchlists.insert(list)
        #about to notify
        self.cv.notifyAll() 

    @locked
    def remove_list(self, list):
        self._fetchlists.remove(list)

    def notify(self): 
        self.cv.acquire()
        self.cv.notify()
        self.cv.release() 

    def notifyAll(self): 
        self.cv.acquire()
        self.cv.notifyAll()
        self.cv.release() 


class FetchList: 
    def __init__(self, tasklist): 
        self.tasklist = tasklist
        self._lock = Lock()
        self._tasks = [] 
        self._pending = Set()
        self._in_progress = Set()


    def push(self, task): 
        self._lock.acquire()
        try:
            if (not task.url in self._pending and 
                not task.url in self._in_progress): 
                self._tasks[0:0] = [task]
                self._pending.add(task.url)
                pushed = True
            else:
                pushed = False 
        finally: 
            self._lock.release() 

        self.tasklist.notify() 
        return pushed

    @locked 
    def pop(self): 
        if len(self._tasks):
            task = self._tasks.pop()
            self._pending.remove(task.url)
            self._in_progress.add(task.url)
            return task 
        else: 
            return None

    @locked 
    def __len__(self): 
        return len(self._tasks) 

    @locked 
    def clear(self): 
        self._tasks = []
        self._pending = Set()

    @locked
    def remove_if_mods(self):
        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            if task.request_type != RequestType.conditional_get:
                self._tasks.append(task)
            else:
                self._pending.remove(task.url)

    @locked 
    def completed(self, task): 
        assert (task.url in self._in_progress)
        self._in_progress.remove(task.url)

    @locked 
    def claim(self, url): 
        if url in self._in_progress: 
            return False

        if url in self._pending: 
            self._pending.remove(url)
            tasks = [t for t in self._tasks if t.url == url]
            assert len(tasks) == 0 or len(tasks) == 1
            self._tasks.remove(tasks[0])

        self._in_progress.add(url)

        return True

RequestType = Enum('conditional_get', 'get')

class FetchListItem(WorkRequest): 
    def __init__(self, url, environ, 
                 request_type, 
                 page_manager):         
        self.url = url 
        self.environ = environ.copy() 
        self.request_type = request_type 
        self.page_manager = page_manager 
        WorkRequest.__init__(self, self)

    def __call__(self):
        try: 
            self._do_fetch() 
        except: 
            traceback.print_exc() 

    def _do_fetch(self): 
        self.environ['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(self.environ['transcluder.incookies'], self.url)) # XXX transcluder dependencey

        if self.request_type == RequestType.conditional_get:
            assert 'HTTP_IF_NONE_MATCH' in self.environ or 'HTTP_IF_MODIFIED_SINCE' in self.environ
            if 'HTTP_IF_NONE_MATCH' in self.environ:
                etags = self.environ['transcluder.etags'] # XXX transcluder dependency
                if etags.has_key(self.url):
                    self.environ['HTTP_IF_NONE_MATCH'] = etags[self.url]
        else:
            if 'HTTP_IF_MODIFIED_SINCE' in self.environ:
                del self.environ['HTTP_IF_MODIFIED_SINCE']

            if 'HTTP_IF_NONE_MATCH' in self.environ:
                del self.environ['HTTP_IF_NONE_MATCH']

        self.response = self.page_manager.request(self.url, self.environ)

        if self.response[0].startswith('304'):
            self.page_manager.got_304(self)
        else:
            self.page_manager.got_200(self)

    def archive_info(self): 
        return self.response

    def __str__(self):
        return "FetchListItem(%s, %s)" % (self.url, self.request_type)

PMState = Enum(
    'initial', 
    'check_modification',
    'not_modified', 
    'modified', 
    'get_pages', 
    'done')

class PageManager: 
    def __init__(self, request_url, environ, deptracker, 
                 find_dependencies, tasklist, request_func): 

        self.deptracker = deptracker 
        self.tasklist = tasklist 
        self.fetchlist = FetchList(tasklist) 
        self.find_dependencies = find_dependencies
        self.request = request_func

        self._request_url = request_url
        self._environ = environ.copy()
        self._root_resource = make_resource_key(self._request_url, self._environ)
        self._page_archive = {}         


        self._speculative_dep_info = {} 
        self._needed = Set() 
        self._actual_deps = Set()

        self._lock = RLock()
        self.cv = Condition(self._lock)

        self._state = PMState.initial 


    def __cmp__(self, other):
        return self.task_list_index - other.task_list_index    

    def is_modified(self): 
        if (self._state == PMState.modified or self._state == PMState.done or 
            self._state == PMState.get_pages):
            return True
        if self._state == PMState.not_modified:
            return False


        self._state = PMState.check_modification
        request_url, environ = self._request_url, self._environ
        if not ('HTTP_IF_NONE_MATCH' in environ or 
                'HTTP_IF_MODIFIED_SINCE' in environ):
            self._state = PMState.modified
            return True

        if not self.deptracker.is_tracked(self._root_resource): 
            #possible future todo: compute is-modified by issuing
            #conditional (for is-modified) *and* unconditional (for
            #transclusion tree) requests for each resource.
            self._state = PMState.modified
            return True

        self.tasklist.put_list(self.fetchlist)
        initial_requests = [request_url] 
        initial_requests += self.deptracker.get_all_deps(self._root_resource)
        self.expected_mod_responses = len(initial_requests)
            
        for url in initial_requests: 
            self.add_conditional_get(url)

        while self._state == PMState.check_modification:
            self.cv.acquire() 
            task = self.fetchlist.pop()
            if task:
                self.cv.release()
                task()
            else: 
                if self._state == PMState.check_modification: 
                    self.cv.wait() 
                self.cv.release()

        self.tasklist.remove_list(self.fetchlist)

        assert (self._state == PMState.not_modified or 
                self._state == PMState.modified or 
                self._state == PMState.done)

        if self._state == PMState.not_modified: 
            return False

        return True

    def _get_cached_copy(self, url):
        status, headers, body, parsed = self._page_archive[url]
        return (status, headers, body, copy(parsed))

    def fetch(self, url):
        #print "fetch %s" % url
        self.cv.acquire()
        try:        
            if self.have_page_content(url):
                return self._get_cached_copy(url)

            if self._state == PMState.initial: 
                self._init_speculative_gets()

            should_fetch = self.fetchlist.claim(url)
        finally:
            self.cv.release()

        if should_fetch:
            self._needed.add(url)
            #get it ourselves
            fetch = FetchListItem(url, self._environ, 
                          RequestType.get, 
                          self)
            fetch()
            self.cv.acquire()
            try:
                return self._get_cached_copy(url)
            finally: 
                self.cv.release()

        #otherwise, wait for it
        self.cv.acquire()
        try:
            while 1:
                if self.have_page_content(url): 
                    return self._get_cached_copy(url)
                self.cv.wait()
        finally:
            self.cv.release()
    

    @locked 
    def merge_headers_into(self, headers):        
        if not (self._state == PMState.done or self._state == PMState.not_modified):
            print "Bad state %s" % self._state
            print self._actual_deps
            print self._page_archive
            print self._needed

        assert self._state == PMState.done or self._state == PMState.not_modified 

        response_info = {} 
        cookies = {}
        in_cookies = self._environ['transcluder.incookies']
        for cookie_map in in_cookies:
            key = cookie_key(cookie_map)
            cookies[key] = cookie_map

        for url in self._actual_deps:
            response_info[url] = self._page_archive[url][0:3]
            status, page_headers, body, parsed = self._page_archive[url]
            new_setcookies = get_set_cookies_from_headers(page_headers, url)
            cookies.update(new_setcookies)
        
        merge_cache_headers(response_info, headers)


        if 'HTTP_COOKIE' in self._environ:
            newcookies = wrap_cookies(cookies.values(), oldcookies=self._environ['HTTP_COOKIE'])
        else:
            newcookies = wrap_cookies(cookies.values())

        # XXX probably should just not send any other
        # cookies except these ? 
        for newcookie in newcookies: 
            headers.append(('Set-Cookie', newcookie))



    @locked
    def add_conditional_get(self, url): 
        if not self.have_archive(url): 
            self.fetchlist.push(FetchListItem(url, self._environ, 
                                              RequestType.conditional_get, 
                                              self))
        

    @locked 
    def add_get(self, url): 
        if not self.have_page_content(url): 
            self.fetchlist.push(FetchListItem(url, self._environ, 
                                              RequestType.get, 
                                              self))
           
    @locked
    def got_304(self, task):
        assert task.url not in self._page_archive
        self._page_archive[task.url] = task.archive_info() 

        self.fetchlist.completed(task)

        if self._state != PMState.check_modification: 
            assert(self._state != PMState.not_modified)
            if self._state == PMState.get_pages or self._state == PMState.modified: 
                self.add_get(task.url)
                self.notify() 
                return 

        self.expected_mod_responses -= 1 
        
        if self.expected_mod_responses: 
            assert(self.expected_mod_responses) > 0 
            self.notify() 
            return 

        else: 
            assert(len(self.fetchlist) == 0)
            self._state = PMState.not_modified
            self.notify()


    @locked 
    def notify(self):
        self.cv.notifyAll()
        
    @locked 
    def got_200(self, task): 
        self._page_archive[task.url] = task.archive_info() 
        
        # update dependencies 
        status, headers, body, parsed = task.archive_info() 
        resource = make_resource_key(task.url, task.environ)
        if parsed:
            dep_list = self.find_dependencies(parsed, task.url)
        else:
            dep_list = []
        resource = make_resource_key(task.url, self._environ)
        self.deptracker.set_direct_deps(resource, dep_list)

        if self._state == PMState.check_modification: 
            self._init_speculative_gets()            

        self._speculative_dep_info[task.url] = dep_list

        for dep in dep_list:
            self.add_get(dep)

        if task.url in self._needed: 
            self._got_needed(task.url) 

        self.fetchlist.completed(task)

        self.notify()

    def _got_needed(self, url): 
        assert url in self._needed 

        self._needed.remove(url)
        self._actual_deps.add(url)

        all_deps = self.get_all_deps(url)
        for dep in all_deps: 
            if not self.have_page_content(dep):
                self._needed.add(dep)
            else: 
                self._actual_deps.add(dep)


        if len(self._needed) == 0:
            self._state = PMState.done
            self.tasklist.remove_list(self.fetchlist)



    @locked
    def have_page_content(self, url): 

        self.cv.acquire() 
        try: 
            return url in self._page_archive and not self._page_archive[url][0].startswith('304')
        finally: 
            self.cv.release()

    @locked
    def have_archive(self, url): 
        self.cv.acquire() 
        try: 
            return url in self._page_archive
        finally: 
            self.cv.release()

    @locked 
    def get_all_deps(self, url): 
        seen = Set() 
        deps = self._speculative_dep_info.get(url, [])[:]
        index = 0
        while index < len(deps): 
            new_deps = self._speculative_dep_info.get(deps[index], [])
            for dep in new_deps: 
                if not dep in seen: 
                    seen.add(dep)
                    deps.append(dep)
            index += 1
        return deps
    


    @locked 
    def begin_speculative_gets(self): 

        if self._state == PMState.done:
            return

        assert(self._state == PMState.initial or 
               self._state == PMState.modified)
        
        if self._state == PMState.initial: 
            self._init_speculative_gets()

        self.tasklist.put_list(self.fetchlist)

        self._state = PMState.get_pages



    @locked 
    def _init_speculative_gets(self):         
        assert(self._state == PMState.initial or 
               self._state == PMState.check_modification)

        self._state = PMState.modified
        self.fetchlist.remove_if_mods()

        self._speculative_dep_info = {} 
        
        self._needed = Set([self._request_url]) 

        self.add_get(self._request_url)        
        urls = self.deptracker.get_all_deps(self._root_resource)
        for url in urls: 
            self.add_get(url)



