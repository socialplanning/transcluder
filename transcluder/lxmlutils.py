# XXX these are also in deliverance

from lxml import etree
import urlparse
import re

def replace_element(old_el, new_el):
    """
    replaces old_el with new_el in the parent 
    element of old_el. The tail of 
    new_el is replaced by the tail of old_el 
    """
    new_el.tail = old_el.tail
    old_el.getparent().replace(old_el, new_el)



def fixup_links(doc, uri):
    """ 
    replaces relative urls found in the document given 
    with absolute urls by prepending the uri given. 
    <base href> tags are removed from the document. 

    Affects urls in href attributes, src attributes and 
    css of the form url(...) in style elements 
    """
    base_uri = uri
    basetags = doc.xpath('//base[@href]')
    if basetags:
        base_uri = basetags[0].attrib['href']

        for b in basetags:
            b.getparent().remove(b)

    elts = doc.xpath('//*[@href]')
    fixup_link_attrs(elts, base_uri, 'href')

    elts = doc.xpath('//*[@src]')
    fixup_link_attrs(elts, base_uri, 'src')

    elts = doc.xpath('//*[@action]')
    fixup_link_attrs(elts, base_uri, 'action')

    #elts = doc.xpath('//head/style')
    #fixup_css_links(elts, base_uri)

    return doc


def fixup_link_attrs(elts, base_uri, attr):
    """
    prepends base_uri onto the attribute given by attr for 
    all elements given in elts 
    """
    for el in elts:
        el.attrib[attr] = urlparse.urljoin(base_uri, el.attrib[attr])


def append_text(parent, text):
    if text is None:
        return
    if len(parent) == 0:
        target = parent
    else:
        target = parent[-1]

    if target.text:
        target.text = target.text + text
    else:
        target.text = text



def attach_text_to_previous(el, text):
    """
    attaches the text given to the nearest previous node to el, 
    ie its preceding sibling or parent         
    """
    if text is None:
        return 

    el_i = el.getparent().index(el)
    if el_i > 0:
        sib_el = el.getparent()[el_i - 1]
        if sib_el.tail:
            sib_el.tail += text 
        else:
            sib_el.tail = text
    else: 
        if el.getparent().text:
            el.getparent().text += text 
        else:
            el.getparent().text = text

def elements_in(els):
    """
    return a list containing elements from els which are not strings 
    """
    return [x for x in els if type(x) is not type(str())]



def strip_tails(els):
    """
    for each lxml etree element in the list els, 
    set the tail of the element to None
    """
    for el in els:
        el.tail = None


def attach_tails(els):
    """
    whereever an lxml element in the list is followed by 
    a string, set the tail of the lxml element to that string 
    """
    for index,el in enumerate(els): 
        # if we run into a string after the current element, 
        # attach it to the current element as the tail 
        if (type(el) is not type(str()) and 
            index + 1 < len(els) and 
            type(els[index+1]) is type(str())):
            el.tail = els[index+1]   


def append_many(parent, children):

    if children is None or len(children) == 0:
        return

    if type(children[0]) is type(str()):
        append_text(parent,children[0])            
        children = children[1:]

    non_text_els = elements_in(children)
    strip_tails(non_text_els)
    attach_tails(children)

    for el in non_text_els:
        parent.append(el)


def replace_many(old_el, new_els):
    non_text_els = elements_in(new_els)
    strip_tails(non_text_els)

    # the xpath may return a mixture of strings and elements, handle strings 
            # by attaching them to the proper element 
    if (type(new_els[0]) is type(str())):
        # text must be appended to the tail of the most recent sibling or appended 
        # to the text of the parent of the replaced element
        attach_text_to_previous(old_el, new_els[0])

    if len(non_text_els) == 0:
        attach_text_to_previous(old_el, old_el.tail)
        old_el.getparent().remove(old_el)
        return

    attach_tails(new_els)

    # this tail, if there is one, should stick around 
    preserve_tail = non_text_els[0].tail 

    #replaces first element
    replace_element(old_el, non_text_els[0])
    temptail = non_text_els[0].tail 
    non_text_els[0].tail = None
    parent = non_text_els[0].getparent()

    # appends the rest of the elements
    i = parent.index(non_text_els[0])
    parent[i+1:i+1] = non_text_els[1:]

    if non_text_els[-1].tail:
        non_text_els[-1].tail += temptail
    else:
        non_text_els[-1].tail = temptail

    # tack in any preserved tail we stored above
    if preserve_tail:
        if non_text_els[0].tail:
            non_text_els[0].tail = preserve_tail + non_text_els[0].tail
        else:
            non_text_els[0].tail = preserve_tail

html_xsl = """
<xsl:transform xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" encoding="UTF-8" /> 
  <xsl:template match="/">
    <xsl:copy-of select="."/>
  </xsl:template>
</xsl:transform>
"""

html_transform = etree.XSLT(etree.XML(html_xsl))


def tostring(doc, doctype_pair=None):
    """
    return HTML string representation of the document given 
 
    note: this will create a meta http-equiv="Content" tag in the head
    and may replace any that are present 
    """

    doc = str(html_transform(doc))

    if doctype_pair: 
        doc = """<!DOCTYPE html PUBLIC "%s" "%s">\n%s""" % (doctype_pair[0], doctype_pair[1], doc) 

    return doc

                  
