from setuptools import find_packages, setup
from os.path import dirname, join


with open(join(dirname(__file__), 'README.md')) as readme:
    description = readme.read()

setup(
    name='hh',
    version='0.3.0',
    author='CelebrateYourself',
    description='CLI utility for use hh.ru API',
    long_description=description,
    long_description_content_type="text/markdown",
    url="https://github.com/CelebrateYourself/util-hh",
    packages=find_packages(),
)
