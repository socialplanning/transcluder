from sets import Set
from lxml import etree
import urlparse
import lxmlutils 
from transcluder import helpers 
from transcluder import uritemplates
import traceback 


class Transcluder: 

    def __init__(self, variables, fetch, 
                 should_recurse=helpers.always_recurse): 
        self.variables = variables 
        self.fetch = fetch 
        self.should_recurse = should_recurse

    def transclude(self, document, document_url): 
        """
        perform transclusion on the document given 

        document: lxml etree structure representing the document to perform
          transclusion on

        document_url: the url of the document

        self.fetch: a callable which given a url can return an
          lxml etree structure for the document referred to by the url 
          (no fragment interpretation should be performed) 

        self.should_recurse: a predicate accepting a url and returning 
          whether the transcluder should recurse and perform transclusion on 
          the url given. 
        """

        target_links = document.xpath("//a[@rel='include']")
        for target in target_links: 
            source_url = self.get_include_url(target, document_url) 

            if source_url is None: 
                self.attach_warning(target, "no href specified")
                continue

            try: 
                subdoc = self.fetch(source_url)

                if subdoc is None: 
                    self.attach_warning(target, "No HTML content in %s" % source_url)
                    continue

                if self.should_recurse(source_url): 
                    self.transclude(subdoc, source_url)

                lxmlutils.fixup_links(subdoc, source_url)
                self.merge(target, subdoc, source_url)

            except Exception, message: 
                self.attach_warning(target, "failed to retrieve %s (%s)" % 
                               (source_url, traceback.format_exc()))

    def find_dependencies(self, document, document_url): 
        """
        """

        deps = Set() 

        target_links = document.xpath("//a[@rel='include']")
        for target in target_links: 
            source_url = self.get_include_url(target, document_url)

            if source_url is not None: 
                deps.add(source_url)

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
            els = subdoc.xpath("//*[@id='%s']" % fragment)

            if els is None or len(els) == 0: 
                self.attach_warning(target, 
                                    'no element with id %s found in %s' % 
                                    (fragment, source_url))
                return
            lxmlutils.replace_element(target, els[0])
        else: 
            lxmlutils.replace_many(target, subdoc.xpath('//body/child::node()'))


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


    def attach_warning(self, target, message): 
        """
        add the warning 'message' to the link 'target' 
        """
        target.set('title', message)


