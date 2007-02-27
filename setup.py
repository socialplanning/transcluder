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
      license="",
      packages=find_packages(exclude=[]),
      zip_safe=False,
      install_requires=[
        'lxml',
        'Paste',
        'FormEncode', 
        'WSGIFilter', 
        "decorator",
	"enum",
        'pyavl',
	'nose',
        'ElementTree'
      ],
      include_package_data=True,
      entry_points="""
      [paste.filter_app_factory]
      main = transcluder.middleware:make_filter
      """,
      )


