
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


from transcluder.cookie_wrapper import unwrap_cookies
import sys

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print "Usage %s <cookie header value>" % sys.argv[0]
        sys.exit(0)

    print unwrap_cookies(sys.argv[1])
