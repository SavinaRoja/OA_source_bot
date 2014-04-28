# -*- coding: utf-8 -*-

from distutils.core import setup


def long_description():
    with open('README.md', 'r') as readme:
        readme_text = readme.read()
    return(readme_text)

setup(name='OA_source_bot',
      version='0.0.1',
      description='Reddit bot that replies to OA submissions with content files',
      long_description=long_description(),
      author='Paul Barton',
      author_email='pablo.barton@gmail.com',
      url='https://github.com/SavinaRoja/OA_source_bot',
      package_dir={},
      packages=[],
      package_data={},
      scripts=[],
      data_files=[('', ['README.md'])],
      classifiers=[],
      install_requires=['docopt', 'praw', 'bcoding']
      )