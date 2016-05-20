from os import path
from setuptools import find_packages, setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the README.rst file
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="django-world-languages",
    version="0.1",
    license="BSD",
    description="Languages and dialects of the world for Django projects",
    long_description=long_description,
    author="Blag",
    author_email="blag@users.noreply.github.com",
    url="https://github.com/blag/django-world-languages",
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        'django-cities>=0.4.1',
        'pyquery>=1.2.13',
        'regex>=2016.05.23',
        'tqdm>=4.7.1',
        'PyYAML>=3.11',
    ],
    keywords="languages, dialects, linguistics",
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Scientific/Engineering :: Information Analysis',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Text Processing :: Linguistic',
    ]
)
