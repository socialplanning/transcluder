
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
        'lxml>=2',
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
      	'http://sourceforge.net/projects/pyavl/files/pyavl/1.12/pyavl-1.12.tar.gz/download#egg=pyavl-dev'
      ],
      include_package_data=True,
      entry_points="""
      [paste.filter_factory]
      main = transcluder.middleware:make_filter

      [paste.app_factory]
      main = transcluder.proxyapp:make_proxy

      """,
      )


