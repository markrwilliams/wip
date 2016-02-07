#!/usr/bin/env python

from setuptools import setup, find_packages
import os


def next_to_setup(*path):
    return os.path.join(os.path.dirname(__file__), *path)

with open(next_to_setup('README.rst')) as readme_file:
    readme = readme_file.read()

with open(next_to_setup('HISTORY.rst')) as history_file:
    history = history_file.read().replace('.. :changelog:', '')

with open(next_to_setup('requirements.txt')) as requirements_file:
    requirements = requirements_file.read().splitlines()

test_requirements = [
    # TODO: put package test requirements here
]

setup(
    name='wip',
    version='15.0',
    description="Easy-to-use Python WSGI Server",
    long_description=readme + '\n\n' + history,
    author="Mark Williams",
    author_email='markrwilliams@gmail.com',
    url='https://github.com/markrwilliams/wip',
    packages=find_packages(),
    package_dir={'wip':
                 'wip'},
    include_package_data=True,
    install_requires=requirements,
    license="ISCL",
    zip_safe=False,
    keywords='wip',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
)
