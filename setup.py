
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


__version__ = '0.1'

from setuptools import setup, find_packages

setup(name="Transcluder",
      version=__version__,
      description="",
      long_description="""\
""",
      classifiers=[
        # dev status, license, HTTP categories
        ],
      keywords='',
      author="The Open Planning Project",
      author_email="",
      url="",
      license="MIT",
      packages=find_packages(exclude=[]),
      zip_safe=False,
      install_requires=[
        'lxml>=1.2,<2.0dev',
        'Paste >= 1.3',
        'PasteScript',
        'FormEncode', 
        'WSGIFilter', 
        "decorator",
	"enum",
        'pyavl',
	'nose',
        'ElementTree'
      ],
      dependency_links=[
      	'http://superb-west.dl.sourceforge.net/sourceforge/pyavl/pyavl-1.1.tar.gz#egg=pyavl-dev'
      ],
      include_package_data=True,
      entry_points="""
      [paste.filter_app_factory]
      main = transcluder.middleware:make_filter

      [paste.app_factory]
      main = transcluder.proxyapp:make_proxy

      """,
      )


