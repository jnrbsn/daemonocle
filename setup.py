from setuptools import setup

with open('README.rst') as fp:
    long_description = fp.read().split('\n\n-----\n\n', 1)[1].lstrip()

setup(
    name='daemonocle',
    version='0.4',
    description='A Python library for creating super fancy Unix daemons',
    long_description=long_description,
    url='http://github.com/jnrbsn/daemonocle',
    author='Jonathan Robson',
    author_email='jnrbsn@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
    ],
    keywords='daemon daemonize fork unix cli',
    packages=['daemonocle'],
    install_requires=[
        'click==0.7',
        'psutil==2.1.1',
    ],
)
