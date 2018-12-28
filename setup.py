from setuptools import find_packages, setup
from os.path import dirname, join


with open(join(dirname(__file__), 'README.md')) as readme:
    description = readme.read()

setup(
    name='hh',
    version='0.3.0',
    packages=find_packages(),
    long_description=description,
)
