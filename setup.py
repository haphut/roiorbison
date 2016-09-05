#!/usr/bin/env python3

# Always prefer setuptools over distutils
from setuptools import setup
# To use a consistent encoding
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='roiorbison',
    version='0.0.1',
    description='Publish ROI messages on an MQTT broker',
    long_description=long_description,
    url='https://github.com/hsldevcom/roiorbison',
    author='haphut',
    author_email='haphut@gmail.com',
    license='AGPLv3',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Programming Language :: Python :: 3.5',
        'Topic :: Internet',
    ],
    keywords='roi noptis mqtt',
    packages=['roiorbison'],
    install_requires=[
        'automaton>=1.4.0,<2',
        'isodate>=0.5.4,<1',
        'lxml>=3.6.4,<4',
        'paho-mqtt>=1.2,<2',
        'PyYAML>=3.12,<4',
    ],
    data_files=[
        ('',
            [
                'LICENSE',
                'LICENSE_AGPL',
                'config.yaml.template',
            ]
        ),
        ('templates', ['templates/*.template']),
    ],
    entry_points={
        'console_scripts': [
            'roiorbison=roiorbison.roiorbison:main',
        ],
    },
)
