
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


from sets import Set
from lxml import etree
import urlparse
import lxmlutils 
from transcluder import helpers 
from transcluder import uritemplates
import traceback 
from threading import Lock
from transcluder.locked import locked
import copy

class Transcluder: 
    """
    This class performs the transclusion
    operation on a document. Each anchor
    tag in a transcluded document of
    the form:
    
    <a rel="include" href="someurl">...</a>

    is replaced by the content referred to
    by 'someurl'.

    further, the url may be a uri template
    as described in uritemplates.
    """


    def __init__(self, variables, fetch,
                 should_include=helpers.all_urls,
                 should_recurse=helpers.all_urls,
                 max_depth=3):
        """
        variables - a dictionary which specifies the
          values to use when filling in uri template
          variables

        fetch - a function acception a url and
          returning a parsed lxml document representing
          the content located at the url.

        should_include - a predicate accepting a url
          which returns true iff it is acceptable to
          include content from the url given

        should_recurse - a predicate accepting a url
          which returns true iff it is acceptable to
          perform recursive transclusion on a document
          located at the url specified

        max_depth - the maximum depth of recursive
          transclusions performed when transcluding a
          document. Set to 1 to only include documents
          referenced by the document given. 
        """
        self.variables = variables 
        self.fetch = fetch
        self.should_include = should_include
        self.should_recurse = should_recurse
        self.max_depth = max_depth
        self._lock = Lock()

    @locked
    def xpath(self, document, path):
        return document.xpath(path)

    def transclude(self, document, document_url, _cache=None, _depth=1): 
        """
        perform transclusion on the document given 

        document - lxml etree structure representing the document to perform
          transclusion on

        document_url - the url of the document
        """

        if _cache is None:
            _cache = {}

        target_links = self.get_transcluder_links(document)
        if not target_links:
            return False #nothing to transclude
        for target in target_links:
            source_url = self.get_include_url(target, document_url) 

            if source_url is None: 
                self.attach_warning(target, "no href specified")
                continue

            try:
                if not self.should_include(source_url):
                    self.attach_warning(target,
                                        "Including from this URL is forbidden")
                    continue

                subdoc = self._get(source_url, _depth, _cache)
                if subdoc is None:
                    self.attach_warning(target, "No HTML content in %s" % source_url)
                    continue
                else:
                    self.merge(target, subdoc, source_url)

            except: 
                print "HERE"

#             except object, message:
#                 print "HERE", message
#                 self.attach_warning(target, "Failed to retrieve (%s), url: %s"
#                                     % (message, source_url))
                # XXX should log traceback.format_exc() ?  
        return True

    def _get(self, source_url, depth, cache):
        """
        helper function for retrieving subdocuments
        """
        base_url = self.base_url(source_url)
        if base_url in cache:
            return cache[base_url]
        else:
            subdoc = self.fetch(base_url)
            if subdoc is None:
                return None

            should_cache = True
            if depth >= self.max_depth:
                self.attach_warning_all(subdoc, "Maximum recursion depth reached")
                should_cache = False
            elif not self.should_recurse(source_url):
                self.attach_warning_all(subdoc,
                                        "Including from parent"
                                        "document is forbidden (%s)" %
                                        source_url)
            else:
                self.transclude(subdoc, source_url,
                                _cache=cache,
                                _depth=depth+1)

            lxmlutils.fixup_links(subdoc, source_url)
                
            if should_cache:
                cache[base_url] = subdoc

            return subdoc


    def find_dependencies(self, document, document_url): 
        """
        retrieves the direct dependencies of the document
        given, ie all urls which referred to in transcluder
        links and are allowable according to the should_include
        policy. This does not include recursive dependencies. 
        """

        deps = Set() 

        target_links = self.get_transcluder_links(document)
        for target in target_links: 
            source_url = self.get_include_url(target, document_url)
            if (source_url is not None and
                self.should_include(source_url)):
                deps.add(self.base_url(source_url))

        return list(deps)


    def merge(self, target, subdoc, source_url): 
        """
        replace the link 'target' with the element or elements in 
        'subdoc' according to the url 'source_url'. 

        if source_url contains a fragement identifier, the element 
        from subdoc with id equal to the fragment identifier is used. 
        otherwise, all children of the body element of subdoc
        are used. 
        """

        # XXX additional merging behavior ? 
        fragment = urlparse.urlparse(source_url)[5]

        if len(fragment) > 0:                 
            els = self.xpath(subdoc, "//*[@id='%s']" % fragment)

            if els is None or len(els) == 0: 
                self.attach_warning(target, 
                                    'no element with id %s found in %s' % 
                                    (fragment, source_url))
                return

            el = copy.deepcopy(els[0]) 
            lxmlutils.replace_element(target, el)
        else:
            els = copy.deepcopy(self.xpath(subdoc, '//body/child::node()'))
            lxmlutils.replace_many(target, els)

    def get_transcluder_links(self, document):
        """
        find all link tags in a document which are
        relevant to transcluder (ie with rel=include)
        """
        return self.xpath(document, "//a[@rel='include']")

    def get_include_url(self, target, document_url): 
        """
        get and normalize the href attribute of the link 'target'.  
        1. expand uri template self.variables with the dictionary 'self.variables' 
        2. make the url absolute by joining it to the document_url given 

        target: the link element 
        document_url: the url of the document containing the link 
        self.variables: a dictionary used for uri template expansion 
        """
        source_url = target.get("href", None)

        if source_url is None or len(source_url) == 0: 
            return None

        source_url = uritemplates.expand_uri_template(source_url, self.variables)
        return urlparse.urljoin(document_url, source_url)

    def base_url(self, url):
        """
        returns the url given without a fragment identifier
        """
        parts = urlparse.urlparse(url)
        return urlparse.urlunparse(parts[0:5] + ('',))

    def attach_warning(self, target, message): 
        """
        add the warning 'message' to the link 'target' 
        """
        target.set("title", message)

    def attach_warning_all(self, document, message):
        """
        add the warning 'message' to all transcluder
        links in the document 
        """
        for x in self.get_transcluder_links(document):
            self.attach_warning(x, message)
